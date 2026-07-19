from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import shlex
import signal
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Awaitable, Callable, Iterable
from urllib.parse import urlsplit

from app.borg_compat import version_probe_shell
from app.config import (
    APP_TIMEZONE_NAME,
    COMMAND_TIMEOUT,
    EXPORT_DIR,
    MANAGER_BORG_SECURITY_DIR,
    REPOSITORY_KEYFILES_PATH,
)
from app.models import Host, Job, Repository
from app.repository_cache import manager_repository_cache_dir
from app.schemas import DEFAULT_CREATE_OPTIONS, validate_create_options
from app.vault import get_repository_secret, get_system_secret, load_repository_environment, repository_secret_exists


@dataclass
class Command:
    argv: list[str]
    preview: str
    stdin_data: bytes | None = None
    env: dict[str, str] | None = None
    temp_files: dict[str, str] | None = None
    # Commands wrapped by ``_SECRET_WRAPPER`` keep stdin open after the
    # one-time secret payload. Closing that pipe is then a dedicated,
    # out-of-band cancellation signal for the wrapper. This is essential for
    # SSH jobs: killing the local ssh client alone can otherwise disconnect the
    # remote shell before Borg has received SIGINT and released its lock.
    stdin_controlled_cancel: bool = False


class CommandCancelled(RuntimeError):
    """Raised after a cancelled command process tree has been terminated."""

    def __init__(self, *, forced: bool = False, remote_cleanup_confirmed: bool = False):
        super().__init__("Execution cancelled by user")
        self.forced = forced
        self.remote_cleanup_confirmed = remote_cleanup_confirmed


def manager_borg_argv(parts: Iterable[str]) -> list[str]:
    """Run manager-side Borg commands as the dedicated repository user.

    The production Web API already runs as ``borg``. ``runuser`` is only
    valid while the caller is root, for example during development helpers
    or root-side maintenance. Re-wrapping an already unprivileged process
    fails with ``runuser: may not be used by non-root users`` and prevents
    every manager-side repository action from reaching Borg.
    """
    argv = list(parts)
    if os.geteuid() == 0:
        return ["runuser", "-u", "borg", "--", *argv]
    return argv


def _replace_temp_file_placeholders(argv: list[str], replacements: dict[str, str]) -> list[str]:
    """Replace temporary-file placeholders even when embedded in an option.

    OpenSSH options such as ``UserKnownHostsFile=<path>`` are passed as one
    argument. Replacing only complete argv elements leaves the placeholder
    untouched and makes strict host-key verification read the wrong file.
    """
    resolved: list[str] = []
    for argument in argv:
        for placeholder, path in replacements.items():
            argument = argument.replace(placeholder, path)
        resolved.append(argument)
    return resolved


def _repository_secret(repository: Repository) -> str | None:
    return get_repository_secret(repository, "passphrase")


def repository_identity_file(repository: Repository) -> str:
    if repository.id is None:
        raise ValueError("Managed repository must be persisted before use")
    return f"~/.ssh/bbm_repository_{repository.id}_ed25519"


def _repository_uses_ssh(repository: Repository) -> bool:
    parsed = urlsplit(repository.location)
    return parsed.scheme == "ssh" or bool(re.match(r"^[^/@:]+@[^/:]+:.+", repository.location))


def _common_repository_env(repository: Repository) -> dict[str, str]:
    env = {"BORG_REPO": repository.location, "TZ": APP_TIMEZONE_NAME}
    if (repository.encryption_mode or "repokey-blake2") in {"none", "authenticated", "authenticated-blake2"}:
        env["BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK"] = "yes"
    secret = _repository_secret(repository)
    if secret is not None:
        env["_BBM_STDIN_SECRET"] = secret
    encryption_mode = repository.encryption_mode or "repokey-blake2"
    if encryption_mode.startswith("keyfile"):
        keyfile = get_repository_secret(repository, "keyfile")
        if not keyfile:
            raise ValueError("Keyfile repository has no stored Borg key")
        env["_BBM_KEYFILE"] = keyfile
        env["_BBM_KEYFILE_NAME"] = f"bbm_repository_{repository.id}"
    extra = load_repository_environment(repository)
    if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(key)) for key in extra):
        raise ValueError("Repository environment contains an invalid variable name")
    reserved = {
        "BORG_REPO", "BORG_RSH", "BORG_PASSPHRASE", "BORG_PASSPHRASE_FD",
        "BORG_PASSCOMMAND", "BORG_KEY_FILE", "BORG_CACHE_DIR", "BORG_SECURITY_DIR",
        "BORG_RELOCATED_REPO_ACCESS_IS_OK", "TZ", "PATH", "HOME", "SHELL", "USER", "LOGNAME",
        "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
        "ENV", "BASH_ENV", "IFS", "SSH_AUTH_SOCK", "SSH_AGENT_PID",
    }
    if reserved.intersection(extra):
        raise ValueError("Repository environment attempts to override a reserved Borg variable")
    env.update({str(k): str(v) for k, v in extra.items()})
    return env


def _remote_env(repository: Repository, *, verbose_ssh: bool = False) -> dict[str, str]:
    env = _common_repository_env(repository)
    if repository.id is None:
        raise ValueError("Repository must be persisted before client cache isolation is used")
    # Source devices receive a BBM-private, repository-scoped cache below the
    # connecting user's home directory. This avoids collisions with manually
    # executed Borg commands and with stale locks in Borg's historical default
    # ~/.cache/borg directory.
    env["_BBM_CLIENT_CACHE_KEY"] = f"repository-{repository.id}"
    common = (
        "-o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 "
        "-o ServerAliveInterval=10 -o ServerAliveCountMax=30"
    )
    if repository.storage_path:
        verbosity = " -vv" if verbose_ssh else ""
        env["BORG_RSH"] = (
            f"ssh{verbosity} -i {repository_identity_file(repository)} {common} "
            "-o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
            "-o UserKnownHostsFile=~/.ssh/bbm_repository_known_hosts"
        )
    elif _repository_uses_ssh(repository):
        ssh_key = get_repository_secret(repository, "external_ssh_private_key")
        known_hosts = get_repository_secret(repository, "external_known_hosts")
        if not ssh_key:
            raise ValueError("External repository has no manager SSH key configured")
        if not known_hosts:
            raise ValueError("External repository has no manager known_hosts entry configured")
        env["_BBM_EXTERNAL_SSH_KEY"] = ssh_key
        env["_BBM_EXTERNAL_KNOWN_HOSTS"] = known_hosts
        env["_BBM_EXTERNAL_SSH_VERBOSE"] = "1" if verbose_ssh else "0"
    return env


def _payload_line(value: str | None) -> bytes:
    if value is None:
        return b"-\n"
    return base64.b64encode(value.encode("utf-8")) + b"\n"


def _secret_payload(env: dict[str, str], *, required: bool = False) -> bytes | None:
    values = (
        env.get("_BBM_EXTERNAL_SSH_KEY"),
        env.get("_BBM_EXTERNAL_KNOWN_HOSTS"),
        env.get("_BBM_KEYFILE"),
        env.get("_BBM_STDIN_SECRET"),
    )
    if not required and not any(value is not None for value in values):
        return None
    return b"".join(_payload_line(value) for value in values)


_SECRET_WRAPPER = r'''
set -eu
umask 077
verbose="$1"
cache_key="$2"
shift 2
tmpdir=$(mktemp -d /tmp/bbm-borg.XXXXXX)
child_pid=""
child_group="0"
watchdog_pid=""
private_cache="0"
graceful_signal="TERM"

cleanup_files() { rm -rf -- "$tmpdir"; }

cleanup_private_cache_locks() {
  [ "$private_cache" = "1" ] || return 0
  [ -d "${BORG_CACHE_DIR:-}" ] || return 0
  # The child process has already ended and this path is private to BBM. Any
  # remaining cache lock is therefore stale and may be removed without touching
  # the repository lock or a user's normal ~/.cache/borg cache.
  find "$BORG_CACHE_DIR" -mindepth 2 -maxdepth 2 -type d -name lock.exclusive -exec rm -rf -- {} \; 2>/dev/null || true
  find "$BORG_CACHE_DIR" -mindepth 2 -maxdepth 2 -type f -name lock.roster -delete 2>/dev/null || true
}

stop_watchdog() {
  if [ -n "$watchdog_pid" ]; then
    kill "$watchdog_pid" 2>/dev/null || true
    wait "$watchdog_pid" 2>/dev/null || true
    watchdog_pid=""
  fi
}

signal_child() {
  sig="$1"
  [ -n "$child_pid" ] || return 0
  if [ "$child_group" = "1" ]; then
    /bin/kill -"$sig" -- "-$child_pid" 2>/dev/null || true
  else
    kill -"$sig" "$child_pid" 2>/dev/null || true
  fi
}

child_running() {
  [ -n "$child_pid" ] && kill -0 "$child_pid" 2>/dev/null
}

cancel_child() {
  # Ignore repeated connection/signal events while controlled cleanup runs.
  trap '' HUP INT TERM
  stop_watchdog
  if child_running; then
    # Prefer SIGINT when the child was started through the signal-reset helper.
    # This matches Ctrl-C and lets Borg cleanly release repository/cache locks.
    # On minimal clients without Python the shell may force background children
    # to inherit SIGINT=ignored, so TERM is used as the portable graceful signal.
    signal_child "$graceful_signal"
    count=0
    while child_running && [ "$count" -lt 200 ]; do
      sleep 0.1
      count=$((count + 1))
    done
    if child_running && [ "$graceful_signal" != "TERM" ]; then
      signal_child TERM
      count=0
      while child_running && [ "$count" -lt 50 ]; do
        sleep 0.1
        count=$((count + 1))
      done
    fi
    if child_running; then
      signal_child KILL
    fi
    wait "$child_pid" 2>/dev/null || true
  fi
  cleanup_private_cache_locks
  child_pid=""
  cleanup_files
  exit 130
}

trap cleanup_files EXIT
trap cancel_child HUP INT TERM
if [ "$cache_key" != "-" ]; then
  cache_number=${cache_key#repository-}
  case "$cache_key:$cache_number" in
    repository-[0-9]*:*[!0-9]*|repository-:*)
      printf '%s\n' 'FEHLER: Ungültiger BBM-Cache-Schlüssel.' >&2; exit 86 ;;
    repository-[0-9]*:[0-9]*) ;;
    *) printf '%s\n' 'FEHLER: Ungültiger BBM-Cache-Schlüssel.' >&2; exit 86 ;;
  esac
  cache_base="${XDG_CACHE_HOME:-$HOME/.cache}/borgbackup-manager"
  export BORG_CACHE_DIR="$cache_base/$cache_key"
  mkdir -p -- "$BORG_CACHE_DIR"
  chmod 700 -- "$cache_base" "$BORG_CACHE_DIR" 2>/dev/null || true
  private_cache="1"
fi
IFS= read -r ssh_key_b64
IFS= read -r known_hosts_b64
IFS= read -r borg_key_b64
IFS= read -r passphrase_b64
if [ "$ssh_key_b64" != "-" ]; then
  ssh_key="$tmpdir/id_ed25519"
  known_hosts="$tmpdir/known_hosts"
  printf '%s' "$ssh_key_b64" | base64 -d > "$ssh_key"
  printf '%s' "$known_hosts_b64" | base64 -d > "$known_hosts"
  chmod 600 "$ssh_key" "$known_hosts"
  ssh_verbosity=""
  [ "$verbose" = "1" ] && ssh_verbosity="-vv"
  export BORG_RSH="ssh $ssh_verbosity -i $ssh_key -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 -o ServerAliveInterval=10 -o ServerAliveCountMax=30 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$known_hosts"
fi
if [ "$borg_key_b64" != "-" ]; then
  borg_key="$tmpdir/borg-key"
  printf '%s' "$borg_key_b64" | base64 -d > "$borg_key"
  chmod 600 "$borg_key"
  export BORG_KEY_FILE="$borg_key"
fi
if [ "$passphrase_b64" != "-" ]; then
  passphrase="$tmpdir/passphrase"
  printf '%s' "$passphrase_b64" | base64 -d > "$passphrase"
  chmod 600 "$passphrase"
  # A shared BORG_PASSPHRASE_FD is consumed by the first Borg process. Commands
  # that invoke Borg repeatedly (for example bulk archive deletion followed by
  # compact) would therefore receive EOF and report an incorrect passphrase on
  # the second invocation. BORG_PASSCOMMAND opens the protected file anew for
  # every Borg process while keeping the secret itself out of argv and env.
  export BORG_PASSCOMMAND="cat '$passphrase'"
fi

# The manager deliberately leaves stdin open after the four payload lines.
# EOF therefore means that cancellation was requested or the controlling SSH
# connection disappeared. Monitor the original descriptor explicitly because
# POSIX shells may redirect stdin of background jobs to /dev/null.
exec 4<&0
parent_pid=$$
(
  # Use the shell builtin read instead of spawning cat. A separate cat process
  # would survive when only the watchdog subshell is stopped after a successful
  # command and keep the SSH/stdout pipes open indefinitely.
  while IFS= read -r _ <&4; do :; done
  kill -HUP "$parent_pid" 2>/dev/null || true
) &
watchdog_pid=$!
exec 4<&-

set +e
if command -v python3 >/dev/null 2>&1; then
  # Non-interactive shells may start background jobs with SIGINT ignored.
  # Reset dispositions and unblock the signals in a tiny Python process before
  # exec. Unlike the GNU env signal-reset extension, this works on clients whose `env` is
  # supplied by BusyBox or an older coreutils release. Borg installations from
  # Debian/Ubuntu packages already provide Python 3.
  if command -v setsid >/dev/null 2>&1; then
    python3 -S -c 'import os,signal,sys; s=(signal.SIGHUP,signal.SIGINT,signal.SIGTERM); [signal.signal(x,signal.SIG_DFL) for x in s]; hasattr(signal,"pthread_sigmask") and signal.pthread_sigmask(signal.SIG_UNBLOCK,s); os.execvp(sys.argv[1],sys.argv[1:])' setsid "$@" &
    child_group="1"
  else
    python3 -S -c 'import os,signal,sys; s=(signal.SIGHUP,signal.SIGINT,signal.SIGTERM); [signal.signal(x,signal.SIG_DFL) for x in s]; hasattr(signal,"pthread_sigmask") and signal.pthread_sigmask(signal.SIG_UNBLOCK,s); os.execvp(sys.argv[1],sys.argv[1:])' "$@" &
    child_group="0"
  fi
  graceful_signal="INT"
else
  # Borg may also be deployed as a standalone binary on a minimal client. Do
  # not fail the backup merely because Python is absent; start it directly and
  # use SIGTERM for controlled cancellation, because SIGINT may be inherited as
  # ignored by a background child.
  if command -v setsid >/dev/null 2>&1; then
    setsid "$@" &
    child_group="1"
  else
    "$@" &
    child_group="0"
  fi
  graceful_signal="TERM"
fi
child_pid=$!
wait "$child_pid"
rc=$?
set -e
cleanup_private_cache_locks
child_pid=""
stop_watchdog
exit "$rc"
'''.strip()


def _manager_repository_command(repository: Repository, parts: list[str], *, verbose_ssh: bool = False) -> Command:
    env = _common_repository_env(repository)
    # Manager-side Borg metadata must stay in /data. The repository root may be
    # an NFS mount and must contain repository data only, not ~/.cache or
    # ~/.config state belonging to the container user.
    env["BORG_CACHE_DIR"] = str(manager_repository_cache_dir(repository))
    env["BORG_SECURITY_DIR"] = str(MANAGER_BORG_SECURITY_DIR)
    if repository.storage_path:
        env["BORG_REPO"] = repository.storage_path
    elif _repository_uses_ssh(repository):
        ssh_key = get_repository_secret(repository, "external_ssh_private_key")
        known_hosts = get_repository_secret(repository, "external_known_hosts")
        if not ssh_key:
            raise ValueError("External repository has no manager SSH key configured")
        if not known_hosts:
            raise ValueError("External repository has no manager known_hosts entry configured")
        env["_BBM_EXTERNAL_SSH_KEY"] = ssh_key
        env["_BBM_EXTERNAL_KNOWN_HOSTS"] = known_hosts
        env["_BBM_EXTERNAL_SSH_VERBOSE"] = "1" if verbose_ssh else "0"
    payload = _secret_payload(env)
    public_env = {key: value for key, value in env.items() if not key.startswith("_BBM_")}
    if payload is not None:
        argv = manager_borg_argv([
            "sh", "-c", _SECRET_WRAPPER, "--",
            env.get("_BBM_EXTERNAL_SSH_VERBOSE", "0"), "-", *parts,
        ])
    else:
        argv = manager_borg_argv(parts)
    location = repository.storage_path or repository.location
    return Command(
        argv=argv,
        preview=f"[direkt im Manager] BORG_REPO={shlex.quote(location)} {shlex.join(parts)}",
        stdin_data=payload,
        env=public_env or None,
        stdin_controlled_cancel=payload is not None,
    )


def _local_repository_command(repository: Repository, parts: list[str]) -> Command:
    if not repository.storage_path:
        raise ValueError("Repository is not locally managed")
    return _manager_repository_command(repository, parts)


def repository_access_command(repository: Repository, parts: list[str], *, fallback_host: Host | None = None, verbose_ssh: bool = False) -> Command:
    # Repository administration is always executed by the Manager. fallback_host
    # remains in the signature for compatibility with older callers but is no
    # longer used for external repositories.
    return _manager_repository_command(repository, parts, verbose_ssh=verbose_ssh)


def _repository_operation(job: Job, parts: list[str]) -> Command:
    return repository_access_command(job.repository, parts)

def _ssh_argv(
    host: Host, remote_parts: Iterable[str], env: dict[str, str], *, supervised: bool = False
) -> Command:
    if not host.enabled:
        raise ValueError(f"Host {host.name} is disabled")
    public_env = {key: value for key, value in env.items() if not key.startswith("_BBM_")}
    command_parts = list(remote_parts)
    cache_key = env.get("_BBM_CLIENT_CACHE_KEY", "-")
    # Every source-device Borg command must pass through the supervised wrapper,
    # even when an unencrypted managed repository needs no secret payload. This
    # guarantees both repository-scoped client caching and controlled SIGINT
    # cancellation for all backup jobs, not only encrypted/external ones.
    payload = _secret_payload(env, required=supervised or cache_key != "-")
    if payload is not None:
        command_parts = [
            "sh", "-c", _SECRET_WRAPPER, "--", env.get("_BBM_EXTERNAL_SSH_VERBOSE", "0"),
            cache_key, *command_parts,
        ]
    assignments = [f"{key}={shlex.quote(value)}" for key, value in public_env.items()]
    remote = " ".join([*assignments, *(shlex.quote(part) for part in command_parts)])
    preview_env = dict(public_env)
    if env.get("_BBM_EXTERNAL_SSH_KEY"):
        preview_env["BORG_RSH"] = "ssh -i [temporärer Manager-Schlüssel] -o StrictHostKeyChecking=yes"
    preview_assignments = [f"{key}={shlex.quote(value)}" for key, value in preview_env.items()]
    preview_remote = " ".join([*preview_assignments, *(shlex.quote(part) for part in list(remote_parts))])
    controller_key = get_system_secret("controller_private_key")
    if not controller_key:
        raise ValueError("Controller-Schlüssel ist im Sicherheitsspeicher nicht vorhanden")
    if not host.host_key:
        raise ValueError(f"SSH-Hostkey für {host.name} fehlt")
    key_placeholder = "__BBM_CONTROLLER_KEY__"
    known_placeholder = "__BBM_CONTROLLER_KNOWN_HOSTS__"
    argv = [
        "ssh", "-i", key_placeholder,
        "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ConnectionAttempts=1",
        "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=30", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known_placeholder}",
        "-p", str(host.port), "--", f"{host.username}@{host.address}", remote,
    ]
    return Command(
        argv=argv,
        preview=f"ssh -i [temporärer Controller-Schlüssel] {host.username}@{host.address} -- {preview_remote}",
        stdin_data=payload,
        temp_files={key_placeholder: controller_key, known_placeholder: host.host_key.strip() + "\n"},
        stdin_controlled_cancel=payload is not None,
    )

def job_archive_prefix(job: Job) -> str:
    if job.archive_prefix:
        return job.archive_prefix
    if job.id is None:
        raise ValueError("Job must be persisted before Borg commands are generated")
    return f"bbm-{job.id}-"


def job_archive_prefixes(job: Job) -> list[str]:
    """Return the active compact prefix followed by historical job prefixes."""
    prefixes = [job_archive_prefix(job)]
    try:
        history = json.loads(getattr(job, "archive_prefix_history_json", "[]") or "[]")
    except (TypeError, json.JSONDecodeError):
        history = []
    if isinstance(history, list):
        for value in history:
            if isinstance(value, str) and value and value not in prefixes:
                prefixes.append(value)
    return prefixes


def job_archive_glob(job: Job) -> str:
    return f"{job_archive_prefix(job)}*"


def validate_archive_name(archive: str) -> str:
    archive = archive.strip()
    if (
        not archive
        or archive.startswith("-")
        or "::" in archive
        or any(c in archive for c in "\x00\r\n/")
    ):
        raise ValueError("Invalid archive name")
    return archive


def _validate_archive_paths(paths: list[str], purpose: str) -> list[str]:
    normalized: list[str] = []
    for value in paths:
        value = value.strip().strip("/")
        path = PurePosixPath(value)
        if not value or value.startswith("-") or ".." in path.parts or any(c in value for c in "\x00\r\n"):
            raise ValueError(f"{purpose} paths must be relative archive paths without '..'")
        normalized.append(value)
    return normalized


def _selection_root_strip_components(paths: list[str]) -> int:
    """Strip the common parent so selected items land directly in the target."""
    if not paths:
        return 0
    parent_parts = [PurePosixPath(value).parts[:-1] for value in paths]
    common: list[str] = []
    for components in zip(*parent_parts):
        if len(set(components)) != 1:
            break
        common.append(components[0])
    return len(common)


def _borg_base(command: str) -> list[str]:
    return ["borg", "--lock-wait", "600", command]


def backup_command(job: Job) -> Command:
    sources = json.loads(job.source_paths_json)
    excludes = json.loads(job.exclude_patterns_json)
    options = validate_create_options(json.loads(job.create_options_json or "{}"))
    # Human-readable Borg statistics are the primary live log. Raw JSON is reserved
    # for API operations which need machine-readable archive metadata.
    parts = [*_borg_base("create"), "--stats", "--show-rc", "--compression", job.compression]
    if options["list_files"]:
        parts.append("--list")
    else:
        # Even when the full file list is disabled, keep Borg's warning-relevant
        # item statuses in the log. ``C`` identifies files that changed while
        # being read and ``E`` identifies file-level access/read errors.
        parts.extend(["--list", "--filter", "CE"])
    if options["one_file_system"]:
        parts.append("--one-file-system")
    if options["exclude_caches"]:
        parts.append("--exclude-caches")
    if options["exclude_nodump"]:
        parts.append("--exclude-nodump")
    if options["numeric_ids"]:
        parts.append("--numeric-ids")
    parts.extend(["--files-cache", options["files_cache"]])
    parts.extend(["--checkpoint-interval", str(options["checkpoint_interval"])])
    for pattern in excludes:
        parts.extend(["--exclude", pattern])
    archive = f"{job_archive_prefix(job)}{job.archive_template}"
    parts.extend([f"::{archive}", *sources])
    file_list_header = ""
    if options["list_files"]:
        file_list_header = "\n".join([
            "printf '%s\\n' 'DATEIVERARBEITUNG (Borg-Status und Pfad):'",
            "printf '%s\\n' '------------------------------------------------------------------------------'",
        ])
    script = f"""
set +e
printf '%s\\n' '=============================================================================='
printf 'BACKUP-JOB: %s\\n' {shlex.quote(job.name)}
printf 'GERÄT:      %s\\n' {shlex.quote(job.host.name)}
printf 'QUELLPFADE: %s\\n' {shlex.quote(', '.join(sources))}
printf 'REPOSITORY: %s\\n' {shlex.quote(job.repository.name)}
printf '%s\\n' '------------------------------------------------------------------------------'
{version_probe_shell(fail_unsupported=True)}
printf '%s\\n' '------------------------------------------------------------------------------'
{file_list_header}
{shlex.join(parts)}
bbm_rc=$?
printf '%s\\n' '------------------------------------------------------------------------------'
if [ "$bbm_rc" -eq 0 ]; then
  printf '%s\\n' 'ERGEBNIS: Backup erfolgreich abgeschlossen.'
elif [ "$bbm_rc" -eq 1 ]; then
  printf '%s\\n' 'ERGEBNIS: Backup mit Warnungen abgeschlossen.' >&2
else
  printf 'ERGEBNIS: Backup fehlgeschlagen (RC %s).\\n' "$bbm_rc" >&2
fi
printf '%s\\n' '=============================================================================='
exit "$bbm_rc"
""".strip()
    return _ssh_argv(job.host, ["sh", "-c", script], _remote_env(job.repository))


def source_stats_command(job: Job) -> Command:
    """Scan configured source paths without accessing or modifying a repository.

    Borg 1.x does not permit ``create --dry-run`` together with ``--stats``.
    A manual refresh therefore performs a read-only filesystem traversal as the
    configured source-device SSH user. Exact post-exclusion values continue to
    come from a completed Borg backup and replace this preliminary scan.
    """
    sources = json.loads(job.source_paths_json or "[]")
    options = validate_create_options(json.loads(job.create_options_json or "{}"))
    one_file_system = "1" if options["one_file_system"] else "0"
    python_scan = r'''
import json
import os
import stat
import sys

one_file_system = sys.argv[1] == "1"
roots = sys.argv[2:]
size_bytes = 0
file_count = 0
warning_count = 0
seen_paths = set()


def warn(message):
    global warning_count
    warning_count += 1
    print("WARNUNG: " + message, file=sys.stderr)


def account(path, st):
    global size_bytes, file_count
    normalized = os.path.normpath(path)
    if normalized in seen_paths:
        return
    seen_paths.add(normalized)
    if stat.S_ISDIR(st.st_mode):
        return
    file_count += 1
    if stat.S_ISREG(st.st_mode):
        size_bytes += max(0, int(st.st_size))


for root in roots:
    try:
        root_stat = os.lstat(root)
    except OSError as exc:
        warn(f"{root}: {exc}")
        continue
    if not stat.S_ISDIR(root_stat.st_mode):
        account(root, root_stat)
        continue
    root_device = root_stat.st_dev
    normalized_root = os.path.normpath(root)
    if normalized_root in seen_paths:
        continue
    seen_paths.add(normalized_root)
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except OSError as exc:
            warn(f"{directory}: {exc}")
            continue
        for entry in entries:
            path = entry.path
            try:
                item_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                warn(f"{path}: {exc}")
                continue
            if stat.S_ISDIR(item_stat.st_mode):
                if one_file_system and item_stat.st_dev != root_device:
                    continue
                normalized_path = os.path.normpath(path)
                if normalized_path in seen_paths:
                    continue
                seen_paths.add(normalized_path)
                stack.append(path)
            else:
                account(path, item_stat)

print("BBM_SOURCE_STATS_JSON=" + json.dumps({
    "size_bytes": size_bytes,
    "file_count": file_count,
    "warning_count": warning_count,
    "method": "python-lstat",
}, separators=(",", ":")))
sys.exit(1 if warning_count else 0)
'''.strip()
    fallback_scan = r'''
set +e
tmpfile=$(mktemp /tmp/bbm-source-stats.XXXXXX) || exit 70
trap 'rm -f -- "$tmpfile"' EXIT HUP INT TERM
warnings=0
for source in "$@"; do
  if [ ! -e "$source" ] && [ ! -L "$source" ]; then
    printf 'WARNUNG: Quelle nicht gefunden: %s\n' "$source" >&2
    warnings=$((warnings + 1))
    continue
  fi
  if [ -d "$source" ]; then
    if [ "$one_file_system" = "1" ]; then
      find "$source" -xdev \( -type f -o -type l \) -exec stat -c '%s' {} \; >>"$tmpfile" 2>/dev/null
    else
      find "$source" \( -type f -o -type l \) -exec stat -c '%s' {} \; >>"$tmpfile" 2>/dev/null
    fi
    rc=$?
  else
    stat -c '%s' "$source" >>"$tmpfile" 2>/dev/null
    rc=$?
  fi
  if [ "$rc" -ne 0 ]; then
    printf 'WARNUNG: Quelle konnte nicht vollständig gelesen werden: %s\n' "$source" >&2
    warnings=$((warnings + 1))
  fi
done
awk -v warnings="$warnings" '
  { size += $1; count += 1 }
  END {
    printf "BBM_SOURCE_STATS_JSON={\"size_bytes\":%.0f,\"file_count\":%d,\"warning_count\":%d,\"method\":\"find-stat\"}\n", size, count, warnings
  }
' "$tmpfile"
[ "$warnings" -eq 0 ]
'''.strip()
    script = f'''
set +e
printf '%s\n' '=== Quellenstatistik aktualisieren (Live-Scan) ==='
printf 'BACKUP-JOB: %s\n' {shlex.quote(job.name)}
printf 'QUELLPFADE: %s\n' {shlex.quote(', '.join(sources))}
printf '%s\n' 'Hinweis: Der manuelle Scan zählt die konfigurierten Quellen vor Borg-Ausschlüssen.'
printf '%s\n' 'Das Repository wird nicht geöffnet und es wird kein Archiv geschrieben.'
printf '%s\n' '------------------------------------------------------------------------------'
one_file_system={one_file_system}
if command -v python3 >/dev/null 2>&1; then
  python3 -S -c {shlex.quote(python_scan)} "$one_file_system" "$@"
  bbm_rc=$?
elif command -v find >/dev/null 2>&1 && command -v stat >/dev/null 2>&1 && stat -c '%s' / >/dev/null 2>&1; then
  {fallback_scan}
  bbm_rc=$?
else
  printf '%s\n' 'FEHLER: Für die Quellenstatistik wird Python 3 oder eine kompatible find/stat-Umgebung benötigt.' >&2
  bbm_rc=2
fi
printf '%s\n' '------------------------------------------------------------------------------'
if [ "$bbm_rc" -eq 0 ]; then
  printf '%s\n' 'ERGEBNIS: Quellenstatistik erfolgreich aktualisiert.'
elif [ "$bbm_rc" -eq 1 ]; then
  printf '%s\n' 'ERGEBNIS: Quellenstatistik mit Warnungen aktualisiert.' >&2
else
  printf 'ERGEBNIS: Quellenstatistik fehlgeschlagen (RC %s).\n' "$bbm_rc" >&2
fi
exit "$bbm_rc"
'''.strip()
    return _ssh_argv(
        job.host,
        ["sh", "-c", script, "--", *sources],
        {},
        supervised=True,
    )

def prune_command(job: Job) -> Command:
    options = json.loads(job.prune_options_json or "{}")
    retention: list[str] = []
    for key in ("last", "hourly", "daily", "weekly", "monthly", "yearly"):
        value = options.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            retention.extend([f"--keep-{key}", str(value)])
    prefixes = job_archive_prefixes(job)
    commands = [
        [*_borg_base("prune"), "--list", "--show-rc", "--glob-archives", f"{prefix}*", *retention]
        for prefix in prefixes
    ]
    if len(commands) == 1:
        return _repository_operation(job, commands[0])
    script_lines = ["set +e", "bbm_result=0"]
    for command in commands:
        script_lines.extend([
            shlex.join(command),
            "bbm_rc=$?",
            'if [ "$bbm_rc" -gt "$bbm_result" ]; then bbm_result="$bbm_rc"; fi',
        ])
    script_lines.append('exit "$bbm_result"')
    return _repository_operation(job, ["sh", "-c", "\n".join(script_lines)])


def host_version_command(host: Host) -> Command:
    script = "\n".join([
        "printf '%s\\n' '=== Borg-Version und Kompatibilität ==='",
        version_probe_shell(fail_unsupported=False),
    ])
    return _ssh_argv(host, ["sh", "-c", script], {})


def repository_command(job: Job, action: str, *, consider_checkpoints: bool = False) -> Command:
    if action == "version":
        script = "\n".join([
            "printf '%s\\n' '=== Borg-Version und Kompatibilität ==='",
            version_probe_shell(fail_unsupported=False),
        ])
        return _ssh_argv(job.host, ["sh", "-c", script], {})
    archive_glob = job_archive_glob(job)
    archive_prefixes = job_archive_prefixes(job)
    list_checkpoint_option = ["--consider-checkpoints"] if consider_checkpoints else []
    if len(archive_prefixes) > 1 and action in {"list", "info", "check", "verify"}:
        commands: list[list[str]] = []
        for prefix in archive_prefixes:
            scoped_glob = f"{prefix}*"
            if action == "list":
                commands.append([*_borg_base("list"), "--json", *list_checkpoint_option, "--glob-archives", scoped_glob])
            elif action == "info":
                commands.append([*_borg_base("info"), "--json", "--glob-archives", scoped_glob])
            elif action == "check":
                commands.append([*_borg_base("check"), "--show-rc", "--glob-archives", scoped_glob])
            else:
                commands.append([
                    *_borg_base("check"), "--show-rc", "--archives-only", "--verify-data",
                    "--glob-archives", scoped_glob,
                ])
        script_lines = ["set +e", "bbm_result=0"]
        for command in commands:
            script_lines.extend([
                shlex.join(command),
                "bbm_rc=$?",
                'if [ "$bbm_rc" -gt "$bbm_result" ]; then bbm_result="$bbm_rc"; fi',
            ])
        script_lines.append('exit "$bbm_result"')
        return _repository_operation(job, ["sh", "-c", "\n".join(script_lines)])
    allowed = {
        "list": [*_borg_base("list"), "--json", *list_checkpoint_option, "--glob-archives", archive_glob],
        "list-all": [*_borg_base("list"), "--json", *list_checkpoint_option],
        "info": [*_borg_base("info"), "--json", "--glob-archives", archive_glob],
        "check": [*_borg_base("check"), "--show-rc", "--glob-archives", archive_glob],
        "verify": [
            *_borg_base("check"), "--show-rc", "--archives-only", "--verify-data",
            "--glob-archives", archive_glob,
        ],
        "compact": [*_borg_base("compact"), "--verbose", "--show-rc"],
    }
    if action == "confirm-location":
        env = _remote_env(job.repository, verbose_ssh=False)
        # Borg intentionally requires explicit approval when the same repository
        # ID appears under a different location. This one-shot action answers
        # only that single safety prompt and lets Borg update the client-side
        # security metadata. Normal jobs never receive this environment value.
        env["BORG_RELOCATED_REPO_ACCESS_IS_OK"] = "yes"
        script = rf'''
set -eu
printf '%s\n' '=== Repository-Standort bestätigen ==='
printf '%s\n' 'Repository-Aktionen werden serialisiert; Borg wartet bei Bedarf bis zu 600 Sekunden auf eine aktive Sperre.'
set +e
borg --lock-wait 600 info --json --show-rc --glob-archives {shlex.quote(archive_glob)}
bbm_rc=$?
set -e
if [ "$bbm_rc" -le 1 ]; then
  printf '%s\n' 'Repository-Standort wurde für diesen Client bestätigt.'
fi
exit "$bbm_rc"
'''.strip()
        return _ssh_argv(job.host, ["sh", "-c", script], env)
    if action == "probe":
        checks = ""
        if job.repository.storage_path:
            identity = repository_identity_file(job.repository)
            parsed = urlsplit(job.repository.location)
            if not parsed.hostname:
                raise ValueError("Managed repository URL has no SSH host")
            repository_host = parsed.hostname
            repository_port = parsed.port or 22
            checks = rf'''
key="$HOME/{identity[2:]}"
known="$HOME/.ssh/bbm_repository_known_hosts"
printf '%s\n' '=== Repository-SSH-Dateien ==='
for path in "$key" "$known"; do
  if [ ! -f "$path" ]; then
    printf 'FEHLER: Datei fehlt: %s\n' "$path" >&2
    exit 72
  fi
  if [ ! -r "$path" ]; then
    printf 'FEHLER: Datei ist nicht lesbar: %s\n' "$path" >&2
    exit 73
  fi
  ls -l "$path"
done
printf '%s\n' '=== Repository-SSH-Banner/Hostkey ==='
scan_file=$(mktemp)
trap 'rm -f "$scan_file"' EXIT
if ! ssh-keyscan -T 10 -t ed25519 -p {repository_port} {shlex.quote(repository_host)} >"$scan_file" 2>&1; then
  cat "$scan_file" >&2
  printf 'FEHLER: Repository-SSH-Dienst liefert keinen SSH-Banner/Hostkey.\n' >&2
  exit 75
fi
cat "$scan_file"
'''
        script = rf'''
set -eu
printf '%s\n' '=== Borg-Client ==='
{version_probe_shell(fail_unsupported=True)}
{checks}
printf '%s\n' '=== Repository-Verbindung ==='
exec borg --debug --lock-wait 30 info --json --show-rc --glob-archives {shlex.quote(archive_glob)}
'''.strip()
        return _ssh_argv(
            job.host,
            ["sh", "-c", script],
            _remote_env(job.repository, verbose_ssh=bool(job.repository.storage_path)),
        )
    if action not in allowed:
        raise ValueError(f"Unsupported action: {action}")
    return _repository_operation(job, allowed[action])


def archive_info_command(job: Job, archive: str) -> Command:
    archive = validate_archive_name(archive)
    return _repository_operation(job, [*_borg_base("info"), "--json", f"::{archive}"])


def repository_compact_command(repository: Repository) -> Command:
    """Compact an entire repository directly from the manager."""
    return repository_access_command(
        repository, [*_borg_base("compact"), "--verbose", "--show-rc"]
    )


def delete_archives_command(
    repository: Repository, archives: list[str], compact_after: bool = True
) -> Command:
    """Delete one or more exact archives and compact at most once afterwards."""
    safe_archives = [validate_archive_name(archive) for archive in archives]
    if not safe_archives:
        raise ValueError("At least one archive must be selected")
    if len(set(safe_archives)) != len(safe_archives):
        raise ValueError("Archive names must be unique")

    if len(safe_archives) == 1 and not compact_after:
        return repository_access_command(
            repository,
            [*_borg_base("delete"), "--stats", "--show-rc", f"::{safe_archives[0]}"],
        )

    script_lines = ["set +e", "bbm_result=0"]
    for archive in safe_archives:
        delete_parts = [*_borg_base("delete"), "--stats", "--show-rc", f"::{archive}"]
        script_lines.extend([
            f"printf '%s\\n' {shlex.quote('=== Archiv löschen: ' + archive + ' ===')}",
            shlex.join(delete_parts),
            "bbm_rc=$?",
            'if [ "$bbm_rc" -gt 1 ]; then exit "$bbm_rc"; fi',
            'if [ "$bbm_rc" -gt "$bbm_result" ]; then bbm_result="$bbm_rc"; fi',
        ])
    if compact_after:
        compact_parts = [*_borg_base("compact"), "--verbose", "--show-rc"]
        script_lines.extend([
            "printf '%s\\n' '=== Repository Compact ==='",
            shlex.join(compact_parts),
            "bbm_rc=$?",
            'if [ "$bbm_rc" -gt "$bbm_result" ]; then bbm_result="$bbm_rc"; fi',
        ])
    script_lines.append('exit "$bbm_result"')
    return repository_access_command(repository, ["sh", "-c", "\n".join(script_lines)])


def delete_archive_command(job: Job, archive: str, compact_after: bool = True) -> Command:
    """Backward-compatible job wrapper for repository-wide archive deletion."""
    return delete_archives_command(job.repository, [archive], compact_after)


def rename_archive_command(job: Job, archive: str, new_name: str) -> Command:
    archive = validate_archive_name(archive)
    new_name = validate_archive_name(new_name)
    if archive == new_name:
        raise ValueError("New archive name must differ from the current name")
    return _repository_operation(job, [*_borg_base("rename"), "--show-rc", f"::{archive}", new_name])


def diff_archives_command(
    job: Job,
    archive: str,
    second_archive: str,
    paths: list[str] | None = None,
    content_only: bool = False,
) -> Command:
    archive = validate_archive_name(archive)
    second_archive = validate_archive_name(second_archive)
    if archive == second_archive:
        raise ValueError("Two different archives are required")
    safe_paths: list[str] = []
    for value in paths or []:
        path = PurePosixPath(value)
        if not value or value.startswith(("-", "/")) or ".." in path.parts or any(c in value for c in "\x00\r\n"):
            raise ValueError("Diff paths must be relative archive paths without '..'")
        safe_paths.append(value)
    parts = [*_borg_base("diff"), "--json-lines"]
    if content_only:
        parts.append("--content-only")
    parts.extend([f"::{archive}", second_archive, *safe_paths])
    return _repository_operation(job, parts)


def browse_archive_command(job: Job, archive: str, relative_path: str = "") -> Command:
    archive = validate_archive_name(archive)
    relative = PurePosixPath(relative_path or ".")
    if relative_path.startswith("/") or ".." in relative.parts or any(c in relative_path for c in "\x00\r\n"):
        raise ValueError("Invalid archive browser path")
    current = relative_path.strip("/")
    prefix = re.escape(current + "/" if current else "")
    direct_children = f"re:^{prefix}[^/]+$"
    parts = [
        *_borg_base("list"),
        "--json-lines",
        "--format", "{path}{type}{size}{mtime}{source}{mode}{user}{group}{uid}{gid}",
        "--pattern", f"+ {direct_children}",
        "--pattern", "- re:.*",
        f"::{archive}",
    ]
    return _repository_operation(job, parts)


def mount_archive_command(job: Job, archive: str) -> Command:
    archive = validate_archive_name(archive)
    suffix = hashlib.sha256(archive.encode("utf-8")).hexdigest()[:12]
    mount_name = f"job-{job.id}-{suffix}"
    script = r'''
set -eu
archive="$1"
mount_name="$2"
command -v mountpoint >/dev/null 2>&1 || {
  printf '%s\n' 'FEHLER: mountpoint fehlt auf dem Client (Paket util-linux).' >&2
  exit 76
}
if ! command -v fusermount3 >/dev/null 2>&1 && ! command -v fusermount >/dev/null 2>&1; then
  printf '%s\n' 'FEHLER: FUSE fehlt auf dem Client (unter Debian/Ubuntu Paket fuse3 installieren).' >&2
  exit 79
fi
[ -e /dev/fuse ] || {
  printf '%s\n' 'FEHLER: /dev/fuse ist auf dem Client nicht verfügbar.' >&2
  exit 80
}
mount_root="$HOME/.local/share/bbm/mounts"
mount_path="$mount_root/$mount_name"
mkdir -p "$mount_path"
if ! mountpoint -q "$mount_path"; then
  borg --lock-wait 600 mount "::$archive" "$mount_path"
fi
if ! mountpoint -q "$mount_path"; then
  printf 'FEHLER: Archiv wurde nicht eingehängt: %s\n' "$mount_path" >&2
  exit 77
fi
printf 'BBM_MOUNT_PATH=%s\n' "$mount_path"
'''.strip()
    return _ssh_argv(
        job.host,
        ["sh", "-c", script, "--", archive, mount_name],
        _remote_env(job.repository),
    )


def unmount_archive_command(job: Job, mount_path: str) -> Command:
    path = PurePosixPath(mount_path)
    if not mount_path.startswith("/") or ".." in path.parts or any(c in mount_path for c in "\x00\r\n"):
        raise ValueError("Invalid mount path")
    script = r'''
set -eu
mount_path="$1"
if command -v mountpoint >/dev/null 2>&1 && mountpoint -q "$mount_path"; then
  borg umount "$mount_path"
fi
rmdir "$mount_path" 2>/dev/null || true
printf 'BBM_UNMOUNTED=%s\n' "$mount_path"
'''.strip()
    return _ssh_argv(job.host, ["sh", "-c", script, "--", mount_path], {})


def browse_mount_command(job: Job, mount_path: str, relative_path: str = "") -> Command:
    mount = PurePosixPath(mount_path)
    relative = PurePosixPath(relative_path or ".")
    if not mount_path.startswith("/") or ".." in mount.parts or any(c in mount_path for c in "\x00\r\n"):
        raise ValueError("Invalid mount path")
    if relative_path.startswith("/") or ".." in relative.parts or any(c in relative_path for c in "\x00\r\n"):
        raise ValueError("Invalid archive browser path")
    script = r'''
set -eu
mount_path="$1"
relative_path="$2"
command -v mountpoint >/dev/null 2>&1 || exit 76
mountpoint -q "$mount_path" || {
  printf 'FEHLER: Archiv ist nicht mehr eingehängt: %s\n' "$mount_path" >&2
  exit 77
}
target="$mount_path"
if [ -n "$relative_path" ]; then target="$mount_path/$relative_path"; fi
[ -d "$target" ] || {
  printf 'FEHLER: Verzeichnis im Archiv nicht gefunden: %s\n' "$relative_path" >&2
  exit 78
}
command -v find >/dev/null 2>&1 || {
  printf '%s\n' 'FEHLER: find fehlt auf dem Client (unter Debian/Ubuntu Paket findutils).' >&2
  exit 84
}
if ! find "$target" -maxdepth 0 -printf '' >/dev/null 2>&1; then
  printf '%s\n' 'FEHLER: Der Archivbrowser benötigt GNU find mit -printf (Paket findutils).' >&2
  exit 85
fi
find "$target" -mindepth 1 -maxdepth 1 -printf '%f\0%y\0%s\0%T@\0%l\0'
'''.strip()
    return _ssh_argv(job.host, ["sh", "-c", script, "--", mount_path, relative_path], {})


def repository_init_command(repository: Repository) -> Command:
    if not repository.storage_path:
        raise ValueError("Only managed repositories can be initialized by the manager")
    secret = _repository_secret(repository)
    encryption = repository.encryption_mode or "repokey-blake2"
    if encryption == "none" and secret is not None:
        raise ValueError("Unencrypted repositories cannot use a passphrase")
    if encryption != "none" and secret is None:
        raise ValueError(f"Encryption mode {encryption} requires a passphrase")
    env = {
        "BORG_CACHE_DIR": str(manager_repository_cache_dir(repository)),
        "BORG_SECURITY_DIR": str(MANAGER_BORG_SECURITY_DIR),
    }
    if secret is not None:
        env["BORG_PASSPHRASE_FD"] = "0"
    if encryption.startswith("keyfile"):
        env["BORG_KEY_FILE"] = str(repository_keyfile_path(repository))
    return Command(
        argv=manager_borg_argv([
            "borg", "--lock-wait", "600", "init",
            f"--encryption={encryption}", repository.storage_path,
        ]),
        preview=f"borg --lock-wait 600 init --encryption={encryption} {shlex.quote(repository.storage_path)}",
        stdin_data=(secret + "\n").encode() if secret is not None else None,
        env=env,
    )


def repository_cache_delete_command(repository: Repository) -> Command:
    """Delete only Borg's local manager cache for an external repository."""
    return repository_access_command(
        repository,
        ["borg", "--lock-wait", "30", "delete", "--cache-only"],
        verbose_ssh=False,
    )


def repository_validation_command(repository: Repository) -> Command:
    return repository_access_command(
        repository,
        ["borg", "--lock-wait", "30", "info", "--json"],
        # Normal validation must stay concise. OpenSSH -vv output contains
        # hundreds of negotiation lines and obscures the actionable error.
        verbose_ssh=False,
    )


def repository_size_command(repository: Repository) -> Command:
    """Return repository-wide Borg statistics for remote size estimation."""
    return repository_access_command(
        repository,
        ["borg", "--lock-wait", "30", "info", "--json"],
        verbose_ssh=False,
    )


def repository_archives_info_command(repository: Repository) -> Command:
    """Return repository totals and detailed statistics for all regular archives."""
    return repository_access_command(
        repository,
        ["borg", "--lock-wait", "30", "info", "--json", "--glob-archives", "*"],
        verbose_ssh=False,
    )


def repository_list_command(repository: Repository, *, consider_checkpoints: bool = False) -> Command:
    options = ["--consider-checkpoints"] if consider_checkpoints else []
    return repository_access_command(repository, [*_borg_base("list"), "--json", *options])


def repository_archive_info_command(repository: Repository, archive: str) -> Command:
    archive = validate_archive_name(archive)
    return repository_access_command(repository, [*_borg_base("info"), "--json", f"::{archive}"])


def repository_browse_archive_command(repository: Repository, archive: str, relative_path: str = "") -> Command:
    archive = validate_archive_name(archive)
    relative = PurePosixPath(relative_path or ".")
    if relative_path.startswith("/") or ".." in relative.parts or any(c in relative_path for c in "\x00\r\n"):
        raise ValueError("Invalid archive browser path")
    current = relative_path.strip("/")
    prefix = re.escape(current + "/" if current else "")
    direct_children = f"re:^{prefix}[^/]+$"
    parts = [
        *_borg_base("list"),
        "--json-lines",
        "--format", "{path}{type}{size}{mtime}{source}{mode}{user}{group}{uid}{gid}",
        "--pattern", f"+ {direct_children}",
        "--pattern", "- re:.*",
        f"::{archive}",
    ]
    return repository_access_command(repository, parts)


def repository_keyfile_path(repository: Repository) -> PurePosixPath:
    if repository.id is None:
        raise ValueError("Repository must be persisted before creating a keyfile")
    return PurePosixPath(REPOSITORY_KEYFILES_PATH) / f"repository-{repository.id}.key"


def host_repository_bootstrap_command(
    host: Host,
    known_hosts_line: str,
    repository_ids: list[int],
) -> Command:
    if not repository_ids:
        raise ValueError("Host has no managed repository assignments")
    script = """
set -eu
umask 077
mkdir -p "$HOME/.ssh"
known="$HOME/.ssh/bbm_repository_known_hosts"
printf '%s\n' "$1" > "$known"
shift
for repository_id in "$@"; do
  case "$repository_id" in *[!0-9]*|'') exit 74 ;; esac
  key="$HOME/.ssh/bbm_repository_${repository_id}_ed25519"
  if [ ! -f "$key" ]; then
    ssh-keygen -q -t ed25519 -N '' -C "bbm-repository-${repository_id}" -f "$key"
  fi
  chmod 600 "$key" "$known"
  printf 'BBM_REPOSITORY_KEY %s ' "$repository_id"
  cat "$key.pub"
done
""".strip()
    return _ssh_argv(
        host,
        ["sh", "-c", script, "--", known_hosts_line, *(str(value) for value in repository_ids)],
        {},
    )


async def scan_host_key(address: str, port: int) -> tuple[str, str]:
    scan = await asyncio.create_subprocess_exec(
        "ssh-keyscan", "-T", "10", "-H", "-t", "ed25519", "-p", str(port), "--", address,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await scan.communicate()
    lines = [line for line in stdout.decode(errors="replace").splitlines() if line and not line.startswith("#")]
    if scan.returncode != 0 or not lines:
        message = stderr.decode(errors="replace").strip() or "No ed25519 host key returned"
        raise ValueError(f"SSH host key scan failed: {message}")
    line = lines[0]
    fingerprint_process = await asyncio.create_subprocess_exec(
        "ssh-keygen", "-lf", "-", stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    fingerprint_out, fingerprint_err = await fingerprint_process.communicate(input=(line + "\n").encode())
    if fingerprint_process.returncode != 0:
        raise ValueError(f"SSH fingerprint failed: {fingerprint_err.decode(errors='replace').strip()}")
    fields = fingerprint_out.decode(errors="replace").strip().split()
    fingerprint = fields[1] if len(fields) > 1 else fingerprint_out.decode(errors="replace").strip()
    return line, fingerprint


def restore_command(
    job: Job,
    archive: str,
    paths: list[str],
    target: str | None,
    dry_run: bool,
    allow_legacy_archive: bool = False,
    restore_mode: str = "target",
    target_layout: str = "archive-paths",
    overwrite_existing: bool = False,
) -> Command:
    archive = validate_archive_name(archive)
    if not allow_legacy_archive and not any(archive.startswith(prefix) for prefix in job_archive_prefixes(job)):
        raise ValueError("Archive does not belong to this job; enable legacy restore explicitly if required")
    paths = _validate_archive_paths(paths, "Restore")
    if restore_mode not in {"original", "target"}:
        raise ValueError("Unsupported restore destination mode")
    if target_layout not in {"selection-root", "archive-paths"}:
        raise ValueError("Unsupported restore path layout")

    if restore_mode == "original":
        if not paths:
            raise ValueError("Restore to original locations requires selected archive paths")
        if not dry_run and not overwrite_existing:
            raise ValueError("In-place restore requires explicit overwrite confirmation")
        effective_target = "/"
    else:
        if not target:
            raise ValueError("Restore target is required")
        target_path = PurePosixPath(target)
        if not target.startswith("/") or ".." in target_path.parts or any(c in target for c in "\x00\r\n"):
            raise ValueError("Restore target must be a safe absolute path")
        effective_target = target

    extract = [*_borg_base("extract"), "--list"]
    if dry_run:
        extract.append("--dry-run")
    if restore_mode == "target" and target_layout == "selection-root" and paths:
        strip_components = _selection_root_strip_components(paths)
        if strip_components:
            extract.extend(["--strip-components", str(strip_components)])
    extract.extend([f"::{archive}", *paths])

    script = rf'''
set -eu
target="$1"
dry_run="$2"
restore_mode="$3"
layout="$4"
printf '%s\n' '=============================================================================='
printf 'RESTORE-MODUS: %s\n' "$restore_mode"
printf 'ZIEL:           %s\n' "$target"
printf 'PFADLAYOUT:     %s\n' "$layout"
printf '%s\n' '------------------------------------------------------------------------------'
if [ "$restore_mode" = "original" ]; then
  cd -- /
elif [ "$dry_run" = "1" ]; then
  cd -- /
else
  if [ -L "$target" ]; then
    printf 'FEHLER: Restore-Ziel darf kein symbolischer Link sein: %s\n' "$target" >&2
    exit 81
  fi
  if [ -e "$target" ] && [ ! -d "$target" ]; then
    printf 'FEHLER: Restore-Ziel ist kein Verzeichnis: %s\n' "$target" >&2
    exit 82
  fi
  mkdir -p -- "$target"
  if find "$target" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    printf 'FEHLER: Alternatives Restore-Ziel ist nicht leer: %s\n' "$target" >&2
    exit 83
  fi
  cd -- "$target"
fi
exec {shlex.join(extract)}
'''.strip()
    return _ssh_argv(
        job.host,
        ["sh", "-c", script, "--", effective_target, "1" if dry_run else "0", restore_mode, target_layout],
        _remote_env(job.repository),
    )


def archive_export_command(job: Job, archive: str, paths: list[str], destination: str) -> Command:
    archive = validate_archive_name(archive)
    paths = _validate_archive_paths(paths, "Export")
    if not paths:
        raise ValueError("At least one archive path must be selected")
    destination_path = PurePosixPath(destination)
    export_root = str(EXPORT_DIR.resolve())
    if not destination.startswith(export_root + "/") or ".." in destination_path.parts or any(c in destination for c in "\x00\r\n"):
        raise ValueError("Invalid export working directory")
    extract = [*_borg_base("extract"), "--list"]
    strip_components = _selection_root_strip_components(paths)
    if strip_components:
        extract.extend(["--strip-components", str(strip_components)])
    extract.extend([f"::{archive}", *paths])
    script = rf'''
set -eu
destination="$1"
mkdir -p -- "$destination"
cd -- "$destination"
exec {shlex.join(extract)}
'''.strip()
    return repository_access_command(job.repository, ["sh", "-c", script, "--", destination])


async def execute(
    command: Command,
    on_output: Callable[[str, str], Awaitable[None] | None] | None = None,
    capture_limit_bytes: int | None = None,
) -> tuple[int, str, str]:
    process_env = {**os.environ, **command.env} if command.env else None
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    process: asyncio.subprocess.Process | None = None
    argv = list(command.argv)

    def signal_process_group(sig: signal.Signals) -> None:
        if process is None or process.returncode is not None:
            return
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        except (PermissionError, OSError):
            try:
                process.send_signal(sig)
            except ProcessLookupError:
                pass

    async def wait_after_signal(sig: signal.Signals, timeout: float) -> bool:
        signal_process_group(sig)
        if process is None:
            return True
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    try:
        if command.temp_files:
            temporary_directory = tempfile.TemporaryDirectory(prefix="bbm-command-", dir=tempfile.gettempdir())
            root = Path(temporary_directory.name)
            replacements: dict[str, str] = {}
            for index, (placeholder, content) in enumerate(command.temp_files.items(), start=1):
                path = root / f"secret-{index}"
                path.write_text(content, encoding="utf-8")
                os.chmod(path, 0o600)
                replacements[placeholder] = str(path)
            argv = _replace_temp_file_placeholders(argv, replacements)

        # Every Borg invocation receives its own process group. Cancelling the
        # asyncio task must reach borg itself, not only wrappers such as runuser,
        # sh or ssh. SIGINT is deliberately used first so Borg can close files,
        # remove cache/repository locks and leave a consistent checkpoint.
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if command.stdin_data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=process_env,
            start_new_session=True,
        )
        output_parts: dict[str, list[str]] = {"stdout": [], "stderr": []}
        output_sizes: dict[str, int] = {"stdout": 0, "stderr": 0}

        def capture(name: str, text: str) -> None:
            output_parts[name].append(text)
            output_sizes[name] += len(text.encode("utf-8", errors="replace"))
            if not capture_limit_bytes or capture_limit_bytes <= 0:
                return
            while output_parts[name] and output_sizes[name] > capture_limit_bytes:
                removed = output_parts[name].pop(0)
                output_sizes[name] -= len(removed.encode("utf-8", errors="replace"))

        async def pump(name: str, stream: asyncio.StreamReader | None) -> None:
            if stream is None:
                return
            while chunk := await stream.read(4096):
                text = chunk.decode(errors="replace")
                capture(name, text)
                if on_output:
                    result = on_output(name, text)
                    if result is not None:
                        await result

        if command.stdin_data is not None and process.stdin:
            process.stdin.write(command.stdin_data)
            await process.stdin.drain()
            if not command.stdin_controlled_cancel:
                process.stdin.close()

        stdout_task = asyncio.create_task(pump("stdout", process.stdout))
        stderr_task = asyncio.create_task(pump("stderr", process.stderr))
        wait_task = asyncio.create_task(process.wait())
        process_tasks = asyncio.gather(stdout_task, stderr_task, wait_task)
        try:
            await asyncio.wait_for(asyncio.shield(process_tasks), timeout=COMMAND_TIMEOUT)
        except TimeoutError:
            if not await wait_after_signal(signal.SIGTERM, 5):
                await wait_after_signal(signal.SIGKILL, 5)
            await asyncio.gather(process_tasks, return_exceptions=True)
            return 124, "".join(output_parts["stdout"]), "Command timed out"
        except asyncio.CancelledError:
            # Commands using the secret wrapper have a dedicated cancellation
            # channel: closing stdin after the payload makes the remote wrapper
            # signal Borg itself and wait for its shutdown. This avoids killing
            # the local ssh client before the remote Borg process has released
            # an external repository lock.
            forced = False
            wrapper_confirmed = False
            if command.stdin_controlled_cancel and process.stdin:
                if not process.stdin.is_closing():
                    process.stdin.close()
                    try:
                        await process.stdin.wait_closed()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                try:
                    await asyncio.wait_for(asyncio.shield(process_tasks), timeout=25)
                    wrapper_confirmed = True
                except TimeoutError:
                    wrapper_confirmed = False
            if not wrapper_confirmed:
                # Fallback for commands without the wrapper or a remote wrapper
                # that no longer responds. SIGINT still comes first so Borg can
                # perform its normal checkpoint and lock cleanup.
                if not await wait_after_signal(signal.SIGINT, 20):
                    forced = True
                    if not await wait_after_signal(signal.SIGTERM, 5):
                        await wait_after_signal(signal.SIGKILL, 5)
            await asyncio.gather(process_tasks, return_exceptions=True)
            raise CommandCancelled(
                forced=forced,
                remote_cleanup_confirmed=wrapper_confirmed,
            )
        return process.returncode or 0, "".join(output_parts["stdout"]), "".join(output_parts["stderr"])
    finally:
        if process is not None and process.stdin and not process.stdin.is_closing():
            process.stdin.close()
        if process is not None and process.returncode is None:
            signal_process_group(signal.SIGKILL)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                pass
        if temporary_directory is not None:
            temporary_directory.cleanup()

