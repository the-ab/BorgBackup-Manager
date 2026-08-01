from __future__ import annotations

import asyncio
import base64
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
from app.external_repository import storage_probe_target_from_location
from app.models import Host, Job, Repository
from app.repository_cache import manager_repository_cache_dir
from app.schemas import validate_create_options
from app.vault import get_repository_secret, get_system_secret, load_repository_environment


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
    timeout_seconds: int | None = None
    # Manager-side Borg commands share one persistent cache per repository.
    # The service serializes these commands separately from client-side backup
    # jobs so metadata requests cannot race prune/compact on the same cache.
    manager_cache_repository_id: int | None = None
    # Archive-mount lifecycle commands and repository-independent source scans
    # may run while a manager-side archive mount record exists. All other
    # repository commands are rejected with a clear conflict before Borg starts.
    allow_active_archive_mount: bool = False


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


def _repository_network_host(repository: Repository) -> str | None:
    """Return the source-side network target for an SSH repository."""
    location = str(repository.location or "").strip()
    parsed = urlsplit(location)
    if parsed.scheme == "ssh" and parsed.hostname:
        return parsed.hostname
    match = re.match(r"^[^/@:]+@(?P<host>\[[^\]]+\]|[^/:]+):.+", location)
    if not match:
        return None
    return match.group("host").strip("[]") or None


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


_EXTERNAL_STORAGE_SSH_WRAPPER = r'''
set -eu
umask 077
port="$1"
destination="$2"
remote_with_path="$3"
allow_pathless_fallback="$4"
tmpdir=$(mktemp -d /tmp/bbm-storage-probe.XXXXXX)
trap 'rm -rf -- "$tmpdir"' EXIT HUP INT TERM
IFS= read -r ssh_key_b64 || exit 90
IFS= read -r known_hosts_b64 || exit 91
ssh_key="$tmpdir/id_ed25519"
known_hosts="$tmpdir/known_hosts"
printf '%s' "$ssh_key_b64" | base64 -d > "$ssh_key"
printf '%s' "$known_hosts_b64" | base64 -d > "$known_hosts"
chmod 600 "$ssh_key" "$known_hosts"
run_ssh() {
  ssh \
    -i "$ssh_key" \
    -p "$port" \
    -o BatchMode=yes \
    -o ConnectTimeout=10 \
    -o ConnectionAttempts=1 \
    -o ServerAliveInterval=10 \
    -o ServerAliveCountMax=2 \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$known_hosts" \
    "$destination" "$1"
}

# Restricted SSH services such as Hetzner Storage Box expose `df` directly but
# do not provide a full remote shell. Avoid environment assignments, pipes and
# redirects. `df -m` is both restricted-shell friendly and machine-readable.
if run_ssh "$remote_with_path"; then
  exit 0
fi

# For relative Borg locations (for example ./borg on Storage Box) a pathless
# `df -m` still refers to the account/home filesystem containing the repository.
# Never use this fallback for absolute repository paths because that could report
# an unrelated login filesystem on a normal server.
if [ "$allow_pathless_fallback" = "1" ]; then
  run_ssh "df -m"
  exit $?
fi
exit 1
'''.strip()


def external_repository_storage_command(repository: Repository) -> Command:
    """Query the filesystem containing an external SSH repository.

    This uses a separate SSH connection rather than Borg so the remote
    filesystem can be checked before and while ``borg create`` is running.
    Targets that intentionally expose only ``borg serve`` will reject the
    command; callers can then show that filesystem monitoring is unavailable.
    """
    if repository.storage_path:
        raise ValueError("Filesystem SSH probe is only used for external repositories")
    target = storage_probe_target_from_location(repository.location)
    if target is None:
        raise ValueError("Externe Dateisystemprüfung benötigt ein SSH-Repository mit Benutzer und Host")
    ssh_key = get_repository_secret(repository, "external_ssh_private_key")
    known_hosts = get_repository_secret(repository, "external_known_hosts")
    if not ssh_key:
        raise ValueError("External repository has no manager SSH key configured")
    if not known_hosts:
        raise ValueError("External repository has no manager known_hosts entry configured")
    repository_path = target.repository_path
    if repository_path.startswith("-"):
        repository_path = "./" + repository_path
    allow_pathless_fallback = "1" if not repository_path.startswith("/") else "0"
    remote_with_path = f"df -m {shlex.quote(repository_path)}"
    payload = _payload_line(ssh_key) + _payload_line(known_hosts)
    ssh_host = f"[{target.host}]" if ":" in target.host and not target.host.startswith("[") else target.host
    destination = f"{target.username}@{ssh_host}"
    return Command(
        argv=manager_borg_argv([
            "sh", "-c", _EXTERNAL_STORAGE_SSH_WRAPPER, "--",
            str(target.port), destination, remote_with_path, allow_pathless_fallback,
        ]),
        preview=(
            f"[direkt im Manager] ssh -p {target.port} {shlex.quote(destination)} "
            f"-- df -m {shlex.quote(target.repository_path)}"
            + (" (Fallback: df -m)" if allow_pathless_fallback == "1" else "")
        ),
        stdin_data=payload,
        timeout_seconds=20,
    )


def parse_external_repository_storage(output: str, repository_path: str) -> dict[str, int | float | str]:
    """Parse ``df -m`` output from an external repository probe."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        parts = line.split()
        percent_index = next((i for i, value in enumerate(parts) if re.fullmatch(r"\d+%", value)), None)
        if percent_index is None or percent_index < 3:
            continue
        try:
            total_blocks = int(parts[percent_index - 3])
            used_blocks = int(parts[percent_index - 2])
            free_blocks = int(parts[percent_index - 1])
            percent = float(parts[percent_index].rstrip("%"))
        except ValueError:
            continue
        mount_point = " ".join(parts[percent_index + 1:]) or repository_path
        return {
            "total": total_blocks * 1024 * 1024,
            "used": used_blocks * 1024 * 1024,
            "free": free_blocks * 1024 * 1024,
            "percent": round(percent, 1),
            "path": repository_path,
            "mount_point": mount_point,
        }
    raise ValueError("Dateisystemausgabe des externen Repositorys konnte nicht ausgewertet werden")


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
        manager_cache_repository_id=(int(repository.id) if not repository.storage_path else None),
    )


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
    parts = [*_borg_base("create"), "--stats", "--progress", "--show-rc", "--compression", job.compression]
    if options["list_files"]:
        parts.append("--list")
    else:
        # Keep a lightweight A/M/C/E activity stream even when the complete file
        # list is disabled. A/M are consumed only for live counters and stripped
        # before the persistent log; C/E remain visible for warning diagnosis.
        parts.extend(["--list", "--filter", "AMCE"])
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

    # The backup data path is source client -> repository. Monitor the route
    # interface first and expose up to two additional active IPv4 interfaces so
    # multi-NIC clients remain visible in the live dialog. Only the route
    # interface contributes to the cumulative per-job traffic counters.
    network_host = _repository_network_host(job.repository)
    network_monitor = "bbm_stop_network_monitor() { :; }"
    if network_host:
        network_monitor = rf"""
bbm_network_pid=""
bbm_stop_network_monitor() {{
  if [ -n "${{bbm_network_pid:-}}" ]; then
    kill "$bbm_network_pid" 2>/dev/null || true
    wait "$bbm_network_pid" 2>/dev/null || true
    bbm_network_pid=""
  fi
}}
bbm_start_network_monitor() {{
  bbm_net_target={shlex.quote(network_host)}
  command -v ip >/dev/null 2>&1 || return 0
  command -v awk >/dev/null 2>&1 || return 0
  bbm_net_ip="$bbm_net_target"
  if command -v getent >/dev/null 2>&1; then
    set -- $(getent ahosts "$bbm_net_target" 2>/dev/null)
    [ "$#" -gt 0 ] && bbm_net_ip="$1"
  fi
  set -- $(ip route get "$bbm_net_ip" 2>/dev/null)
  [ "$#" -gt 0 ] || return 0
  bbm_route_iface=""
  bbm_route_src=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      dev) shift; [ "$#" -gt 0 ] && bbm_route_iface="$1" ;;
      src) shift; [ "$#" -gt 0 ] && bbm_route_src="$1" ;;
    esac
    [ "$#" -gt 0 ] && shift
  done
  [ -n "$bbm_route_iface" ] || return 0
  bbm_route_iface=${{bbm_route_iface%%@*}}
  [ -n "$bbm_route_src" ] || bbm_route_src="-"

  bbm_interfaces="$(
    ip -o -4 addr show up scope global 2>/dev/null |
      awk -v route="$bbm_route_iface" -v route_ip="$bbm_route_src" '
        BEGIN {{ count=0; if (route != "") {{ print route "\t" route_ip "\t1"; seen[route]=1; count++ }} }}
        count < 3 {{
          iface=$2; sub(/@.*/, "", iface);
          split($4, addr, "/");
          if (iface != "" && !seen[iface]) {{ print iface "\t" addr[1] "\t0"; seen[iface]=1; count++ }}
        }}
      '
  )"
  [ -n "$bbm_interfaces" ] || return 0
  (
    while :; do
      printf '%s\n' "$bbm_interfaces" | while IFS='	' read -r bbm_iface bbm_src bbm_is_route; do
        [ -n "$bbm_iface" ] || continue
        bbm_rx_file="/sys/class/net/$bbm_iface/statistics/rx_bytes"
        bbm_tx_file="/sys/class/net/$bbm_iface/statistics/tx_bytes"
        [ -r "$bbm_rx_file" ] && [ -r "$bbm_tx_file" ] || continue
        IFS= read -r bbm_rx < "$bbm_rx_file" || continue
        IFS= read -r bbm_tx < "$bbm_tx_file" || continue
        printf '\036BBMNET\t%s\t%s\t%s\t%s\t%s\n' "$bbm_iface" "$bbm_src" "$bbm_rx" "$bbm_tx" "$bbm_is_route" >&2
      done
      sleep 1
    done
  ) &
  bbm_network_pid=$!
}}
bbm_start_network_monitor
""".strip()


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
{network_monitor}
{file_list_header}
{shlex.join(parts)}
bbm_rc=$?
bbm_stop_network_monitor 2>/dev/null || true
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
    """Scan source paths read-only and mirror Borg exclusions for source baselines.

    The preferred Python scanner applies the job's path excludes, cache tags,
    nodump flag and one-file-system setting and emits separate totals for every
    configured source. A minimal find/stat fallback remains for unusual clients
    without Python and is explicitly marked as partial so the stored source
    statistics are not presented as fully exclusion-accurate.
    """
    sources = json.loads(job.source_paths_json or "[]")
    excludes = json.loads(job.exclude_patterns_json or "[]")
    options = validate_create_options(json.loads(job.create_options_json or "{}"))
    one_file_system = "1" if options["one_file_system"] else "0"
    exclude_caches = "1" if options["exclude_caches"] else "0"
    exclude_nodump = "1" if options["exclude_nodump"] else "0"
    patterns_json = json.dumps(excludes, ensure_ascii=False, separators=(",", ":"))
    python_scan = r'''
import array
import fnmatch
import json
import os
import re
import stat
import sys

one_file_system = sys.argv[1] == "1"
exclude_caches = sys.argv[2] == "1"
exclude_nodump = sys.argv[3] == "1"
try:
    raw_patterns = json.loads(sys.argv[4])
except Exception:
    raw_patterns = []
roots = sys.argv[5:]
warning_count = 0
seen_paths = set()
skipped_mounts = []
included_mounts = []
unsupported_patterns = []
path_excluded_count = 0
excluded_file_count = 0
excluded_size_bytes = 0
CACHEDIR_SIGNATURE = b"Signature: 8a477f597d28d172789f06886806bc55"
FS_IOC_GETFLAGS = 0x80086601
FS_NODUMP_FL = 0x00000040

try:
    import fcntl
except Exception:
    fcntl = None


def remember(items, path):
    normalized = os.path.normpath(path)
    if normalized not in items and len(items) < 50:
        items.append(normalized)


def warn(message):
    global warning_count
    warning_count += 1
    if warning_count <= 50:
        print("WARNUNG: " + message, file=sys.stderr)


def archive_path(path):
    normalized = os.path.normpath(path).replace(os.sep, "/")
    return normalized.lstrip("/")


def shell_regex(pattern):
    out = ["^"]
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                while i + 1 < len(pattern) and pattern[i + 1] == "*":
                    i += 1
                if i + 1 < len(pattern) and pattern[i + 1] == "/":
                    i += 1
                    out.append("(?:.*/)?")
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            end = pattern.find("]", i + 1)
            if end < 0:
                out.append(r"\[")
            else:
                content = pattern[i + 1:end]
                if content.startswith("!"):
                    content = "^" + content[1:]
                out.append("[" + content + "]")
                i = end
        else:
            out.append(re.escape(char))
        i += 1
    out.append("(?:/.*)?$")
    return re.compile("".join(out))


def compile_pattern(raw):
    value = str(raw or "").strip()
    if not value:
        return None
    style = "sh"
    body = value
    if len(value) >= 3 and value[2] == ":":
        style, body = value[:2].lower(), value[3:]
    if style not in {"sh", "fm", "re", "pp", "pf"}:
        unsupported_patterns.append(value)
        return None
    try:
        if style == "re":
            regex = re.compile(body)
            return lambda candidate: bool(regex.search(candidate))
        body = body.replace("\\", "/").lstrip("/")
        if style == "pp":
            prefix = body.rstrip("/")
            return lambda candidate: candidate == prefix or candidate.startswith(prefix + "/")
        if style == "pf":
            return lambda candidate: candidate == body
        if style == "fm":
            return lambda candidate: fnmatch.fnmatchcase(candidate, body)
        regex = shell_regex(body)
        return lambda candidate: bool(regex.match(candidate))
    except (re.error, ValueError):
        unsupported_patterns.append(value)
        return None


matchers = [matcher for matcher in (compile_pattern(item) for item in raw_patterns) if matcher is not None]


def excluded_by_pattern(path):
    candidate = archive_path(path)
    return any(matcher(candidate) for matcher in matchers)


def cache_tagged(directory):
    if not exclude_caches:
        return False
    try:
        with open(os.path.join(directory, "CACHEDIR.TAG"), "rb") as handle:
            return handle.read(len(CACHEDIR_SIGNATURE)) == CACHEDIR_SIGNATURE
    except OSError:
        return False


def has_nodump(path):
    if not exclude_nodump or fcntl is None:
        return False
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return False
    try:
        values = array.array("I", [0])
        fcntl.ioctl(fd, FS_IOC_GETFLAGS, values, True)
        return bool(values[0] & FS_NODUMP_FL)
    except (OSError, TypeError, ValueError):
        return False
    finally:
        os.close(fd)


def excluded_after_metadata(path, *, is_dir=False):
    if has_nodump(path):
        return True
    if is_dir and cache_tagged(path):
        return True
    return False


source_results = []
total_size = 0
total_files = 0
for root in roots:
    source_size = 0
    source_files = 0
    if excluded_by_pattern(root):
        path_excluded_count += 1
        source_results.append({"path": root, "size_bytes": 0, "file_count": 0})
        continue
    try:
        root_stat = os.lstat(root)
    except OSError as exc:
        warn(f"{root}: {exc}")
        source_results.append({"path": root, "size_bytes": 0, "file_count": 0})
        continue
    root_is_dir = stat.S_ISDIR(root_stat.st_mode)
    if excluded_after_metadata(root, is_dir=root_is_dir):
        source_results.append({"path": root, "size_bytes": 0, "file_count": 0})
        continue
    if not root_is_dir:
        normalized = os.path.normpath(root)
        if normalized not in seen_paths:
            seen_paths.add(normalized)
            source_files += 1
            if stat.S_ISREG(root_stat.st_mode):
                source_size += max(0, int(root_stat.st_size))
        source_results.append({"path": root, "size_bytes": source_size, "file_count": source_files})
        total_size += source_size
        total_files += source_files
        continue
    root_device = root_stat.st_dev
    normalized_root = os.path.normpath(root)
    if normalized_root in seen_paths:
        source_results.append({"path": root, "size_bytes": 0, "file_count": 0})
        continue
    seen_paths.add(normalized_root)
    stack = [(root, root_device)]
    while stack:
        directory, directory_device = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    path = entry.path
                    # Borg path patterns depend only on the archive path. Check
                    # them before stat() so excluded files and complete directory
                    # trees do not cause avoidable metadata traffic on NFS/CIFS.
                    if excluded_by_pattern(path):
                        path_excluded_count += 1
                        continue
                    try:
                        item_stat = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        warn(f"{path}: {exc}")
                        continue
                    is_dir = stat.S_ISDIR(item_stat.st_mode)
                    if excluded_after_metadata(path, is_dir=is_dir):
                        if not is_dir:
                            excluded_file_count += 1
                            if stat.S_ISREG(item_stat.st_mode):
                                excluded_size_bytes += max(0, int(item_stat.st_size))
                        continue
                    if is_dir:
                        if one_file_system and item_stat.st_dev != root_device:
                            remember(skipped_mounts, path)
                            continue
                        if not one_file_system and item_stat.st_dev != directory_device:
                            remember(included_mounts, path)
                        normalized_path = os.path.normpath(path)
                        if normalized_path in seen_paths:
                            continue
                        seen_paths.add(normalized_path)
                        stack.append((path, item_stat.st_dev))
                    else:
                        normalized_path = os.path.normpath(path)
                        if normalized_path in seen_paths:
                            continue
                        seen_paths.add(normalized_path)
                        source_files += 1
                        if stat.S_ISREG(item_stat.st_mode):
                            source_size += max(0, int(item_stat.st_size))
        except OSError as exc:
            warn(f"{directory}: {exc}")
            continue
    source_results.append({"path": root, "size_bytes": source_size, "file_count": source_files})
    total_size += source_size
    total_files += source_files

if skipped_mounts:
    print(
        "HINWEIS: " + str(len(skipped_mounts))
        + " eingebundene Unterdateisystem(e) wurden wegen 'Nur jeweiliges Quelldateisystem' nicht mitgezählt: "
        + ", ".join(skipped_mounts[:10]) + (" …" if len(skipped_mounts) > 10 else ""),
        file=sys.stderr,
    )
elif included_mounts:
    print(
        "HINWEIS: Eingebundene Unterdateisysteme werden mitgezählt: "
        + ", ".join(included_mounts[:10]) + (" …" if len(included_mounts) > 10 else ""),
        file=sys.stderr,
    )
if unsupported_patterns:
    print(
        "WARNUNG: " + str(len(unsupported_patterns))
        + " Ausschlussmuster konnten für die Quellenstatistik nicht sicher nachgebildet werden: "
        + ", ".join(unsupported_patterns[:10]),
        file=sys.stderr,
    )

nodump_unavailable = exclude_nodump and fcntl is None
quality = "high" if not warning_count and not unsupported_patterns and not nodump_unavailable else "partial"
print("BBM_SOURCE_STATS_JSON=" + json.dumps({
    "size_bytes": total_size,
    "file_count": total_files,
    "warning_count": warning_count,
    "skipped_mount_count": len(skipped_mounts),
    "skipped_mounts": skipped_mounts,
    "included_mount_count": len(included_mounts),
    "path_excluded_count": path_excluded_count,
    "excluded_file_count": excluded_file_count,
    "excluded_size_bytes": excluded_size_bytes,
    "unsupported_patterns": unsupported_patterns,
    "nodump_supported": not nodump_unavailable,
    "quality": quality,
    "sources": source_results,
    "method": "python-borg-excludes",
}, separators=(",", ":")))
sys.exit(1 if (warning_count or unsupported_patterns or nodump_unavailable) else 0)
'''.strip()
    fallback_scan = r'''
set +e
tmpfile=$(mktemp /tmp/bbm-source-stats.XXXXXX) || exit 70
trap 'rm -f -- "$tmpfile"' EXIT HUP INT TERM
warnings=0
printf '%s\n' 'WARNUNG: Python 3 fehlt; Ausschlüsse und Quellenaufteilung können im Fallback nicht vollständig nachgebildet werden.' >&2
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
  if [ "$rc" -ne 0 ]; then warnings=$((warnings + 1)); fi
done
awk -v warnings="$warnings" '
  { size += $1; count += 1 }
  END {
    printf "BBM_SOURCE_STATS_JSON={\"size_bytes\":%.0f,\"file_count\":%d,\"warning_count\":%d,\"quality\":\"partial\",\"sources\":[],\"method\":\"find-stat-fallback\"}\n", size, count, warnings
  }
' "$tmpfile"
[ "$warnings" -eq 0 ]
'''.strip()
    script = f'''
set +e
printf '%s\n' '=== Quellenstatistik aktualisieren (ausschlussbereinigter Live-Scan) ==='
printf 'BACKUP-JOB: %s\n' {shlex.quote(job.name)}
printf 'QUELLPFADE: %s\n' {shlex.quote(', '.join(sources))}
printf '%s\n' 'Hinweis: Der bevorzugte Scan berücksichtigt Borg-Pfadausschlüsse, Cache-Tags, nodump und Dateisystemgrenzen.'
printf '%s\n' 'Das Repository wird nicht geöffnet und es wird kein Archiv geschrieben.'
printf '%s\n' '------------------------------------------------------------------------------'
one_file_system={one_file_system}
exclude_caches={exclude_caches}
exclude_nodump={exclude_nodump}
if [ "$one_file_system" = "1" ]; then
  printf '%s\n' "HINWEIS: 'Nur jeweiliges Quelldateisystem' ist aktiv; eingehängte Unterverzeichnisse werden wie beim Backup übersprungen."
else
  printf '%s\n' 'HINWEIS: Eingehängte Unterverzeichnisse werden in die Quellenstatistik einbezogen.'
fi
if command -v python3 >/dev/null 2>&1; then
  python3 -S -c {shlex.quote(python_scan)} "$one_file_system" "$exclude_caches" "$exclude_nodump" {shlex.quote(patterns_json)} "$@"
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
  printf '%s\n' 'ERGEBNIS: Ausschlussbereinigte Quellenstatistik erfolgreich aktualisiert.'
elif [ "$bbm_rc" -eq 1 ]; then
  printf '%s\n' 'ERGEBNIS: Quellenstatistik mit Warnungen aktualisiert.' >&2
else
  printf 'ERGEBNIS: Quellenstatistik fehlgeschlagen (RC %s).\n' "$bbm_rc" >&2
fi
exit "$bbm_rc"
'''.strip()
    command = _ssh_argv(
        job.host,
        ["sh", "-c", script, "--", *sources],
        {},
        supervised=True,
    )
    command.allow_active_archive_mount = True
    return command

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


def client_borg_cache_export_command(host: Host, repository_id: int) -> Command:
    """Stream one BBM-private repository cache from a managed source device.

    The remote side emits a tiny text protocol first and then an uncompressed
    tar stream. Keeping compression in the outer Manager backup avoids wasting
    client CPU and lets the Manager choose the requested ZIP compression level.
    """
    if isinstance(repository_id, bool) or int(repository_id) <= 0:
        raise ValueError("Repository-ID für Client-Cache ist ungültig")
    repository_id = int(repository_id)
    script = r'''\
set -eu
repository_id="$1"
case "$repository_id" in *[!0-9]*|'') printf '%s\n' 'BBM_CLIENT_CACHE_ERROR'; exit 86 ;; esac
cache_base="${XDG_CACHE_HOME:-$HOME/.cache}/borgbackup-manager"
cache_name="repository-$repository_id"
cache_dir="$cache_base/$cache_name"
printf '%s\n' 'BBM_CLIENT_CACHE_V1'
if [ ! -d "$cache_dir" ]; then
  printf '%s\n' 'MISSING'
  exit 0
fi
if find "$cache_dir" -type l -print -quit 2>/dev/null | grep -q .; then
  printf '%s\n' 'ERROR'
  printf '%s\n' 'Client-Cache enthält einen symbolischen Link und wird aus Sicherheitsgründen nicht gesichert.' >&2
  exit 91
fi
printf '%s\n' 'PRESENT'
cd -- "$cache_base"
# Cache locks are process-local and must never be revived by a restore.
exec tar --exclude='*/lock.exclusive' --exclude='*/lock.exclusive/*' --exclude='*/lock.roster' -cf - -- "$cache_name"
'''.strip()
    command = _ssh_argv(host, ["sh", "-c", script, "--", str(repository_id)], {})
    command.timeout_seconds = COMMAND_TIMEOUT
    command.preview = (
        f"ssh -i [temporärer Controller-Schlüssel] {host.username}@{host.address} -- "
        f"Client-Borg-Cache repository-{repository_id} streamen"
    )
    return command


def client_borg_security_export_command(host: Host, repository_id: int, repository_location: str) -> Command:
    """Stream the Borg security state associated with one BBM client repository.

    Borg 1.x names security directories by the real 64-hex repository ID, not
    by BBM's numeric repository record. Prefer the repository ID stored in the
    BBM-private cache config and use an exact security-location match only as a
    conservative fallback when the cache itself is missing.
    """
    if isinstance(repository_id, bool) or int(repository_id) <= 0:
        raise ValueError("Repository-ID für Client-Sicherheitsstatus ist ungültig")
    repository_id = int(repository_id)
    if not repository_location or any(ch in repository_location for ch in "\x00\r\n"):
        raise ValueError("Repository-Standort für Client-Sicherheitsstatus ist ungültig")
    script = r'''\
set -eu
repository_id="$1"
repository_location="$2"
case "$repository_id" in *[!0-9]*|'') printf '%s\n' 'BBM_CLIENT_SECURITY_ERROR'; exit 86 ;; esac
cache_base="${XDG_CACHE_HOME:-$HOME/.cache}/borgbackup-manager"
cache_config="$cache_base/repository-$repository_id/config"
config_base="${BORG_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/borg}"
security_base="${BORG_SECURITY_DIR:-$config_base/security}"
repo_id=""
if [ -f "$cache_config" ] && [ ! -L "$cache_config" ]; then
  repo_id=$(awk '
    BEGIN { in_cache=0 }
    /^[[:space:]]*\[/ { in_cache=($0 ~ /^[[:space:]]*\[cache\][[:space:]]*$/); next }
    in_cache && /^[[:space:]]*repository[[:space:]]*=/ {
      sub(/^[^=]*=[[:space:]]*/, ""); gsub(/[[:space:]]/, ""); print tolower($0); exit
    }
  ' "$cache_config" 2>/dev/null || true)
fi
case "$repo_id" in *[!0-9a-f]*|'') repo_id="" ;; esac
[ -z "$repo_id" ] || [ "${#repo_id}" -eq 64 ] || repo_id=""
if [ -z "$repo_id" ] && [ -d "$security_base" ]; then
  matches=0
  matched=""
  for path in "$security_base"/*; do
    [ -d "$path" ] && [ ! -L "$path" ] || continue
    name=${path##*/}
    case "$name" in *[!0-9a-f]*|'') continue ;; esac
    [ "${#name}" -eq 64 ] || continue
    [ -f "$path/location" ] && [ ! -L "$path/location" ] || continue
    location=$(cat -- "$path/location" 2>/dev/null || true)
    if [ "$location" = "$repository_location" ]; then
      matches=$((matches + 1)); matched="$name"
    fi
  done
  [ "$matches" -eq 1 ] && repo_id="$matched"
fi
printf '%s\n' 'BBM_CLIENT_SECURITY_V1'
if [ -z "$repo_id" ]; then
  if [ -d "$security_base" ]; then printf '%s\n' 'UNRESOLVED'; else printf '%s\n' 'MISSING'; fi
  printf '%s\n' '-'
  exit 0
fi
target="$security_base/$repo_id"
if [ ! -d "$target" ]; then
  printf '%s\n' 'MISSING'
  printf '%s\n' "$repo_id"
  exit 0
fi
if [ -L "$target" ] || find "$target" -type l -print -quit 2>/dev/null | grep -q .; then
  printf '%s\n' 'ERROR'
  printf '%s\n' "$repo_id"
  printf '%s\n' 'Client-Borg-Sicherheitsstatus enthält einen symbolischen Link und wird nicht gesichert.' >&2
  exit 91
fi
printf '%s\n' 'PRESENT'
printf '%s\n' "$repo_id"
cd -- "$security_base"
exec tar -cf - -- "$repo_id"
'''.strip()
    command = _ssh_argv(host, ["sh", "-c", script, "--", str(repository_id), repository_location], {})
    command.timeout_seconds = COMMAND_TIMEOUT
    command.preview = (
        f"ssh -i [temporärer Controller-Schlüssel] {host.username}@{host.address} -- "
        f"Client-Borg-Sicherheitsstatus für Repository {repository_id} streamen"
    )
    return command


def client_borg_security_restore_command(host: Host, borg_repository_id: str) -> Command:
    """Restore missing Borg security state without overwriting a newer local state."""
    import re
    repo_id = str(borg_repository_id).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", repo_id):
        raise ValueError("Borg-Repository-ID für Client-Sicherheitsstatus ist ungültig")
    script = r'''\
set -eu
umask 077
repo_id="$1"
case "$repo_id" in *[!0-9a-f]*|'') exit 86 ;; esac
[ "${#repo_id}" -eq 64 ] || exit 86
config_base="${BORG_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/borg}"
security_base="${BORG_SECURITY_DIR:-$config_base/security}"
target="$security_base/$repo_id"
if [ -e "$target" ] || [ -L "$target" ]; then
  printf '%s\n' 'BBM_CLIENT_SECURITY_KEPT_EXISTING'
  exit 0
fi
stage="$security_base/.${repo_id}.bbm-restore.$$"
cleanup() { rm -rf -- "$stage"; }
trap cleanup EXIT HUP INT TERM
mkdir -p -- "$security_base"
chmod 700 -- "$config_base" "$security_base" 2>/dev/null || true
rm -rf -- "$stage"
mkdir -p -- "$stage"
if ! tar --no-same-owner --no-same-permissions -xf - -C "$stage"; then
  printf '%s\n' 'FEHLER: Client-Sicherheitsstatus konnte nicht entpackt werden.' >&2
  exit 87
fi
incoming="$stage/$repo_id"
if find "$stage" -mindepth 1 -maxdepth 1 ! -name "$repo_id" -print -quit | grep -q .; then
  printf '%s\n' 'FEHLER: Client-Sicherheitsarchiv enthält unerwartete zusätzliche Pfade.' >&2
  exit 88
fi
if [ ! -d "$incoming" ] || [ -L "$incoming" ]; then
  printf '%s\n' 'FEHLER: Client-Sicherheitsarchiv enthält keinen gültigen Repository-Status.' >&2
  exit 89
fi
if find "$incoming" -type l -print -quit | grep -q .; then
  printf '%s\n' 'FEHLER: Client-Sicherheitsarchiv enthält symbolische Links.' >&2
  exit 90
fi
for required in location key-type manifest-timestamp; do
  if [ ! -f "$incoming/$required" ] || [ -L "$incoming/$required" ]; then
    printf 'FEHLER: Client-Sicherheitsarchiv ist unvollständig: %s fehlt.\n' "$required" >&2
    exit 91
  fi
done
mv -- "$incoming" "$target"
chmod 700 -- "$target" 2>/dev/null || true
printf '%s\n' 'BBM_CLIENT_SECURITY_RESTORED'
'''.strip()
    command = _ssh_argv(host, ["sh", "-c", script, "--", repo_id], {})
    command.timeout_seconds = COMMAND_TIMEOUT
    command.preview = (
        f"ssh -i [temporärer Controller-Schlüssel] {host.username}@{host.address} -- "
        f"Client-Borg-Sicherheitsstatus {repo_id[:12]}… wiederherstellen"
    )
    return command

def client_borg_cache_scan_command(host: Host) -> Command:
    """List BBM-private caches, legacy Borg caches, and Borg security state."""
    script = r'''\
set -eu
passwd_home=$(getent passwd "$(id -u)" 2>/dev/null | awk -F: 'NR == 1 { print $6 }' || true)
home_dir=${HOME:-$passwd_home}
[ -n "$home_dir" ] || home_dir="$passwd_home"
[ -n "$home_dir" ] || home_dir=/root
bbm_cache_base="${XDG_CACHE_HOME:-$home_dir/.cache}/borgbackup-manager"
config_base="${BORG_CONFIG_DIR:-${XDG_CONFIG_HOME:-$home_dir/.config}/borg}"
security_base="${BORG_SECURITY_DIR:-$config_base/security}"
encode_path() { printf '%s' "$1" | base64 | tr -d '\n'; }
printf '%s\n' 'BBM_CLIENT_CACHE_SCAN_V5'
printf 'SCAN_HOME\t%s\n' "$(encode_path "$home_dir")"
printf 'PASSWD_HOME\t%s\n' "$(encode_path "$passwd_home")"
if [ ! -d "$bbm_cache_base" ]; then
  printf 'BBM_BASE\tMISSING\t%s\n' "$(encode_path "$bbm_cache_base")"
else
  printf 'BBM_BASE\tPRESENT\t%s\n' "$(encode_path "$bbm_cache_base")"
  for path in "$bbm_cache_base"/repository-*; do
    [ -e "$path" ] || [ -L "$path" ] || continue
    name=${path##*/}
    encoded_path=$(encode_path "$path")
    if [ -L "$path" ]; then
      printf 'ENTRY5\t%s\t%s\t%s\n' "$name" 'SYMLINK' "$encoded_path"
      continue
    fi
    if [ ! -d "$path" ]; then
      printf 'ENTRY5\t%s\t%s\t%s\n' "$name" 'OTHER' "$encoded_path"
      continue
    fi
    kib=$(du -sk -- "$path" 2>/dev/null | awk '{print $1}')
    case "$kib" in *[!0-9]*|'') kib=0 ;; esac
    printf 'ENTRY5\t%s\t%s\t%s\n' "$name" "$kib" "$encoded_path"
    case "$name" in repository-[1-9][0-9]*) ;; *) continue ;; esac
    config="$path/config"
    [ -f "$config" ] && [ ! -L "$config" ] || continue
    repo_id=$(awk '
      BEGIN { in_cache=0 }
      /^[[:space:]]*\[/ { in_cache=($0 ~ /^[[:space:]]*\[cache\][[:space:]]*$/); next }
      in_cache && /^[[:space:]]*repository[[:space:]]*=/ {
        sub(/^[^=]*=[[:space:]]*/, ""); gsub(/[[:space:]]/, ""); print tolower($0); exit
      }
    ' "$config" 2>/dev/null || true)
    case "$repo_id" in *[!0-9a-f]*|'') continue ;; esac
    [ "${#repo_id}" -eq 64 ] || continue
    printf 'CACHE_REPO\t%s\t%s\n' "$name" "$repo_id"
  done
fi

legacy_candidates=''
add_legacy_base() {
  candidate=$1
  [ -n "$candidate" ] || return 0
  [ "$candidate" != "$bbm_cache_base" ] || return 0
  case "
$legacy_candidates
" in *"
$candidate
"*) return 0 ;; esac
  legacy_candidates="${legacy_candidates}${legacy_candidates:+
}${candidate}"
}
[ -z "${BORG_CACHE_DIR:-}" ] || add_legacy_base "$BORG_CACHE_DIR"
add_legacy_base "${XDG_CACHE_HOME:-$home_dir/.cache}/borg"
add_legacy_base "$home_dir/.cache/borg"
[ -z "$passwd_home" ] || add_legacy_base "$passwd_home/.cache/borg"

printf '%s\n' "$legacy_candidates" | while IFS= read -r user_cache_base; do
  [ -n "$user_cache_base" ] || continue
  encoded_base=$(encode_path "$user_cache_base")
  if [ ! -d "$user_cache_base" ]; then
    printf 'USER_CACHE_BASE5\tMISSING\t%s\n' "$encoded_base"
    continue
  fi
  printf 'USER_CACHE_BASE5\tPRESENT\t%s\n' "$encoded_base"
  find "$user_cache_base" -mindepth 1 -maxdepth 1 -print 2>/dev/null | while IFS= read -r path; do
    [ -e "$path" ] || [ -L "$path" ] || continue
    name=${path##*/}
    encoded_path=$(encode_path "$path")
    case "$name" in
      CACHEDIR.TAG|cachedir.tag)
        kib=$(du -sk -- "$path" 2>/dev/null | awk '{print $1}')
        case "$kib" in *[!0-9]*|'') kib=0 ;; esac
        printf 'USER_CACHE_META5\t%s\t%s\t%s\t%s\n' "$name" "$kib" 'CACHEDIR_TAG' "$encoded_path"
        continue
        ;;
    esac
    if [ -L "$path" ]; then
      printf 'USER_CACHE5\t%s\t%s\t%s\t%s\n' "$name" '0' 'SYMLINK' "$encoded_path"
      continue
    fi
    kib=$(du -sk -- "$path" 2>/dev/null | awk '{print $1}')
    case "$kib" in *[!0-9]*|'') kib=0 ;; esac
    if [ -d "$path" ]; then
      printf 'USER_CACHE5\t%s\t%s\t%s\t%s\n' "$name" "$kib" 'DIR' "$encoded_path"
    elif [ -f "$path" ]; then
      printf 'USER_CACHE5\t%s\t%s\t%s\t%s\n' "$name" "$kib" 'FILE' "$encoded_path"
    else
      printf 'USER_CACHE5\t%s\t%s\t%s\t%s\n' "$name" "$kib" 'OTHER' "$encoded_path"
    fi
  done
done

if [ ! -d "$security_base" ]; then
  printf 'SECURITY_BASE5\tMISSING\t%s\n' "$(encode_path "$security_base")"
  exit 0
fi
printf 'SECURITY_BASE5\tPRESENT\t%s\n' "$(encode_path "$security_base")"
for path in "$security_base"/*; do
  [ -e "$path" ] || [ -L "$path" ] || continue
  name=${path##*/}
  encoded_path=$(encode_path "$path")
  if [ -L "$path" ]; then
    printf 'SECURITY5\t%s\t%s\t%s\t%s\t%s\t%s\n' "$name" '0' 'SYMLINK' '-' '-' "$encoded_path"
    continue
  fi
  if [ ! -d "$path" ]; then
    printf 'SECURITY5\t%s\t%s\t%s\t%s\t%s\t%s\n' "$name" '0' 'OTHER' '-' '-' "$encoded_path"
    continue
  fi
  kib=$(du -sk -- "$path" 2>/dev/null | awk '{print $1}')
  case "$kib" in *[!0-9]*|'') kib=0 ;; esac
  location='-'
  if [ -f "$path/location" ] && [ ! -L "$path/location" ]; then
    location=$(base64 < "$path/location" 2>/dev/null | tr -d '\n' || true)
    [ -n "$location" ] || location='-'
  fi
  manifest_timestamp='-'
  if [ -f "$path/manifest-timestamp" ] && [ ! -L "$path/manifest-timestamp" ]; then
    manifest_timestamp=$(base64 < "$path/manifest-timestamp" 2>/dev/null | tr -d '\n' || true)
    [ -n "$manifest_timestamp" ] || manifest_timestamp='-'
  fi
  printf 'SECURITY5\t%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$kib" 'DIR' "$location" "$manifest_timestamp" "$encoded_path"
done
'''.strip()
    command = _ssh_argv(host, ["sh", "-c", script], {})
    command.timeout_seconds = COMMAND_TIMEOUT
    command.preview = (
        f"ssh -i [temporärer Controller-Schlüssel] {host.username}@{host.address} -- "
        "BBM-Client-Cache, Legacy-Borg-Cache und Borg-Sicherheitsstatus prüfen"
    )
    return command

def client_borg_cache_cleanup_command(host: Host, names: list[str]) -> Command:
    """Delete only explicitly named, syntax-validated BBM client-cache directories."""
    if not names:
        raise ValueError("Keine Client-Cache-Verzeichnisse zur Bereinigung angegeben")
    if len(names) > 1000:
        raise ValueError("Zu viele Client-Cache-Verzeichnisse zur Bereinigung angegeben")
    import re
    allowed = re.compile(r"^repository-[1-9][0-9]*(?:\.pre-bbm-restore-[0-9]{8}-[0-9]{6})?$")
    cleaned: list[str] = []
    for value in names:
        name = str(value)
        if not allowed.fullmatch(name):
            raise ValueError("Ungültiger Client-Cache-Name zur Bereinigung")
        if name not in cleaned:
            cleaned.append(name)
    script = r'''\
set -eu
cache_base="${XDG_CACHE_HOME:-$HOME/.cache}/borgbackup-manager"
printf '%s\n' 'BBM_CLIENT_CACHE_CLEANUP_V1'
for name in "$@"; do
  case "$name" in
    repository-[1-9][0-9]*|repository-[1-9][0-9]*.pre-bbm-restore-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) printf 'SKIPPED\t%s\tinvalid-name\n' "$name"; continue ;;
  esac
  target="$cache_base/$name"
  if [ -L "$target" ]; then
    printf 'SKIPPED\t%s\tsymlink\n' "$name"
    continue
  fi
  if [ ! -e "$target" ]; then
    printf 'MISSING\t%s\n' "$name"
    continue
  fi
  if [ ! -d "$target" ]; then
    printf 'SKIPPED\t%s\tnot-directory\n' "$name"
    continue
  fi
  if rm -rf -- "$target"; then
    printf 'REMOVED\t%s\n' "$name"
  else
    printf 'FAILED\t%s\n' "$name"
  fi
done
'''.strip()
    command = _ssh_argv(host, ["sh", "-c", script, "--", *cleaned], {})
    command.timeout_seconds = COMMAND_TIMEOUT
    command.preview = (
        f"ssh -i [temporärer Controller-Schlüssel] {host.username}@{host.address} -- "
        f"{len(cleaned)} BBM-Client-Cache-Verzeichnis(se) bereinigen"
    )
    return command


def client_borg_user_cache_cleanup_command(host: Host, targets: list[str]) -> Command:
    """Delete explicitly selected safe top-level entries from legacy Borg cache roots.

    Absolute paths emitted by the V5 scanner are preferred. Older callers may
    still pass a simple basename, which is resolved below the canonical
    $HOME/.cache/borg root. Every target is revalidated remotely against the
    same set of allowed legacy cache roots before deletion.
    """
    if not targets:
        raise ValueError("Keine Legacy-Borg-Cache-Einträge zur Bereinigung angegeben")
    if len(targets) > 1000:
        raise ValueError("Zu viele Legacy-Borg-Cache-Einträge zur Bereinigung angegeben")
    cleaned: list[str] = []
    for value in targets:
        target = str(value).strip()
        basename = target.rsplit("/", 1)[-1]
        if (
            not target
            or basename.lower() == "cachedir.tag"
            or basename in {".", ".."}
            or "\x00" in target
            or "\r" in target
            or "\n" in target
            or len(target.encode("utf-8")) > 4096
        ):
            raise ValueError("Ungültiger Legacy-Borg-Cache-Name oder -Pfad zur Bereinigung")
        if target not in cleaned:
            cleaned.append(target)
    script = r'''\
set -eu
passwd_home=$(getent passwd "$(id -u)" 2>/dev/null | awk -F: 'NR == 1 { print $6 }' || true)
home_dir=${HOME:-$passwd_home}
[ -n "$home_dir" ] || home_dir="$passwd_home"
[ -n "$home_dir" ] || home_dir=/root
bbm_cache_base="${XDG_CACHE_HOME:-$home_dir/.cache}/borgbackup-manager"
legacy_candidates=''
add_legacy_base() {
  candidate=$1
  [ -n "$candidate" ] || return 0
  [ "$candidate" != "$bbm_cache_base" ] || return 0
  case "
$legacy_candidates
" in *"
$candidate
"*) return 0 ;; esac
  legacy_candidates="${legacy_candidates}${legacy_candidates:+
}${candidate}"
}
[ -z "${BORG_CACHE_DIR:-}" ] || add_legacy_base "$BORG_CACHE_DIR"
add_legacy_base "${XDG_CACHE_HOME:-$home_dir/.cache}/borg"
add_legacy_base "$home_dir/.cache/borg"
[ -z "$passwd_home" ] || add_legacy_base "$passwd_home/.cache/borg"
printf '%s\n' 'BBM_CLIENT_USER_CACHE_CLEANUP_V3'
for requested in "$@"; do
  case "$requested" in
    /*) target=$requested ;;
    *) target="$home_dir/.cache/borg/$requested" ;;
  esac
  name=${target##*/}
  parent=${target%/*}
  case "$name" in
    ''|.|..|CACHEDIR.TAG|cachedir.tag) printf 'SKIPPED\t%s\tinvalid-name\n' "$name"; continue ;;
  esac
  allowed=0
  printf '%s\n' "$legacy_candidates" | while IFS= read -r base; do
    [ -n "$base" ] || continue
    if [ "$parent" = "$base" ]; then
      printf '%s\n' ALLOWED
      break
    fi
  done > /tmp/bbm-cache-allowed.$$
  if grep -q '^ALLOWED$' /tmp/bbm-cache-allowed.$$ 2>/dev/null; then allowed=1; fi
  rm -f /tmp/bbm-cache-allowed.$$ 2>/dev/null || true
  if [ "$allowed" != 1 ]; then
    printf 'SKIPPED\t%s\toutside-legacy-cache-roots\n' "$name"
    continue
  fi
  if [ -L "$target" ]; then
    printf 'SKIPPED\t%s\tsymlink\n' "$name"
    continue
  fi
  if [ ! -e "$target" ]; then
    printf 'MISSING\t%s\n' "$name"
    continue
  fi
  if [ -d "$target" ]; then
    if rm -rf -- "$target"; then
      printf 'REMOVED\t%s\n' "$name"
    else
      printf 'FAILED\t%s\n' "$name"
    fi
  elif [ -f "$target" ]; then
    if rm -f -- "$target"; then
      printf 'REMOVED\t%s\n' "$name"
    else
      printf 'FAILED\t%s\n' "$name"
    fi
  else
    printf 'SKIPPED\t%s\tnot-regular\n' "$name"
  fi
done
'''.strip()
    command = _ssh_argv(host, ["sh", "-c", script, "--", *cleaned], {})
    command.timeout_seconds = COMMAND_TIMEOUT
    command.preview = (
        f"ssh -i [temporärer Controller-Schlüssel] {host.username}@{host.address} -- "
        f"{len(cleaned)} Legacy-Borg-Cache-Einträge bereinigen"
    )
    return command

def client_borg_security_cleanup_command(host: Host, repository_ids: list[str]) -> Command:
    """Delete only explicitly selected 64-hex Borg security directories."""
    import re
    if not repository_ids:
        raise ValueError("Keine Client-Sicherheitsstatus-Verzeichnisse zur Bereinigung angegeben")
    if len(repository_ids) > 1000:
        raise ValueError("Zu viele Client-Sicherheitsstatus-Verzeichnisse zur Bereinigung angegeben")
    cleaned: list[str] = []
    for value in repository_ids:
        repo_id = str(value).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", repo_id):
            raise ValueError("Ungültige Borg-Repository-ID zur Bereinigung")
        if repo_id not in cleaned:
            cleaned.append(repo_id)
    script = r'''\
set -eu
config_base="${BORG_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/borg}"
security_base="${BORG_SECURITY_DIR:-$config_base/security}"
printf '%s\n' 'BBM_CLIENT_SECURITY_CLEANUP_V1'
for repo_id in "$@"; do
  case "$repo_id" in *[!0-9a-f]*|'') printf 'SKIPPED\t%s\tinvalid-id\n' "$repo_id"; continue ;; esac
  [ "${#repo_id}" -eq 64 ] || { printf 'SKIPPED\t%s\tinvalid-id\n' "$repo_id"; continue; }
  target="$security_base/$repo_id"
  if [ -L "$target" ]; then
    printf 'SKIPPED\t%s\tsymlink\n' "$repo_id"
    continue
  fi
  if [ ! -e "$target" ]; then
    printf 'MISSING\t%s\n' "$repo_id"
    continue
  fi
  if [ ! -d "$target" ]; then
    printf 'SKIPPED\t%s\tnot-directory\n' "$repo_id"
    continue
  fi
  if rm -rf -- "$target"; then
    printf 'REMOVED\t%s\n' "$repo_id"
  else
    printf 'FAILED\t%s\n' "$repo_id"
  fi
done
'''.strip()
    command = _ssh_argv(host, ["sh", "-c", script, "--", *cleaned], {})
    command.timeout_seconds = COMMAND_TIMEOUT
    command.preview = (
        f"ssh -i [temporärer Controller-Schlüssel] {host.username}@{host.address} -- "
        f"{len(cleaned)} verwaiste Borg-Sicherheitsstatus-Verzeichnis(se) bereinigen"
    )
    return command

def client_borg_cache_restore_command(host: Host, repository_id: int) -> Command:
    """Restore one authenticated client-cache tar stream without touching user caches."""
    if isinstance(repository_id, bool) or int(repository_id) <= 0:
        raise ValueError("Repository-ID für Client-Cache ist ungültig")
    repository_id = int(repository_id)
    script = r'''\
set -eu
umask 077
repository_id="$1"
case "$repository_id" in *[!0-9]*|'') printf '%s\n' 'FEHLER: Ungültige Repository-ID.' >&2; exit 86 ;; esac
cache_base="${XDG_CACHE_HOME:-$HOME/.cache}/borgbackup-manager"
cache_name="repository-$repository_id"
target="$cache_base/$cache_name"
stamp=$(date +%Y%m%d-%H%M%S)
previous="$cache_base/${cache_name}.pre-bbm-restore-$stamp"
stage="$cache_base/.${cache_name}.bbm-restore.$$"
previous_created=0
cleanup_stage() { rm -rf -- "$stage"; }
rollback() {
  rm -rf -- "$target" 2>/dev/null || true
  if [ "$previous_created" = "1" ] && [ -e "$previous" ]; then mv -- "$previous" "$target" 2>/dev/null || true; fi
  cleanup_stage
}
trap rollback HUP INT TERM
mkdir -p -- "$cache_base"
chmod 700 -- "$cache_base" 2>/dev/null || true
rm -rf -- "$stage"
mkdir -p -- "$stage"
if ! tar --no-same-owner --no-same-permissions -xf - -C "$stage"; then
  cleanup_stage
  printf '%s\n' 'FEHLER: Client-Cache-Archiv konnte nicht entpackt werden.' >&2
  exit 87
fi
incoming="$stage/$cache_name"
if find "$stage" -mindepth 1 -maxdepth 1 ! -name "$cache_name" -print -quit | grep -q .; then
  cleanup_stage
  printf '%s\n' 'FEHLER: Client-Cache-Archiv enthält unerwartete zusätzliche Pfade.' >&2
  exit 88
fi
if [ ! -d "$incoming" ]; then
  cleanup_stage
  printf '%s\n' 'FEHLER: Client-Cache-Archiv enthält nicht den erwarteten Cache-Pfad.' >&2
  exit 88
fi
if find "$incoming" -type l -print -quit 2>/dev/null | grep -q .; then
  cleanup_stage
  printf '%s\n' 'FEHLER: Client-Cache-Archiv enthält symbolische Links.' >&2
  exit 88
fi
# Locks from old backups are forbidden even if an imported archive was crafted
# outside BBM. They are local coordination artifacts, never useful cache data.
find "$incoming" -type d -name lock.exclusive -prune -exec rm -rf -- {} + 2>/dev/null || true
find "$incoming" -type f -name lock.roster -delete 2>/dev/null || true
if [ -e "$target" ]; then
  if [ -e "$previous" ]; then
    printf '%s\n' 'FEHLER: Sicherheitskopie des vorhandenen Client-Caches existiert bereits.' >&2
    cleanup_stage
    exit 89
  fi
  mv -- "$target" "$previous"
  previous_created=1
fi
if ! mv -- "$incoming" "$target"; then
  rollback
  printf '%s\n' 'FEHLER: Client-Cache konnte nicht aktiviert werden.' >&2
  exit 90
fi
cleanup_stage
chmod 700 -- "$target" 2>/dev/null || true
trap - HUP INT TERM
printf '%s\n' 'BBM_CLIENT_CACHE_RESTORED'
if [ "$previous_created" = "1" ]; then printf 'BBM_PREVIOUS_CACHE=%s\n' "$previous"; fi
'''.strip()
    command = _ssh_argv(host, ["sh", "-c", script, "--", str(repository_id)], {})
    command.timeout_seconds = COMMAND_TIMEOUT
    command.preview = (
        f"ssh -i [temporärer Controller-Schlüssel] {host.username}@{host.address} -- "
        f"Client-Borg-Cache repository-{repository_id} wiederherstellen"
    )
    return command


def host_ssh_action_command(host: Host, shell_command: str, timeout_seconds: int = 300) -> Command:
    """Execute one explicitly saved administrator command on a managed device.

    The command is passed as a single ``sh -lc`` argument through the same
    strict host-key verified controller SSH channel used by the manager. The
    Web API never accepts an ad-hoc command for execution; only persisted action
    IDs can reach this helper.
    """
    text = shell_command.strip()
    if not text or "\x00" in text:
        raise ValueError("SSH command must not be empty")
    command = _ssh_argv(host, ["sh", "-lc", text], {}, supervised=False)
    command.preview = f"ssh -i [temporärer Controller-Schlüssel] {host.username}@{host.address} -- sh -lc {shlex.quote(text)}"
    command.timeout_seconds = max(5, min(3600, int(timeout_seconds)))
    return command


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
    parts = [*_borg_base("diff")]
    if content_only:
        parts.append("--content-only")
    parts.extend([f"::{archive}", second_archive, *safe_paths])
    path_label = ", ".join(safe_paths) if safe_paths else "gesamtes Archiv"
    script = f"""
set +e
printf '%s\n' '=============================================================================='
printf '%s\n' 'ARCHIVVERGLEICH'
printf 'ÄLTERES ARCHIV: %s\n' {shlex.quote(archive)}
printf 'NEUERES ARCHIV: %s\n' {shlex.quote(second_archive)}
printf 'BEREICH:         %s\n' {shlex.quote(path_label)}
printf 'INHALT-ONLY:     %s\n' {'ja' if content_only else 'nein'!r}
printf '%s\n' '------------------------------------------------------------------------------'
{shlex.join(parts)}
bbm_rc=$?
printf '%s\n' '------------------------------------------------------------------------------'
if [ "$bbm_rc" -eq 0 ]; then
  printf '%s\n' 'ERGEBNIS: Archivvergleich erfolgreich abgeschlossen.'
elif [ "$bbm_rc" -eq 1 ]; then
  printf '%s\n' 'ERGEBNIS: Archivvergleich mit Warnungen abgeschlossen.' >&2
else
  printf 'ERGEBNIS: Archivvergleich fehlgeschlagen (RC %s).\n' "$bbm_rc" >&2
fi
printf '%s\n' '=============================================================================='
exit "$bbm_rc"
""".strip()
    return repository_access_command(job.repository, ["sh", "-c", script])


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


def manager_archive_mount_command(repository: Repository, archive: str, mount_path: str) -> Command:
    archive = validate_archive_name(archive)
    target = PurePosixPath(mount_path)
    if not mount_path.startswith("/") or ".." in target.parts or any(c in mount_path for c in "\x00\r\n"):
        raise ValueError("Invalid archive mount path")
    command = repository_access_command(
        repository,
        [*_borg_base("mount"), "-o", "allow_other", f"::{archive}", mount_path],
    )
    command.allow_active_archive_mount = True
    command.timeout_seconds = min(COMMAND_TIMEOUT, 900)
    return command


def manager_archive_unmount_command(mount_path: str) -> Command:
    target = PurePosixPath(mount_path)
    if not mount_path.startswith("/") or ".." in target.parts or any(c in mount_path for c in "\x00\r\n"):
        raise ValueError("Invalid archive mount path")
    script = r"""
set +e
mount_path="$1"
if command -v mountpoint >/dev/null 2>&1 && ! mountpoint -q "$mount_path"; then
  exit 0
fi
try_unmount() {
  timeout -k 1 5 "$@" "$mount_path"
}
if command -v fusermount3 >/dev/null 2>&1; then
  try_unmount fusermount3 -u && exit 0
elif command -v fusermount >/dev/null 2>&1; then
  try_unmount fusermount -u && exit 0
fi
try_unmount borg umount && exit 0
if command -v fusermount3 >/dev/null 2>&1; then
  try_unmount fusermount3 -uz && exit 0
elif command -v fusermount >/dev/null 2>&1; then
  try_unmount fusermount -uz && exit 0
fi
if command -v umount >/dev/null 2>&1; then
  try_unmount umount -l && exit 0
fi
exit 79
""".strip()
    return Command(
        argv=manager_borg_argv(["sh", "-c", script, "--", mount_path]),
        preview=f"[direkt im Manager] Archiv-Mount aushängen: {shlex.quote(mount_path)}",
        timeout_seconds=18,
        allow_active_archive_mount=True,
    )


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
    on_output_bytes: Callable[[str, bytes], Awaitable[bytes | None] | bytes | None] | None = None,
    abort_event: asyncio.Event | None = None,
    abort_reason: Callable[[], str] | None = None,
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

    async def stop_process_gracefully() -> tuple[bool, bool]:
        """Stop a Borg command while giving the remote wrapper time to clean up."""
        forced = False
        wrapper_confirmed = False
        if command.stdin_controlled_cancel and process is not None and process.stdin:
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
            if not await wait_after_signal(signal.SIGINT, 20):
                forced = True
                if not await wait_after_signal(signal.SIGTERM, 5):
                    await wait_after_signal(signal.SIGKILL, 5)
        await asyncio.gather(process_tasks, return_exceptions=True)
        return forced, wrapper_confirmed

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
        output_parts: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}

        def capture(name: str, chunk: bytes) -> None:
            output_parts[name].extend(chunk)
            if capture_limit_bytes and capture_limit_bytes > 0 and len(output_parts[name]) > capture_limit_bytes:
                del output_parts[name][:-capture_limit_bytes]

        async def pump(name: str, stream: asyncio.StreamReader | None) -> None:
            if stream is None:
                return
            # Large reads significantly reduce Python callback overhead for
            # ``borg create --list`` while preserving the byte stream exactly.
            while chunk := await stream.read(256 * 1024):
                capture_chunk = chunk
                if on_output_bytes:
                    result = on_output_bytes(name, chunk)
                    if result is not None and hasattr(result, "__await__"):
                        result = await result
                    if isinstance(result, (bytes, bytearray, memoryview)):
                        capture_chunk = bytes(result)
                elif on_output:
                    result = on_output(name, chunk.decode(errors="replace"))
                    if result is not None:
                        await result
                capture(name, capture_chunk)

        if command.stdin_data is not None and process.stdin:
            process.stdin.write(command.stdin_data)
            await process.stdin.drain()
            if not command.stdin_controlled_cancel:
                process.stdin.close()

        stdout_task = asyncio.create_task(pump("stdout", process.stdout))
        stderr_task = asyncio.create_task(pump("stderr", process.stderr))
        wait_task = asyncio.create_task(process.wait())
        process_tasks = asyncio.gather(stdout_task, stderr_task, wait_task)
        abort_task: asyncio.Task[bool] | None = None
        try:
            timeout = command.timeout_seconds if command.timeout_seconds is not None else COMMAND_TIMEOUT
            if abort_event is None:
                await asyncio.wait_for(asyncio.shield(process_tasks), timeout=timeout)
            else:
                abort_task = asyncio.create_task(abort_event.wait())
                done, _pending = await asyncio.wait(
                    {process_tasks, abort_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED,
                )
                if process_tasks in done:
                    await process_tasks
                elif abort_task in done and abort_event.is_set():
                    await stop_process_gracefully()
                    reason = abort_reason() if abort_reason is not None else "Command aborted by safety monitor"
                    return 75, output_parts["stdout"].decode(errors="replace"), reason
                else:
                    raise TimeoutError
        except TimeoutError:
            if not await wait_after_signal(signal.SIGTERM, 5):
                await wait_after_signal(signal.SIGKILL, 5)
            await asyncio.gather(process_tasks, return_exceptions=True)
            return 124, output_parts["stdout"].decode(errors="replace"), "Command timed out"
        except asyncio.CancelledError:
            # Commands using the secret wrapper have a dedicated cancellation
            # channel: closing stdin after the payload makes the remote wrapper
            # signal Borg itself and wait for its shutdown. This avoids killing
            # the local ssh client before the remote Borg process has released
            # an external repository lock.
            forced, wrapper_confirmed = await stop_process_gracefully()
            raise CommandCancelled(
                forced=forced,
                remote_cleanup_confirmed=wrapper_confirmed,
            )
        finally:
            if abort_task is not None:
                abort_task.cancel()
                await asyncio.gather(abort_task, return_exceptions=True)
        return (
            process.returncode or 0,
            output_parts["stdout"].decode(errors="replace"),
            output_parts["stderr"].decode(errors="replace"),
        )
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

