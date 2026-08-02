from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from collections import deque
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.borg_compat import classify_borg_version, parse_borg_version, version_tuple
from app.borg_stats import merge_archive_statistics, parse_archive_listing, parse_borg_info
from app.archive_metadata import sort_archives_newest_first
from app.borg_progress import (
    BorgItemActivityStreamFilter, BorgNetworkStreamFilter, BorgProgressStreamFilter,
    BorgRestoreProgressStreamFilter, clear_run_live_activity, clear_run_progress,
    clear_run_restore_progress, get_run_network_activity, get_run_restore_progress,
    set_run_item_activity, set_run_network_activity, set_run_progress, set_run_restore_progress,
)
from app.backup_stats import parse_backup_statistics, parse_source_scan_statistics
from app.borg_warnings import BorgWarningCollector, unresolved_warning_summary
from app.config import (
    REPOSITORY_AUTHORIZED_KEYS_PATH,
    REPOSITORY_HOST_KEY_PUBLIC_PATH,
    REPOSITORY_PUBLIC_HOST,
    REPOSITORY_ROOT,
    REPOSITORY_SSH_PORT,
)
from app.database import SessionLocal
from app.debug_logging import (
    detail_requires_debug_log, log_unexpected_exception, public_error_message,
)
from app.models import BackupSchedule, Host, HostRepositoryAccess, Job, ManagerArchiveMount, Repository, Run
from app.security_store import get_host_ssh_action
from app.repository_sizes import (
    managed_repository_filesystem_size, repository_statistics_from_borg_info,
    store_repository_statistics,
)
from app.archive_cache import invalidate_archive_cache, store_archive_cache
from app.archive_mounts import archive_mount_is_active
from app.repository_cache import clear_repository_manager_cache, clear_repository_manager_cache_locks
from app.repository_diagnostics import compact_repository_diagnostic
from app.repository_state import (
    managed_repository_present, require_empty_managed_repository,
    require_initializable_managed_repository,
)
from app.run_logs import RunLogWriter, append_run_log
from app.runner import (
    Command,
    CommandCancelled,
    backup_command,
    delete_archives_command,
    diff_archives_command,
    execute,
    host_repository_bootstrap_command,
    host_ssh_action_command,
    prune_command,
    repository_command,
    repository_init_command,
    repository_keyfile_path,
    repository_size_command,
    repository_validation_command,
    external_repository_storage_command,
    parse_external_repository_storage,
    repository_compact_command,
    repository_archives_info_command, repository_list_command,
    source_stats_command,
    rename_archive_command,
    restore_command,
)
from app.external_repository import (
    external_filesystem_parallel_identity, generate_ed25519_keypair,
    storage_probe_target_from_location,
)
from app.vault import get_system_secret, set_repository_secret, set_system_secret
from app.log_filter import extract_error_output, strip_borg_item_lines
from app.notifications import notify_run_completion
from app.settings import load_settings
from app.schedules import schedule_target_job_ids
from app.storage_guard import (
    effective_storage_guard, mounted_filesystems_below, repository_mount_path, repository_storage_status,
)



class ActiveArchiveMountError(RuntimeError):
    def __init__(self, repository_id: int, archive: str):
        self.repository_id = repository_id
        self.archive = archive
        super().__init__(
            f'Repository besitzt einen aktiven Archiv-Mount ({archive}). '
            'Archiv zuerst aushängen.'
        )


def _active_manager_archive_mount(repository_id: int | None) -> ManagerArchiveMount | None:
    if repository_id is None:
        return None
    with SessionLocal() as db:
        row = db.scalar(
            select(ManagerArchiveMount).where(
                ManagerArchiveMount.repository_id == repository_id,
            ).order_by(ManagerArchiveMount.id).limit(1)
        )
        if row is None:
            return None
        # Treat every physically active FUSE mount as a repository blocker,
        # including mounts whose previous unmount attempt ended in an error.
        # A freshly inserted "mounting" row is also active until creation either
        # succeeds or rolls back.
        if row.status == "mounting" or archive_mount_is_active(row.mount_path):
            db.expunge(row)
            return row
        if row.status != "stale":
            row.status = "stale"
            row.error = "Mount ist nicht mehr im Container aktiv. Eintrag kann entfernt werden."
            db.commit()
        return None



_SQLITE_BORG_ITEM_LINE_BYTES_RE = re.compile(
    rb"^[ \t]*(?:[Rr][Ee][Mm][Oo][Tt][Ee]:[ \t]*)?[AMUCERdbchsfipx?+\-.][ \t]+\S"
)
_SQLITE_ONLY_BORG_ITEM_BLOCK_BYTES_RE = re.compile(
    rb"(?:(?:[ \t]*(?:[Rr][Ee][Mm][Oo][Tt][Ee]:[ \t]*)?"
    rb"[AMUCERdbchsfipx?+\-.][ \t]+[^\r\n]*(?:\r?\n)))+\Z"
)


class _BackupSqlitePreviewFilter:
    """Keep readable metadata while excluding every Borg item path.

    Complete item-only blocks take a regex fast path in C. Mixed blocks are
    inspected line by line, with a carry buffer so a path split across process
    chunks can never leak its continuation into the database preview.
    """

    def __init__(self) -> None:
        self._carry = bytearray()

    def feed(self, data: bytes) -> str:
        if not data:
            return ""
        payload = bytes(self._carry) + data
        newline = payload.rfind(b"\n")
        if newline < 0:
            self._carry[:] = payload
            return ""
        complete = payload[: newline + 1]
        self._carry[:] = payload[newline + 1 :]
        if _SQLITE_ONLY_BORG_ITEM_BLOCK_BYTES_RE.fullmatch(complete):
            return ""
        kept = [
            line for line in complete.splitlines(keepends=True)
            if not _SQLITE_BORG_ITEM_LINE_BYTES_RE.match(line)
        ]
        return b"".join(kept).decode("utf-8", errors="replace")

    def finalize(self) -> str:
        if not self._carry:
            return ""
        final = bytes(self._carry)
        self._carry.clear()
        if _SQLITE_BORG_ITEM_LINE_BYTES_RE.match(final):
            return ""
        return final.decode("utf-8", errors="replace")

_key_file_lock = Lock()
_repository_init_lock = Lock()
_initializing_repositories: set[int] = set()
_active_run_lock = Lock()
_active_run_tasks: dict[int, asyncio.Task] = {}
_executing_run_ids: set[int] = set()
_repository_locks: dict[tuple[int, str], "_AdjustableCapacity"] = {}
_mount_locks: dict[tuple[int, str], "_AdjustableCapacity"] = {}
_manager_borg_locks: dict[tuple[int, int], asyncio.Lock] = {}
_run_claim_lock = Lock()
_repository_chain_lock = Lock()
_repository_chain_reservations: dict[str, list[dict[str, object]]] = {}
_run_chain_tokens: dict[int, str] = {}
_maintenance_chain_tasks: set[asyncio.Task] = set()
_mount_topology_lock = Lock()
_mount_topology_cache: tuple[float, list[Path]] = (0.0, [])




def _register_repository_chain(repository: Repository, run_id: int, token: str) -> None:
    key = _repository_execution_key(repository, repository.id)
    with _repository_chain_lock:
        queue = _repository_chain_reservations.setdefault(key, [])
        queue.append({"token": token, "root_run_id": int(run_id), "started": False})
        queue.sort(key=lambda item: int(item["root_run_id"]))
        _run_chain_tokens[int(run_id)] = token


def _register_chain_run(run_id: int, token: str | None) -> None:
    if not token:
        return
    with _repository_chain_lock:
        _run_chain_tokens[int(run_id)] = token


def _mark_repository_chain_started(run_id: int) -> None:
    with _repository_chain_lock:
        token = _run_chain_tokens.get(int(run_id))
        if not token:
            return
        for queue in _repository_chain_reservations.values():
            for item in queue:
                if item.get("token") == token and int(item.get("root_run_id", 0)) == int(run_id):
                    item["started"] = True
                    return


def _release_repository_chain(token: str) -> None:
    with _repository_chain_lock:
        empty: list[str] = []
        for key, queue in _repository_chain_reservations.items():
            queue[:] = [item for item in queue if item.get("token") != token]
            if not queue:
                empty.append(key)
        for key in empty:
            _repository_chain_reservations.pop(key, None)
        for run_id, run_token in list(_run_chain_tokens.items()):
            if run_token == token:
                _run_chain_tokens.pop(run_id, None)


def _repository_chain_snapshot() -> tuple[dict[str, dict[str, object]], dict[int, str]]:
    with _repository_chain_lock:
        active = {
            key: dict(queue[0])
            for key, queue in _repository_chain_reservations.items()
            if queue
        }
        tokens = dict(_run_chain_tokens)
    return active, tokens


def _track_maintenance_task(task: asyncio.Task) -> None:
    _maintenance_chain_tasks.add(task)
    task.add_done_callback(_maintenance_chain_tasks.discard)


def trust_host_key(line: str) -> None:
    # Hostkeys are stored per device in manager.db. They are public verification
    # material and no longer copied to a shared persistent known_hosts file.
    if not line.strip():
        raise ValueError("SSH host key must not be empty")


def controller_public_key() -> str:
    public_key = get_system_secret("controller_public_key")
    if not public_key:
        raise ValueError("Controller public key is not available; restart the container to initialize security material")
    return public_key.strip()


def rotate_controller_key() -> str:
    """Generate a new controller key and archive the previous pair encrypted."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    previous_private = get_system_secret("controller_private_key")
    previous_public = get_system_secret("controller_public_key")
    private_key, public_key = generate_ed25519_keypair(f"borgbackup-manager-controller-{stamp}")
    if previous_private:
        set_system_secret(f"controller_private_key_archive_{stamp}", previous_private)
    if previous_public:
        set_system_secret(f"controller_public_key_archive_{stamp}", previous_public)
    set_system_secret("controller_private_key", private_key)
    set_system_secret("controller_public_key", public_key)
    return public_key.strip()


def _repository_known_hosts_line() -> str:
    if not REPOSITORY_HOST_KEY_PUBLIC_PATH.exists():
        raise ValueError("Repository SSH host key is not available; run the installer first")
    parts = REPOSITORY_HOST_KEY_PUBLIC_PATH.read_text(encoding="utf-8").strip().split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519":
        raise ValueError("Repository SSH host key is invalid")
    public_host = REPOSITORY_PUBLIC_HOST.strip("[]")
    target = public_host if REPOSITORY_SSH_PORT == 22 else f"[{public_host}]:{REPOSITORY_SSH_PORT}"
    return f"{target} {parts[0]} {parts[1]}"


def _normalize_public_key(public_key: str, comment: str) -> str:
    parts = public_key.strip().split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519" or not re.fullmatch(r"[A-Za-z0-9+/=]+", parts[1]):
        raise ValueError("Device returned an invalid repository public key")
    return f"{parts[0]} {parts[1]} {comment}"


def _write_authorized_keys(lines: list[str]) -> None:
    path = REPOSITORY_AUTHORIZED_KEYS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with _key_file_lock:
        old_stat = path.stat() if path.exists() else None
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        os.chmod(temporary, 0o600)
        try:
            if old_stat:
                os.chown(temporary, old_stat.st_uid, old_stat.st_gid)
            else:
                os.chown(
                    temporary,
                    int(os.getenv("BBM_BORG_UID", "1000")),
                    int(os.getenv("BBM_BORG_GID", "1000")),
                )
        except (OSError, ValueError):
            pass
        temporary.replace(path)


def rebuild_repository_authorized_keys() -> int:
    """Write the current repository-scoped BBM key set."""
    lines: list[str] = []
    with SessionLocal() as db:
        rows = db.scalars(
            select(HostRepositoryAccess)
            .options(joinedload(HostRepositoryAccess.host), joinedload(HostRepositoryAccess.repository))
            .order_by(HostRepositoryAccess.host_id, HostRepositoryAccess.repository_id)
        ).all()
        for access in rows:
            host, repository = access.host, access.repository
            if not access.public_key or not host.enabled or not repository.enabled or not repository.storage_path:
                continue
            root = REPOSITORY_ROOT.resolve()
            repository_path = Path(repository.storage_path).resolve()
            if repository_path == root or root not in repository_path.parents:
                continue
            key = _normalize_public_key(
                access.public_key,
                f"bbm-access-h{host.id}-r{repository.id}",
            )
            forced = f'/usr/local/bin/bbm-borg-serve --repository {repository_path}'
            lines.append(f'restrict,command="{forced}" {key}')
    _write_authorized_keys(lines)
    return len(lines)


def sync_repository_access_assignments() -> None:
    """Synchronize per-host/per-repository access rows with current managed jobs."""
    with SessionLocal() as db:
        desired = {
            (host_id, repository_id)
            for host_id, repository_id in db.execute(
                select(Job.host_id, Job.repository_id)
                .join(Repository, Repository.id == Job.repository_id)
                .where(Repository.storage_path.is_not(None))
            ).all()
        }
        existing_rows = db.scalars(select(HostRepositoryAccess)).all()
        existing = {(row.host_id, row.repository_id): row for row in existing_rows}
        for pair, row in list(existing.items()):
            if pair not in desired:
                db.delete(row)
                existing.pop(pair, None)
        for host_id, repository_id in desired - set(existing):
            db.add(HostRepositoryAccess(host_id=host_id, repository_id=repository_id))
        db.flush()
        access_rows = db.scalars(select(HostRepositoryAccess).options(joinedload(HostRepositoryAccess.repository))).all()
        by_host: dict[int, list[HostRepositoryAccess]] = {}
        for access in access_rows:
            if access.repository and access.repository.enabled:
                by_host.setdefault(access.host_id, []).append(access)
        for host in db.scalars(select(Host)):
            assignments = by_host.get(host.id, [])
            host.repository_ready = bool(assignments) and all(bool(item.public_key) for item in assignments)
        db.commit()
    rebuild_repository_authorized_keys()


def revoke_host_repository_access(host_id: int) -> None:
    with SessionLocal() as db:
        for row in db.scalars(select(HostRepositoryAccess).where(HostRepositoryAccess.host_id == host_id)):
            db.delete(row)
        host = db.get(Host, host_id)
        if host:
            host.repository_ready = False
        db.commit()
    sync_repository_access_assignments()


def repository_access_ready(host_id: int, repository_id: int) -> bool:
    with SessionLocal() as db:
        row = db.scalar(
            select(HostRepositoryAccess).join(Repository, Repository.id == HostRepositoryAccess.repository_id).where(
                HostRepositoryAccess.host_id == host_id,
                HostRepositoryAccess.repository_id == repository_id,
                HostRepositoryAccess.public_key.is_not(None),
                Repository.enabled.is_(True),
            )
        )
        return row is not None


def _repository_execution_key(repository: Repository | None, repository_id: int | None = None) -> str:
    """Return a stable key for the physical Borg repository target.

    Database IDs alone are insufficient: duplicate imports or slug collisions can
    leave two repository records pointing at the same managed directory or
    external URL. Borg still sees one physical repository and must therefore
    be serialized as one queue.
    """
    if repository is None:
        return f"repository-id:{repository_id}"
    if repository.storage_path:
        try:
            target = str(Path(repository.storage_path).resolve(strict=False))
        except (OSError, RuntimeError):
            target = str(repository.storage_path).strip()
        return f"managed:{target}"
    location = str(repository.location or "").strip().rstrip("/")
    return f"external:{location}" if location else f"repository-id:{repository.id}"


def _repository_execution_key_by_id(repository_id: int) -> str:
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        return _repository_execution_key(repository, repository_id)


def _execution_mounts(*, max_age_seconds: float = 1.0) -> list[Path]:
    global _mount_topology_cache
    now = time.monotonic()
    with _mount_topology_lock:
        sampled_at, mounts = _mount_topology_cache
        if mounts and now - sampled_at <= max(0.1, max_age_seconds):
            return list(mounts)
        try:
            mounts = mounted_filesystems_below(REPOSITORY_ROOT)
        except OSError:
            mounts = []
        _mount_topology_cache = (now, list(mounts))
        return list(mounts)


def _repository_mount_key(repository: Repository | None, *, mounts=None) -> str | None:
    """Return the managed or external filesystem parallelism group key."""
    if repository is None:
        return None
    if repository.storage_path:
        mount = repository_mount_path(repository.storage_path, REPOSITORY_ROOT, mounts=mounts)
        return str(mount) if mount is not None else None
    identity = external_filesystem_parallel_identity(
        repository.location, repository.external_storage_path
    )
    return identity[0] if identity else None


def _mount_parallel_limit(mount_key: str | None, settings=None) -> int:
    if not mount_key:
        return 0
    active_settings = settings or load_settings()
    try:
        limits = (
            active_settings.external_storage_parallel_limits
            if mount_key.startswith("external:")
            else active_settings.mount_parallel_limits
        )
        return max(0, min(64, int((limits or {}).get(mount_key, 0))))
    except (AttributeError, TypeError, ValueError):
        return 0


def _source_stats_parallel_limit(settings=None) -> int:
    """Return the global cap for simultaneous manual source-statistics scans."""
    active_settings = settings or load_settings()
    try:
        return max(1, min(64, int(getattr(active_settings, "source_stats_parallel_limit", 1) or 1)))
    except (TypeError, ValueError):
        return 1


class _AdjustableCapacity:
    """Small event-loop-local capacity limiter whose limit can change live.

    ``asyncio.Semaphore`` cannot be resized safely.  The previous cache kept an
    old semaphore until it became completely idle; with a continuous queue a
    mount changed from 1 to 2 therefore remained stuck at 1 indefinitely.
    This limiter tracks occupied slots explicitly, applies increases
    immediately and lets decreases take effect as soon as active users leave.
    """

    def __init__(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._in_use = 0
        self._waiters: deque[asyncio.Future[bool]] = deque()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def in_use(self) -> int:
        return self._in_use

    def set_limit(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._wake_waiters()

    async def acquire(self) -> bool:
        if self._in_use < self._limit and not self._waiters:
            self._in_use += 1
            return True
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[bool] = loop.create_future()
        self._waiters.append(waiter)
        self._wake_waiters()
        try:
            await waiter
            return True
        except BaseException:
            if waiter.done() and not waiter.cancelled():
                # The slot was already reserved by _wake_waiters().
                self._in_use = max(0, self._in_use - 1)
                self._wake_waiters()
            else:
                try:
                    self._waiters.remove(waiter)
                except ValueError:
                    pass
                waiter.cancel()
            raise

    def release(self) -> None:
        if self._in_use <= 0:
            raise ValueError("capacity limiter released too many times")
        self._in_use -= 1
        self._wake_waiters()

    def _wake_waiters(self) -> None:
        while self._in_use < self._limit and self._waiters:
            waiter = self._waiters.popleft()
            if waiter.done():
                continue
            self._in_use += 1
            waiter.set_result(True)


def _capacity_semaphore(cache, key: tuple[int, str], limit: int) -> _AdjustableCapacity:
    limiter = cache.get(key)
    if limiter is None:
        limiter = _AdjustableCapacity(limit)
        cache[key] = limiter
    else:
        limiter.set_limit(limit)
    return limiter


def _repository_lock(repository_id: int | None) -> _AdjustableCapacity | None:
    """Return the runtime lock for one repository database record.

    Persisted runs are serialized by the atomic queue planner using the stable
    physical repository key.  This additional lock only coordinates a queued
    run with direct interactive calls for the same repository record.  Keying
    it by the database ID prevents two distinct repositories on one filesystem
    from being accidentally collapsed by path canonicalization before the
    queue planner can apply the configured mount parallelism.
    """
    if repository_id is None:
        return None
    loop = asyncio.get_running_loop()
    with SessionLocal() as db:
        if db.get(Repository, repository_id) is None:
            return None
    return _capacity_semaphore(_repository_locks, (id(loop), f"repository-id:{repository_id}"), 1)


def _manager_borg_lock(repository_id: int | None) -> asyncio.Lock | None:
    """Return the one-at-a-time lock for BBM's manager-side Borg cache.

    Backup jobs run Borg on the source client and do not use this lock. Manager
    operations such as info/list/prune/compact share /data/borg-cache and must
    never overlap for one repository.
    """
    if repository_id is None:
        return None
    loop = asyncio.get_running_loop()
    key = (id(loop), int(repository_id))
    lock = _manager_borg_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _manager_borg_locks[key] = lock
    return lock


def _cleanup_external_manager_cache_locks(repository_id: int | None) -> dict[str, int]:
    """Repair only stale BBM-private cache locks for external repositories.

    The caller must already hold ``_manager_borg_lock``. Since the cache path
    belongs exclusively to BBM, any remaining lock at this point cannot belong
    to another active manager Borg command. Managed repositories keep their
    existing behavior unchanged.
    """
    if repository_id is None:
        return {"lock_directories_removed": 0, "lock_files_removed": 0}
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if repository is None or repository.storage_path:
            return {"lock_directories_removed": 0, "lock_files_removed": 0}
        db.expunge(repository)
    return clear_repository_manager_cache_locks(repository)


def _mount_lock(repository_id: int | None) -> _AdjustableCapacity | None:
    if repository_id is None:
        return None
    loop = asyncio.get_running_loop()
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if repository is None:
            return None
        mount_key = _repository_mount_key(repository, mounts=_execution_mounts())
    limit = _mount_parallel_limit(mount_key)
    if not mount_key or limit <= 0:
        return None
    return _capacity_semaphore(_mount_locks, (id(loop), mount_key), limit)


async def _acquire_mount_capacity(repository_id: int | None) -> _AdjustableCapacity | None:
    """Acquire mount capacity while reloading live limit changes.

    A task may already be waiting when an administrator raises a mount limit.
    Re-resolving every 250 ms applies the new value immediately instead of
    requiring the entire mount queue to drain first.  Setting the limit to 0
    also releases the task from mount limiting on the next refresh.
    """
    while True:
        limiter = _mount_lock(repository_id)
        if limiter is None:
            return None
        try:
            await asyncio.wait_for(limiter.acquire(), timeout=0.25)
            return limiter
        except TimeoutError:
            continue


async def _acquire_repository_exclusive(repository_id: int) -> tuple[_AdjustableCapacity, int]:
    """Acquire the single repository execution slot for maintenance."""
    semaphore = _repository_lock(repository_id)
    if semaphore is None:
        raise LookupError("Repository not found")
    await semaphore.acquire()
    return semaphore, 1


def _release_repository_exclusive(semaphore: _AdjustableCapacity, permits: int) -> None:
    for _ in range(max(0, permits)):
        semaphore.release()

def _repository_run_blocker(run_id: int, repository_id: int) -> int | None:
    """Return the earlier run that owns the repository's single Borg slot."""
    execution_key = _repository_execution_key_by_id(repository_id)
    with SessionLocal() as db:
        rows = db.scalars(
            select(Run)
            .options(joinedload(Run.repository))
            .where(Run.status.in_(["queued", "running"]), Run.id != run_id)
            .order_by(Run.id)
        ).all()
        blockers = [
            row.id for row in rows
            if _repository_execution_key(row.repository, row.repository_id) == execution_key
            and (row.status == "running" or row.id < run_id)
        ]
        return min(blockers) if blockers else None



def _run_schedule_key(run: Run) -> str | None:
    if run.trigger_type != "schedule":
        return None
    if run.schedule_id_snapshot:
        return f"schedule-id:{run.schedule_id_snapshot}"
    name = (run.schedule_name_snapshot or "").strip().casefold()
    return f"schedule-name:{name}" if name else None


def _execution_plan(
    db, *, current_run_id: int | None = None
) -> tuple[set[int], dict[int, dict[str, int | str]]]:
    """Return queued runs allowed to start now and a reason for blocked runs.

    Capacity is evaluated in run-ID order across four independent layers:
    global, schedule, the physical Borg repository and the underlying managed
    mount. Every Borg repository has exactly one execution slot; mount limits
    control parallel work only across different repositories on that mount.
    """
    rows = db.scalars(
        select(Run)
        .options(joinedload(Run.repository))
        .where(Run.status.in_(["queued", "running"]))
        .order_by(Run.id)
    ).all()
    with _active_run_lock:
        live_task_ids: set[int] = set()
        stale_task_ids: list[int] = []
        for candidate_id, task in _active_run_tasks.items():
            if not isinstance(task, asyncio.Task) or task.done() or task.get_loop().is_closed():
                stale_task_ids.append(candidate_id)
                continue
            live_task_ids.add(candidate_id)
        for candidate_id in stale_task_ids:
            _active_run_tasks.pop(candidate_id, None)
        live_run_ids = live_task_ids | set(_executing_run_ids)
    if current_run_id is not None:
        live_run_ids.add(current_run_id)
    rows = [row for row in rows if row.id in live_run_ids]
    running = [row for row in rows if row.status == "running"]
    queued = [row for row in rows if row.status == "queued"]
    settings = load_settings()
    global_limit = settings.max_parallel_runs
    active_archive_mount_repositories: set[int] = set()
    mount_rows = list(db.scalars(select(ManagerArchiveMount)))
    mount_state_changed = False
    for mount_row in mount_rows:
        if mount_row.status == "mounting" or archive_mount_is_active(mount_row.mount_path):
            active_archive_mount_repositories.add(mount_row.repository_id)
        elif mount_row.status != "stale":
            mount_row.status = "stale"
            mount_row.error = "Mount ist nicht mehr im Container aktiv. Eintrag kann entfernt werden."
            mount_state_changed = True
    if mount_state_changed:
        db.flush()
    mounts = _execution_mounts()
    chain_reservations, run_chain_tokens = _repository_chain_snapshot()

    mount_limits: dict[str, int] = {}
    row_repository_keys: dict[int, str | None] = {}
    row_mount_keys: dict[int, str | None] = {}
    for row in rows:
        repository_key = (
            _repository_execution_key(row.repository, row.repository_id)
            if row.repository_id is not None and row.action != "source-stats" else None
        )
        row_repository_keys[row.id] = repository_key
        mount_key = (
            _repository_mount_key(row.repository, mounts=mounts)
            if row.action != "source-stats" else None
        )
        row_mount_keys[row.id] = mount_key
        if mount_key:
            limit = _mount_parallel_limit(mount_key, settings)
            if limit > 0:
                mount_limits[mount_key] = limit

    repository_occupants: dict[str, list[int]] = {}
    mount_occupants: dict[str, list[int]] = {}
    schedule_occupants: dict[str, list[int]] = {}
    schedule_limits: dict[str, int] = {}
    for row in rows:
        key = _run_schedule_key(row)
        limit = int(row.schedule_parallel_limit_snapshot or 0)
        if key and limit > 0:
            previous = schedule_limits.get(key)
            schedule_limits[key] = min(previous, limit) if previous else limit
    for row in running:
        repository_key = row_repository_keys.get(row.id)
        if repository_key:
            repository_occupants.setdefault(repository_key, []).append(row.id)
        mount_key = row_mount_keys.get(row.id)
        if mount_key and mount_key in mount_limits:
            mount_occupants.setdefault(mount_key, []).append(row.id)
        schedule_key = _run_schedule_key(row)
        if schedule_key:
            schedule_occupants.setdefault(schedule_key, []).append(row.id)

    selected: set[int] = set()
    blockers: dict[int, dict[str, int | str]] = {}
    global_occupants = [row.id for row in running]
    source_stats_limit = _source_stats_parallel_limit(settings)
    source_stats_occupants = [row.id for row in running if row.action == "source-stats"]
    for row in queued:
        repository_key = row_repository_keys.get(row.id)
        if row.repository_id in active_archive_mount_repositories and row.action != "source-stats":
            blockers[row.id] = {
                "kind": "archive-mount",
                "blocker_id": 0,
                "repository": row.repository.name if row.repository else "Repository",
            }
            continue
        reservation = chain_reservations.get(repository_key) if repository_key else None
        if reservation:
            owner_token = str(reservation.get("token") or "")
            root_run_id = int(reservation.get("root_run_id") or 0)
            started = bool(reservation.get("started"))
            row_token = run_chain_tokens.get(row.id)
            if row_token != owner_token and (started or row.id > root_run_id):
                blockers[row.id] = {
                    "kind": "maintenance-chain",
                    "blocker_id": root_run_id,
                    "repository": row.repository.name if row.repository else "Repository",
                }
                continue
        repository_blockers = repository_occupants.get(repository_key, []) if repository_key else []
        if repository_key and repository_blockers:
            blockers[row.id] = {
                "kind": "repository", "blocker_id": min(repository_blockers),
                "limit": 1,
                "repository": row.repository.name if row.repository else "Repository",
            }
            continue

        mount_key = row_mount_keys.get(row.id)
        mount_limit = mount_limits.get(mount_key, 0) if mount_key else 0
        mount_blockers = mount_occupants.get(mount_key, []) if mount_key else []
        if mount_limit > 0 and len(mount_blockers) >= mount_limit:
            blockers[row.id] = {
                "kind": "mount", "blocker_id": min(mount_blockers),
                "limit": mount_limit, "mount": mount_key or "/repositories",
            }
            continue

        schedule_key = _run_schedule_key(row)
        schedule_limit = schedule_limits.get(schedule_key, 0) if schedule_key else 0
        schedule_blockers = schedule_occupants.get(schedule_key, []) if schedule_key else []
        if schedule_limit > 0 and len(schedule_blockers) >= schedule_limit:
            blockers[row.id] = {
                "kind": "schedule", "blocker_id": min(schedule_blockers),
                "limit": schedule_limit, "schedule": row.schedule_name_snapshot or "Zeitplan",
            }
            continue

        if row.action == "source-stats" and len(source_stats_occupants) >= source_stats_limit:
            blockers[row.id] = {
                "kind": "source-stats",
                "blocker_id": min(source_stats_occupants) if source_stats_occupants else 0,
                "limit": source_stats_limit,
            }
            continue

        if global_limit > 0 and len(global_occupants) >= global_limit:
            blockers[row.id] = {
                "kind": "global", "blocker_id": min(global_occupants) if global_occupants else 0,
                "limit": global_limit,
            }
            continue

        selected.add(row.id)
        global_occupants.append(row.id)
        if row.action == "source-stats":
            source_stats_occupants.append(row.id)
        if repository_key:
            repository_occupants.setdefault(repository_key, []).append(row.id)
        if mount_key and mount_limit > 0:
            mount_occupants.setdefault(mount_key, []).append(row.id)
        if schedule_key:
            schedule_occupants.setdefault(schedule_key, []).append(row.id)

    return selected, blockers


def _claim_execution_turn(run_id: int) -> tuple[bool, dict[str, int | str] | None]:
    """Atomically claim a queue slot within the manager process."""
    with _run_claim_lock:
        with SessionLocal() as db:
            current = db.get(Run, run_id)
            if not current or current.status != "queued":
                return False, None
            selected, blockers = _execution_plan(db, current_run_id=run_id)
            if run_id not in selected:
                return False, blockers.get(run_id)
            current.status = "running"
            current.started_at = datetime.now(timezone.utc)
            db.commit()
            _mark_repository_chain_started(run_id)
            return True, None


def _queue_message(reason: dict[str, int | str] | None) -> str:
    if not reason:
        return "WARTESCHLANGE: Warte auf freie Ausführungskapazität."
    blocker = int(reason.get("blocker_id", 0) or 0)
    suffix = f" #{blocker}" if blocker else ""
    wait_target = f"Ausführung #{blocker}" if blocker else "freie Kapazität"
    if reason.get("kind") == "archive-mount":
        return (
            f"WARTESCHLANGE: Repository „{reason.get('repository', 'Repository')}“ besitzt einen aktiven "
            "Archiv-Mount; die Ausführung startet nach dem Aushängen."
        )
    if reason.get("kind") == "repository":
        return (
            f"WARTESCHLANGE: Repository „{reason.get('repository', 'Repository')}“ wird bereits von "
            f"{wait_target} verwendet; Borg erlaubt dort nur einen schreibenden Lauf gleichzeitig."
        )
    if reason.get("kind") == "mount":
        return (
            f"WARTESCHLANGE: Repository-Dateisystem „{reason.get('mount', '/repositories')}“ erlaubt maximal "
            f"{reason.get('limit', 1)} parallele Ausführung(en); warte auf {wait_target}."
        )
    if reason.get("kind") == "schedule":
        return (
            f"WARTESCHLANGE: Zeitplan „{reason.get('schedule', 'Zeitplan')}“ erlaubt maximal "
            f"{reason.get('limit', 1)} parallele Ausführung(en); warte auf {wait_target}."
        )
    if reason.get("kind") == "source-stats":
        return (
            f"WARTESCHLANGE: Quellenstatistik erlaubt maximal "
            f"{reason.get('limit', 1)} parallele Aktualisierung(en); warte auf {wait_target}."
        )
    if reason.get("kind") == "maintenance-chain":
        return (
            f"WARTESCHLANGE: Repository „{reason.get('repository', 'Repository')}“ ist bis zum Ende "
            f"der manuellen Backup-/Archivbereinigungs-/Compact-Kette reserviert; warte auf {wait_target}."
        )
    if reason.get("kind") == "global":
        return (
            f"WARTESCHLANGE: Globale Parallelitätsgrenze {reason.get('limit', 1)} erreicht; "
            f"warte auf {wait_target}."
        )
    return "WARTESCHLANGE: Warte auf freie Ausführungskapazität."


async def _wait_for_repository_turn(run_id: int, repository_id: int | None) -> bool:
    if repository_id is None:
        return True
    last_blocker: int | None = None
    while True:
        with SessionLocal() as db:
            current = db.get(Run, run_id)
            if not current or current.status != "queued":
                return False
        blocker = _repository_run_blocker(run_id, repository_id)
        if blocker is None:
            return True
        if blocker != last_blocker:
            append_run_log(
                run_id,
                f"WARTESCHLANGE: Warte auf Repository-Ausführung #{blocker}.\n",
                load_settings().run_log_max_mib * 1024 * 1024,
            )
            last_blocker = blocker
        await asyncio.sleep(0.25)


async def execute_interactive(repository_id: int | None, command: Command) -> tuple[int, str, str]:
    """Execute an interactive command under repository and manager-cache limits."""
    if repository_id is not None and not command.allow_active_archive_mount:
        active_mount = _active_manager_archive_mount(repository_id)
        if active_mount is not None:
            raise ActiveArchiveMountError(repository_id, active_mount.archive)
    mount_lock = None
    repository_lock = _repository_lock(repository_id)
    manager_lock = _manager_borg_lock(command.manager_cache_repository_id)
    mount_acquired = repository_acquired = manager_acquired = False
    try:
        mount_lock = await _acquire_mount_capacity(repository_id)
        mount_acquired = mount_lock is not None
        if repository_lock:
            await repository_lock.acquire(); repository_acquired = True
        if manager_lock:
            await manager_lock.acquire(); manager_acquired = True
            # External repositories can leave a stale local cache lock after an
            # interrupted/aborted manager-side Borg process. Once the dedicated
            # manager lock is held, no other BBM manager command can own this
            # private cache, so removing only its lock artifacts is safe.
            await asyncio.to_thread(
                _cleanup_external_manager_cache_locks, command.manager_cache_repository_id
            )
        return await execute(command)
    finally:
        if manager_lock and manager_acquired:
            manager_lock.release()
        if repository_lock and repository_acquired:
            repository_lock.release()
        if mount_lock and mount_acquired:
            mount_lock.release()


EXTERNAL_STORAGE_POLL_SECONDS = 15
EXTERNAL_STORAGE_MAX_CONSECUTIVE_FAILURES = 2


def format_external_storage_bytes(value: int | float) -> str:
    """Format remote free-space values for human-readable run logs.

    Keep sub-GB values in MB, sub-TB values in GB and larger values in TB so
    operators never have to interpret raw byte counters in backup logs.
    """
    size = max(0.0, float(value))
    mib = 1024.0 ** 2
    gib = 1024.0 ** 3
    tib = 1024.0 ** 4
    if size < mib:
        if size < 1024:
            return f"{int(size)} Byte"
        return f"{size / 1024.0:.1f} KB"
    if size < gib:
        return f"{size / mib:.1f} MB"
    if size < tib:
        return f"{size / gib:.1f} GB"
    return f"{size / tib:.2f} TB"


def _external_storage_error_text(output: str, error: str, code: int) -> str:
    detail = (error or output or f"SSH/df exit code {code}").strip()
    detail = re.sub(r"\s+", " ", detail)
    if len(detail) > 500:
        detail = detail[:497] + "…"
    return detail or "Unbekannter Fehler bei der externen Dateisystemprüfung"


def _store_external_storage_error(repository_id: int, message: str) -> None:
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if repository and not repository.storage_path:
            repository.external_storage_error = message[:2000]
            # Keep external_storage_checked_at as the timestamp of the last
            # successful measurement. The UI can then distinguish a stale but
            # known value from a fresh failed probe.
            db.commit()


def _store_external_storage_usage(repository_id: int, usage: dict) -> dict:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if not repository:
            raise LookupError("Repository not found")
        if repository.storage_path:
            raise ValueError("External storage usage can only be stored for external repositories")
        repository.external_storage_total_bytes = int(usage["total"])
        repository.external_storage_used_bytes = int(usage["used"])
        repository.external_storage_free_bytes = int(usage["free"])
        repository.external_storage_usage_percent = float(usage["percent"])
        repository.external_storage_path = str(usage.get("mount_point") or usage.get("path") or "")[:500] or None
        repository.external_storage_checked_at = now
        repository.external_storage_error = None
        db.commit()
        enabled, threshold, source = effective_storage_guard(repository, load_settings())
    return {
        **usage,
        "checked_at": now,
        "guard_enabled": enabled,
        "guard_threshold_percent": threshold,
        "guard_source": source,
        "guard_blocked": bool(enabled and float(usage["percent"]) >= threshold),
    }


async def refresh_external_repository_storage(repository_id: int) -> dict:
    """Query and persist the filesystem usage of an external SSH repository."""
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if not repository:
            raise LookupError("Repository not found")
        if repository.storage_path:
            raise ValueError("Repository ist nicht extern")
        if not repository.enabled:
            raise ValueError("Repository ist deaktiviert")
        target = storage_probe_target_from_location(repository.location)
        if target is None:
            message = "Externe Dateisystemprüfung benötigt ein SSH-Repository mit Benutzer und Host"
            _store_external_storage_error(repository_id, message)
            raise ValueError(message)
        try:
            command = external_repository_storage_command(repository)
        except ValueError as exc:
            _store_external_storage_error(repository_id, str(exc))
            raise

    code, output, error = await execute(command, capture_limit_bytes=64 * 1024)
    if code != 0:
        message = _external_storage_error_text(output, error, code)
        technical = "\n".join(part for part in (output, error) if part).strip()
        if detail_requires_debug_log(technical):
            error_id = log_unexpected_exception(
                f"External filesystem probe for repository {repository_id} returned technical output",
                detail=technical,
                logger_name="bbm.background",
            )
            message += f" Technische Details: Debug-Log, Fehler-ID {error_id}."
        _store_external_storage_error(repository_id, message)
        raise ValueError(message)
    try:
        usage = parse_external_repository_storage(output, target.repository_path)
    except ValueError as exc:
        _store_external_storage_error(repository_id, str(exc))
        raise
    return _store_external_storage_usage(repository_id, usage)


async def _monitor_external_repository_storage(
    repository_id: int, run_id: int, abort_event: asyncio.Event, abort_state: dict[str, str],
    log_writer: RunLogWriter, *, guard_enabled: bool, threshold: int,
) -> None:
    """Refresh remote filesystem usage while a backup runs and trip the guard."""
    failures = 0
    while not abort_event.is_set():
        await asyncio.sleep(EXTERNAL_STORAGE_POLL_SECONDS)
        if abort_event.is_set():
            return
        try:
            usage = await refresh_external_repository_storage(repository_id)
        except (LookupError, ValueError) as exc:
            failures += 1
            if guard_enabled and failures >= EXTERNAL_STORAGE_MAX_CONSECUTIVE_FAILURES:
                message = (
                    "Externe Speicherplatz-Sperre: Dateisystembelegung konnte während des Backups "
                    f"{failures}-mal hintereinander nicht geprüft werden: {exc}"
                )
                abort_state["reason"] = message
                log_writer.append("\nSPEICHERPLATZ-SPERRE: " + message + "\n")
                abort_event.set()
                return
            continue
        failures = 0
        if guard_enabled and float(usage["percent"]) >= threshold:
            message = (
                f"Externer Repository-Speicher ist zu {float(usage['percent']):.1f}% belegt; "
                f"die konfigurierte {threshold}%-Speicherplatz-Sperre wurde während des Backups erreicht "
                f"({usage.get('mount_point') or usage.get('path')})."
            )
            abort_state["reason"] = message
            log_writer.append("\nSPEICHERPLATZ-SPERRE: " + message + " Borg wird kontrolliert gestoppt.\n")
            abort_event.set()
            return


async def clear_repository_cache(repository_id: int) -> dict[str, int | bool | str]:
    """Clear the manager-private Borg cache for one repository record.

    The cache is removed directly while the repository execution lock is held.
    Calling ``borg delete --cache-only`` would first need to acquire the very
    cache lock that this maintenance action is intended to recover from.
    """
    semaphore, permits = await _acquire_repository_exclusive(repository_id)
    try:
        with SessionLocal() as db:
            repository = db.get(Repository, repository_id)
            if not repository:
                raise LookupError("Repository not found")
            if db.scalar(select(Run.id).where(
                Run.repository_id == repository_id, Run.status.in_(["queued", "running"])
            ).limit(1)):
                raise ValueError("Repository hat eine wartende oder laufende Ausführung")
            db.expunge(repository)
        return await asyncio.to_thread(clear_repository_manager_cache, repository)
    finally:
        _release_repository_exclusive(semaphore, permits)


async def refresh_repository_statistics(repository_id: int) -> dict[str, int | None]:
    """Refresh Borg totals and managed filesystem usage for one repository."""
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if not repository:
            raise LookupError("Repository not found")
        if not repository.enabled:
            raise ValueError("Repository ist deaktiviert")
        if not repository.initialized:
            raise ValueError("Repository is not initialized")
        if repository.storage_path and not managed_repository_present(repository):
            raise ValueError("Verwaltetes Repository ist derzeit nicht verfügbar; Mount prüfen und Status erneut aktualisieren")
        managed = bool(repository.storage_path)
        command = repository_size_command(repository)

    filesystem_size = None
    external_storage = None
    if managed:
        filesystem_size = await asyncio.to_thread(managed_repository_filesystem_size, repository_id)
    else:
        try:
            external_storage = await refresh_external_repository_storage(repository_id)
        except (LookupError, ValueError):
            # Borg statistics remain useful even when the remote SSH account is
            # intentionally restricted to borg serve and cannot execute df.
            external_storage = None
    code, output, error = await execute_interactive(repository_id, command)
    if code not in {0, 1}:
        summary, _details = compact_repository_diagnostic(output, error, code)
        raise ValueError(_repository_command_error_summary(
            f"Repository statistics refresh for repository {repository_id} returned technical Borg output",
            summary, output, error,
        ))
    statistics = repository_statistics_from_borg_info(output)
    stored = store_repository_statistics(
        repository_id,
        filesystem_size=filesystem_size,
        original_size=statistics.get("original_size"),
        compressed_size=statistics.get("compressed_size"),
        deduplicated_size=statistics.get("deduplicated_size"),
    )
    if external_storage is not None:
        stored["external_storage"] = external_storage
    return stored


async def _execute_run_inner(
    run_id: int, command: Command, *, refresh_size_after: bool = True,
    terminal_db_hook: Callable[[Session, Run, str], None] | None = None,
) -> None:
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if not run:
            return
        repository_id = run.repository_id
        action = run.action
        full_file_list = True
        if action == "backup" and run.job is not None:
            try:
                full_file_list = bool(json.loads(run.job.create_options_json or "{}").get("list_files", True))
            except (TypeError, ValueError):
                full_file_list = True
        run.command_preview = command.preview
        db.commit()

    settings = load_settings()
    log_file_max_bytes = settings.run_log_max_mib * 1024 * 1024
    # Complete high-volume output is file-backed. SQLite stores only small
    # metadata previews and structured warning causes; normal --list item lines
    # never enter the database write path.
    db_log_tail_bytes = 16 * 1024
    stdout_tail_bytes = 4 * 1024
    stderr_tail_bytes = 32 * 1024
    pending_stdout: list[str] = []
    pending_warning_summary_json: str | None = None
    pending_borg_version: str | None = None
    technical_error_id: str | None = None
    version_probe_bytes = bytearray()
    backup_preview_filter = _BackupSqlitePreviewFilter() if action == "backup" else None
    warning_collector = BorgWarningCollector(max_items=100) if action == "backup" else None
    progress_filter = BorgProgressStreamFilter() if action == "backup" else None
    restore_progress_filter = BorgRestoreProgressStreamFilter() if action == "restore" else None
    item_activity_filter = (
        BorgItemActivityStreamFilter(strip_added_modified=not full_file_list)
        if action == "backup" else None
    )
    network_filter = BorgNetworkStreamFilter() if action == "backup" else None
    last_flush = 0.0
    flush_lock = asyncio.Lock()
    log_writer = RunLogWriter(run_id, log_file_max_bytes)

    async def flush_live_log_periodically() -> None:
        # Sparse jobs (full file list disabled) can emit a header and then stay
        # silent until Borg prints final statistics. A time-driven flush keeps
        # that header and later warning lines visible without increasing the
        # high-volume writer's configured flush frequency.
        interval = min(0.25, max(0.05, log_writer.flush_interval / 2))
        while True:
            await asyncio.sleep(interval)
            log_writer.flush_if_due()

    live_log_flush_task = asyncio.create_task(flush_live_log_periodically())

    async def flush_output(force: bool = False) -> None:
        nonlocal last_flush, pending_warning_summary_json, pending_borg_version
        if not pending_stdout and pending_warning_summary_json is None and pending_borg_version is None:
            return
        now = time.monotonic()
        if not force and now - last_flush < 1.5:
            return
        async with flush_lock:
            now = time.monotonic()
            if not force and now - last_flush < 1.5:
                return
            if not pending_stdout and pending_warning_summary_json is None and pending_borg_version is None:
                return
            stdout_text = "".join(pending_stdout)
            with SessionLocal() as db:
                current = db.get(Run, run_id)
                if current:
                    if stdout_text:
                        current.output = ((current.output or "") + stdout_text)[-stdout_tail_bytes:]
                        detected_version = parse_borg_version(current.output)
                        if detected_version:
                            current.borg_version = detected_version
                    if pending_borg_version is not None:
                        current.borg_version = pending_borg_version
                    if pending_warning_summary_json is not None:
                        current.warning_summary_json = pending_warning_summary_json
                    db.commit()
            pending_stdout.clear()
            pending_warning_summary_json = None
            pending_borg_version = None
            last_flush = now

    async def append_output_bytes(stream: str, data: bytes) -> bytes:
        nonlocal pending_warning_summary_json, pending_borg_version
        # Borg's --progress stream is useful for the WebUI but would create
        # thousands of carriage-return frames in the permanent run log. Extract
        # it only from stderr and keep the remaining byte stream unchanged.
        persisted = data
        if progress_filter is not None and stream == "stderr":
            persisted, progress = progress_filter.feed(data)
            if progress is not None:
                set_run_progress(run_id, progress)
            if network_filter is not None:
                persisted, network_activity = network_filter.feed(persisted)
                if network_activity is not None:
                    set_run_network_activity(run_id, network_activity)
            if item_activity_filter is not None:
                persisted, item_activity = item_activity_filter.feed(persisted)
                if item_activity is not None:
                    set_run_item_activity(run_id, item_activity)
        elif restore_progress_filter is not None and stream == "stderr":
            persisted, restore_progress = restore_progress_filter.feed(data)
            if restore_progress is not None:
                set_run_restore_progress(run_id, restore_progress)

        # The normal production path stays binary: millions of file names are
        # written without UTF-8 decoding, line splitting or SQLite mirroring.
        log_writer.append_bytes(persisted)
        warning_changed = False
        if warning_collector and persisted:
            warning_changed = warning_collector.feed_bytes(persisted, stream=stream)
            if warning_changed:
                pending_warning_summary_json = json.dumps(
                    warning_collector.summary(), ensure_ascii=False, separators=(",", ":"),
                )
        if action == "backup":
            # The file-backed log is the authoritative live-output source.
            # SQLite receives only non-item metadata; all A/M/U/C/E/... path
            # lines are filtered with chunk-boundary protection.
            if stream == "stdout" and backup_preview_filter is not None:
                preview_text = backup_preview_filter.feed(persisted)
                if preview_text:
                    pending_stdout.append(preview_text)
            if pending_borg_version is None and len(version_probe_bytes) < 8192:
                remaining = 8192 - len(version_probe_bytes)
                version_probe_bytes.extend(persisted[:remaining])
                detected = parse_borg_version(version_probe_bytes.decode("utf-8", errors="replace"))
                if detected:
                    pending_borg_version = detected
        elif stream == "stdout":
            pending_stdout.append(persisted.decode("utf-8", errors="replace"))
        if warning_changed or pending_stdout or pending_borg_version is not None:
            await flush_output()
        # ``execute`` also uses this filtered stream for its bounded capture, so
        # progress frames cannot evict a real warning from the final stderr tail.
        return persisted

    async def append_output(stream: str, text: str) -> None:
        # Compatibility callback for tests and third-party executors that still
        # provide decoded strings. The built-in runner uses append_output_bytes.
        await append_output_bytes(stream, text.encode("utf-8", errors="replace"))

    repository_lock = None
    manager_lock = _manager_borg_lock(command.manager_cache_repository_id)
    repository_acquired = manager_acquired = False
    external_storage_monitor_task: asyncio.Task[None] | None = None
    external_storage_abort_event: asyncio.Event | None = None
    external_storage_abort_state: dict[str, str] = {}
    external_storage_probe_active = False
    last_queue_message = ""
    try:
        while True:
            with SessionLocal() as db:
                current = db.get(Run, run_id)
                if not current or current.status != "queued":
                    return
            # The database-backed planner is the single admission controller
            # for persisted runs.  Older releases reserved a process-local mount
            # slot before asking the planner, effectively applying mount limits
            # twice and allowing a stale/incorrect limiter to keep a second job
            # queued even when the configured mount limit was 2.
            claimed, reason = _claim_execution_turn(run_id)
            if claimed:
                break
            message = _queue_message(reason)
            if message != last_queue_message:
                log_writer.append(message + "\n")
                last_queue_message = message
            await asyncio.sleep(0.25)

        # Repository locking remains as a physical safety net against direct
        # interactive operations that do not use the persisted queue.  It is
        # acquired only after the queue slot has been claimed, so an invisible
        # process-local lock can no longer leave the run displayed as queued.
        if action != "source-stats":
            repository_lock = _repository_lock(repository_id)
            if repository_lock:
                await repository_lock.acquire()
                repository_acquired = True
        if manager_lock:
            await manager_lock.acquire()
            manager_acquired = True
            cache_cleanup = await asyncio.to_thread(
                _cleanup_external_manager_cache_locks, command.manager_cache_repository_id
            )
            removed_cache_locks = int(cache_cleanup.get("lock_directories_removed", 0)) + int(
                cache_cleanup.get("lock_files_removed", 0)
            )
            if removed_cache_locks:
                log_writer.append(
                    "HINWEIS: Verwaiste lokale BBM-Borg-Cache-Sperre des externen Repositorys "
                    "vor dem Manager-Aufruf automatisch bereinigt.\n"
                )

        # External repositories have no manager-local filesystem that shutil can
        # inspect. Probe their remote filesystem immediately before borg create
        # and continue refreshing it in a separate SSH connection while the
        # backup runs. This keeps the displayed value current and lets an
        # enabled guard stop a job that crosses the threshold mid-run.
        if action == "backup" and repository_id:
            with SessionLocal() as db:
                repository = db.get(Repository, repository_id)
                external_repository = bool(
                    repository and not repository.storage_path
                    and storage_probe_target_from_location(repository.location) is not None
                )
                if external_repository:
                    guard_enabled, guard_threshold, _guard_source = effective_storage_guard(repository, settings)
                else:
                    guard_enabled, guard_threshold = False, int(getattr(settings, "storage_guard_threshold_percent", 95))
            if external_repository:
                initial_usage = None
                try:
                    initial_usage = await refresh_external_repository_storage(repository_id)
                except (LookupError, ValueError) as exc:
                    log_writer.append(
                        "HINWEIS: Externe Repository-Dateisystembelegung konnte vor dem Backup "
                        f"nicht aktualisiert werden: {exc}\n"
                    )
                    if guard_enabled:
                        raise ValueError(
                            "Externe Speicherplatz-Sperre ist aktiviert, aber die aktuelle "
                            f"Dateisystembelegung konnte nicht geprüft werden: {exc}"
                        ) from exc
                if initial_usage is not None:
                    log_writer.append(
                        "EXTERNER REPOSITORY-SPEICHER: "
                        f"{float(initial_usage['percent']):.1f}% belegt · "
                        f"{format_external_storage_bytes(initial_usage['free'])} frei · "
                        f"Prüfintervall {EXTERNAL_STORAGE_POLL_SECONDS} s"
                        + (f" · Sperre ab {guard_threshold}%" if guard_enabled else " · Sperre deaktiviert")
                        + "\n"
                    )
                    if guard_enabled and float(initial_usage["percent"]) >= guard_threshold:
                        raise ValueError(
                            f"Externer Repository-Speicher ist zu {float(initial_usage['percent']):.1f}% "
                            f"belegt; Backup durch die {guard_threshold}%-Speicherplatz-Sperre blockiert "
                            f"({initial_usage.get('mount_point') or initial_usage.get('path')})"
                        )
                if initial_usage is not None:
                    external_storage_probe_active = True
                    external_storage_abort_event = asyncio.Event()
                    external_storage_monitor_task = asyncio.create_task(
                        _monitor_external_repository_storage(
                            repository_id, run_id, external_storage_abort_event, external_storage_abort_state,
                            log_writer, guard_enabled=guard_enabled, threshold=guard_threshold,
                        )
                    )

        code, output, error = await execute(
            command,
            on_output=append_output,
            on_output_bytes=append_output_bytes,
            capture_limit_bytes=32 * 1024,
            abort_event=external_storage_abort_event,
            abort_reason=lambda: external_storage_abort_state.get(
                "reason", "Backup durch externe Speicherplatz-Sperre beendet"
            ),
        )
        if external_storage_monitor_task is not None:
            external_storage_monitor_task.cancel()
            await asyncio.gather(external_storage_monitor_task, return_exceptions=True)
            external_storage_monitor_task = None
        if external_storage_probe_active and repository_id:
            try:
                final_usage = await refresh_external_repository_storage(repository_id)
                log_writer.append(
                    "EXTERNER REPOSITORY-SPEICHER NACH JOB: "
                    f"{float(final_usage['percent']):.1f}% belegt · "
                    f"{format_external_storage_bytes(final_usage['free'])} frei\n"
                )
            except (LookupError, ValueError) as exc:
                log_writer.append(
                    "HINWEIS: Externe Repository-Dateisystembelegung konnte nach dem Job "
                    f"nicht aktualisiert werden: {exc}\n"
                )
        if progress_filter is not None:
            trailing, progress = progress_filter.finalize()
            if progress is not None:
                set_run_progress(run_id, progress)
            if trailing and network_filter is not None:
                trailing, network_activity = network_filter.feed(trailing)
                if network_activity is not None:
                    set_run_network_activity(run_id, network_activity)
            if network_filter is not None:
                network_trailing, network_activity = network_filter.finalize()
                trailing += network_trailing
                if network_activity is not None:
                    set_run_network_activity(run_id, network_activity)
            if trailing and item_activity_filter is not None:
                trailing, item_activity = item_activity_filter.feed(trailing)
                if item_activity is not None:
                    set_run_item_activity(run_id, item_activity)
            if item_activity_filter is not None:
                item_trailing, item_activity = item_activity_filter.finalize()
                trailing += item_trailing
                if item_activity is not None:
                    set_run_item_activity(run_id, item_activity)
            if trailing:
                log_writer.append_bytes(trailing)
                error += trailing.decode("utf-8", errors="replace")
                if warning_collector:
                    warning_collector.feed_bytes(trailing, stream="stderr")
        if restore_progress_filter is not None:
            restore_trailing, restore_progress = restore_progress_filter.finalize()
            if restore_progress is not None:
                set_run_restore_progress(run_id, restore_progress)
            if restore_trailing:
                log_writer.append_bytes(restore_trailing)
                error += restore_trailing.decode("utf-8", errors="replace")
        if warning_collector and warning_collector.finalize():
            pending_warning_summary_json = json.dumps(
                warning_collector.summary(), ensure_ascii=False, separators=(",", ":"),
            )
        if backup_preview_filter is not None:
            final_preview = backup_preview_filter.finalize()
            if final_preview:
                pending_stdout.append(final_preview)
        await flush_output(force=True)
        status = "success" if code == 0 else "warning" if code == 1 else "failed"
    except CommandCancelled as exc:
        code, output, status = 130, "", "cancelled"
        error = (
            "Execution cancelled by user after forced process termination"
            if exc.forced
            else (
                "Execution cancelled by user; remote Borg shutdown confirmed"
                if exc.remote_cleanup_confirmed
                else "Execution cancelled by user; Borg process group stopped cleanly"
            )
        )
        if exc.forced:
            cancellation_detail = "zwangsweise beendet. Repository-Sperre vor einem neuen Lauf prüfen."
        elif exc.remote_cleanup_confirmed:
            cancellation_detail = (
                "über den überwachten Remote-Abbruchkanal mit SIGINT beendet; "
                "das Ende des Borg-Prozesses auf dem Gerät wurde bestätigt."
            )
        else:
            cancellation_detail = "kontrolliert mit SIGINT beendet; Borg konnte seine Sperren freigeben."
        log_writer.append(
            "\nABBRUCH: Borg und alle zugehörigen Wrapper-Prozesse wurden "
            + cancellation_detail
            + "\n",
        )
    except asyncio.CancelledError:
        # Compatibility path for monkeypatched executors and cancellations that
        # occur before the subprocess has been created.
        code, output, error, status = 130, "", "Execution cancelled by user", "cancelled"
    except Exception as exc:
        error_id = log_unexpected_exception(
            f"Execution #{run_id} failed unexpectedly",
            exc=exc,
            logger_name="bbm.run",
        )
        code, output, error, status = 255, "", public_error_message(error_id), "failed"
    finally:
        try:
            await flush_output(force=True)
        except Exception as exc:
            # The file-backed log remains authoritative even if a final SQLite
            # preview update fails during shutdown or cancellation.
            log_unexpected_exception(
                f"Final SQLite preview update for execution #{run_id} failed",
                exc=exc,
                logger_name="bbm.run",
            )
        if external_storage_monitor_task is not None:
            external_storage_monitor_task.cancel()
            await asyncio.gather(external_storage_monitor_task, return_exceptions=True)
        live_log_flush_task.cancel()
        await asyncio.gather(live_log_flush_task, return_exceptions=True)
        log_writer.close()
        if manager_lock and manager_acquired:
            manager_lock.release()
        if repository_lock and repository_acquired:
            repository_lock.release()

    technical_stream = "\n".join(part for part in (output, error) if part).strip()
    if detail_requires_debug_log(technical_stream):
        technical_error_id = log_unexpected_exception(
            f"Borg execution #{run_id} returned traceback/technical output",
            detail=technical_stream,
            logger_name="bbm.run",
        )

    # Invalidate before publishing the terminal run status. The browser follows
    # that status and may request the archive list immediately afterwards.
    if repository_id and (
        (
            status in {"success", "warning"}
            and action in {"repository-init", "backup", "prune", "delete-archive", "rename-archive"}
        )
        or action == "delete-archive"
    ):
        # A multi-archive deletion can be partially effective before a later
        # archive fails or the run is cancelled. Never retain a potentially
        # stale archive list after a destructive command was attempted.
        invalidate_archive_cache(repository_id)

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if run:
            run.status = status
            if action == "backup" and status == "warning":
                summary = warning_collector.summary() if warning_collector else None
                if not summary:
                    summary = unresolved_warning_summary()
                run.warning_summary_json = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
            elif action == "backup" and status == "success":
                # A successful Borg return code is authoritative. Discard any
                # incidental helper text that happened to look like a warning.
                run.warning_summary_json = ""
            # Keep the complete stream only in /data/run-logs. SQLite stores a
            # small metadata/diagnostic preview without ordinary Borg item paths.
            # Concrete C/E warning paths remain in warning_summary_json.
            clean_source = output if action == "backup" else (run.output or output)
            clean_output = strip_borg_item_lines(clean_source)[-stdout_tail_bytes:]
            filtered_error = strip_borg_item_lines(extract_error_output(error))[-stderr_tail_bytes:]
            if technical_error_id:
                if detail_requires_debug_log(filtered_error):
                    filtered_error = public_error_message(technical_error_id)
                elif filtered_error:
                    filtered_error = (
                        filtered_error.rstrip()
                        + f"\nTechnische Details: Debug-Log, Fehler-ID {technical_error_id}."
                    )[-stderr_tail_bytes:]
                else:
                    filtered_error = public_error_message(technical_error_id)
            run.output = clean_output
            run.error = filtered_error
            preview_parts = [part for part in (clean_output, filtered_error) if part]
            run.log_output = "\n".join(preview_parts)[-db_log_tail_bytes:]
            if not run.error and code:
                run.error = f"Exit code: {code}"
            version = run.borg_version if version_tuple(run.borg_version) else parse_borg_version(run.log_output or f"{run.output}\n{run.error}")
            if version:
                run.borg_version = version
            if version and run.job_id:
                job = db.get(Job, run.job_id)
                host = db.get(Host, job.host_id) if job else None
                if host:
                    compatibility = classify_borg_version(version)
                    host.borg_version = version
                    host.borg_version_status = compatibility.level
                    host.borg_checked_at = datetime.now(timezone.utc)
            if action == "backup":
                network_snapshot = get_run_network_activity(run_id, max_age_seconds=None)
                if network_snapshot is not None:
                    run.backup_network_download_bytes = int(network_snapshot.get("download_bytes") or 0)
                    run.backup_network_upload_bytes = int(network_snapshot.get("upload_bytes") or 0)
            elif action == "restore":
                restore_snapshot = get_run_restore_progress(run_id)
                if restore_snapshot is not None:
                    run.restore_total_size_bytes = int(restore_snapshot.get("total_bytes") or 0)
                    run.restore_processed_size_bytes = int(restore_snapshot.get("processed_bytes") or 0)
                    run.restore_total_file_count = int(restore_snapshot.get("total_files") or 0)
                    run.restore_processed_file_count = int(restore_snapshot.get("processed_files") or 0)

            if action in {"backup", "source-stats"} and status in {"success", "warning"}:
                statistics = (
                    parse_backup_statistics(output + "\n" + error)
                    if action == "backup"
                    else parse_source_scan_statistics(output + "\n" + error)
                )
                if action == "backup":
                    run.archive_name_snapshot = statistics.get("archive_name")
                    run.backup_original_size_bytes = statistics.get("original_size_bytes")
                    run.backup_compressed_size_bytes = statistics.get("compressed_size_bytes")
                    run.backup_deduplicated_size_bytes = statistics.get("deduplicated_size_bytes")
                    run.backup_file_count = statistics.get("file_count")
                job = db.get(Job, run.job_id) if run.job_id else None
                if job and statistics.get("original_size_bytes") is not None:
                    job.source_size_bytes = statistics.get("original_size_bytes")
                    job.source_file_count = statistics.get("file_count")
                    job.source_stats_checked_at = datetime.now(timezone.utc)
                    job.source_stats_origin = "backup" if action == "backup" else "scan"
                    if action == "source-stats":
                        job.source_stats_detail_json = json.dumps({
                            "version": 2,
                            "quality": statistics.get("quality") or "partial",
                            "scan_method": statistics.get("scan_method"),
                            "warning_count": statistics.get("warning_count") or 0,
                            "path_excluded_count": statistics.get("path_excluded_count") or 0,
                            "unsupported_patterns": statistics.get("unsupported_patterns") or [],
                            "nodump_supported": statistics.get("nodump_supported"),
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                        }, ensure_ascii=False, separators=(",", ":"))
                    elif action == "backup":
                        # A successful Borg run supplies the new total baseline.
                        # Scan-specific limitation metadata from an older manual
                        # refresh must not remain attached to that fresh backup.
                        job.source_stats_detail_json = "{}"
            if terminal_db_hook is not None:
                terminal_db_hook(db, run, status)
            run.finished_at = datetime.now(timezone.utc)
            db.commit()

    if repository_id and status in {"success", "warning"}:
        if (
            refresh_size_after
            and action in {"repository-init", "backup", "prune", "compact", "delete-archive"}
            and load_settings().repository_size_after_run
        ):
            try:
                await refresh_repository_statistics(repository_id)
            except (OSError, LookupError, ValueError):
                pass


async def execute_run(
    run_id: int, command: Command, *, refresh_size_after: bool = True,
    terminal_db_hook: Callable[[Session, Run, str], None] | None = None,
) -> None:
    """Execute one persisted run and track its live queue ownership.

    The process-wide live set allows the database-backed queue planner to
    distinguish real work from orphaned queued/running rows. Cleanup happens
    for every exit path, including cancellation before command execution.
    """
    clear_run_progress(run_id)
    clear_run_restore_progress(run_id)
    clear_run_live_activity(run_id)
    with _active_run_lock:
        _executing_run_ids.add(run_id)
    try:
        await _execute_run_inner(
            run_id, command, refresh_size_after=refresh_size_after, terminal_db_hook=terminal_db_hook,
        )
    finally:
        clear_run_progress(run_id)
        clear_run_restore_progress(run_id)
        clear_run_live_activity(run_id)
        with _active_run_lock:
            _executing_run_ids.discard(run_id)
            if _active_run_tasks.get(run_id) is asyncio.current_task():
                _active_run_tasks.pop(run_id, None)
    # Release all repository/global queue slots before contacting external
    # notification services. Delivery failures never alter the Borg result.
    await asyncio.to_thread(notify_run_completion, run_id)


async def reset_managed_repository_state(repository_id: int) -> dict[str, int | str]:
    """Reset stale manager metadata only when the managed target is truly empty.

    The function deliberately never deletes repository contents. The repository
    lock serializes the reset with manager-side Borg operations and all checks
    are repeated while that lock is held.
    """
    semaphore, permits = await _acquire_repository_exclusive(repository_id)
    try:
        with SessionLocal() as db:
            repository = db.get(Repository, repository_id)
            if not repository:
                raise LookupError("Repository not found")
            if not repository.storage_path:
                raise ValueError("Nur verwaltete Repositorys können zurückgesetzt werden")
            if db.scalar(
                select(Run.id).where(
                    Run.repository_id == repository_id,
                    Run.status.in_(["queued", "running"]),
                ).limit(1)
            ):
                raise ValueError("Repository hat eine wartende oder laufende Ausführung")
            if db.scalar(
                select(ManagerArchiveMount.id).where(
                    ManagerArchiveMount.repository_id == repository_id,
                    ManagerArchiveMount.status.in_(["mounting", "mounted"]),
                ).limit(1)
            ):
                raise ValueError("Repository besitzt noch einen aktiven Archiv-Mount")

            path = require_empty_managed_repository(repository)
            keyfile_mode = (repository.encryption_mode or "").startswith("keyfile")
            now = datetime.now(timezone.utc)
            repository.initialized = False
            repository.validation_error = None
            repository.validation_details = None
            repository.validated_at = None
            repository.size_bytes = None
            repository.original_size_bytes = None
            repository.compressed_size_bytes = None
            repository.deduplicated_size_bytes = None
            repository.size_checked_at = None
            run = Run(
                job_id=None,
                job_name_snapshot=f"Repository: {repository.name}"[:100],
                repository_id=repository_id,
                action="repository-reset",
                status="success",
                command_preview="Managerstatus eines leeren Repository-Zielordners zurücksetzen",
                output=(
                    "Nur Initialisierungs-, Prüf- und Größenmetadaten wurden zurückgesetzt. "
                    "Es wurden keine Repository-Dateien gelöscht. "
                    f"Geprüfter leerer Zielordner: {path}"
                ),
                trigger_type="manual",
                started_at=now,
                finished_at=now,
            )
            db.add(run)
            db.commit()
            run_id = run.id

        if keyfile_mode:
            set_repository_secret(repository_id, "keyfile", None)
            Path(repository_keyfile_path(repository)).unlink(missing_ok=True)
        invalidate_archive_cache(repository_id)
        return {"status": "reset", "repository_id": repository_id, "run_id": run_id}
    finally:
        _release_repository_exclusive(semaphore, permits)


async def execute_repository_init(run_id: int, repository_id: int, command: Command) -> None:
    try:
        await execute_run(run_id, command)
        try:
            with SessionLocal() as db:
                run = db.get(Run, run_id)
                repository = db.get(Repository, repository_id)
                if run and repository and run.status == "success":
                    key_path = None
                    if repository.encryption_mode.startswith("keyfile"):
                        key_path = Path(repository_keyfile_path(repository))
                        if not key_path.is_file():
                            raise ValueError("Borg did not create the expected repository keyfile")
                        set_repository_secret(repository, "keyfile", key_path.read_text(encoding="utf-8"))
                    repository.initialized = True
                    db.commit()
                    if key_path:
                        key_path.unlink(missing_ok=True)
        except Exception as exc:
            error_id = log_unexpected_exception(
                f"Repository initialization finalization for execution #{run_id} failed",
                exc=exc,
                logger_name="bbm.run",
            )
            with SessionLocal() as db:
                run = db.get(Run, run_id)
                if run:
                    run.status = "failed"
                    run.error = public_error_message(error_id)
                    run.finished_at = datetime.now(timezone.utc)
                    db.commit()
    finally:
        with _repository_init_lock:
            _initializing_repositories.discard(repository_id)



def queue_repository_init(repository_id: int) -> int:
    with _repository_init_lock:
        if repository_id in _initializing_repositories:
            raise ValueError("Repository initialization is already running")
        _initializing_repositories.add(repository_id)
    with SessionLocal() as db:
        try:
            repository = db.get(Repository, repository_id)
            if not repository:
                raise LookupError("Repository not found")
            if not repository.enabled:
                raise ValueError("Repository ist deaktiviert")
            if repository.initialized:
                if repository.storage_path and not managed_repository_present(repository):
                    raise ValueError("Repository-Managerstatus ist veraltet; das leere Repository vor der Initialisierung zurücksetzen")
                raise ValueError("Repository ist bereits initialisiert")
            require_initializable_managed_repository(repository)
            command = repository_init_command(repository)
            run = Run(
                job_id=None,
                job_name_snapshot=None,
                repository_id=repository_id,
                action="repository-init",
                status="queued",
                command_preview=command.preview,
            )
            db.add(run)
            db.commit()
            run_id = run.id
        except Exception:
            with _repository_init_lock:
                _initializing_repositories.discard(repository_id)
            raise
    task = asyncio.create_task(execute_repository_init(run_id, repository_id, command))
    with _active_run_lock:
        _active_run_tasks[run_id] = task
    return run_id


async def bootstrap_host_repository(
    host_id: int,
    repository_ids: list[int],
) -> dict[int, str]:
    """Provision repository-scoped SSH keys for an explicit device assignment."""
    sync_repository_access_assignments()
    with SessionLocal() as db:
        host = db.get(Host, host_id)
        if not host:
            raise LookupError("Host not found")
        assigned_ids = list(
            db.scalars(
                select(HostRepositoryAccess.repository_id)
                .join(Repository, Repository.id == HostRepositoryAccess.repository_id)
                .where(HostRepositoryAccess.host_id == host_id, Repository.enabled.is_(True))
                .order_by(HostRepositoryAccess.repository_id)
            )
        )
        selected_ids = sorted(set(repository_ids))
        if not selected_ids:
            raise ValueError("No managed repository access is assigned to this device")
        missing = sorted(set(selected_ids) - set(assigned_ids))
        if missing:
            raise ValueError(f"Managed repository access is not assigned to this device: {missing}")
        command = host_repository_bootstrap_command(host, _repository_known_hosts_line(), selected_ids)

    code, output, error = await execute(command)
    if code != 0:
        raise ValueError(error.strip() or output.strip() or f"SSH bootstrap failed with exit code {code}")
    keys: dict[int, str] = {}
    for line in output.splitlines():
        match = re.match(r"^BBM_REPOSITORY_KEY\s+(\d+)\s+(ssh-ed25519\s+\S+(?:\s+.*)?)$", line.strip())
        if match:
            keys[int(match.group(1))] = match.group(2)
    if set(keys) != set(selected_ids):
        missing = sorted(set(selected_ids) - set(keys))
        raise ValueError(f"Device did not return keys for managed repositories: {missing}")
    with SessionLocal() as db:
        for repository_id, public_key in keys.items():
            access = db.scalar(
                select(HostRepositoryAccess).where(
                    HostRepositoryAccess.host_id == host_id,
                    HostRepositoryAccess.repository_id == repository_id,
                )
            )
            if access:
                access.public_key = _normalize_public_key(
                    public_key,
                    f"bbm-access-h{host_id}-r{repository_id}",
                )
        db.commit()
    sync_repository_access_assignments()
    return keys



async def execute_repository_validation(run_id: int, repository_id: int, command: Command) -> None:
    """Execute a queued connection test and publish readiness atomically.

    The repository readiness update is committed in the same transaction that
    publishes the terminal run status. Otherwise the browser can observe a
    successful test for a few milliseconds while the repository still appears
    unvalidated and reject an immediately following archive request.
    """

    def persist_validation_state(db: Session, run: Run, status: str) -> None:
        repository = db.get(Repository, repository_id)
        if not repository or status == "cancelled":
            return
        if status in {"success", "warning"}:
            repository.initialized = True
            repository.validation_error = None
            repository.validation_details = None
            repository.validated_at = datetime.now(timezone.utc)
            return
        raw_output = run.output or ""
        raw_error = "\n".join(
            part for part in (run.error or "", run.log_output or "") if part
        )
        summary, details = compact_repository_diagnostic(raw_output, raw_error, 2)
        if not repository.storage_path:
            repository.initialized = False
        repository.validation_error = summary
        repository.validation_details = details

    await execute_run(
        run_id, command, refresh_size_after=False, terminal_db_hook=persist_validation_state,
    )
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        run = db.get(Run, run_id)
        should_probe_storage = bool(
            repository and not repository.storage_path
            and storage_probe_target_from_location(repository.location) is not None
            and run and run.status in {"success", "warning"}
        )
    if should_probe_storage:
        try:
            await refresh_external_repository_storage(repository_id)
        except (LookupError, ValueError):
            pass


def queue_host_ssh_action(action_id: int) -> int:
    """Queue one saved SSH action and persist its output as a normal run."""
    action = get_host_ssh_action(action_id)
    if not action:
        raise LookupError("SSH action not found")
    with SessionLocal() as db:
        host = db.get(Host, action.host_id)
        if not action.enabled:
            raise ValueError("SSH-Aktion ist deaktiviert")
        if not host or not host.enabled:
            raise ValueError("Gerät ist deaktiviert")
        if not host.host_key:
            raise ValueError("SSH-Fingerprint des Geräts ist nicht bestätigt")
        command = host_ssh_action_command(host, action.command, action.timeout_seconds)
        command.preview = f"Gespeicherte SSH-Aktion: {action.name} · Gerät: {host.name}"
        run = Run(
            job_id=None,
            job_name_snapshot=f"{host.name} · {action.name}"[:100],
            repository_id=None,
            action="ssh-command",
            status="queued",
            command_preview=command.preview,
            trigger_type="manual",
        )
        db.add(run)
        db.commit()
        run_id = int(run.id)

    task = asyncio.create_task(execute_run(run_id, command, refresh_size_after=False))
    with _active_run_lock:
        _active_run_tasks[run_id] = task
    return run_id



def _repository_command_error_summary(
    context: str, summary: str, output: str, error: str,
) -> str:
    technical = "\n".join(part for part in (output, error) if part).strip()
    if not detail_requires_debug_log(technical):
        return summary
    error_id = log_unexpected_exception(
        context, detail=technical, logger_name="bbm.run",
    )
    return f"{summary} Technische Details: Debug-Log, Fehler-ID {error_id}."


async def execute_repository_archive_refresh(
    run_id: int,
    repository_id: int,
    consider_checkpoints: bool = False,
) -> None:
    """Refresh the persistent archive cache outside the HTTP request lifecycle.

    Large repositories can make ``borg info --glob-archives '*'`` run for many
    minutes. Keeping that work in a persisted run avoids reverse-proxy 504s and
    still uses the existing repository / manager-cache locks. The Borg JSON is
    parsed in memory and written directly to the compact archive cache; it is
    deliberately not copied into SQLite or the run log.
    """
    max_log_bytes = load_settings().run_log_max_mib * 1024 * 1024
    status = "failed"
    summary = ""
    error_text = ""
    with _active_run_lock:
        _executing_run_ids.add(run_id)
    try:
        if not await _wait_for_repository_turn(run_id, repository_id):
            return
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            repository = db.get(Repository, repository_id)
            if not run or run.status != "queued":
                return
            if not repository:
                raise LookupError("Repository not found")
            if not repository.enabled:
                raise ValueError("Repository ist deaktiviert")
            if not repository.initialized:
                raise ValueError("Repository is not initialized")
            if repository.storage_path and not managed_repository_present(repository):
                raise ValueError("Verwaltetes Repository ist derzeit nicht verfügbar; Mount prüfen und Status erneut aktualisieren")
            info_command = repository_archives_info_command(repository)
            list_command = repository_list_command(repository, consider_checkpoints=consider_checkpoints)
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            db.commit()

        append_run_log(
            run_id,
            "ARCHIVLISTE: Repository wird außerhalb der HTTP-Anfrage eingelesen.\n",
            max_log_bytes,
        )
        info_code, info_output, info_error = await execute_interactive(repository_id, info_command)
        if info_code not in {0, 1}:
            diagnostic, _details = compact_repository_diagnostic(info_output, info_error, info_code)
            raise ValueError(_repository_command_error_summary(
                f"Archive scan execution #{run_id} received technical Borg output",
                diagnostic, info_output, info_error,
            ))
        normalized = parse_borg_info(info_output + "\n" + info_error)
        repository_statistics = normalized.get("repository", {})
        archives = normalized.get("archives", [])
        final_code = info_code
        append_run_log(
            run_id,
            f"ARCHIVLISTE: Borg-Information gelesen · {len(archives)} Archiv(e) mit Detailstatistik.\n",
            max_log_bytes,
        )

        # ``borg info`` normally already returns every regular archive with
        # statistics. A list pass remains necessary for checkpoint inclusion and
        # for Borg variants that return no archive array in the info document.
        if consider_checkpoints or not archives:
            append_run_log(
                run_id,
                "ARCHIVLISTE: Zusätzliche Repository-Liste wird eingelesen.\n",
                max_log_bytes,
            )
            list_code, list_output, list_error = await execute_interactive(repository_id, list_command)
            if list_code not in {0, 1}:
                diagnostic, _details = compact_repository_diagnostic(list_output, list_error, list_code)
                raise ValueError(_repository_command_error_summary(
                    f"Archive list execution #{run_id} received technical Borg output",
                    diagnostic, list_output, list_error,
                ))
            listed = parse_archive_listing(list_output + "\n" + list_error)
            archives = merge_archive_statistics(listed, archives)
            final_code = max(final_code, list_code)

        archives = sort_archives_newest_first(archives)
        dataset = {"repository_statistics": repository_statistics, "archives": archives}
        cached = store_archive_cache(repository_id, consider_checkpoints, dataset)
        # The normal repository-wide ``borg info`` output already includes
        # checkpoint archives on supported Borg versions.  Keep the explicit
        # checkpoint cache in sync when such entries are detected so selecting
        # a checkpoint for restore does not require a redundant second scan.
        if not consider_checkpoints and any(bool(item.get("checkpoint")) for item in archives):
            store_archive_cache(repository_id, True, dataset)
        if repository_statistics.get("deduplicated_size") is not None:
            store_repository_statistics(
                repository_id,
                original_size=repository_statistics.get("original_size"),
                compressed_size=repository_statistics.get("compressed_size"),
                deduplicated_size=repository_statistics.get("deduplicated_size"),
            )
        status = "warning" if final_code == 1 else "success"
        generated_at = cached.get("generated_at") or ""
        summary = (
            f"Archivliste aktualisiert: {len(archives)} Archiv(e)"
            + (" einschließlich Checkpoints" if consider_checkpoints else "")
            + (f" · Cache {generated_at}" if generated_at else "")
        )
        append_run_log(run_id, f"ARCHIVLISTE: {summary}.\n", max_log_bytes)
    except CommandCancelled as exc:
        status = "cancelled"
        error_text = (
            "Archivscan wurde kontrolliert abgebrochen; Borg-Prozess wurde beendet."
            if not exc.forced
            else "Archivscan wurde zwangsweise abgebrochen; Repository-Sperre vor einem neuen Lauf prüfen."
        )
        append_run_log(run_id, f"ABBRUCH: {error_text}\n", max_log_bytes)
    except asyncio.CancelledError:
        status = "cancelled"
        error_text = "Archivscan wurde vor dem Start abgebrochen."
        append_run_log(run_id, f"ABBRUCH: {error_text}\n", max_log_bytes)
    except (LookupError, ValueError) as exc:
        status = "failed"
        error_text = str(exc)
        append_run_log(run_id, f"FEHLER: {error_text}\n", max_log_bytes)
    except Exception as exc:
        status = "failed"
        error_id = log_unexpected_exception(
            f"Archive scan execution #{run_id} failed unexpectedly",
            exc=exc,
            logger_name="bbm.run",
        )
        error_text = public_error_message(error_id)
        append_run_log(run_id, f"FEHLER: {error_text}\n", max_log_bytes)
    finally:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            if run and run.status in {"queued", "running"}:
                run.status = status
                run.output = summary[-64 * 1024:]
                run.error = error_text[-32 * 1024:]
                run.log_output = "\n".join(part for part in (run.output, run.error) if part)[-64 * 1024:]
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
        with _active_run_lock:
            _executing_run_ids.discard(run_id)
            if _active_run_tasks.get(run_id) is asyncio.current_task():
                _active_run_tasks.pop(run_id, None)


def queue_repository_archive_refresh(
    repository_id: int,
    consider_checkpoints: bool = False,
) -> int:
    """Queue one long-running repository archive-cache refresh."""
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if not repository:
            raise LookupError("Repository not found")
        if not repository.enabled:
            raise ValueError("Repository ist deaktiviert")
        if not repository.initialized:
            raise ValueError("Repository is not initialized")
        if repository.storage_path and not managed_repository_present(repository):
            raise ValueError("Verwaltetes Repository ist derzeit nicht verfügbar; Mount prüfen und Status erneut aktualisieren")
        if db.scalar(
            select(Run.id).where(
                Run.repository_id == repository_id,
                Run.status.in_(["queued", "running"]),
            ).limit(1)
        ):
            raise ValueError("Repository hat eine wartende oder laufende Ausführung")
        info_command = repository_archives_info_command(repository)
        run = Run(
            job_id=None,
            job_name_snapshot=f"Archivliste: {repository.name}"[:100],
            repository_id=repository_id,
            action="archive-refresh",
            status="queued",
            command_preview=(
                info_command.preview
                + (" · anschließend borg list --consider-checkpoints" if consider_checkpoints else "")
            ),
            trigger_type="manual",
        )
        db.add(run)
        db.commit()
        run_id = int(run.id)

    task = asyncio.create_task(
        execute_repository_archive_refresh(run_id, repository_id, consider_checkpoints)
    )
    with _active_run_lock:
        _active_run_tasks[run_id] = task
    return run_id

def queue_repository_action(
    repository_id: int,
    action: str,
    data: dict | None = None,
    *,
    subject: str | None = None,
    refresh_size_after: bool = True,
) -> int:
    """Queue a repository-wide administrative action without requiring a job."""
    payload = data or {}
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if not repository:
            raise LookupError("Repository not found")
        if not repository.enabled:
            raise ValueError("Repository ist deaktiviert")
        if action != "test" and not repository.initialized:
            raise ValueError("Repository is not initialized")
        if repository.storage_path and not managed_repository_present(repository):
            raise ValueError("Verwaltetes Repository ist derzeit nicht verfügbar; Mount prüfen und Status erneut aktualisieren")
        if db.scalar(
            select(Run.id).where(
                Run.repository_id == repository_id,
                Run.status.in_(["queued", "running"]),
            ).limit(1)
        ):
            raise ValueError("Repository hat eine wartende oder laufende Ausführung")

        archive_snapshot = None
        run_action = action
        if action == "test":
            command = repository_validation_command(repository)
            run_action = "repository-test"
        elif action == "compact":
            command = repository_compact_command(repository)
        elif action == "delete-archive":
            archives = list(payload.get("archives") or [])
            command = delete_archives_command(
                repository, archives, payload.get("compact_after", True)
            )
            archive_snapshot = archives[0] if len(archives) == 1 else f"{len(archives)} Archive"
        else:
            raise ValueError(f"Unsupported repository action: {action}")

        run = Run(
            job_id=None,
            job_name_snapshot=(subject or f"Repository: {repository.name}")[:100],
            repository_id=repository_id,
            action=run_action,
            status="queued",
            command_preview=command.preview,
            trigger_type="manual",
            archive_name_snapshot=archive_snapshot,
        )
        db.add(run)
        db.commit()
        run_id = run.id

    if action == "test":
        task = asyncio.create_task(execute_repository_validation(run_id, repository_id, command))
    else:
        task = asyncio.create_task(
            execute_run(run_id, command, refresh_size_after=refresh_size_after)
        )
    with _active_run_lock:
        _active_run_tasks[run_id] = task
    return run_id


def queue_job_action(
    job_id: int,
    action: str,
    restore: dict | None = None,
    *,
    refresh_size_after: bool = True,
    trigger_type: str = "manual",
    schedule_name: str | None = None,
    schedule_id: int | None = None,
    schedule_parallel_limit: int = 0,
    run_label: str | None = None,
    chain_token: str | None = None,
    reserve_repository_chain: bool = False,
) -> int:
    with SessionLocal() as db:
        job = db.scalar(
            select(Job)
            .options(joinedload(Job.host), joinedload(Job.repository))
            .where(Job.id == job_id)
        )
        if not job:
            raise LookupError("Job not found")
        if not job.repository.enabled:
            raise ValueError("Repository ist deaktiviert")
        if action == "confirm-location":
            # Relocation approval belongs to the Borg client/repository pair,
            # not to an individual backup job. Reuse an already queued or
            # running confirmation instead of launching the same client action
            # repeatedly through several jobs.
            existing_confirmation = db.scalar(
                select(Run.id)
                .join(Job, Run.job_id == Job.id)
                .where(
                    Run.action == "confirm-location",
                    Run.repository_id == job.repository_id,
                    Run.status.in_(["queued", "running"]),
                    Job.host_id == job.host_id,
                )
                .order_by(Run.id)
                .limit(1)
            )
            if existing_confirmation:
                return int(existing_confirmation)
        if db.scalar(
            select(Run).where(Run.job_id == job_id, Run.status.in_(["queued", "running"])).limit(1)
        ):
            raise ValueError("A run for this job is already queued or running")
        if job.repository.storage_path:
            if action not in {"version", "source-stats"} and (
                not job.repository.initialized or not managed_repository_present(job.repository)
            ):
                raise ValueError("Verwaltetes Repository ist nicht verfügbar oder nicht initialisiert; Mount prüfen und Status erneut aktualisieren")
            if action in {"backup", "restore", "probe", "confirm-location"} and not repository_access_ready(job.host_id, job.repository_id):
                raise ValueError("Repository access for this backup job is not configured; set it up in the Backup Jobs view")
            if action == "backup":
                try:
                    guard = repository_storage_status(job.repository, load_settings())
                except OSError as exc:
                    raise ValueError(
                        f"Repository-Speicherplatz konnte nicht geprüft werden: {exc}"
                    ) from exc
                if guard and guard["guard_blocked"]:
                    raise ValueError(
                        f"Repository-Speicher für {job.repository.name} ist zu "
                        f"{guard['percent']:.1f}% belegt; Backup durch die "
                        f"{guard['guard_threshold_percent']}%-Speicherplatz-Sperre blockiert "
                        f"({guard['path']})"
                    )
        if action == "backup":
            command = backup_command(job)
        elif action == "source-stats":
            command = source_stats_command(job)
        elif action == "prune":
            retention = json.loads(job.prune_options_json or "{}")
            if not any(
                isinstance(value, int) and not isinstance(value, bool) and value > 0
                for value in retention.values()
            ):
                raise ValueError("Prune is disabled because no positive retention value is configured")
            command = prune_command(job)
        elif action in {"list", "list-all", "info", "check", "verify", "compact", "version", "probe", "confirm-location"}:
            command = repository_command(job, action)
        elif action == "restore" and restore:
            command = restore_command(
                job,
                restore["archive"],
                restore.get("paths", []),
                restore.get("target_directory"),
                restore.get("dry_run", True),
                restore.get("allow_legacy_archive", False),
                restore.get("restore_mode", "target"),
                restore.get("target_layout", "archive-paths"),
                restore.get("overwrite_existing", False),
            )
        elif action == "delete-archive" and restore:
            command = delete_archives_command(
                job.repository,
                [restore["archive"]],
                restore.get("compact_after", True),
            )
        elif action == "rename-archive" and restore:
            command = rename_archive_command(job, restore["archive"], restore["new_name"])
        elif action == "diff-archives" and restore:
            command = diff_archives_command(
                job,
                restore["archive"],
                restore["second_archive"],
                restore.get("paths", []),
                restore.get("content_only", False),
            )
        else:
            raise ValueError(f"Unsupported action: {action}")
        run = Run(
            job_id=job_id,
            job_name_snapshot=(run_label or job.name)[:100],
            repository_id=job.repository_id,
            action=action,
            status="queued",
            command_preview=command.preview,
            trigger_type="schedule" if trigger_type == "schedule" else "manual",
            schedule_name_snapshot=schedule_name.strip()[:100] if schedule_name else None,
            schedule_id_snapshot=schedule_id if trigger_type == "schedule" else None,
            schedule_parallel_limit_snapshot=(schedule_parallel_limit if trigger_type == "schedule" else 0),
            backup_source_size_bytes_snapshot=(job.source_size_bytes if action == "backup" else None),
            backup_source_file_count_snapshot=(job.source_file_count if action == "backup" else None),
        )
        db.add(run)
        db.commit()
        run_id = run.id
        chain_repository = job.repository
    if reserve_repository_chain:
        if not chain_token:
            raise ValueError("Internal maintenance chain token is missing")
        _register_repository_chain(chain_repository, run_id, chain_token)
    else:
        _register_chain_run(run_id, chain_token)
    task = asyncio.create_task(execute_run(run_id, command, refresh_size_after=refresh_size_after))
    with _active_run_lock:
        _active_run_tasks[run_id] = task
    return run_id


def cancel_run(run_id: int) -> asyncio.Task:
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if not run:
            raise LookupError("Run not found")
        if run.status not in {"queued", "running"}:
            raise ValueError("Only queued or running executions can be cancelled")
    with _active_run_lock:
        task = _active_run_tasks.get(run_id)
    if not task:
        raise ValueError("Execution process is no longer active")
    task.cancel()
    return task


def retry_run(run_id: int) -> int:
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if not run:
            raise LookupError("Run not found")
        allowed = {"backup", "prune", "list", "list-all", "info", "check", "verify", "compact", "version", "probe"}
        if not run.job_id or run.action not in allowed:
            raise ValueError("This execution cannot be repeated automatically")
        job_id, action = run.job_id, run.action
    return queue_manual_backup(job_id) if action == "backup" else queue_job_action(job_id, action)


async def _wait_for_run(run_id: int) -> str:
    while True:
        await asyncio.sleep(1)
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            if not run:
                return "failed"
            if run.status in {"success", "warning", "failed", "cancelled"}:
                return run.status


def _background_error_message(context: str, exc: BaseException) -> str:
    if isinstance(exc, (LookupError, ValueError)):
        return str(exc)
    error_id = log_unexpected_exception(
        context, exc=exc, logger_name="bbm.background",
    )
    return public_error_message(error_id)


def _record_schedule_error(
    job_id: int,
    message: str,
    schedule_name: str | None = None,
    *,
    schedule_id: int | None = None,
    schedule_parallel_limit: int = 0,
) -> int:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        run = Run(
            job_id=job_id if job else None,
            job_name_snapshot=job.name if job else None,
            repository_id=job.repository_id if job else None,
            action="schedule",
            status="failed",
            error=message,
            trigger_type="schedule",
            schedule_name_snapshot=schedule_name.strip()[:100] if schedule_name else None,
            schedule_id_snapshot=schedule_id,
            schedule_parallel_limit_snapshot=schedule_parallel_limit,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()
        return int(run.id)


def _has_retention(job: Job | None) -> bool:
    if job is None:
        return False
    try:
        retention = json.loads(job.prune_options_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    return any(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in retention.values()
    )


async def _refresh_changed_repositories(repository_ids: set[int]) -> None:
    if not repository_ids or not load_settings().repository_size_after_run:
        return
    for repository_id in sorted(repository_ids):
        try:
            await refresh_repository_statistics(repository_id)
        except (OSError, LookupError, ValueError):
            pass


async def _finish_manual_backup_chain(
    job_id: int,
    backup_run_id: int,
    repository_id: int,
    token: str,
    *,
    compact_after: bool,
) -> None:
    """Run manual retention maintenance while reserving the repository.

    The reservation starts with the backup run and remains active through prune
    and optional compact. Runs queued before the chain may finish first; once
    the root backup starts, no unrelated run can enter the repository until the
    chain releases it.
    """
    changed = False
    try:
        backup_status = await _wait_for_run(backup_run_id)
        if backup_status not in {"success", "warning"}:
            return
        changed = True
        prune_run = queue_job_action(
            job_id,
            "prune",
            refresh_size_after=False,
            chain_token=token,
        )
        prune_status = await _wait_for_run(prune_run)
        if prune_status == "success" and compact_after:
            compact_run = queue_job_action(
                job_id,
                "compact",
                refresh_size_after=False,
                chain_token=token,
            )
            await _wait_for_run(compact_run)
    except Exception as exc:
        # Keep expected queue/validation errors actionable. Unexpected failures
        # receive a short public reference while the complete traceback stays
        # in debug.log.
        detail = _background_error_message(
            f"Manual backup maintenance chain after execution #{backup_run_id} failed", exc,
        )
        append_run_log(
            backup_run_id,
            f"\nNACHBEREITUNG FEHLER: {detail}\n",
            load_settings().run_log_max_mib * 1024 * 1024,
        )
    finally:
        _release_repository_chain(token)
        if changed:
            await _refresh_changed_repositories({repository_id})


def queue_manual_backup(job_id: int) -> int:
    """Queue a manual backup and optional job-specific maintenance chain."""
    with SessionLocal() as db:
        job = db.scalar(
            select(Job).options(joinedload(Job.repository)).where(Job.id == job_id)
        )
        if not job:
            raise LookupError("Job not found")
        prune_after = bool(job.manual_prune_after_backup)
        compact_after = bool(job.manual_compact_after_prune) and prune_after
        repository_id = int(job.repository_id)
        if prune_after and not _has_retention(job):
            raise ValueError("Manuelle Archivbereinigung ist aktiviert, aber es ist keine Aufbewahrungsregel konfiguriert")

    if not prune_after:
        return queue_job_action(job_id, "backup")

    token = f"manual-{job_id}-{time.monotonic_ns()}-{os.urandom(4).hex()}"
    backup_run = queue_job_action(
        job_id,
        "backup",
        refresh_size_after=False,
        chain_token=token,
        reserve_repository_chain=True,
    )
    task = asyncio.create_task(
        _finish_manual_backup_chain(
            job_id,
            backup_run,
            repository_id,
            token,
            compact_after=compact_after,
        )
    )
    _track_maintenance_task(task)
    return backup_run


async def _scheduled_backup_group(
    job_ids: list[int],
    schedule_name: str | None,
    *,
    schedule_id: int | None = None,
    schedule_parallel_limit: int = 0,
) -> None:
    """Execute one complete schedule in backup -> prune -> compact phases.

    All backups are queued first. Only after every backup is terminal are prune
    runs queued. Compact is then executed at most once per repository and only
    after all prune runs for that repository finished successfully.
    """
    queue_kwargs: dict[str, object] = {
        "refresh_size_after": False,
        "trigger_type": "schedule",
        "schedule_name": schedule_name,
    }
    if schedule_id is not None:
        queue_kwargs["schedule_id"] = schedule_id
    if schedule_parallel_limit:
        queue_kwargs["schedule_parallel_limit"] = schedule_parallel_limit

    backup_runs: dict[int, int] = {}
    repository_by_job: dict[int, int] = {}
    for job_id in job_ids:
        try:
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if job:
                    repository_by_job[job_id] = int(job.repository_id)
            backup_runs[job_id] = queue_job_action(job_id, "backup", **queue_kwargs)
        except Exception as exc:
            failed_run_id = _record_schedule_error(
                job_id,
                _background_error_message(f"Scheduled backup queueing failed for job {job_id}", exc),
                schedule_name,
                schedule_id=schedule_id,
                schedule_parallel_limit=schedule_parallel_limit,
            )
            await asyncio.to_thread(notify_run_completion, failed_run_id)

    backup_statuses: dict[int, str] = {}
    if backup_runs:
        results = await asyncio.gather(*(_wait_for_run(run_id) for run_id in backup_runs.values()))
        backup_statuses = dict(zip(backup_runs.keys(), results))

    changed_repositories = {
        repository_by_job[job_id]
        for job_id, status in backup_statuses.items()
        if status in {"success", "warning"} and job_id in repository_by_job
    }

    prune_runs: dict[int, int] = {}
    prune_repository: dict[int, int] = {}
    for job_id, status in backup_statuses.items():
        if status not in {"success", "warning"}:
            continue
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if not _has_retention(job):
                continue
            repository_id = int(job.repository_id)
        try:
            prune_runs[job_id] = queue_job_action(job_id, "prune", **queue_kwargs)
            prune_repository[job_id] = repository_id
        except Exception as exc:
            detail = _background_error_message(f"Scheduled prune queueing failed for job {job_id}", exc)
            failed_run_id = _record_schedule_error(
                job_id,
                f"Archivbereinigung konnte nicht gestartet werden: {detail}",
                schedule_name,
                schedule_id=schedule_id,
                schedule_parallel_limit=schedule_parallel_limit,
            )
            await asyncio.to_thread(notify_run_completion, failed_run_id)

    prune_statuses: dict[int, str] = {}
    if prune_runs:
        results = await asyncio.gather(*(_wait_for_run(run_id) for run_id in prune_runs.values()))
        prune_statuses = dict(zip(prune_runs.keys(), results))

    if load_settings().compact_after_prune:
        jobs_by_repository: dict[int, list[int]] = {}
        for job_id, repository_id in prune_repository.items():
            jobs_by_repository.setdefault(repository_id, []).append(job_id)
        compact_runs: list[int] = []
        for repository_id, repository_job_ids in sorted(jobs_by_repository.items()):
            if not repository_job_ids or any(prune_statuses.get(job_id) != "success" for job_id in repository_job_ids):
                continue
            representative_job_id = min(repository_job_ids)
            try:
                compact_runs.append(queue_job_action(
                    representative_job_id,
                    "compact",
                    **queue_kwargs,
                ))
            except Exception as exc:
                detail = _background_error_message(
                    f"Scheduled compact queueing failed for job {representative_job_id}", exc,
                )
                failed_run_id = _record_schedule_error(
                    representative_job_id,
                    f"Compact konnte nicht gestartet werden: {detail}",
                    schedule_name,
                    schedule_id=schedule_id,
                    schedule_parallel_limit=schedule_parallel_limit,
                )
                await asyncio.to_thread(notify_run_completion, failed_run_id)
        if compact_runs:
            await asyncio.gather(*(_wait_for_run(run_id) for run_id in compact_runs))

    await _refresh_changed_repositories(changed_repositories)


async def scheduled_schedule(
    schedule_id: int,
    schedule_name: str | None = None,
    *,
    schedule_parallel_limit: int = 0,
) -> None:
    """Execute all current targets of one central schedule as a coordinated batch."""
    with SessionLocal() as db:
        schedule = db.get(BackupSchedule, schedule_id)
        if not schedule or not schedule.enabled:
            return
        job_ids = schedule_target_job_ids(db, schedule)
        effective_name = schedule.name or schedule_name
        effective_limit = int(schedule.parallel_limit or schedule_parallel_limit or 0)
    if not job_ids:
        return
    await _scheduled_backup_group(
        job_ids,
        effective_name,
        schedule_id=schedule_id,
        schedule_parallel_limit=effective_limit,
    )

