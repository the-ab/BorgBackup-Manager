from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import threading
import time
import unicodedata
import zipfile
from contextlib import asynccontextmanager
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError

from app.archive_cache import invalidate_archive_cache, load_archive_cache
from app.access_logging import configure_access_logging, write_access_event
from app.archive_mounts import (
    archive_mount_capability, archive_mount_host_path, archive_mount_is_active,
    archive_mount_path, cleanup_archive_mount_path, prepare_archive_mount_path,
    require_archive_mount_capability,
)
from app.archive_metadata import annotate_archive_devices, infer_archive_device, sort_archives_newest_first
from app.borg_compat import classify_borg_version, parse_borg_version, version_tuple
from app.borg_progress import get_run_item_activity, get_run_network_activity, get_run_progress, get_run_restore_progress
from app.backup_eta import estimate_fixed_baseline_remaining, source_stats_limitations
from app.manager_backup_progress import begin_task as begin_manager_backup_task, current_task as current_manager_backup_task, fail_task as fail_manager_backup_task, finish_task as finish_manager_backup_task, get_task as get_manager_backup_task, update_task as update_manager_backup_task
from app.borg_warnings import (
    parse_borg_warnings,
    unresolved_warning_summary,
    warning_diagnosis,
    warning_summary_from_json,
)
from app.borg_stats import parse_archive_listing, parse_borg_info
from app.config import (
    BACKUP_DIR,
    BACKUP_MAX_FILE_BYTES,
    BACKUP_CACHE_MAX_FILE_BYTES,
    DATA_DIR,
    EXPORT_DIR,
    RUN_LOG_DIR,
    DEBUG_LOG_PATH,
    ACCESS_LOG_PATH,
    REPOSITORY_PUBLIC_HOST,
    REPOSITORY_ROOT,
    REPOSITORY_SSH_PORT,
    REPOSITORY_AUTHORIZED_KEYS_PATH,
    RUNTIME_SECRET_DIR,
    HEALTH_REQUIRE_SSHD,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
)
from app.backups import (
    apply_prepared_restore,
    backup_path,
    client_borg_cache_inventory,
    create_cache_backup_set,
    create_full_backup,
    list_full_backups,
    prepare_full_backup_restore,
    restore_client_borg_cache_from_backup,
    restore_manager_borg_cache_from_backup,
    store_uploaded_backup, cleanup_stale_security_snapshots,
)
from app.database import SessionLocal, engine, initialize_manager_database
from app.database_maintenance import cleanup_manager_database, database_cleanup_preview
from app.external_repository import (
    external_filesystem_parallel_identity, fingerprint_known_hosts, generate_ed25519_keypair, normalize_known_hosts,
    public_key_from_private, repository_location_uses_ssh, scan_repository_host_key,
    storage_probe_target_from_location,
)
from app.repository_diagnostics import compact_repository_diagnostic
from app.system_network import sample_manager_network
from app.header_network import discover_interfaces as discover_header_network_interfaces, sample_interfaces as sample_header_network_interfaces
from app.system_diagnostics import repository_access_diagnostic
from app.debug_logging import (
    configure_debug_logging, detail_requires_debug_log, install_asyncio_exception_handler,
    log_unexpected_exception, public_error_message,
)
from app.notifications import (
    NotificationSettingsInput, NotificationSettingsOut, NotificationTestIn,
    cleanup_deliveries, clear_deliveries, list_deliveries, notification_settings_out,
    save_notification_settings, send_test_notification, notify_system_health_observation,
)
from app.repository_state import managed_repository_present
from app.release import APP_RELEASE_DATE
from app.log_filter import extract_error_output
from app.models import BackupSchedule, Host, HostRepositoryAccess, Job, JobIdReservation, ManagerArchiveMount, NotificationDelivery, Repository, Run
from app.sqlite_maintenance import run_pending_manager_vacuum
from app.runner import (
    archive_export_command,
    archive_info_command,
    execute,
    browse_archive_command,
    host_version_command,
    repository_command,
    repository_keyfile_path,
    repository_validation_command,
    repository_size_command,
    repository_archive_info_command,
    repository_browse_archive_command,
    job_archive_prefixes,
    manager_borg_argv,
    manager_archive_mount_command,
    manager_archive_unmount_command,
    scan_host_key,
)
from app.schemas import (
    ArchiveBulkDeleteIn,
    ArchiveExportIn,
    ArchiveDiffIn,
    ArchiveMountIn,
    ArchiveRenameIn,
    ControllerKeyRotateIn,
    HostIn,
    HostOut,
    EnabledStateIn,
    HostScanIn,
    HostSshActionIn,
    HostSshActionOut,
    JobIn,
    JobOut,
    BackupScheduleIn,
    BackupScheduleOut,
    LoginIn,
    PasswordChangeIn,
    ManagerBackupCreateIn,
    CacheBackupCreateIn,
    ClientBorgCacheCleanupIn,
    ClientBorgCacheScanIn,
    ManagerBackupRestoreIn,
    ManagerBorgCacheCleanupIn,
    ManagerCacheRestoreIn,
    ManagerClientCacheInspectIn,
    ManagerClientCacheRestoreIn,
    RepositoryIn,
    RepositoryImportIn,
    RepositoryOut,
    RepositoryUpdate,
    RestoreIn,
    RunCleanupIn,
    SettingsIn,
    UserCreateIn,
    UserPasswordResetIn,
    UserPreferencesIn,
    UserUpdateIn,
    TwoFactorSetupIn, TwoFactorConfirmIn, TwoFactorDisableIn, TwoFactorRecoveryRegenerateIn, DatabaseCleanupIn,
)
from app.repository_sizes import (
    managed_repository_filesystem_size, repository_statistics_from_borg_info,
    store_repository_statistics,
)
from app.run_logs import available_run_log_ids, cleanup_orphan_run_logs, delete_run_log, read_run_log, read_run_log_delta, run_log_path, run_log_storage_bytes
from app.settings import load_settings, save_settings
from app.update_check import check_latest_release, load_update_status
from app.storage_guard import (
    effective_storage_guard, mounted_filesystems_below, repository_mount_path,
    repository_storage_filesystems, repository_storage_status,
)
from app.time_utils import APP_TIMEZONE, APP_TIMEZONE_NAME, ensure_utc, iso_utc
from app.schedules import (
    schedule_assignments, schedule_expressions,
    schedule_target_job_ids, validate_job_schedule_conflicts, validate_schedule_conflicts,
    validate_schedule_targets_exist,
)
from app.security_bootstrap import bootstrap_security_material
from app.security_store import (
    AuthUser, authenticate_user, change_own_password, consume_login_attempt, create_session, create_session_reload_token, create_user,
    delete_user as delete_security_user, get_session_user, get_session_user_by_reload_token, initialize_security_store,
    list_users, reset_login_rate_limit, revoke_session, revoke_session_by_reload_token, security_status, authentication_readiness, set_user_password, update_user, update_user_preferences,
    begin_two_factor_setup, confirm_two_factor_setup, disable_two_factor, regenerate_two_factor_recovery_codes, reset_two_factor,
    create_host_ssh_action as create_security_host_ssh_action,
    delete_host_ssh_action as delete_security_host_ssh_action,
    delete_host_ssh_actions_for_host,
    list_host_ssh_actions as list_security_host_ssh_actions,
    update_host_ssh_action as update_security_host_ssh_action,
)
from app.vault import (
    delete_repository_secrets, get_repository_secret, repository_secret_exists,
    set_repository_secret, store_repository_environment,
)
from app.security import require_authenticated_user, require_token, session_cookie_values
from app.request_security import (
    client_address,
    origin_matches_request,
    request_uses_https,
)
from app.service import (
    ActiveArchiveMountError,
    bootstrap_host_repository,
    clear_repository_cache,
    execute_interactive,
    cancel_run,
    controller_public_key,
    rotate_controller_key,
    queue_job_action,
    queue_manual_backup,
    queue_host_ssh_action,
    queue_repository_action,
    queue_repository_archive_refresh,
    queue_repository_init,
    refresh_external_repository_storage,
    reset_managed_repository_state,
    retry_run,
    revoke_host_repository_access,
    scheduled_schedule,
    sync_repository_access_assignments,
    trust_host_key,
)


STATIC = Path(__file__).parent / "static"
VERSION_FILE = Path(__file__).parent.parent / "VERSION"
APP_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.is_file() else "0.0.0"
scheduler = AsyncIOScheduler(timezone=APP_TIMEZONE)
UPDATE_CHECK_JOB_ID = "github-release-check"


def _request_uses_https(request: Request) -> bool:
    return request_uses_https(request)

def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    expires = datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        expires=expires,
        httponly=True,
        secure=_request_uses_https(request),
        samesite="strict",
        path="/",
    )


def _delete_session_cookie(response: Response, request: Request) -> None:
    secure = _request_uses_https(request)
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=secure,
        httponly=True,
        samesite="strict",
    )


def host_out(row: Host) -> HostOut:
    return HostOut.model_validate(row)


def repo_out(row: Repository, *, mounts: list[Path] | None = None) -> RepositoryOut:
    repository_present = managed_repository_present(row)
    settings = load_settings()
    effective_enabled, effective_threshold, guard_source = effective_storage_guard(row, settings)
    mount = repository_mount_path(row.storage_path, REPOSITORY_ROOT, mounts=mounts) if row.storage_path else None
    storage_total = storage_used = storage_free = None
    storage_percent = None
    storage_path = None
    storage_checked_at = None
    storage_error = None
    storage_source = None
    if row.storage_path:
        try:
            local_storage = repository_storage_status(row, settings)
        except OSError as exc:
            local_storage = None
            storage_error = str(exc)
        if local_storage is not None:
            storage_total = int(local_storage["total"])
            storage_used = int(local_storage["used"])
            storage_free = int(local_storage["free"])
            storage_percent = float(local_storage["percent"])
            storage_path = str(mount or local_storage["path"])
            storage_checked_at = datetime.now(timezone.utc)
            storage_source = "managed"
    else:
        storage_total = row.external_storage_total_bytes
        storage_used = row.external_storage_used_bytes
        storage_free = row.external_storage_free_bytes
        storage_percent = row.external_storage_usage_percent
        storage_path = row.external_storage_path
        storage_checked_at = row.external_storage_checked_at
        storage_error = row.external_storage_error
        storage_source = "external-ssh"
    guard_blocked = bool(
        effective_enabled and storage_percent is not None and float(storage_percent) >= effective_threshold
    )
    external_parallel = (
        external_filesystem_parallel_identity(row.location, row.external_storage_path)
        if not row.storage_path else None
    )
    return RepositoryOut(
        id=row.id, name=row.name, enabled=bool(row.enabled), location=row.location,
        passphrase_env=None, extra_env=json.loads(row.extra_env_json or "{}"),
        encryption_mode=row.encryption_mode,
        managed=bool(row.storage_path), initialized=row.initialized,
        repository_present=repository_present,
        has_passphrase=repository_secret_exists(row, "passphrase"),
        has_keyfile=repository_secret_exists(row, "keyfile"),
        has_external_ssh_key=repository_secret_exists(row, "external_ssh_private_key"),
        external_ssh_public_key=row.external_ssh_public_key,
        has_external_known_hosts=repository_secret_exists(row, "external_known_hosts"),
        external_host_fingerprint=row.external_host_fingerprint,
        validation_error=row.validation_error,
        validation_details=row.validation_details,
        validated_at=row.validated_at,
        size_bytes=row.size_bytes,
        original_size_bytes=row.original_size_bytes,
        compressed_size_bytes=row.compressed_size_bytes,
        deduplicated_size_bytes=row.deduplicated_size_bytes,
        size_checked_at=row.size_checked_at,
        storage_guard_enabled=row.storage_guard_enabled,
        storage_guard_threshold_percent=row.storage_guard_threshold_percent,
        mount_path=str(mount) if mount is not None else None,
        storage_guard_effective_enabled=effective_enabled,
        storage_guard_effective_threshold_percent=effective_threshold,
        storage_guard_source=guard_source,
        storage_usage_total_bytes=storage_total,
        storage_usage_used_bytes=storage_used,
        storage_usage_free_bytes=storage_free,
        storage_usage_percent=storage_percent,
        storage_usage_path=storage_path,
        storage_usage_checked_at=storage_checked_at,
        storage_usage_error=storage_error,
        storage_usage_source=storage_source,
        storage_guard_blocked=guard_blocked,
        external_parallel_key=external_parallel[0] if external_parallel else None,
        external_parallel_label=external_parallel[1] if external_parallel else None,
    )


async def prepare_external_repository_credentials(data, existing: Repository | None = None) -> dict[str, str | None]:
    location = data.location or (existing.location if existing else "")
    if not repository_location_uses_ssh(location):
        return {
            "external_ssh_private_key": None,
            "external_ssh_public_key": None,
            "external_known_hosts": None,
            "external_host_fingerprint": None,
        }

    private_key = data.external_ssh_private_key.get_secret_value() if data.external_ssh_private_key else None
    if data.generate_external_ssh_key:
        private_key, public_key = generate_ed25519_keypair(f"bbm-repository-{existing.id if existing else 'new'}")
    elif private_key:
        public_key = public_key_from_private(private_key, f"bbm-repository-{existing.id if existing else 'new'}")
    elif existing:
        private_key = get_repository_secret(existing, "external_ssh_private_key")
        public_key = existing.external_ssh_public_key or (public_key_from_private(private_key) if private_key else None)
    else:
        private_key = public_key = None
    if not private_key or not public_key:
        raise ValueError("Für ein SSH-Repository muss der Manager einen Ed25519-Schlüssel erzeugen oder einen vorhandenen privaten Schlüssel übernehmen")

    known_hosts = data.external_known_hosts.get_secret_value() if data.external_known_hosts else None
    if known_hosts:
        known_hosts = normalize_known_hosts(known_hosts)
        fingerprint = fingerprint_known_hosts(known_hosts)
    elif data.scan_external_host_key:
        known_hosts, fingerprint = await scan_repository_host_key(location)
    elif existing:
        known_hosts = get_repository_secret(existing, "external_known_hosts")
        fingerprint = existing.external_host_fingerprint or (fingerprint_known_hosts(known_hosts) if known_hosts else None)
    else:
        known_hosts = fingerprint = None
    if not known_hosts or not fingerprint:
        raise ValueError("Für ein SSH-Repository muss known_hosts angegeben oder der Hostkey-Scan aktiviert werden")

    return {
        "external_ssh_private_key": private_key,
        "external_ssh_public_key": public_key,
        "external_known_hosts": known_hosts,
        "external_host_fingerprint": fingerprint,
    }


def repository_slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    prefix = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:48] or "repository"
    suffix = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{suffix}"


def managed_repository_location(slug: str) -> str:
    host = REPOSITORY_PUBLIC_HOST.strip("[]")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"ssh://borg@{host}:{REPOSITORY_SSH_PORT}/./{slug}"



def sync_managed_repository_locations() -> None:
    """Refresh managed repository URLs after endpoint or server changes."""
    root = REPOSITORY_ROOT.resolve()
    with SessionLocal() as db:
        changed = False
        for repository in db.scalars(select(Repository).where(Repository.storage_path.is_not(None))):
            try:
                relative = Path(repository.storage_path).resolve(strict=False).relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            if not relative or relative == ".":
                continue
            expected = managed_repository_location(relative)
            if repository.location != expected:
                repository.location = expected
                changed = True
        if changed:
            db.commit()

def job_out(
    row: Job,
    assigned_schedules: list[BackupSchedule] | None = None,
    repository_access_ready: bool = False,
) -> JobOut:
    names = [schedule.name for schedule in (assigned_schedules or [])]
    return JobOut(
        id=row.id, name=row.name, host_id=row.host_id, repository_id=row.repository_id,
        source_paths=json.loads(row.source_paths_json),
        exclude_patterns=json.loads(row.exclude_patterns_json), archive_template=row.archive_template,
        archive_prefix=row.archive_prefix or f"bbm-{row.id}-",
        archive_prefixes=job_archive_prefixes(row),
        compression=row.compression,
        prune_options=json.loads(row.prune_options_json or "{}"),
        create_options=json.loads(row.create_options_json or "{}"),
        manual_prune_after_backup=bool(row.manual_prune_after_backup),
        manual_compact_after_prune=bool(row.manual_compact_after_prune),
        enabled=row.enabled, repository_enabled=bool(getattr(row.repository, "enabled", True)),
        schedule_mode="scheduled" if names else "manual", schedule_names=names,
        repository_access_ready=repository_access_ready,
        source_size_bytes=row.source_size_bytes,
        source_file_count=row.source_file_count,
        source_stats_checked_at=row.source_stats_checked_at,
        source_stats_origin=row.source_stats_origin,
        source_stats_limitations=source_stats_limitations(getattr(row, "source_stats_detail_json", "{}")),
    )


def schedule_out(row: BackupSchedule, db) -> BackupScheduleOut:
    job_ids = schedule_target_job_ids(db, row, enabled_jobs_only=False)
    runnable_job_ids = schedule_target_job_ids(db, row, enabled_jobs_only=True)
    repository_disabled_job_count = 0
    if job_ids:
        repository_disabled_job_count = int(db.scalar(
            select(func.count())
            .select_from(Job)
            .join(Repository, Repository.id == Job.repository_id)
            .where(Job.id.in_(job_ids), Repository.enabled.is_(False))
        ) or 0)
    return BackupScheduleOut(
        id=row.id, name=row.name, expressions=row.expressions, target_mode=row.target_mode,
        target_host_ids=json.loads(row.target_host_ids_json or "[]"),
        target_repository_id=row.target_repository_id,
        target_job_ids=json.loads(row.target_job_ids_json or "[]"),
        parallel_limit=row.parallel_limit or 0,
        enabled=row.enabled, assigned_job_ids=job_ids, assigned_job_count=len(job_ids),
        runnable_job_count=len(runnable_job_ids),
        repository_disabled_job_count=repository_disabled_job_count,
    )


def managed_repository_candidates(*, max_depth: int = 6, max_directories: int = 5000) -> list[dict]:
    """Find unregistered Borg repositories safely below the managed root.

    Search is bounded and never follows symlinks.  Once a Borg ``config`` is
    found the repository directory is recorded and not traversed further,
    avoiding scans through Borg's internal data tree.
    """
    REPOSITORY_ROOT.mkdir(parents=True, exist_ok=True)
    root = REPOSITORY_ROOT.resolve()
    with SessionLocal() as db:
        registered = {
            Path(value).resolve()
            for value in db.scalars(select(Repository.storage_path).where(Repository.storage_path.is_not(None)))
            if value
        }

    candidates: list[dict] = []
    queue = deque([(root, 0)])
    scanned = 0
    while queue and scanned < max_directories and len(candidates) < 500:
        current, depth = queue.popleft()
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            continue
        for child in children:
            if scanned >= max_directories:
                break
            try:
                if child.is_symlink() or not child.is_dir():
                    continue
            except OSError:
                continue
            scanned += 1
            if child.name in {".cache", ".config"}:
                continue
            config = child / "config"
            try:
                is_repository = config.is_file()
            except OSError:
                is_repository = False
            if is_repository:
                try:
                    resolved = child.resolve(strict=True)
                except OSError:
                    continue
                if resolved in registered:
                    continue
                repository_id = None
                try:
                    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
                        if line.strip().startswith("id") and "=" in line:
                            repository_id = line.split("=", 1)[1].strip() or None
                            break
                except OSError:
                    pass
                relative = resolved.relative_to(root).as_posix()
                candidates.append({
                    "directory_name": relative,
                    "path": str(resolved),
                    "suggested_name": child.name.replace("-", " ").replace("_", " ").strip().title() or child.name,
                    "repository_id": repository_id,
                })
                continue
            if depth + 1 < max_depth:
                queue.append((child, depth + 1))
    return candidates



def load_job_with_connections(db, job_id: int, require_client_access: bool = True) -> Job:
    job = db.scalar(
        select(Job)
        .options(joinedload(Job.host), joinedload(Job.repository))
        .where(Job.id == job_id)
    )
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.repository.enabled:
        raise HTTPException(409, "Repository ist deaktiviert")
    if job.repository.storage_path:
        if not job.repository.initialized or not managed_repository_present(job.repository):
            raise HTTPException(400, "Managed repository is missing or not initialized")
        if require_client_access:
            access = db.scalar(
                select(HostRepositoryAccess.id).where(
                    HostRepositoryAccess.host_id == job.host_id,
                    HostRepositoryAccess.repository_id == job.repository_id,
                    HostRepositoryAccess.public_key.is_not(None),
                )
            )
            if not access:
                raise HTTPException(400, "Repository-Zugang für diesen Backup-Job ist nicht eingerichtet. Unter Backup-Jobs → Mehr → Repository-Zugang einrichten.")
    return job


def load_repository_with_access(db, repository_id: int) -> Repository:
    repository = db.get(Repository, repository_id)
    if not repository:
        raise HTTPException(404, "Repository not found")
    if not repository.enabled:
        raise HTTPException(409, "Repository ist deaktiviert")
    if repository.storage_path and (not repository.initialized or not managed_repository_present(repository)):
        raise HTTPException(400, "Verwaltetes Repository fehlt oder ist nicht initialisiert")
    if not repository.initialized and not repository.storage_path:
        detail = repository.validation_error or "Externes Repository wurde noch nicht erfolgreich geprüft"
        raise HTTPException(400, detail)
    if not repository.storage_path and repository_location_uses_ssh(repository.location):
        if not repository_secret_exists(repository, "external_ssh_private_key") or not repository_secret_exists(repository, "external_known_hosts"):
            raise HTTPException(400, "Externer Repository-Zugang ist im Manager nicht vollständig eingerichtet")
    return repository


def assign_archive_owners(archives: list[dict], repository_jobs: list[Job], selected_job_id: int | None = None) -> list[dict]:
    prefixes = sorted(
        (
            (
                prefix, row.id, row.name, row.host_id,
                row.host.name if getattr(row, "host", None) else None,
            )
            for row in repository_jobs
            for prefix in job_archive_prefixes(row)
        ),
        key=lambda item: len(item[0]), reverse=True,
    )
    for archive in archives:
        owner = next((item for item in prefixes if archive["name"].startswith(item[0])), None)
        archive["job_id"] = owner[1] if owner else None
        archive["job_name"] = owner[2] if owner else None
        archive["host_id"] = owner[3] if owner else None
        archive["device_name"] = owner[4] if owner else None
        archive["legacy"] = owner is None
        archive["selected_job"] = bool(selected_job_id and archive["job_id"] == selected_job_id)
    return archives


def archive_owner_job(archive_name: str, repository_jobs: list[Job]) -> Job | None:
    """Return the most specific job whose archive prefix owns ``archive_name``."""
    candidates = [
        (prefix, job)
        for job in repository_jobs
        for prefix in job_archive_prefixes(job)
        if archive_name.startswith(prefix)
    ]
    return max(candidates, key=lambda item: len(item[0]))[1] if candidates else None


def _archive_device_key(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def resolve_archive_devices(archives: list[dict], repository_jobs: list[Job]) -> list[dict]:
    """Resolve an archive to its device by series first, then Borg/name metadata."""
    annotate_archive_devices(archives)
    jobs_by_host: dict[int, list[Job]] = {}
    for job in repository_jobs:
        jobs_by_host.setdefault(job.host_id, []).append(job)

    host_keys: dict[int, set[str]] = {}
    for host_id, jobs in jobs_by_host.items():
        host = jobs[0].host if jobs and getattr(jobs[0], "host", None) else None
        host_keys[host_id] = {
            key for key in (
                _archive_device_key(getattr(host, "name", None)),
                _archive_device_key(getattr(host, "address", None)),
            ) if key
        }

    for archive in archives:
        if archive.get("job_id"):
            archive["action_job_id"] = archive["job_id"]
            continue
        candidates = {
            key for key in (
                _archive_device_key(archive.get("hostname")),
                _archive_device_key(archive.get("archive_device")),
            ) if key
        }
        matching_host_ids = [
            host_id for host_id, keys in host_keys.items() if candidates.intersection(keys)
        ]
        if len(matching_host_ids) == 1:
            matching_jobs = sorted(jobs_by_host[matching_host_ids[0]], key=lambda row: row.id)
            archive["action_job_id"] = matching_jobs[0].id
            archive["host_id"] = matching_jobs[0].host_id
            archive["device_name"] = matching_jobs[0].host.name
        else:
            archive["action_job_id"] = None
            archive["device_name"] = archive.get("hostname") or archive.get("archive_device") or None
    return archives


def compact_repository_error_with_debug(
    context: str, output: str, error: str, return_code: int,
) -> tuple[str, str]:
    summary, details = compact_repository_diagnostic(output, error, return_code)
    technical = "\n".join(part for part in (output, error) if part).strip()
    if detail_requires_debug_log(technical):
        error_id = log_unexpected_exception(
            context, detail=technical, logger_name="bbm.http",
        )
        summary = f"{summary} Technische Details: Debug-Log, Fehler-ID {error_id}."
    return summary, details


def borg_operation_error(output: str, error: str, return_code: int) -> HTTPException:
    summary, _details = compact_repository_error_with_debug(
        "Repository operation returned technical Borg output", output, error, return_code,
    )
    return HTTPException(400, summary)


async def repository_archive_names(job: Job, *, consider_checkpoints: bool = True) -> set[str]:
    command = repository_command(job, "list-all", consider_checkpoints=consider_checkpoints)
    code, output, error = await execute_interactive(job.repository_id, command)
    if code not in {0, 1}:
        raise borg_operation_error(output, error, code)
    try:
        return {item["name"] for item in parse_archive_listing(output + "\n" + error)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


async def archive_exists(job: Job, archive: str) -> bool:
    return archive in await repository_archive_names(job)


def apply_job(row: Job, data: JobIn) -> None:
    source_paths_json = json.dumps(data.source_paths)
    exclude_patterns_json = json.dumps(data.exclude_patterns)
    create_options_json = json.dumps(data.create_options)
    statistics_inputs_changed = any((
        row.host_id is not None and row.host_id != data.host_id,
        row.source_paths_json not in {None, source_paths_json},
        row.exclude_patterns_json not in {None, exclude_patterns_json},
        row.create_options_json not in {None, create_options_json},
    ))
    row.name = data.name
    row.host_id = data.host_id
    row.repository_id = data.repository_id
    row.source_paths_json = source_paths_json
    row.exclude_patterns_json = exclude_patterns_json
    row.archive_template = data.archive_template
    row.compression = data.compression
    row.prune_options_json = json.dumps(data.prune_options)
    row.create_options_json = create_options_json
    row.manual_prune_after_backup = data.manual_prune_after_backup
    row.manual_compact_after_prune = data.manual_compact_after_prune if data.manual_prune_after_backup else False
    row.enabled = data.enabled
    if statistics_inputs_changed:
        row.source_size_bytes = None
        row.source_file_count = None
        row.source_stats_checked_at = None
        row.source_stats_origin = None
        row.source_stats_detail_json = "{}"


def allocate_job_id(db) -> int:
    """Allocate a monotonically increasing job ID that survives job deletion."""
    highest = max(
        db.scalar(select(func.max(Job.id))) or 0,
        db.scalar(select(func.max(JobIdReservation.id))) or 0,
        db.scalar(select(func.max(Run.job_id))) or 0,
    )
    job_id = highest + 1
    db.add(JobIdReservation(id=job_id))
    return job_id


def retained_run_ids_for_existing_jobs(db) -> set[int]:
    """Return reliable backup runs that must survive normal retention cleanup.

    For each currently existing job only the newest successful or warning
    backup is retained. Failed, cancelled or otherwise aborted runs are useful
    history, but they are not a reliable source/size baseline and therefore
    remain subject to the normal retention policy. Deleted jobs are naturally
    excluded because their historical runs have job_id=NULL.
    """
    existing_job_ids = select(Job.id).join(Host, Host.id == Job.host_id)
    retained_ids = db.scalars(
        select(func.max(Run.id))
        .where(
            Run.action == "backup",
            Run.job_id.in_(existing_job_ids),
            Run.status.in_(["success", "warning"]),
        )
        .group_by(Run.job_id)
    )
    return {int(run_id) for run_id in retained_ids if run_id is not None}


def _clear_retained_job_statistics(db) -> None:
    """Clear per-job source statistics for the explicit "all logs" action."""
    for job in db.scalars(select(Job)):
        job.source_size_bytes = None
        job.source_file_count = None
        job.source_stats_checked_at = None
        job.source_stats_origin = None
        job.source_stats_detail_json = "{}"


def cleanup_run_history(days: int | None = None, *, all_finished: bool = False) -> int:
    retention_days = load_settings().run_retention_days if days is None else days
    if not all_finished and retention_days <= 0:
        return 0
    run_ids: list[int] = []
    with SessionLocal() as db:
        query = select(Run.id).where(Run.status.notin_(["queued", "running"]))
        if not all_finished:
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            protected_ids = retained_run_ids_for_existing_jobs(db)
            query = query.where(Run.created_at < cutoff)
            if protected_ids:
                query = query.where(Run.id.notin_(protected_ids))
        run_ids = list(db.scalars(query))
        if run_ids:
            db.execute(delete(Run).where(Run.id.in_(run_ids)))
        if all_finished:
            _clear_retained_job_statistics(db)
        if run_ids or all_finished:
            db.commit()
    for run_id in run_ids:
        delete_run_log(run_id)
    # Notification deliveries are operational history and follow the same
    # retention window. The explicit all-logs action removes them all.
    cleanup_deliveries(retention_days, all_entries=all_finished)
    return len(run_ids)


def vacuum_database() -> bool:
    if engine.dialect.name != "sqlite":
        return False
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql("VACUUM")
        return True
    except Exception:
        # Cleanup itself must remain successful if another short transaction
        # temporarily prevents SQLite from acquiring the exclusive VACUUM lock.
        return False


def run_storage_info() -> dict:
    with SessionLocal() as db:
        total = int(db.scalar(select(func.count()).select_from(Run)) or 0)
        active = int(db.scalar(select(func.count()).select_from(Run).where(Run.status.in_(["queued", "running"]))) or 0)
        database_payload = int(db.scalar(select(func.coalesce(func.sum(
            func.coalesce(func.length(Run.output), 0)
            + func.coalesce(func.length(Run.error), 0)
            + func.coalesce(func.length(Run.log_output), 0)
        ), 0))) or 0)
        oldest = db.scalar(select(func.min(Run.created_at)))
        notification_deliveries = int(db.scalar(select(func.count()).select_from(NotificationDelivery)) or 0)
        oldest_notification_delivery = db.scalar(select(func.min(NotificationDelivery.created_at)))
    database_file_bytes = 0
    if engine.dialect.name == "sqlite" and engine.url.database:
        try:
            database_file_bytes = Path(engine.url.database).stat().st_size
        except OSError:
            pass
    return {
        "total_runs": total,
        "active_runs": active,
        "finished_runs": max(0, total - active),
        "oldest_run": oldest,
        "notification_deliveries": notification_deliveries,
        "oldest_notification_delivery": oldest_notification_delivery,
        "log_file_bytes": run_log_storage_bytes(),
        "database_log_payload_bytes": database_payload,
        "database_file_bytes": database_file_bytes,
        "log_directory": str(RUN_LOG_DIR),
        "retention_days": load_settings().run_retention_days,
    }


def _update_check_next_run(interval_hours: int, *, immediate: bool = False) -> datetime:
    """Keep the release-check cadence stable when application schedules are rebuilt."""
    now = datetime.now(timezone.utc)
    if immediate:
        return now
    status = load_update_status(APP_VERSION)
    raw = status.get("last_attempt_at") or status.get("checked_at")
    if not raw:
        return now
    try:
        previous = datetime.fromisoformat(str(raw))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        else:
            previous = previous.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return now
    due = previous + timedelta(hours=max(1, int(interval_hours)))
    return due if due > now else now



async def scheduled_update_check() -> None:
    settings = load_settings()
    if not settings.update_check_enabled:
        return
    await asyncio.to_thread(check_latest_release, APP_VERSION)

def sync_update_check_job(*, immediate: bool = False) -> None:
    if scheduler.get_job(UPDATE_CHECK_JOB_ID) is not None:
        scheduler.remove_job(UPDATE_CHECK_JOB_ID)
    settings = load_settings()
    if not settings.update_check_enabled:
        return
    scheduler.add_job(
        scheduled_update_check,
        IntervalTrigger(hours=settings.update_check_interval_hours, timezone=APP_TIMEZONE),
        id=UPDATE_CHECK_JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        next_run_time=_update_check_next_run(settings.update_check_interval_hours, immediate=immediate),
    )


def update_status_payload() -> dict:
    settings = load_settings()
    status = load_update_status(APP_VERSION)
    status["enabled"] = settings.update_check_enabled
    status["interval_hours"] = settings.update_check_interval_hours
    return status


def sync_schedules() -> None:
    scheduler.remove_all_jobs()
    scheduler.add_job(
        cleanup_run_history, CronTrigger(hour=3, minute=30, timezone=APP_TIMEZONE), id="housekeeping-run-history",
        max_instances=1, coalesce=True, misfire_grace_time=3600, replace_existing=True,
    )
    with SessionLocal() as db:
        for schedule in db.scalars(select(BackupSchedule).where(BackupSchedule.enabled.is_(True)).order_by(BackupSchedule.id)):
            try:
                expressions = schedule_expressions(schedule.expressions)
                job_ids = schedule_target_job_ids(db, schedule)
            except ValueError:
                continue
            if not job_ids:
                continue
            for index, expression in enumerate(expressions, start=1):
                trigger = CronTrigger.from_crontab(expression, timezone=APP_TIMEZONE)
                scheduler.add_job(
                    scheduled_schedule, trigger, args=[schedule.id, schedule.name],
                    kwargs={"schedule_parallel_limit": schedule.parallel_limit or 0},
                    id=f"schedule-{schedule.id}-{index}",
                    max_instances=1, coalesce=True, misfire_grace_time=3600, replace_existing=True,
                )
    sync_update_check_job(immediate=False)


def recover_interrupted_runs() -> None:
    """Close stale process state after an application/container restart."""
    with SessionLocal() as db:
        rows = db.scalars(select(Run).where(Run.status.in_(["queued", "running"]))).all()
        for row in rows:
            row.status = "failed"
            row.error = ((row.error + "\n") if row.error else "") + "Manager restarted while execution was active"
            row.finished_at = datetime.now(timezone.utc)
        db.commit()



def reconcile_manager_archive_mounts() -> None:
    """Drop stale database rows left by a container restart or hard stop."""
    with SessionLocal() as db:
        rows = list(db.scalars(select(ManagerArchiveMount).order_by(ManagerArchiveMount.id)))
        for row in rows:
            if archive_mount_is_active(row.mount_path):
                row.status = "mounted"
                row.error = ""
            else:
                mount_path = row.mount_path
                db.delete(row)
                cleanup_archive_mount_path(mount_path)
        db.commit()


async def system_health_watch_loop() -> None:
    """Watch core health independently from APScheduler.

    This loop deliberately does not run as an APScheduler job; otherwise a
    stopped scheduler could never report its own failure.
    """
    await asyncio.sleep(15)
    while True:
        try:
            payload, _strict_healthy = component_health_payload()
            await asyncio.to_thread(notify_system_health_observation, payload, confirmations=2)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger(__name__).exception("System-health notification check failed")
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global scheduler
    configure_debug_logging()
    configure_access_logging()
    loop = asyncio.get_running_loop()
    previous_exception_handler = install_asyncio_exception_handler(loop)
    # AsyncIOScheduler binds itself to the current event loop when started.
    # Build a fresh instance for every application lifecycle so reloads and
    # clean restarts never reuse a scheduler attached to a closed loop.
    scheduler = AsyncIOScheduler(timezone=APP_TIMEZONE)
    initialize_manager_database()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    reconcile_manager_archive_mounts()
    initialize_security_store()
    run_pending_manager_vacuum(engine)
    cleanup_stale_security_snapshots()
    # The container entrypoint materializes runtime TLS and SSH material as root
    # before dropping privileges.  Do not repeat that privileged operation in
    # the unprivileged Web API process.  Direct development/test starts still
    # bootstrap normally when the marker is absent.
    if os.getenv("BBM_RUNTIME_SECURITY_PREPARED") != "1":
        bootstrap_security_material()
    sync_managed_repository_locations()
    with SessionLocal() as db:
        cleanup_orphan_run_logs(set(db.scalars(select(Run.id))))
    sync_repository_access_assignments()
    recover_interrupted_runs()
    cleanup_run_history()
    scheduler.start()
    sync_schedules()
    health_watch_task = asyncio.create_task(system_health_watch_loop(), name="bbm-system-health-watch")
    try:
        yield
    finally:
        health_watch_task.cancel()
        try:
            await health_watch_task
        except asyncio.CancelledError:
            pass
        scheduler.shutdown(wait=False)
        loop.set_exception_handler(previous_exception_handler)


app = FastAPI(title="BorgBackup Manager", version=APP_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(ActiveArchiveMountError)
async def active_archive_mount_exception(_request: Request, exc: ActiveArchiveMountError):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(StarletteHTTPException)
async def compact_http_exception(request: Request, exc: StarletteHTTPException):
    """Sanitize tracebacks and record application-side HTTP 5xx incidents."""
    detail_text = str(exc.detail or "").strip()
    already_referenced = bool(re.search(r"\bBBM-[A-F0-9]{8}\b", detail_text))
    technical = detail_requires_debug_log(exc.detail)
    server_error = int(exc.status_code) >= 500
    if (technical or server_error) and not already_referenced:
        cause = exc.__cause__ if isinstance(exc.__cause__, BaseException) else None
        error_id = log_unexpected_exception(
            f"HTTP {exc.status_code} response was recorded",
            exc=cause,
            detail=exc.detail,
            method=request.method,
            path=request.url.path,
            logger_name="bbm.http",
        )
        request.state.debug_error_logged = True
        if technical:
            public_detail = public_error_message(error_id)
        else:
            concise = detail_text if detail_text and len(detail_text) <= 300 else f"HTTP {exc.status_code}"
            public_detail = f"{concise} Technische Details: Debug-Log, Fehler-ID {error_id}."
        return JSONResponse(
            {"detail": public_detail},
            status_code=exc.status_code,
            headers=exc.headers,
        )
    if already_referenced:
        request.state.debug_error_logged = True
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


protected = [Depends(require_token)]


def require_admin_access(user: AuthUser = Depends(require_token)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator permission required")
    return user


admin_protected = [Depends(require_admin_access)]


@app.middleware("http")
async def browser_security_headers(request: Request, call_next):
    access_started = time.monotonic()
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
        if request.headers.get("x-bbm-request", "") != "1":
            return JSONResponse({"detail": "Missing anti-CSRF request header"}, status_code=403)
        if not origin_matches_request(request):
            return JSONResponse({"detail": "Request origin does not match this BorgBackup Manager"}, status_code=403)
    try:
        response = await call_next(request)
    except Exception as exc:
        error_id = log_unexpected_exception(
            "Unhandled HTTP exception",
            exc=exc,
            method=request.method,
            path=request.url.path,
            logger_name="bbm.http",
        )
        request.state.debug_error_logged = True
        response = JSONResponse(
            {"detail": public_error_message(error_id)},
            status_code=500,
        )
    if response.status_code >= 500 and not getattr(request.state, "debug_error_logged", False):
        log_unexpected_exception(
            f"HTTP {response.status_code} response completed without an exception reference",
            detail={"status_code": response.status_code},
            method=request.method,
            path=request.url.path,
            logger_name="bbm.http",
        )
        request.state.debug_error_logged = True
    if request_uses_https(request):
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'; manifest-src 'self'"
    )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    path = request.url.path
    if path.startswith("/static/") and request.query_params.get("v") == APP_VERSION:
        # Versioned static assets are immutable for this release. This avoids
        # repeated transfer and validation requests without risking stale files
        # after an update because every release changes the query version.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, max-age=0"
    elif path == "/" or path.startswith("/api/") or path.endswith("/index.html"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    write_access_event(
        "http_access", remote_address=client_address(request), method=request.method, path=request.url.path,
        http_status=response.status_code, user_agent=request.headers.get("user-agent"),
        duration_ms=(time.monotonic() - access_started) * 1000.0,
    )
    return response


@app.post("/api/auth/login")
def login(data: LoginIn, request: Request, response: Response):
    remote_address = client_address(request)
    user_agent = request.headers.get("user-agent")
    allowed, retry_after = consume_login_attempt(data.username, remote_address)
    if not allowed:
        write_access_event("login_blocked", remote_address=remote_address, username=data.username, status="blocked", user_agent=user_agent, detail="rate_limit")
        raise HTTPException(
            429,
            "Zu viele Anmeldeversuche von dieser Quelle. Bitte später erneut versuchen.",
            headers={"Retry-After": str(retry_after)},
        )
    second_factor = data.second_factor.get_secret_value() if data.second_factor else None
    user, auth_status = authenticate_user(
        data.username, data.password.get_secret_value(), remote_address, second_factor,
        return_status=True,
    )
    if auth_status == "two_factor_required":
        write_access_event("login_two_factor_required", remote_address=remote_address, username=data.username, status="challenge", user_agent=user_agent)
        return JSONResponse({"status": "two-factor-required", "detail": "Zwei-Faktor-Code erforderlich"}, status_code=202)
    if user is None:
        reason = "invalid_second_factor" if auth_status == "invalid_second_factor" else "invalid_credentials"
        write_access_event("login_failed", remote_address=remote_address, username=data.username, status="failed", user_agent=user_agent, detail=reason)
        detail = "Der Zwei-Faktor-Code oder Wiederherstellungscode ist ungültig" if reason == "invalid_second_factor" else "Benutzername oder Passwort ist falsch"
        raise HTTPException(401, detail)
    reset_login_rate_limit(data.username, remote_address)
    token = create_session(
        user, SESSION_TTL_SECONDS, remote_address,
        user_agent,
    )
    _set_session_cookie(response, request, token)
    reload_token = create_session_reload_token(token, SESSION_TTL_SECONDS, user_agent)
    write_access_event("login_success", remote_address=remote_address, username=user.username, status="success", user_agent=user_agent, detail=auth_status)
    return {
        "status": "ok", "username": user.username, "role": user.role,
        "must_change_password": user.must_change_password,
        "language": user.language, "appearance": user.appearance,
        "two_factor_enabled": user.two_factor_enabled,
        "recovery_code_used": auth_status == "recovery_code",
        "reload_token": reload_token,
    }


@app.post("/api/auth/logout")
def auth_logout(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict:
    for token in session_cookie_values(request, session_cookie):
        revoke_session(token)
    if authorization and authorization.startswith("BBM-Reload "):
        revoke_session_by_reload_token(authorization[len("BBM-Reload "):])
    _delete_session_cookie(response, request)
    write_access_event("logout", remote_address=client_address(request), status="success", user_agent=request.headers.get("user-agent"))
    return {"status": "logged-out"}


@app.get("/api/auth/status")
def auth_status(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict:
    values = session_cookie_values(request, session_cookie)
    user = None
    valid_token = None
    for token in values:
        candidate = get_session_user(token)
        if candidate is not None:
            user = candidate
            valid_token = token
            break
    auth_mode = "cookie"
    if user is None and authorization and authorization.startswith("BBM-Reload "):
        user = get_session_user_by_reload_token(
            authorization[len("BBM-Reload "):], request.headers.get("user-agent")
        )
        auth_mode = "reload"
    if user is None:
        if not values and not authorization:
            raise HTTPException(
                401,
                f"Der Browser hat den Sitzungs-Cookie {SESSION_COOKIE_NAME!r} nicht gesendet. "
                "Die tabgebundene Reload-Sitzung ist ebenfalls nicht vorhanden. "
                "Öffentliche URL und BBM_SESSION_COOKIE_SECURE prüfen.",
            )
        raise HTTPException(401, "Die gespeicherte Sitzung ist ungültig oder abgelaufen. Bitte erneut anmelden.")
    if valid_token is not None:
        _set_session_cookie(response, request, valid_token)
    return {
        "status": "authenticated", "id": user.id, "username": user.username,
        "role": user.role, "must_change_password": user.must_change_password,
        "language": user.language, "appearance": user.appearance,
        "auth_mode": auth_mode,
    }


@app.put("/api/auth/preferences")
def auth_update_preferences(
    data: UserPreferencesIn, user: AuthUser = Depends(require_authenticated_user),
) -> dict:
    try:
        updated = update_user_preferences(user.id, data.language, data.appearance)
    except KeyError as exc:
        raise HTTPException(404, "Benutzer nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "status": "preferences-updated",
        "language": updated["language"],
        "appearance": updated["appearance"],
    }


@app.post("/api/auth/change-password")
def auth_change_password(
    data: PasswordChangeIn, request: Request, response: Response,
    user: AuthUser = Depends(require_authenticated_user),
) -> dict:
    try:
        change_own_password(
            user.id, data.current_password.get_secret_value(), data.new_password.get_secret_value(),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    _delete_session_cookie(response, request)
    return {"status": "password-changed", "reauthentication_required": True}


@app.get("/api/auth/2fa/status")
def auth_two_factor_status(user: AuthUser = Depends(require_authenticated_user)) -> dict:
    current = next((item for item in list_users() if int(item["id"]) == int(user.id)), None)
    return {
        "enabled": bool(current and current.get("two_factor_enabled")),
        "confirmed_at": current.get("two_factor_confirmed_at") if current else None,
    }


@app.post("/api/auth/2fa/setup")
def auth_two_factor_setup(data: TwoFactorSetupIn, user: AuthUser = Depends(require_authenticated_user)) -> dict:
    try:
        return begin_two_factor_setup(user.id, data.current_password.get_secret_value())
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/auth/2fa/confirm")
def auth_two_factor_confirm(data: TwoFactorConfirmIn, user: AuthUser = Depends(require_authenticated_user)) -> dict:
    try:
        confirm_two_factor_setup(user.id, data.code.get_secret_value())
        return {"status": "enabled", "reauthentication_required": True}
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/auth/2fa/disable")
def auth_two_factor_disable(data: TwoFactorDisableIn, user: AuthUser = Depends(require_authenticated_user)) -> dict:
    try:
        disable_two_factor(user.id, data.current_password.get_secret_value())
        return {"status": "disabled", "reauthentication_required": True}
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/auth/2fa/recovery-codes")
def auth_two_factor_recovery_codes(data: TwoFactorRecoveryRegenerateIn, user: AuthUser = Depends(require_authenticated_user)) -> dict:
    try:
        codes = regenerate_two_factor_recovery_codes(
            user.id, data.current_password.get_secret_value(), data.code.get_secret_value(),
        )
        return {"status": "regenerated", "recovery_codes": codes}
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/users", dependencies=admin_protected)
def users_list() -> list[dict]:
    return list_users()


@app.get("/api/users/security-status", dependencies=admin_protected)
def users_security_status() -> dict:
    status = security_status()
    status.update({
        "secret_database": status.get("database"),
        "master_key_note": "Der Master-Key bleibt als einziger externer Vertrauensanker unter /data/security/master.key.",
    })
    return status


@app.post("/api/users", status_code=201, dependencies=admin_protected)
def users_create(data: UserCreateIn) -> dict:
    try:
        return create_user(
            data.username, data.password.get_secret_value(), data.role, data.must_change_password,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/users/{user_id}")
def users_update(user_id: int, data: UserUpdateIn, current: AuthUser = Depends(require_admin_access)) -> dict:
    try:
        if user_id == current.id and (data.role != current.role or not data.enabled):
            raise ValueError("Die eigene Rolle und der eigene Aktivstatus können nicht geändert werden")
        return update_user(user_id, data.username, data.role, data.enabled)
    except KeyError as exc:
        raise HTTPException(404, "Benutzer nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/users/{user_id}/password", dependencies=admin_protected)
def users_reset_password(user_id: int, data: UserPasswordResetIn) -> dict:
    try:
        set_user_password(user_id, data.password.get_secret_value(), data.must_change_password)
        return {"status": "password-reset", "sessions_revoked": True}
    except KeyError as exc:
        raise HTTPException(404, "Benutzer nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/users/{user_id}/2fa/reset", dependencies=admin_protected)
def users_reset_two_factor(user_id: int) -> dict:
    try:
        user = reset_two_factor(user_id, event="two_factor_admin_reset")
        return {"status": "reset", "user": user}
    except KeyError as exc:
        raise HTTPException(404, "Benutzer nicht gefunden") from exc


@app.delete("/api/users/{user_id}", status_code=204)
def users_delete(user_id: int, current: AuthUser = Depends(require_admin_access)) -> Response:
    try:
        delete_security_user(user_id, current.id)
    except KeyError as exc:
        raise HTTPException(404, "Benutzer nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(status_code=204)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


def repository_sshd_listening() -> bool:
    """Return true only when the internal service emits a valid SSH banner."""
    try:
        with socket.create_connection(("127.0.0.1", 2222), timeout=2) as connection:
            connection.settimeout(2)
            banner = b""
            while len(banner) < 255 and b"\n" not in banner:
                chunk = connection.recv(255 - len(banner))
                if not chunk:
                    break
                banner += chunk
        return banner.startswith(b"SSH-")
    except OSError:
        return False


@app.get("/api/ready")
def ready():
    """Lightweight startup/readiness probe for Docker and update handling.

    Repository SSH diagnostics are intentionally not part of this endpoint.
    The supervised entrypoint terminates the container if sshd exits, while a
    transient SSH-banner probe must not trigger a rollback of an otherwise
    usable WebUI.
    """
    auth = authentication_readiness()
    is_ready = scheduler.running and auth["ready"]
    payload = {"status": "ready" if is_ready else "starting"}
    return payload if is_ready else JSONResponse(payload, status_code=503)


def manager_database_available() -> bool:
    """Return whether the primary manager database accepts a trivial query."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def authentication_store_available() -> bool:
    """Return whether the security store is readable and authentication-ready."""
    try:
        return bool(authentication_readiness().get("ready"))
    except Exception:
        return False


def component_health_payload() -> tuple[dict, bool]:
    database = manager_database_available()
    authentication = authentication_store_available()
    sshd = repository_sshd_listening()
    scheduler_running = bool(scheduler.running)
    # The visible/notification status evaluates every BBM core component.
    # HEALTH_REQUIRE_SSHD controls whether the public strict probe also fails
    # when the repository SSH service is unavailable.
    operational_healthy = database and authentication and scheduler_running and sshd
    strict_healthy = database and authentication and scheduler_running and (sshd or not HEALTH_REQUIRE_SSHD)
    return {
        "status": "ok" if operational_healthy else "degraded",
        "database": database,
        "authentication": authentication,
        "scheduler": scheduler_running,
        "repository_sshd": sshd,
        "repository_sshd_required": bool(HEALTH_REQUIRE_SSHD),
    }, strict_healthy


@app.get("/api/health/strict")
def strict_health():
    """Public strict probe without internal component disclosure."""
    payload, strict_healthy = component_health_payload()
    result = {"status": payload["status"]}
    return result if strict_healthy else JSONResponse(result, status_code=503)


@app.get("/api/system/health", dependencies=admin_protected)
def detailed_system_health():
    """Administrator-only component health details."""
    payload, strict_healthy = component_health_payload()
    return payload if strict_healthy else JSONResponse(payload, status_code=503)


@app.get("/api/system/database-maintenance", dependencies=admin_protected)
def database_maintenance_status() -> dict:
    return database_cleanup_preview()


@app.post("/api/system/database-maintenance", dependencies=admin_protected)
def database_maintenance_run(data: DatabaseCleanupIn) -> dict:
    with SessionLocal() as db:
        active = int(db.scalar(select(func.count()).select_from(Run).where(Run.status.in_(["queued", "running"]))) or 0)
    if active or current_manager_backup_task(include_last=False):
        raise HTTPException(409, "Datenbankbereinigung ist nur ohne laufende oder wartende Ausführungen und ohne Manager-/Cache-Backup möglich")
    try:
        return cleanup_manager_database(create_safety_copy=data.create_safety_copy, vacuum=data.vacuum)
    except (OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/dashboard", dependencies=protected)
def dashboard() -> dict:
    settings = load_settings()
    with SessionLocal() as db:
        counts = {
            "hosts": db.scalar(select(func.count()).select_from(Host)),
            "repositories": db.scalar(select(func.count()).select_from(Repository)),
            "jobs": db.scalar(select(func.count()).select_from(Job)),
            "running": db.scalar(select(func.count()).select_from(Run).where(Run.status == "running")),
            "waiting": db.scalar(select(func.count()).select_from(Run).where(Run.status == "queued")),
            "failed": db.scalar(select(func.count()).select_from(Run).where(Run.status == "failed")),
        }
        counts["repository_size_bytes"] = db.scalar(
            select(func.coalesce(func.sum(Repository.size_bytes), 0))
        )
        runs = db.scalars(
            select(Run).options(joinedload(Run.job)).order_by(Run.id.desc()).limit(settings.dashboard_recent_runs_limit)
        ).all()
        protected_run_ids = retained_run_ids_for_existing_jobs(db) if runs else set()
        jobs = list(db.scalars(
            select(Job).options(joinedload(Job.host), joinedload(Job.repository)).order_by(Job.id)
        ))
        assignments = schedule_assignments(db)
        latest_backup_ids = (
            select(Run.job_id, func.max(Run.id).label("run_id"))
            .where(Run.action == "backup", Run.job_id.is_not(None))
            .group_by(Run.job_id)
            .subquery()
        )
        latest_runs = {
            row.job_id: row
            for row in db.scalars(
                select(Run).join(latest_backup_ids, Run.id == latest_backup_ids.c.run_id)
            )
            if row.job_id is not None
        }
        latest_successful_backup_ids = (
            select(Run.job_id, func.max(Run.id).label("run_id"))
            .where(
                Run.action == "backup",
                Run.job_id.is_not(None),
                Run.status.in_(["success", "warning"]),
            )
            .group_by(Run.job_id)
            .subquery()
        )
        latest_successful_runs = {
            row.job_id: row
            for row in db.scalars(
                select(Run).join(latest_successful_backup_ids, Run.id == latest_successful_backup_ids.c.run_id)
            )
            if row.job_id is not None
        }
        ready_access_pairs = set(db.execute(
            select(HostRepositoryAccess.host_id, HostRepositoryAccess.repository_id)
            .join(Repository, Repository.id == HostRepositoryAccess.repository_id)
            .where(HostRepositoryAccess.public_key.is_not(None), Repository.enabled.is_(True))
        ).all())
        dashboard_jobs = []
        for job in jobs:
            schedule_names = [row.name for row in assignments.get(job.id, [])]
            access_ready = (not bool(job.repository.storage_path)) or ((job.host_id, job.repository_id) in ready_access_pairs)
            dashboard_jobs.append({
                "id": job.id,
                "name": job.name,
                "enabled": job.enabled,
                "host_id": job.host_id,
                "host_name": job.host.name,
                "host_enabled": job.host.enabled,
                "repository_id": job.repository_id,
                "repository_name": job.repository.name,
                "repository_enabled": bool(job.repository.enabled),
                "repository_managed": bool(job.repository.storage_path),
                "repository_access_ready": access_ready,
                "source_paths": json.loads(job.source_paths_json or "[]"),
                "source_size_bytes": job.source_size_bytes,
                "source_file_count": job.source_file_count,
                "source_stats_checked_at": iso_utc(job.source_stats_checked_at),
                "source_stats_origin": job.source_stats_origin,
                "schedule_names": schedule_names,
                "schedule_mode": "scheduled" if schedule_names else "manual",
                "last_run": run_json(latest_runs[job.id], include_details=False) if job.id in latest_runs else None,
                "last_successful_backup": (
                    run_json(latest_successful_runs[job.id], include_details=False)
                    if job.id in latest_successful_runs else None
                ),
            })
        return {
            "counts": counts,
            "runs": [run_json(run, include_details=False, retention_protected=run.id in protected_run_ids) for run in runs],
            "jobs": dashboard_jobs,
        }


@app.get("/api/system", dependencies=protected)
def system_info() -> dict:
    try:
        public_key = controller_public_key()
    except ValueError:
        public_key = None
    return {
        "app_version": APP_VERSION,
        "release_date": APP_RELEASE_DATE,
        "update_status": update_status_payload(),
        "controller_public_key": public_key,
        "repository_endpoint": f"{REPOSITORY_PUBLIC_HOST}:{REPOSITORY_SSH_PORT}",
        "backup_directory": str(BACKUP_DIR),
        "timezone": APP_TIMEZONE_NAME,
        "session_ttl_seconds": SESSION_TTL_SECONDS,
    }


@app.post("/api/system/controller-key/rotate", dependencies=admin_protected)
def rotate_system_controller_key(data: ControllerKeyRotateIn) -> dict:
    with SessionLocal() as db:
        active = db.scalar(
            select(func.count()).select_from(Run).where(Run.status.in_(["queued", "running"]))
        ) or 0
    if active:
        raise HTTPException(409, "Controller-Schlüssel kann während laufender oder wartender Ausführungen nicht erneuert werden")
    try:
        public_key = rotate_controller_key()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "controller_public_key": public_key,
        "warning": "Der neue öffentliche Schlüssel muss auf allen Geräten hinterlegt werden.",
    }


@app.get("/api/header-network", dependencies=protected)
def get_header_network() -> dict:
    settings = load_settings()
    payload = {
        "enabled": bool(settings.header_network_enabled),
        "source": settings.header_network_source,
        "host_id": settings.header_network_host_id,
        "host_name": "",
        "interfaces": [],
        "interval_seconds": int(settings.header_network_interval_seconds),
        "error": "",
    }
    if not settings.header_network_enabled:
        return payload
    host = None
    sample_key = "manager"
    if settings.header_network_source == "host":
        if settings.header_network_host_id is None:
            payload["error"] = "Kein Gerät als Quelle für die Kopfzeilen-Netzwerkanzeige ausgewählt"
            return payload
        with SessionLocal() as db:
            host = db.get(Host, int(settings.header_network_host_id))
            if host is None:
                payload["error"] = "Das ausgewählte Gerät existiert nicht mehr"
                return payload
            if not host.enabled:
                payload["host_name"] = host.name
                payload["error"] = "Das ausgewählte Gerät ist deaktiviert"
                return payload
            # Detach the small host object before the SSH subprocess runs.
            db.expunge(host)
        payload["host_name"] = host.name
        sample_key = f"host:{host.id}"
    else:
        payload["host_name"] = "BBM-Hostsystem"
    try:
        payload["interfaces"] = sample_header_network_interfaces(
            sample_key=sample_key,
            host=host,
            selected=settings.header_network_interfaces,
            maximum=settings.header_network_max_interfaces,
            minimum_interval=max(0.75, min(2.0, settings.header_network_interval_seconds / 2.0)),
        )
    except RuntimeError as exc:
        payload["error"] = str(exc)[:1000]
    return payload


@app.get("/api/header-network/interfaces", dependencies=admin_protected)
def get_header_network_interfaces(source: str = "manager", host_id: int | None = None) -> dict:
    if source not in {"manager", "host"}:
        raise HTTPException(400, "Ungültige Netzwerkquelle")
    host = None
    label = "BBM-Hostsystem"
    if source == "host":
        if host_id is None:
            raise HTTPException(400, "Gerät fehlt")
        with SessionLocal() as db:
            host = db.get(Host, int(host_id))
            if host is None:
                raise HTTPException(404, "Gerät nicht gefunden")
            if not host.enabled:
                raise HTTPException(409, "Gerät ist deaktiviert")
            label = host.name
            db.expunge(host)
    try:
        interfaces = discover_header_network_interfaces(host=host)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"source": source, "host_id": host_id, "host_name": label, "interfaces": interfaces}


@app.get("/api/settings", response_model=SettingsIn, dependencies=protected)
def get_settings() -> SettingsIn:
    return load_settings()


@app.put("/api/settings", response_model=SettingsIn, dependencies=admin_protected)
def update_settings(data: SettingsIn) -> SettingsIn:
    if int(data.session_idle_timeout_seconds) > int(SESSION_TTL_SECONDS):
        raise HTTPException(
            400,
            f"Session-Timeout bei Inaktivität darf die maximale Sitzungsdauer von {SESSION_TTL_SECONDS // 60} Minuten nicht überschreiten",
        )
    previous = load_settings()
    saved = save_settings(data)
    cleanup_run_history()
    if (
        previous.update_check_enabled != saved.update_check_enabled
        or previous.update_check_interval_hours != saved.update_check_interval_hours
    ):
        sync_update_check_job(immediate=saved.update_check_enabled)
    return saved


@app.get("/api/update-status", dependencies=protected)
def get_update_status() -> dict:
    return update_status_payload()


@app.post("/api/update-status/check", dependencies=admin_protected)
async def force_update_check() -> dict:
    settings = load_settings()
    if not settings.update_check_enabled:
        raise HTTPException(409, "Updateprüfung ist deaktiviert")
    status = await asyncio.to_thread(check_latest_release, APP_VERSION)
    status["enabled"] = True
    status["interval_hours"] = settings.update_check_interval_hours
    return status


@app.get("/api/notifications/settings", response_model=NotificationSettingsOut, dependencies=admin_protected)
def get_notification_settings() -> NotificationSettingsOut:
    return notification_settings_out()


@app.put("/api/notifications/settings", response_model=NotificationSettingsOut, dependencies=admin_protected)
def update_notification_settings(data: NotificationSettingsInput) -> NotificationSettingsOut:
    try:
        return save_notification_settings(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/notifications/test", dependencies=admin_protected)
async def test_notification_channel(data: NotificationTestIn) -> dict:
    try:
        results = await asyncio.to_thread(send_test_notification, data.channel)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not results:
        raise HTTPException(400, "Kein Benachrichtigungskanal wurde ausgeführt")
    result = results[0]
    if result["status"] != "success":
        raise HTTPException(502, result["detail"])
    return result


@app.get("/api/notifications/deliveries", dependencies=admin_protected)
def notification_deliveries(limit: int = 100) -> list[dict]:
    return [
        {
            "id": row.id, "run_id": row.run_id, "event_type": row.event_type,
            "channel": row.channel, "status": row.status, "title": row.title,
            "detail": row.detail, "created_at": iso_utc(row.created_at),
        }
        for row in list_deliveries(limit)
    ]


@app.delete("/api/notifications/deliveries", dependencies=admin_protected)
def delete_notification_deliveries() -> dict:
    return {"deleted": clear_deliveries()}


@app.get("/api/system/release-notes", dependencies=protected)
def release_notes(language: str = "en") -> dict:
    german = language == "de"
    filename = "RELEASE_NOTES.de.md" if german else "RELEASE_NOTES.md"
    path = Path(__file__).parent.parent / filename
    return {
        "version": APP_VERSION,
        "language": "de" if german else "en",
        "content": path.read_text(encoding="utf-8") if path.is_file() else "",
    }


def _group_external_repository_filesystems(rows: list[dict]) -> list[dict]:
    """Merge external repositories that resolve to the same remote filesystem.

    External rows use a display path composed of SSH identity plus the mount
    returned by ``df``. Repositories on the same Storage Box account and mount
    therefore share one diagnostics row, matching the managed-repository view.
    """
    grouped: dict[str, dict] = {}
    for row in rows:
        if not row:
            continue
        key = str(row.get("path") or "")
        current = grouped.get(key)
        if current is None:
            grouped[key] = {**row, "repositories": list(row.get("repositories") or [])}
            continue
        current["repositories"].extend(row.get("repositories") or [])
        current["guard_blocked"] = bool(current.get("guard_blocked") or row.get("guard_blocked"))
        for state in ("running", "queued"):
            current[f"{state}_runs"] = int(current.get(f"{state}_runs") or 0) + int(row.get(f"{state}_runs") or 0)
            current.setdefault(f"{state}_repositories", []).extend(row.get(f"{state}_repositories") or [])

        # Prefer the newest successful measurement when multiple repository
        # paths on one remote filesystem were probed independently.
        row_known = all(row.get(name) is not None for name in ("total", "used", "free", "percent"))
        current_known = all(current.get(name) is not None for name in ("total", "used", "free", "percent"))
        row_checked = row.get("checked_at")
        current_checked = current.get("checked_at")
        newer = bool(row_checked and (not current_checked or row_checked > current_checked))
        if row_known and (not current_known or newer):
            for name in ("total", "used", "free", "percent", "checked_at"):
                current[name] = row.get(name)

        errors = [value for value in (current.get("error"), row.get("error")) if value]
        current["error"] = " | ".join(dict.fromkeys(errors)) if errors else None

    for row in grouped.values():
        row["repositories"] = sorted(row["repositories"], key=lambda item: str(item.get("name") or ""))
    return sorted(grouped.values(), key=lambda item: str(item.get("path") or ""))


@app.get("/api/system/diagnostics", dependencies=admin_protected)
async def system_diagnostics() -> dict:
    try:
        borg_version = subprocess.run(
            ["borg", "--version"], capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip() or "nicht verfügbar"
    except (OSError, subprocess.TimeoutExpired):
        borg_version = "nicht verfügbar"
    settings = load_settings()
    with SessionLocal() as db:
        managed_repositories = list(db.scalars(
            select(Repository).where(
                Repository.storage_path.is_not(None), Repository.enabled.is_(True)
            ).order_by(Repository.name)
        ))
        external_repositories = list(db.scalars(
            select(Repository).where(
                Repository.storage_path.is_(None), Repository.enabled.is_(True)
            ).order_by(Repository.name)
        ))
    filesystems = repository_storage_filesystems(managed_repositories, REPOSITORY_ROOT, settings)

    # Show the real queue occupancy beside each effective mount limit.  This is
    # intentionally derived from the persisted run state so an operator can see
    # immediately whether a mount is at capacity or whether a queued run is
    # blocked by another layer such as repository or schedule exclusivity.
    filesystem_by_path = {str(item.get("path")): item for item in filesystems}
    managed_mounts = [Path(path) for path in filesystem_by_path]
    for item in filesystems:
        item["running_runs"] = 0
        item["queued_runs"] = 0
        item["running_repositories"] = []
        item["queued_repositories"] = []
    with SessionLocal() as db:
        active_runs = list(db.scalars(
            select(Run)
            .options(joinedload(Run.repository))
            .where(Run.status.in_(["queued", "running"]), Run.action != "source-stats")
            .order_by(Run.id)
        ))
    for run in active_runs:
        repository = run.repository
        if not repository or not repository.storage_path:
            continue
        mount = repository_mount_path(repository.storage_path, REPOSITORY_ROOT, mounts=managed_mounts)
        item = filesystem_by_path.get(str(mount)) if mount is not None else None
        if item is None:
            continue
        key = "running" if run.status == "running" else "queued"
        item[f"{key}_runs"] += 1
        item[f"{key}_repositories"].append({
            "run_id": int(run.id),
            "repository_id": int(repository.id),
            "repository": str(repository.name),
            "action": str(run.action),
        })

    async def external_filesystem_row(repository: Repository) -> dict:
        try:
            usage = await refresh_external_repository_storage(repository.id)
            error = None
        except (LookupError, ValueError) as exc:
            usage = None
            error = str(exc)
        with SessionLocal() as db:
            stored = db.get(Repository, repository.id)
            if not stored:
                return {}
            enabled, threshold, source = effective_storage_guard(stored, settings)
            total = stored.external_storage_total_bytes
            used = stored.external_storage_used_bytes
            free = stored.external_storage_free_bytes
            percent = stored.external_storage_usage_percent
            checked_at = stored.external_storage_checked_at
            stored_error = stored.external_storage_error or error
            target = storage_probe_target_from_location(stored.location)
            remote = (
                f"{target.username}@{target.host}:{target.port}" if target else stored.location
            )
            path = stored.external_storage_path or (target.repository_path if target else stored.location)
            parallel_identity = external_filesystem_parallel_identity(
                stored.location, stored.external_storage_path
            )
            blocked = bool(enabled and percent is not None and float(percent) >= threshold)
            return {
                "path": parallel_identity[1] if parallel_identity else f"{remote} · {path}",
                "parallel_key": parallel_identity[0] if parallel_identity else None,
                "total": total, "used": used, "free": free, "percent": percent,
                "repositories": [{
                    "id": int(stored.id), "name": str(stored.name), "path": str(stored.location),
                    "guard_enabled": enabled, "guard_threshold_percent": threshold,
                    "guard_source": source, "guard_blocked": blocked, "external": True,
                }],
                "guard_blocked": blocked, "external": True,
                "parallel_limit": int(
                    (settings.external_storage_parallel_limits or {}).get(parallel_identity[0], 0)
                ) if parallel_identity else None,
                "running_runs": 0, "queued_runs": 0,
                "running_repositories": [], "queued_repositories": [],
                "checked_at": checked_at, "error": stored_error,
            }

    if external_repositories:
        external_rows = await asyncio.gather(*(external_filesystem_row(repo) for repo in external_repositories))
        grouped_external = _group_external_repository_filesystems([row for row in external_rows if row])
        external_by_key = {
            str(item.get("parallel_key")): item
            for item in grouped_external if item.get("parallel_key")
        }
        for run in active_runs:
            repository = run.repository
            if not repository or repository.storage_path:
                continue
            identity = external_filesystem_parallel_identity(
                repository.location, repository.external_storage_path
            )
            item = external_by_key.get(identity[0]) if identity else None
            if item is None:
                continue
            state_key = "running" if run.status == "running" else "queued"
            item[f"{state_key}_runs"] = int(item.get(f"{state_key}_runs") or 0) + 1
            item.setdefault(f"{state_key}_repositories", []).append({
                "run_id": int(run.id),
                "repository_id": int(repository.id),
                "repository": str(repository.name),
                "action": str(run.action),
            })
        filesystems.extend(grouped_external)
    storage = next((item for item in filesystems if Path(item["path"]) == REPOSITORY_ROOT.resolve()), None)
    if storage is not None:
        storage = {
            **storage,
            "guard_enabled": settings.storage_guard_enabled,
            "guard_threshold_percent": settings.storage_guard_threshold_percent,
            "guard_blocked": settings.storage_guard_enabled
            and float(storage["percent"]) >= settings.storage_guard_threshold_percent,
        }
    def read_diagnostic_log(path: Path, limit: int = 20_000) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")[-limit:] if path.is_file() else ""
        except OSError:
            return ""

    borg_log_path = DATA_DIR / "logs" / "borg-serve.log"
    sshd_log_path = DATA_DIR / "logs" / "sshd.log"
    server_log = read_diagnostic_log(borg_log_path)
    sshd_log = read_diagnostic_log(sshd_log_path)
    debug_log = read_diagnostic_log(DEBUG_LOG_PATH, 40_000)
    access_log = read_diagnostic_log(ACCESS_LOG_PATH, 40_000)
    checks = {}
    # The production API already runs as the unprivileged ``borg`` user.
    # Only a root caller may use runuser; manager_borg_argv therefore executes
    # these access checks directly in production and retains root-side
    # support for privileged development and maintenance contexts.
    for name, parts in {
        "repository_readable_as_borg": ["test", "-r", str(REPOSITORY_ROOT)],
        "repository_writable_as_borg": ["test", "-w", str(REPOSITORY_ROOT)],
        "repository_searchable_as_borg": ["test", "-x", str(REPOSITORY_ROOT)],
        "log_writable_as_borg": ["test", "-w", "/data/logs"],
        "serve_wrapper_executable": ["test", "-x", "/usr/local/bin/bbm-borg-serve"],
        "authorized_keys_readable_as_borg": ["test", "-r", str(REPOSITORY_AUTHORIZED_KEYS_PATH)],
    }.items():
        try:
            checks[name] = subprocess.run(
                manager_borg_argv(parts), timeout=5, check=False,
            ).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            checks[name] = False
    # sshd -t needs access to the root-owned host private key. The root
    # entrypoint validates the configuration before starting sshd and records
    # that result in a read-only runtime marker for the unprivileged API.
    sshd_config_marker = RUNTIME_SECRET_DIR / "sshd-config.valid"
    checks["sshd_configuration_valid"] = (
        sshd_config_marker.is_file()
        and sshd_config_marker.read_text(encoding="utf-8", errors="replace").strip() == "ok"
    )
    authorized_keys = REPOSITORY_AUTHORIZED_KEYS_PATH
    authorized_lines = [
        line.strip() for line in authorized_keys.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ] if authorized_keys.is_file() else []
    checks["repository_sshd_listening"] = repository_sshd_listening()
    checks["managed_repositories_shared_across_hosts"] = 0
    with SessionLocal() as db:
        access_rows = list(db.scalars(
            select(HostRepositoryAccess)
            .options(joinedload(HostRepositoryAccess.host), joinedload(HostRepositoryAccess.repository))
            .order_by(HostRepositoryAccess.host_id, HostRepositoryAccess.repository_id)
        ))
        checks.update(repository_access_diagnostic(access_rows, authorized_lines))
        shared = db.execute(
            select(Job.repository_id, func.count(func.distinct(Job.host_id)))
            .join(Repository, Repository.id == Job.repository_id)
            .where(Repository.storage_path.is_not(None), Repository.enabled.is_(True))
            .group_by(Job.repository_id)
            .having(func.count(func.distinct(Job.host_id)) > 1)
        ).all()
        checks["managed_repositories_shared_across_hosts"] = len(shared)
    return {
        "borg_version": borg_version, "repository_storage": storage,
        "global_parallel_limit": int(settings.max_parallel_runs or 0),
        "source_stats_parallel_limit": int(settings.source_stats_parallel_limit or 1),
        "repository_storage_filesystems": filesystems,
        "repository_server_checks": checks, "borg_serve_log": server_log,
        "sshd_log": sshd_log, "debug_log": debug_log, "access_log": access_log,
    }


@app.post("/api/hosts/scan-key", dependencies=admin_protected)
async def scan_host(data: HostScanIn) -> dict:
    try:
        line, fingerprint = await scan_host_key(data.address, data.port)
        return {"host_key": line, "fingerprint": fingerprint}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/hosts", response_model=list[HostOut], dependencies=protected)
def list_hosts():
    with SessionLocal() as db:
        return [host_out(x) for x in db.scalars(select(Host).order_by(Host.name))]


@app.post("/api/hosts", response_model=HostOut, status_code=201, dependencies=admin_protected)
def create_host(data: HostIn):
    with SessionLocal() as db:
        row = Host(**data.model_dump())
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:
            raise HTTPException(409, "Host name already exists") from exc
        if row.host_key:
            trust_host_key(row.host_key)
        return host_out(row)


def _apply_host_enabled_state(db, row: Host, enabled: bool) -> int:
    """Apply the host state and cascade disabling to all related backup jobs.

    Re-enabling a host intentionally does not re-enable jobs: an administrator
    must make that scheduling decision explicitly so backups cannot resume
    unexpectedly after maintenance or an incident.
    """
    disabled_jobs = 0
    if not enabled:
        active = db.scalar(
            select(func.count()).select_from(Run).join(Job, Run.job_id == Job.id).where(
                Job.host_id == row.id, Run.status.in_(["queued", "running"])
            )
        ) or 0
        if active:
            raise HTTPException(409, "Gerät kann während laufender oder wartender Ausführungen nicht deaktiviert werden")
        for job in db.scalars(select(Job).where(Job.host_id == row.id, Job.enabled.is_(True))):
            job.enabled = False
            disabled_jobs += 1
    row.enabled = enabled
    return disabled_jobs


@app.put("/api/hosts/{row_id}", response_model=HostOut, dependencies=admin_protected)
def update_host(row_id: int, data: HostIn):
    with SessionLocal() as db:
        row = db.get(Host, row_id)
        if not row:
            raise HTTPException(404, "Host not found")
        connection_changed = any(
            getattr(row, key) != getattr(data, key)
            for key in ("address", "port", "username")
        )
        enabled_changed = row.enabled != data.enabled
        for key, value in data.model_dump(exclude={"enabled"}).items():
            setattr(row, key, value)
        _apply_host_enabled_state(db, row, data.enabled)
        if connection_changed:
            row.repository_ready = False
        try:
            db.commit()
        except IntegrityError as exc:
            raise HTTPException(409, "Host name already exists") from exc
        if row.host_key:
            trust_host_key(row.host_key)
        result = host_out(row)
    if connection_changed:
        revoke_host_repository_access(row_id)
    else:
        sync_repository_access_assignments()
    if enabled_changed or not data.enabled:
        sync_schedules()
    with SessionLocal() as db:
        current = db.get(Host, row_id)
        return host_out(current) if current else result


@app.post("/api/hosts/{row_id}/enabled", response_model=HostOut, dependencies=admin_protected)
def set_host_enabled(row_id: int, data: EnabledStateIn):
    with SessionLocal() as db:
        row = db.get(Host, row_id)
        if not row:
            raise HTTPException(404, "Host not found")
        _apply_host_enabled_state(db, row, data.enabled)
        db.commit()
    sync_repository_access_assignments()
    sync_schedules()
    with SessionLocal() as db:
        current = db.get(Host, row_id)
        if not current:
            raise HTTPException(404, "Host not found")
        return host_out(current)


@app.delete("/api/hosts/{row_id}", status_code=204, dependencies=admin_protected)
def delete_host(row_id: int):
    with SessionLocal() as db:
        row = db.get(Host, row_id)
        if not row:
            raise HTTPException(404, "Host not found")
        if db.scalar(select(func.count()).select_from(Job).where(Job.host_id == row_id)):
            raise HTTPException(409, "Host is still used by jobs")
        db.execute(delete(HostRepositoryAccess).where(HostRepositoryAccess.host_id == row_id))
        _drop_host_schedule_references(db, row_id)
        db.delete(row)
        db.commit()
    delete_host_ssh_actions_for_host(row_id)
    sync_repository_access_assignments(); sync_schedules()
    return Response(status_code=204)


@app.get("/api/host-ssh-actions", response_model=list[HostSshActionOut], dependencies=admin_protected)
def list_host_ssh_actions():
    return list_security_host_ssh_actions()


@app.post("/api/host-ssh-actions", response_model=HostSshActionOut, status_code=201, dependencies=admin_protected)
def create_host_ssh_action(data: HostSshActionIn):
    with SessionLocal() as db:
        host = db.get(Host, data.host_id)
        if not host:
            raise HTTPException(404, "Host not found")
    try:
        return create_security_host_ssh_action(**data.model_dump())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Für dieses Gerät existiert bereits eine SSH-Aktion mit diesem Namen") from exc


@app.put("/api/host-ssh-actions/{action_id}", response_model=HostSshActionOut, dependencies=admin_protected)
def update_host_ssh_action(action_id: int, data: HostSshActionIn):
    with SessionLocal() as db:
        if not db.get(Host, data.host_id):
            raise HTTPException(404, "Host not found")
    try:
        row = update_security_host_ssh_action(action_id, **data.model_dump())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Für dieses Gerät existiert bereits eine SSH-Aktion mit diesem Namen") from exc
    if row is None:
        raise HTTPException(404, "SSH action not found")
    return row


@app.delete("/api/host-ssh-actions/{action_id}", status_code=204, dependencies=admin_protected)
def delete_host_ssh_action(action_id: int):
    if not delete_security_host_ssh_action(action_id):
        raise HTTPException(404, "SSH action not found")
    return Response(status_code=204)


@app.post("/api/host-ssh-actions/{action_id}/run", status_code=202, dependencies=admin_protected)
async def run_host_ssh_action(action_id: int):
    try:
        return {"run_id": queue_host_ssh_action(action_id)}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/hosts/{host_id}/check-version", dependencies=admin_protected)
async def check_host_version(host_id: int) -> dict:
    with SessionLocal() as db:
        host = db.get(Host, host_id)
        if not host:
            raise HTTPException(404, "Host not found")
        command = host_version_command(host)
    code, output, error = await execute_interactive(None, command)
    combined = output + ("\n" if output and error else "") + error
    version = parse_borg_version(combined)
    compatibility = classify_borg_version(version)
    with SessionLocal() as db:
        host = db.get(Host, host_id)
        if host and version:
            host.borg_version = version
            host.borg_version_status = compatibility.level
            host.borg_checked_at = datetime.now(timezone.utc)
            db.commit()
    return {
        "exit_code": code, "output": combined,
        "version": compatibility.version, "supported": compatibility.supported,
        "level": compatibility.level, "title": compatibility.title, "message": compatibility.message,
    }


@app.post("/api/jobs/{job_id}/bootstrap-repository", dependencies=admin_protected)
async def bootstrap_job_repository(job_id: int) -> dict:
    with SessionLocal() as db:
        job = db.scalar(
            select(Job)
            .options(joinedload(Job.repository))
            .where(Job.id == job_id)
        )
        if not job:
            raise HTTPException(404, "Job not found")
        if not job.repository.storage_path:
            raise HTTPException(400, "External repositories do not use manager-provisioned repository access")
        host_id = job.host_id
        repository_id = job.repository_id
    try:
        keys = await bootstrap_host_repository(host_id, [repository_id])
        return {
            "status": "ready",
            "job_id": job_id,
            "host_id": host_id,
            "repository_id": repository_id,
            "repository_keys": sorted(keys),
            "configured": len(keys),
        }
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/repositories", response_model=list[RepositoryOut], dependencies=protected)
def list_repositories():
    mounts = mounted_filesystems_below(REPOSITORY_ROOT)
    with SessionLocal() as db:
        return [repo_out(x, mounts=mounts) for x in db.scalars(select(Repository).order_by(Repository.name))]


def _safe_repository_browser_path(relative_path: str) -> tuple[Path, Path]:
    root = REPOSITORY_ROOT.resolve()
    raw = (relative_path or "").strip().replace("\\", "/").strip("/")
    if any(part in {"", ".", ".."} for part in raw.split("/") if raw) or "\x00" in raw:
        raise HTTPException(400, "Ungültiger Repository-Browserpfad")
    candidate = root
    for part in raw.split("/") if raw else []:
        candidate = candidate / part
        if candidate.is_symlink():
            raise HTTPException(400, "Symbolische Links werden im Repository-Browser nicht geöffnet")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Repository-Browserpfad ist nicht vorhanden") from exc
    except OSError as exc:
        raise HTTPException(400, f"Repository-Browserpfad kann nicht geöffnet werden: {exc}") from exc
    if resolved != root and root not in resolved.parents:
        raise HTTPException(400, "Repository-Browserpfad liegt außerhalb von /repositories")
    if not resolved.is_dir():
        raise HTTPException(400, "Repository-Browserpfad ist kein Verzeichnis")
    return root, resolved


@app.get("/api/repositories/browse", dependencies=admin_protected)
def browse_repository_directories(path: str = "") -> dict:
    root, current = _safe_repository_browser_path(path)
    try:
        children = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
    except OSError as exc:
        raise HTTPException(400, f"Repository-Verzeichnis kann nicht gelesen werden: {exc}") from exc
    entries = []
    truncated = len(children) > 500
    for child in children[:500]:
        try:
            if child.is_symlink():
                kind = "symlink"
                is_directory = False
                is_repository = False
            else:
                is_directory = child.is_dir()
                kind = "directory" if is_directory else "file"
                is_repository = is_directory and (child / "config").is_file()
            relative = child.relative_to(root).as_posix()
            stat_result = child.stat(follow_symlinks=False)
            entries.append({
                "name": child.name, "path": relative, "type": kind,
                "is_directory": is_directory, "is_repository": is_repository,
                "selectable": is_repository,
                "size": stat_result.st_size if not is_directory else None,
                "modified_at": datetime.fromtimestamp(stat_result.st_mtime, timezone.utc).isoformat(),
            })
        except OSError:
            continue
    relative_current = "" if current == root else current.relative_to(root).as_posix()
    parent = None if current == root else ("" if current.parent == root else current.parent.relative_to(root).as_posix())
    try:
        current_is_repository = current != root and (current / "config").is_file()
    except OSError:
        current_is_repository = False
    return {
        "root": str(root), "path": relative_current, "parent": parent,
        "current_is_repository": current_is_repository,
        "current_selectable": current_is_repository,
        "entries": entries, "truncated": truncated,
    }


@app.get("/api/repositories/discover", dependencies=admin_protected)
def discover_repositories() -> list[dict]:
    try:
        return managed_repository_candidates()
    except OSError as exc:
        raise HTTPException(400, f"Repository directory cannot be scanned: {exc}") from exc


@app.post("/api/repositories/import", response_model=RepositoryOut, status_code=201, dependencies=admin_protected)
async def import_repository(data: RepositoryImportIn):
    root, storage_path = _safe_repository_browser_path(data.directory_name)
    if storage_path == root or not (storage_path / "config").is_file():
        raise HTTPException(400, "Selected directory is not a Borg repository below the managed storage root")
    relative_path = storage_path.relative_to(root).as_posix()
    secret = data.passphrase.get_secret_value() if data.passphrase else None
    keyfile = data.keyfile.get_secret_value() if data.keyfile else None
    with SessionLocal() as db:
        if db.scalar(select(Repository.id).where(Repository.storage_path == str(storage_path))):
            raise HTTPException(409, "Repository directory is already registered")
        row = Repository(
            name=data.name,
            enabled=data.enabled,
            location=managed_repository_location(relative_path),
            encryption_mode=data.encryption_mode,
            storage_path=str(storage_path),
            initialized=False,
            storage_guard_enabled=data.storage_guard_enabled,
            storage_guard_threshold_percent=data.storage_guard_threshold_percent,
            extra_env_json="{}",
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:
            raise HTTPException(409, "Repository name already exists") from exc
        repository_id = row.id
    set_repository_secret(repository_id, "passphrase", secret)
    set_repository_secret(repository_id, "keyfile", keyfile)

    key_path: Path | None = None
    try:
        with SessionLocal() as db:
            row = db.get(Repository, repository_id)
            if not row:
                raise ValueError("Repository registration disappeared")
            if keyfile is not None:
                key_path = Path(repository_keyfile_path(row))
                key_path.parent.mkdir(parents=True, exist_ok=True)
                key_path.write_text(keyfile, encoding="utf-8")
                os.chmod(key_path, 0o600)
                try:
                    os.chown(
                        key_path,
                        int(os.getenv("BBM_BORG_UID", "1000")),
                        int(os.getenv("BBM_BORG_GID", "1000")),
                    )
                except (OSError, ValueError):
                    pass
            command = repository_validation_command(row)
        code, output, error = await execute_interactive(repository_id, command)
        if code not in {0, 1}:
            summary, _details = compact_repository_error_with_debug(
                "Existing repository import returned technical Borg output",
                output, error, code,
            )
            raise ValueError(summary)
        with SessionLocal() as db:
            row = db.get(Repository, repository_id)
            if not row:
                raise ValueError("Repository registration disappeared")
            row.initialized = True
            db.commit()
            return repo_out(row)
    except (OSError, ValueError) as exc:
        with SessionLocal() as db:
            row = db.get(Repository, repository_id)
            if row:
                db.delete(row)
                db.commit()
        delete_repository_secrets(repository_id)
        raise HTTPException(400, f"Existing repository could not be opened: {exc}") from exc
    except Exception as exc:
        with SessionLocal() as db:
            row = db.get(Repository, repository_id)
            if row:
                db.delete(row)
                db.commit()
        delete_repository_secrets(repository_id)
        error_id = log_unexpected_exception(
            "Existing repository import failed unexpectedly",
            exc=exc,
            method="POST",
            path="/api/repositories/import",
            logger_name="bbm.http",
        )
        raise HTTPException(500, public_error_message(error_id)) from None
    finally:
        if key_path:
            key_path.unlink(missing_ok=True)


@app.post("/api/repositories/{repository_id}/refresh-size", dependencies=admin_protected)
async def refresh_size(repository_id: int) -> dict:
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if not repository:
            raise HTTPException(404, "Repository not found")
        if not repository.enabled:
            raise HTTPException(409, "Repository ist deaktiviert")
        managed = bool(repository.storage_path)
        initialized = repository.initialized
        if not initialized:
            raise HTTPException(400, "Repository zuerst erfolgreich prüfen")
        try:
            command = repository_size_command(repository)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    filesystem_size = None
    external_storage = None
    if managed:
        try:
            filesystem_size = managed_repository_filesystem_size(repository_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
    else:
        try:
            external_storage = await refresh_external_repository_storage(repository_id)
        except (LookupError, ValueError):
            # Keep Borg statistics available even when the external account does
            # not permit a shell/df command. The repository row stores the
            # probe error and the WebUI explains that filesystem monitoring is
            # unavailable for this target.
            external_storage = None

    code, output, error = await execute_interactive(repository_id, command)
    if code not in {0, 1}:
        summary, details = compact_repository_error_with_debug(
            f"Repository size refresh for repository {repository_id} returned technical Borg output",
            output, error, code,
        )
        with SessionLocal() as db:
            stored = db.get(Repository, repository_id)
            if stored:
                stored.validation_error = summary
                stored.validation_details = details
                if not managed:
                    stored.initialized = False
                db.commit()
        raise HTTPException(400, summary)
    try:
        statistics = repository_statistics_from_borg_info(output)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    stored = store_repository_statistics(
        repository_id,
        filesystem_size=filesystem_size,
        original_size=statistics.get("original_size"),
        compressed_size=statistics.get("compressed_size"),
        deduplicated_size=statistics.get("deduplicated_size"),
    )
    return {
        "repository_id": repository_id,
        "size_bytes": stored["size_bytes"],
        "filesystem_size_bytes": stored["filesystem_size"],
        "original_size_bytes": stored["original_size"],
        "compressed_size_bytes": stored["compressed_size"],
        "deduplicated_size_bytes": stored["deduplicated_size"],
        "storage_usage": external_storage,
        "size_type": "filesystem-and-borg" if managed else "borg-deduplicated-compressed",
    }


def _set_repository_enabled_state(db, repository: Repository, enabled: bool) -> None:
    if repository.enabled == enabled:
        return
    if not enabled:
        active = db.scalar(select(func.count()).select_from(Run).where(
            Run.repository_id == repository.id, Run.status.in_(["queued", "running"])
        )) or 0
        if active:
            raise ValueError("Repository kann während einer laufenden oder wartenden Ausführung nicht deaktiviert werden")
    repository.enabled = enabled


@app.post("/api/repositories", response_model=RepositoryOut, status_code=201, dependencies=admin_protected)
async def create_repository(data: RepositoryIn):
    secret = data.passphrase.get_secret_value() if data.passphrase else None
    keyfile = data.keyfile.get_secret_value() if data.keyfile else None
    external_credentials: dict[str, str | None] = {}
    if not data.managed:
        try:
            external_credentials = await prepare_external_repository_credentials(data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    with SessionLocal() as db:
        if data.managed:
            slug = repository_slug(data.name)
            storage_path = str(REPOSITORY_ROOT / slug)
            location = managed_repository_location(slug)
        else:
            storage_path = None
            location = data.location or ""
        row = Repository(
            name=data.name,
            enabled=data.enabled,
            location=location,
            passphrase_env=None,
            encryption_mode=data.encryption_mode,
            storage_path=storage_path,
            external_ssh_public_key=external_credentials.get("external_ssh_public_key"),
            external_host_fingerprint=external_credentials.get("external_host_fingerprint"),
            initialized=False,
            validation_error=None,
            validation_details=None,
            storage_guard_enabled=data.storage_guard_enabled,
            storage_guard_threshold_percent=data.storage_guard_threshold_percent,
            extra_env_json="{}",
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:
            raise HTTPException(409, "Repository name already exists") from exc
        row_id = row.id
    set_repository_secret(row_id, "passphrase", secret)
    set_repository_secret(row_id, "keyfile", keyfile)
    if not data.managed:
        set_repository_secret(row_id, "external_ssh_private_key", external_credentials.get("external_ssh_private_key"))
        set_repository_secret(row_id, "external_known_hosts", external_credentials.get("external_known_hosts"))
    with SessionLocal() as db:
        stored = db.get(Repository, row_id)
        if stored:
            stored.extra_env_json = json.dumps(store_repository_environment(row_id, data.extra_env))
            db.commit()

    if data.managed and data.enabled:
        try:
            queue_repository_init(row_id)
        except (LookupError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        with SessionLocal() as db:
            return repo_out(db.get(Repository, row_id))

    with SessionLocal() as db:
        return repo_out(db.get(Repository, row_id))



@app.put("/api/repositories/{row_id}", response_model=RepositoryOut, dependencies=admin_protected)
async def update_repository(row_id: int, data: RepositoryUpdate):
    secret = data.passphrase.get_secret_value() if data.passphrase else None
    keyfile = data.keyfile.get_secret_value() if data.keyfile else None
    with SessionLocal() as db:
        row = db.get(Repository, row_id)
        if not row:
            raise HTTPException(404, "Repository not found")
        if bool(row.storage_path) != data.managed:
            raise HTTPException(400, "Repository type cannot be changed")
        if row.initialized and row.encryption_mode != data.encryption_mode:
            raise HTTPException(400, "Repository encryption cannot be changed after initialization")
        previous_location = row.location
        previous_external_public_key = row.external_ssh_public_key
        previous_external_fingerprint = row.external_host_fingerprint
        external_credentials: dict[str, str | None] = {}
        if not data.managed:
            try:
                external_credentials = await prepare_external_repository_credentials(data, row)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        row.name = data.name
        if data.enabled is not None:
            try:
                _set_repository_enabled_state(db, row, data.enabled)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        row.passphrase_env = None
        row.encryption_mode = data.encryption_mode
        row.storage_guard_enabled = data.storage_guard_enabled
        row.storage_guard_threshold_percent = data.storage_guard_threshold_percent
        if not data.managed:
            next_location = data.location or row.location
            next_public_key = external_credentials.get("external_ssh_public_key")
            next_fingerprint = external_credentials.get("external_host_fingerprint")
            connection_changed = bool(
                next_location != previous_location
                or next_public_key != previous_external_public_key
                or next_fingerprint != previous_external_fingerprint
            )
            row.location = next_location
            if connection_changed:
                row.external_storage_total_bytes = None
                row.external_storage_used_bytes = None
                row.external_storage_free_bytes = None
                row.external_storage_usage_percent = None
                row.external_storage_path = None
                row.external_storage_checked_at = None
                row.external_storage_error = None
            row.external_ssh_public_key = next_public_key
            row.external_host_fingerprint = next_fingerprint
            if connection_changed:
                row.initialized = False
                row.validation_error = None
                row.validation_details = None
        if data.encryption_mode == "none":
            row.passphrase_env = None
        row.extra_env_json = json.dumps(store_repository_environment(row_id, data.extra_env))
        try:
            db.commit()
        except IntegrityError as exc:
            raise HTTPException(409, "Repository name already exists") from exc
    if secret is not None or data.encryption_mode == "none":
        set_repository_secret(row_id, "passphrase", None if data.encryption_mode == "none" else secret)
    if keyfile is not None or data.encryption_mode == "none":
        set_repository_secret(row_id, "keyfile", None if data.encryption_mode == "none" else keyfile)
    if not data.managed:
        set_repository_secret(row_id, "external_ssh_private_key", external_credentials.get("external_ssh_private_key"))
        set_repository_secret(row_id, "external_known_hosts", external_credentials.get("external_known_hosts"))

    sync_repository_access_assignments()
    sync_schedules()
    invalidate_archive_cache(row_id)
    if data.managed:
        with SessionLocal() as db:
            return repo_out(db.get(Repository, row_id))

    with SessionLocal() as db:
        return repo_out(db.get(Repository, row_id))



@app.put("/api/repositories/{repository_id}/enabled", response_model=RepositoryOut, dependencies=admin_protected)
def set_repository_enabled(repository_id: int, data: EnabledStateIn):
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if not repository:
            raise HTTPException(404, "Repository not found")
        try:
            _set_repository_enabled_state(db, repository, data.enabled)
            db.commit()
        except ValueError as exc:
            db.rollback()
            raise HTTPException(409, str(exc)) from exc
    sync_repository_access_assignments()
    sync_schedules()
    with SessionLocal() as db:
        return repo_out(db.get(Repository, repository_id))


@app.post("/api/repositories/{repository_id}/test", status_code=202, dependencies=admin_protected)
async def test_repository(repository_id: int) -> dict:
    """Queue the repository connection test instead of holding the HTTP request.

    External repositories may need to rebuild or synchronize their local Borg
    cache. Running that work as a persisted queue item avoids reverse-proxy 504
    responses while preserving repository-wide serialization.
    """
    try:
        run_id = queue_repository_action(
            repository_id, "test", subject="Repository-Verbindung prüfen",
            refresh_size_after=False,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "queued", "repository_id": repository_id, "run_id": run_id, "access_mode": "manager-local"}


@app.post("/api/repositories/{repository_id}/clear-cache", dependencies=admin_protected)
async def clear_repository_cache_endpoint(repository_id: int) -> dict:
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if not repository:
            raise HTTPException(404, "Repository not found")
        active = db.scalar(
            select(func.count()).select_from(Run).where(
                Run.repository_id == repository_id,
                Run.status.in_(["queued", "running"]),
            )
        ) or 0
        if active:
            raise HTTPException(409, "Repository-Cache kann während einer laufenden oder wartenden Ausführung nicht gelöscht werden")
        repository_name = repository.name
    try:
        result = await clear_repository_cache(repository_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(400, f"Repository-Cache konnte nicht gelöscht werden: {exc}") from exc

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(Run(
            job_id=None,
            job_name_snapshot=None,
            repository_id=repository_id,
            action="repository-cache-clear",
            status="success",
            command_preview=f"Lokalen Borg-Cache für Repository {repository_name} löschen",
            output="Nur lokale Manager-Cache-Daten wurden entfernt. Repository und Archive blieben unverändert.",
            started_at=now,
            finished_at=now,
        ))
        db.commit()
    return {"status": "cleared", "repository_id": repository_id, **result}


@app.delete("/api/repositories/{row_id}", status_code=204, dependencies=admin_protected)
def delete_repository(row_id: int):
    key_path: Path | None = None
    with SessionLocal() as db:
        row = db.get(Repository, row_id)
        if not row:
            raise HTTPException(404, "Repository not found")
        if db.scalar(select(func.count()).select_from(Job).where(Job.repository_id == row_id)):
            raise HTTPException(409, "Repository is still used by jobs")
        if db.scalar(
            select(func.count()).select_from(ManagerArchiveMount).where(
                ManagerArchiveMount.repository_id == row_id,
                ManagerArchiveMount.status.in_(["mounting", "mounted"]),
            )
        ):
            raise HTTPException(409, "Repository still has an active archive mount")
        if db.scalar(
            select(func.count()).select_from(Run).where(
                Run.repository_id == row_id,
                Run.status.in_(["queued", "running"]),
            )
        ):
            raise HTTPException(409, "Repository has a queued or running execution")
        key_path = Path(repository_keyfile_path(row))
        for run in db.scalars(select(Run).where(Run.repository_id == row_id)):
            run.repository_id = None
        db.execute(delete(BackupSchedule).where(BackupSchedule.target_mode == "repository", BackupSchedule.target_repository_id == row_id))
        db.execute(delete(HostRepositoryAccess).where(HostRepositoryAccess.repository_id == row_id))
        db.delete(row)
        db.commit()
    if key_path:
        key_path.unlink(missing_ok=True)
    delete_repository_secrets(row_id)
    invalidate_archive_cache(row_id)
    sync_repository_access_assignments(); sync_schedules()
    return Response(status_code=204)


@app.post("/api/repositories/{repository_id}/reset", dependencies=admin_protected)
async def reset_repository_state(repository_id: int) -> dict:
    try:
        return await reset_managed_repository_state(repository_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/repositories/{repository_id}/init", status_code=202, dependencies=admin_protected)
async def initialize_repository(repository_id: int):
    try:
        return {"run_id": queue_repository_init(repository_id)}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/repositories/{repository_id}/compact", status_code=202, dependencies=admin_protected)
async def compact_repository(repository_id: int) -> dict:
    with SessionLocal() as db:
        repository = load_repository_with_access(db, repository_id)
        if db.scalar(
            select(ManagerArchiveMount.id).where(
                ManagerArchiveMount.repository_id == repository_id,
                ManagerArchiveMount.status.in_(["mounting", "mounted"]),
            ).limit(1)
        ):
            raise HTTPException(409, "Repository Compact is blocked while an archive is mounted")
        subject = f"Repository: {repository.name}"
    try:
        return {"run_id": queue_repository_action(repository_id, "compact", subject=subject)}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        status = 409 if "queued or running" in str(exc) else 400
        raise HTTPException(status, str(exc)) from exc


@app.get("/api/schedules", response_model=list[BackupScheduleOut], dependencies=protected)
def list_backup_schedules():
    with SessionLocal() as db:
        return [schedule_out(row, db) for row in db.scalars(select(BackupSchedule).order_by(BackupSchedule.name))]


@app.post("/api/schedules", response_model=BackupScheduleOut, status_code=201, dependencies=admin_protected)
def create_backup_schedule(data: BackupScheduleIn):
    row = BackupSchedule(
        name=data.name, expressions=data.expressions, target_mode=data.target_mode,
        target_host_ids_json=json.dumps(data.target_host_ids),
        target_repository_id=data.target_repository_id if data.target_mode == "repository" else None,
        target_job_ids_json=json.dumps(data.target_job_ids), parallel_limit=data.parallel_limit,
        enabled=data.enabled,
    )
    with SessionLocal() as db:
        db.add(row)
        try:
            db.flush()
            validate_schedule_targets_exist(db, row)
            validate_schedule_conflicts(db, row, exclude_schedule_id=row.id)
            db.commit()
        except IntegrityError as exc:
            db.rollback(); raise HTTPException(409, "Zeitplanname ist bereits vorhanden") from exc
        except ValueError as exc:
            db.rollback(); raise HTTPException(409, str(exc)) from exc
        result = schedule_out(row, db)
    sync_schedules()
    return result


@app.put("/api/schedules/{schedule_id}", response_model=BackupScheduleOut, dependencies=admin_protected)
def update_backup_schedule(schedule_id: int, data: BackupScheduleIn):
    with SessionLocal() as db:
        row = db.get(BackupSchedule, schedule_id)
        if not row:
            raise HTTPException(404, "Zeitplan nicht gefunden")
        row.name = data.name; row.expressions = data.expressions; row.target_mode = data.target_mode
        row.target_host_ids_json = json.dumps(data.target_host_ids)
        row.target_repository_id = data.target_repository_id if data.target_mode == "repository" else None
        row.target_job_ids_json = json.dumps(data.target_job_ids)
        row.parallel_limit = data.parallel_limit; row.enabled = data.enabled
        try:
            db.flush(); validate_schedule_targets_exist(db, row); validate_schedule_conflicts(db, row, exclude_schedule_id=row.id); db.commit()
        except IntegrityError as exc:
            db.rollback(); raise HTTPException(409, "Zeitplanname ist bereits vorhanden") from exc
        except ValueError as exc:
            db.rollback(); raise HTTPException(409, str(exc)) from exc
        result = schedule_out(row, db)
    sync_schedules()
    return result


@app.delete("/api/schedules/{schedule_id}", status_code=204, dependencies=admin_protected)
def delete_backup_schedule(schedule_id: int):
    with SessionLocal() as db:
        row = db.get(BackupSchedule, schedule_id)
        if not row:
            raise HTTPException(404, "Zeitplan nicht gefunden")
        db.delete(row); db.commit()
    sync_schedules()
    return Response(status_code=204)


@app.get("/api/jobs", response_model=list[JobOut], dependencies=protected)
def list_jobs():
    with SessionLocal() as db:
        assignments = schedule_assignments(db)
        ready_pairs = set(db.execute(
            select(HostRepositoryAccess.host_id, HostRepositoryAccess.repository_id)
            .join(Repository, Repository.id == HostRepositoryAccess.repository_id)
            .where(HostRepositoryAccess.public_key.is_not(None), Repository.enabled.is_(True))
        ).all())
        jobs = list(db.scalars(select(Job).options(joinedload(Job.repository)).order_by(Job.name)))
        return [
            job_out(
                row,
                assignments.get(row.id, []),
                repository_access_ready=(not bool(row.repository.storage_path)) or ((row.host_id, row.repository_id) in ready_pairs),
            )
            for row in jobs
        ]


@app.post("/api/jobs", response_model=JobOut, status_code=201, dependencies=admin_protected)
def create_job(data: JobIn):
    with SessionLocal() as db:
        host = db.get(Host, data.host_id)
        repository = db.get(Repository, data.repository_id)
        if not host or not repository:
            raise HTTPException(400, "Unknown host or repository")
        row = Job(id=allocate_job_id(db)); apply_job(row, data); db.add(row)
        try:
            db.flush()
            row.archive_prefix = f"bbm-{row.id}-"
            row.archive_prefix_history_json = "[]"
            validate_job_schedule_conflicts(db, row)
            db.commit()
        except IntegrityError as exc:
            db.rollback(); raise HTTPException(409, "Job name already exists") from exc
        except ValueError as exc:
            db.rollback(); raise HTTPException(409, str(exc)) from exc
        assignments = schedule_assignments(db)
        result = job_out(row, assignments.get(row.id, []), repository_access_ready=not bool(repository.storage_path))
    sync_repository_access_assignments(); sync_schedules(); return result


@app.put("/api/jobs/{row_id}", response_model=JobOut, dependencies=admin_protected)
def update_job(row_id: int, data: JobIn):
    with SessionLocal() as db:
        row = db.get(Job, row_id)
        if not row: raise HTTPException(404, "Job not found")
        host = db.get(Host, data.host_id)
        repository = db.get(Repository, data.repository_id)
        if not host or not repository:
            raise HTTPException(400, "Unknown host or repository")
        apply_job(row, data)
        try:
            validate_job_schedule_conflicts(db, row)
            db.commit()
        except IntegrityError as exc: raise HTTPException(409, "Job name already exists") from exc
        except ValueError as exc: raise HTTPException(409, str(exc)) from exc
        assignments = schedule_assignments(db)
        ready = (not bool(repository.storage_path)) or bool(db.scalar(
            select(HostRepositoryAccess.id).where(
                HostRepositoryAccess.host_id == row.host_id,
                HostRepositoryAccess.repository_id == row.repository_id,
                HostRepositoryAccess.public_key.is_not(None),
            )
        ))
        result = job_out(row, assignments.get(row.id, []), repository_access_ready=ready)
    sync_repository_access_assignments(); sync_schedules(); return result


def _drop_job_schedule_references(db, job_id: int) -> None:
    for schedule in list(db.scalars(select(BackupSchedule).where(BackupSchedule.target_mode == "jobs"))):
        ids = [int(value) for value in json.loads(schedule.target_job_ids_json or "[]") if int(value) != job_id]
        if ids:
            schedule.target_job_ids_json = json.dumps(ids)
        else:
            db.delete(schedule)


def _drop_host_schedule_references(db, host_id: int) -> None:
    for schedule in list(db.scalars(select(BackupSchedule).where(BackupSchedule.target_mode == "hosts"))):
        ids = [int(value) for value in json.loads(schedule.target_host_ids_json or "[]") if int(value) != host_id]
        if ids:
            schedule.target_host_ids_json = json.dumps(ids)
        else:
            db.delete(schedule)


@app.post("/api/jobs/{row_id}/enabled", response_model=JobOut, dependencies=admin_protected)
def set_job_enabled(row_id: int, data: EnabledStateIn):
    with SessionLocal() as db:
        row = db.get(Job, row_id)
        if not row:
            raise HTTPException(404, "Job not found")
        if not data.enabled:
            active = db.scalar(select(func.count()).select_from(Run).where(
                Run.job_id == row_id, Run.status.in_(["queued", "running"])
            )) or 0
            if active:
                raise HTTPException(409, "Backup-Job kann während einer laufenden oder wartenden Ausführung nicht deaktiviert werden")
        row.enabled = data.enabled
        db.commit()
        assignments = schedule_assignments(db)
        repository = db.get(Repository, row.repository_id)
        ready = bool(repository) and ((not bool(repository.storage_path)) or bool(db.scalar(
            select(HostRepositoryAccess.id).where(
                HostRepositoryAccess.host_id == row.host_id,
                HostRepositoryAccess.repository_id == row.repository_id,
                HostRepositoryAccess.public_key.is_not(None),
            )
        )))
        result = job_out(row, assignments.get(row.id, []), repository_access_ready=ready)
    sync_schedules()
    return result


@app.delete("/api/jobs/{row_id}", status_code=204, dependencies=admin_protected)
def delete_job(row_id: int):
    with SessionLocal() as db:
        row = db.get(Job, row_id)
        if not row: raise HTTPException(404, "Job not found")
        if db.scalar(
            select(func.count()).select_from(Run).where(
                Run.job_id == row_id,
                Run.status.in_(["queued", "running"]),
            )
        ):
            raise HTTPException(409, "Job has a queued or running execution and cannot be deleted yet")
        for run in db.scalars(select(Run).where(Run.job_id == row_id)):
            run.job_name_snapshot = run.job_name_snapshot or row.name
            run.job_id = None
        _drop_job_schedule_references(db, row_id)
        db.delete(row)
        db.commit()
    sync_repository_access_assignments(); sync_schedules(); return Response(status_code=204)


@app.post("/api/jobs/{job_id}/actions/{action}", status_code=202, dependencies=admin_protected)
async def run_action(job_id: int, action: str):
    # Confirming a changed Borg repository location modifies client-side
    # security metadata and therefore has a dedicated admin-only endpoint.
    if action == "confirm-location":
        raise HTTPException(403, "Repository location confirmation requires administrator access")
    # queue_job_action schedules the command on the current asyncio loop.  Keep
    # this endpoint asynchronous so FastAPI does not execute it in a worker
    # thread where asyncio.create_task() has no running loop.
    try:
        return {"run_id": queue_manual_backup(job_id) if action == "backup" else queue_job_action(job_id, action)}
    except LookupError as exc: raise HTTPException(404, str(exc)) from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@app.post("/api/jobs/{job_id}/confirm-repository-location", status_code=202, dependencies=admin_protected)
async def confirm_repository_location(job_id: int):
    """Explicitly approve Borg's one-time relocated-repository safety prompt."""
    try:
        return {"run_id": queue_job_action(job_id, "confirm-location")}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/jobs/{job_id}/restore", status_code=202, dependencies=admin_protected)
async def restore(job_id: int, data: RestoreIn):
    with SessionLocal() as db:
        job = load_job_with_connections(db, job_id)
    if not await archive_exists(job, data.archive):
        raise HTTPException(404, "Archive not found in this repository")
    try:
        return {"run_id": queue_job_action(job_id, "restore", data.model_dump())}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


async def _repository_archive_dataset(
    repository_id: int, *, consider_checkpoints: bool = False, force_refresh: bool = False,
    allow_unvalidated_external: bool = False,
) -> tuple[dict, list[Job], str, str | None]:
    """Return only the persistent archive cache; never scan Borg in an HTTP request.

    Large repositories can take many minutes to enumerate. Repository scans are
    queued separately through ``/archives/refresh`` so reverse proxies cannot
    terminate the operation with HTTP 504 while Borg is still working.
    """
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id) if allow_unvalidated_external else load_repository_with_access(db, repository_id)
        if not repository:
            raise HTTPException(404, "Repository not found")
        repository_jobs = list(db.scalars(
            select(Job).options(joinedload(Job.host)).where(Job.repository_id == repository_id)
        ))

    if force_refresh:
        raise HTTPException(
            409,
            "Repository-Archivscan muss über die asynchrone Aktualisierung gestartet werden",
        )
    cached = load_archive_cache(repository_id, consider_checkpoints)
    if cached:
        return copy.deepcopy(cached["data"]), repository_jobs, "cache", cached.get("generated_at")
    return {"repository_statistics": {}, "archives": []}, repository_jobs, "missing", None



@app.post("/api/repositories/{repository_id}/archives/refresh", status_code=202, dependencies=admin_protected)
async def refresh_repository_archives(repository_id: int, consider_checkpoints: bool = False) -> dict:
    """Queue a repository archive scan and return immediately."""
    try:
        run_id = queue_repository_archive_refresh(repository_id, consider_checkpoints)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "status": "queued",
        "repository_id": repository_id,
        "consider_checkpoints": bool(consider_checkpoints),
        "run_id": run_id,
    }


@app.get("/api/repositories/{repository_id}/archives", dependencies=admin_protected)
async def list_repository_archives(
    repository_id: int, consider_checkpoints: bool = False, force_refresh: bool = False
) -> dict:
    dataset, repository_jobs, cache_source, cache_updated_at = await _repository_archive_dataset(
        repository_id, consider_checkpoints=consider_checkpoints, force_refresh=force_refresh
    )
    archives = sort_archives_newest_first(dataset.get("archives", []))
    assign_archive_owners(archives, repository_jobs)
    resolve_archive_devices(archives, repository_jobs)
    return {
        "repository_id": repository_id,
        "job_id": None,
        "consider_checkpoints": consider_checkpoints,
        "access_mode": "manager-local",
        "repository_statistics": dataset.get("repository_statistics", {}),
        "archives": archives,
        "archive_cache_source": cache_source,
        "archive_cache_updated_at": cache_updated_at,
        "archive_cache_missing": cache_source == "missing",
    }


@app.get("/api/repositories/{repository_id}/archives/{archive}/info", dependencies=admin_protected)
async def repository_archive_info(repository_id: int, archive: str) -> dict:
    with SessionLocal() as db:
        repository = load_repository_with_access(db, repository_id)
        command = repository_archive_info_command(repository, archive)
    code, output, error = await execute_interactive(repository_id, command)
    if code not in {0, 1}:
        summary, _details = compact_repository_error_with_debug(
            f"Archive info for repository {repository_id} returned technical Borg output",
            output, error, code,
        )
        raise HTTPException(400, summary)
    try:
        normalized = parse_borg_info(output + "\n" + error)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    details = normalized.get("archives", [])
    if not details:
        raise HTTPException(400, "Borg hat keine Archivstatistik geliefert")
    return {"archive": details[0], "repository_statistics": normalized.get("repository", {})}


@app.get("/api/repositories/{repository_id}/archives/{archive}/browse", dependencies=admin_protected)
async def browse_repository_archive(repository_id: int, archive: str, path: str = "") -> dict:
    with SessionLocal() as db:
        repository = load_repository_with_access(db, repository_id)
        command = repository_browse_archive_command(repository, archive, path)
        access_mode = "manager-local"
    code, output, error = await execute_interactive(repository_id, command)
    if code not in {0, 1}:
        raise borg_operation_error(output, error, code)
    try:
        entries = parse_archive_browser_listing(output, path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    current = path.strip("/")
    parent = "/".join(current.split("/")[:-1]) if current else None
    return {
        "repository_id": repository_id,
        "archive": archive,
        "path": current,
        "parent": parent,
        "access_mode": access_mode,
        "entries": entries,
    }


@app.post("/api/repositories/{repository_id}/archive-delete", status_code=202, dependencies=admin_protected)
async def delete_repository_archives(repository_id: int, data: ArchiveBulkDeleteIn) -> dict:
    with SessionLocal() as db:
        repository = load_repository_with_access(db, repository_id)
        if db.scalar(
            select(Run.id).where(
                Run.repository_id == repository_id,
                Run.status.in_(["queued", "running"]),
            ).limit(1)
        ):
            raise HTTPException(409, "Repository has a queued or running execution")
        mounted = set(db.scalars(
            select(ManagerArchiveMount.archive).where(
                ManagerArchiveMount.repository_id == repository_id,
                ManagerArchiveMount.archive.in_(data.archives),
                ManagerArchiveMount.status.in_(["mounting", "mounted"]),
            )
        ))
        if mounted:
            raise HTTPException(409, f"Mounted archives must be unmounted first: {', '.join(sorted(mounted))}")
        repository_jobs = list(db.scalars(
            select(Job).options(joinedload(Job.host)).where(Job.repository_id == repository_id)
        ))
        repository_name = repository.name

    # Never enumerate a large Borg repository inside this HTTP request.  The
    # selected names already passed the strict archive-name validator and come
    # from the persistent archive view in normal UI use.  Cached metadata is
    # used only for the human-readable device label; the queued Borg command is
    # the authoritative existence check and reports stale/missing names in the
    # visible run log instead of leaving the browser on "Löschung wird
    # gestartet …" for minutes or until a reverse-proxy timeout occurs.
    archive_map: dict[str, dict] = {}
    for consider_checkpoints in (False, True):
        cached = load_archive_cache(repository_id, consider_checkpoints)
        if not cached:
            continue
        for archive in cached["data"].get("archives", []):
            name = str(archive.get("name") or "")
            if name in data.archives and name not in archive_map:
                archive_map[name] = copy.deepcopy(archive)

    selected = [archive_map.get(name, {"name": name}) for name in data.archives]
    assign_archive_owners(selected, repository_jobs)
    resolve_archive_devices(selected, repository_jobs)
    labels = [str(archive.get("device_name") or "").strip() for archive in selected]
    known_devices = {label for label in labels if label}
    has_unknown = any(not label for label in labels)
    if len(selected) > 1 and (len(known_devices) > 1 or (known_devices and has_unknown)):
        subject = "Mehrere Geräte"
    elif len(known_devices) == 1 and not has_unknown:
        subject = f"Gerät: {next(iter(known_devices))}"
    else:
        subject = f"Repository: {repository_name}"

    try:
        run_id = queue_repository_action(
            repository_id, "delete-archive", data.model_dump(), subject=subject
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        status = 409 if "queued or running" in str(exc) else 400
        raise HTTPException(status, str(exc)) from exc
    return {
        "run_id": run_id,
        "archive_count": len(data.archives),
        "device_label": subject,
    }


@app.get("/api/jobs/{job_id}/archives", dependencies=admin_protected)
async def list_job_archives(
    job_id: int, all_archives: bool = False, consider_checkpoints: bool = False, force_refresh: bool = False
) -> dict:
    with SessionLocal() as db:
        job = load_job_with_connections(db, job_id, require_client_access=False)
        repository_id = job.repository_id
        accepted_prefixes = job_archive_prefixes(job)

    dataset, repository_jobs, cache_source, cache_updated_at = await _repository_archive_dataset(
        repository_id, consider_checkpoints=consider_checkpoints, force_refresh=force_refresh,
        allow_unvalidated_external=True,
    )
    archives = sort_archives_newest_first(dataset.get("archives", []))
    if not all_archives:
        archives = [
            archive for archive in archives
            if any(archive["name"].startswith(prefix) for prefix in accepted_prefixes)
        ]
    assign_archive_owners(archives, repository_jobs, job_id)
    resolve_archive_devices(archives, repository_jobs)
    return {
        "job_id": job_id,
        "repository_id": repository_id,
        "all_archives": all_archives,
        "consider_checkpoints": consider_checkpoints,
        "access_mode": "manager-local",
        "repository_statistics": dataset.get("repository_statistics", {}),
        "archives": archives,
        "archive_cache_source": cache_source,
        "archive_cache_updated_at": cache_updated_at,
        "archive_cache_missing": cache_source == "missing",
    }


@app.get("/api/jobs/{job_id}/archives/{archive}/info", dependencies=admin_protected)
async def archive_info(job_id: int, archive: str) -> dict:
    with SessionLocal() as db:
        job = load_job_with_connections(db, job_id, require_client_access=False)
        command = archive_info_command(job, archive)
        repository_id = job.repository_id
    code, output, error = await execute_interactive(repository_id, command)
    if code not in {0, 1}:
        raise borg_operation_error(output, error, code)
    try:
        normalized = parse_borg_info(output + "\n" + error)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    details = normalized.get("archives", [])
    if not details:
        raise HTTPException(400, "Borg hat keine Archivstatistik geliefert")
    return {"archive": details[0], "repository_statistics": normalized.get("repository", {})}



@app.post("/api/jobs/{job_id}/archive-rename", status_code=202, dependencies=admin_protected)
async def rename_archive(job_id: int, data: ArchiveRenameIn) -> dict:
    with SessionLocal() as db:
        job = load_job_with_connections(db, job_id, require_client_access=False)
        repository_jobs = list(db.scalars(select(Job).where(Job.repository_id == job.repository_id)))
        if db.scalar(
            select(ManagerArchiveMount.id).where(
                ManagerArchiveMount.repository_id == job.repository_id,
                ManagerArchiveMount.archive == data.archive,
                ManagerArchiveMount.status.in_(["mounting", "mounted"]),
            )
        ):
            raise HTTPException(409, "Archive is currently mounted and must be unmounted first")
    names = await repository_archive_names(job)
    if data.archive not in names:
        raise HTTPException(404, "Archive not found in this repository")
    if data.new_name in names:
        raise HTTPException(409, "An archive with the new name already exists")
    owner_prefix = next(
        (
            prefix
            for row in repository_jobs
            for prefix in job_archive_prefixes(row)
            if data.archive.startswith(prefix)
        ),
        None,
    )
    if owner_prefix and not data.new_name.startswith(owner_prefix):
        raise HTTPException(400, f"The new name must keep the job prefix {owner_prefix}")
    try:
        return {"run_id": queue_job_action(job_id, "rename-archive", data.model_dump())}
    except (LookupError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/jobs/{job_id}/archive-diff", status_code=202, dependencies=admin_protected)
async def diff_archives(job_id: int, data: ArchiveDiffIn) -> dict:
    with SessionLocal() as db:
        requested_job = load_job_with_connections(db, job_id, require_client_access=False)
        repository_jobs = list(db.scalars(
            select(Job)
            .options(joinedload(Job.host), joinedload(Job.repository))
            .where(Job.repository_id == requested_job.repository_id)
        ))
        first_owner = archive_owner_job(data.archive, repository_jobs)
        second_owner = archive_owner_job(data.second_archive, repository_jobs)

        # Archive comparisons are repository-side operations. Use any resolved
        # owner only as the technical access job, but keep a dedicated display
        # label that describes both selected archive series. This avoids showing
        # the first-created repository job when two different jobs are compared.
        effective_job = first_owner or second_owner or requested_job

        def owner_label(owner: Job | None, archive_name: str) -> str:
            if owner:
                return owner.name
            inferred = infer_archive_device(archive_name)
            return inferred or archive_name

        first_label = owner_label(first_owner, data.archive)
        second_label = owner_label(second_owner, data.second_archive)
        comparison_label = (
            first_label
            if first_owner and second_owner and first_owner.id == second_owner.id
            else f"{first_label} ↔ {second_label}"
        )[:100]
        db.expunge(effective_job)
    names = await repository_archive_names(effective_job)
    missing = [name for name in (data.archive, data.second_archive) if name not in names]
    if missing:
        raise HTTPException(404, f"Archive not found: {', '.join(missing)}")
    try:
        return {"run_id": queue_job_action(
            effective_job.id, "diff-archives", data.model_dump(),
            run_label=comparison_label,
        )}
    except (LookupError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc



def parse_archive_browser_listing(output: str, current: str = "") -> list[dict]:
    prefix = current.strip("/")
    prefix_with_slash = f"{prefix}/" if prefix else ""
    type_names = {"d": "directory", "f": "file", "l": "symlink"}
    entries: list[dict] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("Borg returned an invalid archive content list") from exc
        path = str(item.get("path") or "").strip("/")
        if not path or (prefix_with_slash and not path.startswith(prefix_with_slash)):
            continue
        name = path[len(prefix_with_slash):] if prefix_with_slash else path
        if not name or "/" in name:
            continue
        raw_type = str(item.get("type") or "").strip().lower()
        if raw_type in {"directory", "dir"}:
            entry_type = "directory"
        elif raw_type in {"symlink", "link"}:
            entry_type = "symlink"
        elif raw_type in {"file", "regular"}:
            entry_type = "file"
        else:
            mode = str(item.get("mode") or "")
            marker = raw_type[:1] or mode[:1]
            entry_type = type_names.get(marker, "other")
        size = item.get("size")
        try:
            normalized_size = max(0, int(size or 0))
        except (TypeError, ValueError):
            normalized_size = 0
        mode = str(item.get("mode") or "").strip() or None
        user = item.get("user")
        group = item.get("group")
        uid = item.get("uid")
        gid = item.get("gid")
        entries.append({
            "name": name,
            "path": path,
            "type": entry_type,
            "size": normalized_size,
            "mtime": item.get("mtime") or item.get("isomtime"),
            "target": item.get("source") or item.get("linktarget") or None,
            "mode": mode,
            "user": str(user) if user is not None and user != "" else None,
            "group": str(group) if group is not None and group != "" else None,
            "uid": uid,
            "gid": gid,
        })
    entries.sort(key=lambda item: (item["type"] != "directory", item["name"].casefold()))
    return entries


@app.get("/api/jobs/{job_id}/archives/{archive}/browse", dependencies=admin_protected)
async def browse_archive(job_id: int, archive: str, path: str = "") -> dict:
    with SessionLocal() as db:
        job = load_job_with_connections(db, job_id, require_client_access=False)
        command = browse_archive_command(job, archive, path)
        repository_id = job.repository_id
        access_mode = "manager-local"
    code, output, error = await execute_interactive(repository_id, command)
    if code not in {0, 1}:
        raise borg_operation_error(output, error, code)
    try:
        entries = parse_archive_browser_listing(output, path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    current = path.strip("/")
    parent = "/".join(current.split("/")[:-1]) if current else None
    return {
        "job_id": job_id,
        "repository_id": repository_id,
        "archive": archive,
        "path": current,
        "parent": parent,
        "access_mode": access_mode,
        "entries": entries,
    }


def _remove_export_artifacts(archive_path: Path, work_path: Path) -> None:
    try:
        archive_path.unlink(missing_ok=True)
    finally:
        shutil.rmtree(work_path, ignore_errors=True)


@app.post("/api/jobs/{job_id}/archive-export", dependencies=admin_protected)
async def export_archive_selection(job_id: int, data: ArchiveExportIn) -> FileResponse:
    with SessionLocal() as db:
        job = load_job_with_connections(db, job_id, require_client_access=False)
        repository_id = job.repository_id
    if not await archive_exists(job, data.archive):
        raise HTTPException(404, "Archive not found in this repository")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(10)
    work_path = EXPORT_DIR / f".work-{token}"
    safe_archive = re.sub(r"[^A-Za-z0-9._-]+", "-", data.archive).strip("-.")[:80] or "archive"
    download_name = f"bbm-export-{safe_archive}.tar.gz"
    archive_path = EXPORT_DIR / f".{token}-{download_name}"
    try:
        command = archive_export_command(job, data.archive, data.paths, str(work_path))
        code, output, error = await execute_interactive(repository_id, command)
        if code not in {0, 1}:
            raise borg_operation_error(output, error, code)
        children = sorted(work_path.iterdir(), key=lambda item: item.name.casefold()) if work_path.is_dir() else []
        if not children:
            raise HTTPException(400, "Borg did not export any selected file or directory")
        with tarfile.open(archive_path, "w:gz", format=tarfile.PAX_FORMAT) as bundle:
            for child in children:
                bundle.add(child, arcname=child.name, recursive=True)
    except HTTPException:
        _remove_export_artifacts(archive_path, work_path)
        raise
    except (OSError, ValueError, tarfile.TarError) as exc:
        _remove_export_artifacts(archive_path, work_path)
        raise HTTPException(400, str(exc)) from exc

    return FileResponse(
        archive_path,
        filename=download_name,
        media_type="application/gzip",
        background=BackgroundTask(_remove_export_artifacts, archive_path, work_path),
    )


async def wait_for_archive_mount_state(
    path: str | Path,
    *,
    active: bool,
    timeout_seconds: float,
    poll_seconds: float = 0.2,
) -> bool:
    """Wait briefly for the kernel mount table to reflect a Borg FUSE lifecycle change."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, timeout_seconds)
    while True:
        if archive_mount_is_active(path) is active:
            return True
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(max(0.02, poll_seconds), remaining))


async def wait_for_archive_mount_activation(
    mount_id: int,
    path: str | Path,
    *,
    timeout_seconds: float,
    poll_seconds: float = 0.2,
) -> str:
    """Wait for mount activation while respecting a concurrent unmount request.

    The WebUI polls the mount list while the original POST request is still in
    flight. A second browser tab or an early refresh can therefore request an
    unmount before the POST has observed the new FUSE entry. Treat that state as
    an intentional cancellation instead of reporting a delayed activation
    failure after the archive was already unmounted.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, timeout_seconds)
    while True:
        with SessionLocal() as db:
            row = db.get(ManagerArchiveMount, mount_id)
            if row is None or row.status in {"unmounting", "stale"}:
                return "cancelled"
        if archive_mount_is_active(path):
            return "active"
        remaining = deadline - loop.time()
        if remaining <= 0:
            # Close the narrow race where an unmount deletes or changes the row
            # just after the last status read but before the deadline check.
            with SessionLocal() as db:
                row = db.get(ManagerArchiveMount, mount_id)
                if row is None or row.status in {"unmounting", "stale"}:
                    return "cancelled"
            return "active" if archive_mount_is_active(path) else "timeout"
        await asyncio.sleep(min(max(0.02, poll_seconds), remaining))


def manager_mount_json(row: ManagerArchiveMount, repository_name: str | None = None) -> dict:
    active = archive_mount_is_active(row.mount_path)
    status = row.status
    if active and status not in {"mounting", "unmounting", "error"}:
        status = "mounted"
    return {
        "id": row.id,
        "kind": "manager",
        "repository_id": row.repository_id,
        "repository_name": repository_name or (row.repository.name if row.repository else None),
        "archive": row.archive,
        "mount_path": row.mount_path,
        "host_path": archive_mount_host_path(row.mount_path),
        "status": status,
        "active": active,
        "error": row.error or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@app.get("/api/archive-mounts/capability", dependencies=admin_protected)
def archive_mount_capability_api() -> dict:
    return archive_mount_capability()


@app.get("/api/archive-mounts", dependencies=admin_protected)
def list_manager_archive_mounts() -> list[dict]:
    with SessionLocal() as db:
        rows = list(db.scalars(
            select(ManagerArchiveMount)
            .options(joinedload(ManagerArchiveMount.repository))
            .order_by(ManagerArchiveMount.id.desc())
        ))
        changed = False
        result: list[dict] = []
        now = datetime.now(timezone.utc)
        for row in rows:
            active = archive_mount_is_active(row.mount_path)
            transition_at = ensure_utc(row.updated_at) or ensure_utc(row.created_at)
            transition_recent = bool(
                row.status in {"mounting", "unmounting"}
                and transition_at
                and now - transition_at < timedelta(seconds=30)
            )
            if active and row.status not in {"mounted", "mounting", "unmounting", "error"}:
                row.status = "mounted"
                row.error = ""
                changed = True
            elif active and row.status == "mounting" and not transition_recent:
                # A normally running POST finalizes this state itself. Promote
                # only an old transition, for example after a worker restart.
                row.status = "mounted"
                row.error = ""
                changed = True
            elif not active and row.status in {"mounting", "mounted", "unmounting"} and not transition_recent:
                row.status = "stale"
                row.error = "Mount ist nicht mehr im Container aktiv. Eintrag kann entfernt werden."
                changed = True
            result.append(manager_mount_json(row))
        if changed:
            db.commit()
        return result


@app.post("/api/repositories/{repository_id}/archive-mounts", status_code=201, dependencies=admin_protected)
async def create_manager_archive_mount(repository_id: int, data: ArchiveMountIn) -> dict:
    try:
        require_archive_mount_capability()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    mount_path: Path | None = None
    row_id: int | None = None
    with SessionLocal() as db:
        repository = load_repository_with_access(db, repository_id)
        if not repository.enabled:
            raise HTTPException(409, "Repository ist deaktiviert")
        if not repository.initialized:
            raise HTTPException(409, "Repository ist nicht initialisiert")
        if not repository.storage_path:
            raise HTTPException(
                409,
                "Archiv-Mounts werden derzeit nur für lokal verwaltete Repositories unterstützt",
            )
        if repository.storage_path and not managed_repository_present(repository):
            raise HTTPException(409, "Verwaltetes Repository ist derzeit nicht verfügbar")
        if db.scalar(select(Run.id).where(
            Run.repository_id == repository_id,
            Run.status.in_(["queued", "running"]),
        ).limit(1)):
            raise HTTPException(409, "Repository besitzt eine laufende oder wartende Ausführung")
        existing = db.scalar(select(ManagerArchiveMount).where(
            ManagerArchiveMount.repository_id == repository_id,
        ).limit(1))
        if existing:
            if archive_mount_is_active(existing.mount_path):
                if existing.archive == data.archive:
                    return manager_mount_json(existing, repository.name)
                raise HTTPException(409, f"Repository besitzt bereits einen aktiven Archiv-Mount: {existing.archive}")
            stale_path = existing.mount_path
            db.delete(existing)
            db.commit()
            cleanup_archive_mount_path(stale_path)
        mount_path = prepare_archive_mount_path(
            archive_mount_path(repository.id, repository.name, data.archive)
        )
        row = ManagerArchiveMount(
            repository_id=repository.id,
            archive=data.archive,
            mount_path=str(mount_path),
            status="mounting",
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            cleanup_archive_mount_path(mount_path)
            raise HTTPException(409, "Repository wird bereits als Archiv-Mount verwendet") from exc
        row_id = row.id
        db.expunge(repository)

    try:
        command = manager_archive_mount_command(repository, data.archive, str(mount_path))
        code, output, error = await execute_interactive(repository_id, command)
        if code != 0:
            raise borg_operation_error(output, error, code)
        activation_state = await wait_for_archive_mount_activation(
            row_id, mount_path, timeout_seconds=15.0, poll_seconds=0.2,
        )
        if activation_state == "cancelled":
            return {
                "cancelled": True,
                "repository_id": repository_id,
                "archive": data.archive,
                "status": "unmounted",
                "active": False,
            }
        if activation_state != "active":
            raise HTTPException(
                400,
                "Borg hat den Mount-Befehl beendet, aber der FUSE-Mount wurde innerhalb von 15 Sekunden nicht aktiv.",
            )
        with SessionLocal() as db:
            row = db.get(ManagerArchiveMount, row_id)
            if not row:
                raise HTTPException(500, "Archiv-Mount wurde erstellt, aber der Datenbankeintrag fehlt")
            row.status = "mounted"
            row.error = ""
            db.commit()
            return manager_mount_json(row, repository.name)
    except Exception:
        if mount_path and archive_mount_is_active(mount_path):
            try:
                command = manager_archive_unmount_command(str(mount_path))
                await asyncio.wait_for(execute(command), timeout=24)
            except Exception:
                pass
        with SessionLocal() as db:
            row = db.get(ManagerArchiveMount, row_id) if row_id else None
            if row:
                db.delete(row)
                db.commit()
        if mount_path:
            cleanup_archive_mount_path(mount_path)
        raise


def archive_unmount_incident(mount_id: int, mount_path: str, detail: str, *, status_code: int = 500) -> HTTPException:
    error_id = log_unexpected_exception(
        f"Archive mount {mount_id} could not be unmounted",
        detail=f"Mount path: {mount_path}\n{detail}",
        logger_name="bbm.archive_mount",
    )
    try:
        with SessionLocal() as db:
            current = db.get(ManagerArchiveMount, mount_id)
            if current:
                current.status = "error"
                current.error = f"Aushängen fehlgeschlagen. Debug-Log, Fehler-ID {error_id}."
                db.commit()
    except Exception:
        pass
    if status_code == 504:
        message = "Zeitüberschreitung beim Aushängen des Archiv-Mounts."
    else:
        message = "Archiv-Mount konnte nicht sicher ausgehängt werden."
    return HTTPException(
        status_code,
        f"{message} Details wurden im Debug-Log gespeichert. Fehler-ID: {error_id}",
    )


@app.delete("/api/archive-mounts/{mount_id}", status_code=204, dependencies=admin_protected)
async def delete_manager_archive_mount(mount_id: int):
    with SessionLocal() as db:
        row = db.get(ManagerArchiveMount, mount_id)
        if not row:
            raise HTTPException(404, "Archiv-Mount nicht gefunden")
        if row.status == "unmounting":
            raise HTTPException(409, "Archiv-Mount wird bereits ausgehängt")
        mount_path = row.mount_path
        row.status = "unmounting"
        row.error = ""
        db.commit()

    if archive_mount_is_active(mount_path):
        command = manager_archive_unmount_command(mount_path)
        try:
            # A FUSE unmount must never wait for the normal repository execution
            # lock. That lock can be occupied by a repository operation which is
            # itself waiting for this archive mount to disappear. Execute only
            # the bounded local lifecycle command here.
            code, output, error = await asyncio.wait_for(execute(command), timeout=24)
        except TimeoutError as exc:
            raise archive_unmount_incident(
                mount_id, mount_path, "Aushänge-Operation überschritt das API-Zeitlimit von 24 Sekunden.", status_code=504,
            ) from exc
        if code == 124:
            raise archive_unmount_incident(
                mount_id, mount_path, f"Aushänge-Befehl überschritt sein Zeitlimit. stdout={output!r} stderr={error!r}", status_code=504,
            )
        if code != 0:
            raise archive_unmount_incident(
                mount_id, mount_path, f"Aushänge-Befehl fehlgeschlagen (rc {code}). stdout={output!r} stderr={error!r}",
            )
        if not await wait_for_archive_mount_state(
            mount_path, active=False, timeout_seconds=4.0, poll_seconds=0.15,
        ):
            raise archive_unmount_incident(
                mount_id, mount_path, "Der Aushänge-Befehl meldete Erfolg, der FUSE-Mount ist aber weiterhin aktiv.",
            )
    with SessionLocal() as db:
        row = db.get(ManagerArchiveMount, mount_id)
        if row:
            db.delete(row)
            db.commit()
    cleanup_archive_mount_path(mount_path)
    return Response(status_code=204)


def run_json(
    row: Run,
    *,
    include_details: bool = True,
    log_max_bytes: int | None = None,
    log_offset: int | None = None,
    log_file_available: bool | None = None,
    retention_protected: bool = False,
) -> dict:
    file_log = None
    live_log_offset: int | None = None
    live_log_reset = False
    live_log_truncated = False
    if include_details:
        settings = load_settings()
        effective_log_max = settings.run_log_view_kib * 1024
        if log_max_bytes is not None:
            effective_log_max = min(effective_log_max, max(64 * 1024, int(log_max_bytes)))
        if log_offset is not None:
            delta = read_run_log_delta(row.id, log_offset, effective_log_max)
            file_log = str(delta["text"])
            live_log_offset = int(delta["offset"])
            live_log_reset = bool(delta["reset"])
            live_log_truncated = bool(delta["truncated"])
        else:
            file_log = read_run_log(row.id, effective_log_max)
        if log_offset is not None:
            combined = file_log or ""
        else:
            combined = file_log or row.log_output or ((row.output or "") + ("\n" if row.output and row.error else "") + (row.error or ""))
    else:
        # Lists use only the bounded SQLite preview. The complete output is
        # read from /data/run-logs exclusively for the selected execution.
        combined = (row.log_output or row.error or row.output)[-16384:]
    active = row.status in {"queued", "running"}
    # The complete file log can be compacted and the bounded database log keeps
    # only a tail. The separately filtered stderr preview therefore remains an
    # important source for warning causes such as ``C``/``E`` item lines.
    diagnostic_base = (row.log_output or row.output or "") if log_offset is not None else combined
    diagnostic_text = diagnostic_base + ("\n" + row.error if row.error else "")
    # Live fragments are not reliable enough for an error diagnosis. In
    # particular Borg can emit transient passphrase-related helper text before
    # a successful final result. Diagnostics are therefore final-state only.
    warning_summary = None
    if row.action == "backup" and row.status in {"running", "warning"}:
        warning_summary = warning_summary_from_json(row.warning_summary_json)
    if not warning_summary and row.status == "warning" and row.action == "backup":
        warning_summary = parse_borg_warnings(diagnostic_text) or unresolved_warning_summary()
    diagnosis = (warning_diagnosis(warning_summary) or diagnose_run(diagnostic_text, "")) if row.status in {"failed", "warning"} else None
    if (
        row.action == "confirm-location"
        and row.status == "failed"
        and "failed to create/acquire the lock" in diagnostic_text.lower()
    ):
        diagnosis = {
            "title": "Repository-Sperre trotz Warteschlange nicht frei",
            "detail": (
                "Die Manager-Warteschlange hat die Standortbestätigung serialisiert. "
                "Borg selbst konnte die Repository-Sperre jedoch innerhalb von 600 Sekunden nicht erhalten."
            ),
            "action": (
                "Prüfen, ob außerhalb des BorgBackup Managers noch ein Borg-Prozess auf dieses Repository zugreift. "
                "Nur wenn sicher kein Prozess mehr läuft, die verwaiste Sperre mit break-lock entfernen."
            ),
        }
    duration = None
    if row.started_at:
        started = row.started_at.replace(tzinfo=timezone.utc) if row.started_at.tzinfo is None else row.started_at
        finished = row.finished_at
        if finished is None:
            finished = datetime.now(timezone.utc)
        elif finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        duration = max(0, int((finished - started).total_seconds()))
    version_source = diagnostic_text if log_offset is not None else combined
    version = row.borg_version if version_tuple(row.borg_version) else parse_borg_version(version_source)
    compatibility = classify_borg_version(version) if version else None
    display_error = extract_error_output(row.error or "")
    if not display_error and row.status in {"failed", "warning"}:
        display_error = extract_error_output(diagnostic_text)
    backup_progress = None
    restore_progress = None
    backup_item_activity = None
    backup_network = None
    if row.action == "backup":
        if active:
            backup_item_activity = get_run_item_activity(row.id)
            backup_network = get_run_network_activity(row.id)
        if backup_network is None and (
            row.backup_network_download_bytes is not None or row.backup_network_upload_bytes is not None
        ):
            backup_network = {
                "interfaces": [],
                "download_bytes": int(row.backup_network_download_bytes or 0),
                "upload_bytes": int(row.backup_network_upload_bytes or 0),
                "route_interface": "",
                "route_ip_address": "",
            }
    if row.action == "backup" and active:
        progress = get_run_progress(row.id)
        if progress:
            if row.job:
                baseline_bytes = (
                    row.backup_source_size_bytes_snapshot
                    if row.backup_source_size_bytes_snapshot is not None
                    else row.job.source_size_bytes
                )
                baseline_files = (
                    row.backup_source_file_count_snapshot
                    if row.backup_source_file_count_snapshot is not None
                    else row.job.source_file_count
                )
                eta = estimate_fixed_baseline_remaining(
                    progress=progress,
                    source_paths=json.loads(row.job.source_paths_json or "[]"),
                    total_bytes=baseline_bytes,
                    total_files=baseline_files,
                    total_origin=row.job.source_stats_origin,
                )
            else:
                eta = {
                    "estimated_total_files": None,
                    "estimated_total_bytes": None,
                    "estimated_percent": None,
                    "estimated_eta_seconds": None,
                    "estimated_remaining_bytes": None,
                    "estimated_remaining_files": None,
                    "estimate_file_factor": 1.0,
                    "estimate_basis": "fixed-1g-source-baseline",
                    "estimate_total_origin": None,
                    "estimate_baseline_exceeded": False,
                    "estimate_byte_baseline_exceeded": False,
                    "estimate_file_baseline_exceeded": False,
                    "estimate_byte_fallback_active": False,
                    "estimate_assumed_interface_gbps": 1.0,
                    "estimate_assumed_utilization_percent": 80,
                    "estimate_assumed_bytes_per_second": 100_000_000,
                    "current_source": None,
                }
            backup_progress = {**progress, **eta}

    if row.action == "restore":
        if active:
            restore_progress = get_run_restore_progress(row.id)
        if restore_progress is None and any(value is not None for value in (
            row.restore_total_size_bytes, row.restore_processed_size_bytes,
            row.restore_total_file_count, row.restore_processed_file_count,
        )):
            total_bytes = int(row.restore_total_size_bytes or 0)
            processed_bytes = int(row.restore_processed_size_bytes or 0)
            total_files = int(row.restore_total_file_count or 0)
            processed_files = int(row.restore_processed_file_count or 0)
            percent = (min(100.0, max(0.0, processed_bytes / total_bytes * 100.0)) if total_bytes else None)
            phase = (
                "finished" if row.status in {"success", "warning"}
                else "cancelled" if row.status == "cancelled"
                else "failed" if row.status == "failed"
                else "preparing"
            )
            average_rate = (processed_bytes / duration) if processed_bytes > 0 and duration and duration > 0 else 0.0
            restore_progress = {
                "phase": phase,
                "processed_bytes": processed_bytes,
                "total_bytes": total_bytes,
                "processed_files": processed_files,
                "total_files": total_files,
                "path": "",
                "bytes_per_second": average_rate,
                "eta_seconds": 0 if phase == "finished" else None,
                "percent": 100.0 if phase == "finished" and total_bytes else percent,
            }

    bbm_network = sample_manager_network() if active and log_offset is not None else None

    return {
        "id": row.id, "job_id": row.job_id, "retention_protected": bool(retention_protected),
        "job_name": (
            row.job_name_snapshot
            if row.action == "diff-archives" and row.job_name_snapshot
            else (row.job.name if row.job else row.job_name_snapshot)
        ),
        "action": row.action, "status": row.status,
        "command_preview": row.command_preview if include_details else "",
        "output": row.output if include_details else "", "error": display_error if include_details else "",
        "log_output": combined if include_details else "",
        "log_file_available": (
            run_log_path(row.id).is_file()
            if log_file_available is None else bool(log_file_available)
        ),
        "log_offset": live_log_offset, "log_reset": live_log_reset, "log_truncated": live_log_truncated,
        "created_at": iso_utc(row.created_at), "started_at": iso_utc(row.started_at), "finished_at": iso_utc(row.finished_at),
        "duration_seconds": duration, "diagnosis": diagnosis,
        "warning_summary": warning_summary,
        "trigger_type": row.trigger_type or "manual",
        "schedule_name": row.schedule_name_snapshot,
        "archive_name": row.archive_name_snapshot,
        "backup_original_size_bytes": row.backup_original_size_bytes,
        "backup_compressed_size_bytes": row.backup_compressed_size_bytes,
        "backup_deduplicated_size_bytes": row.backup_deduplicated_size_bytes,
        "backup_file_count": row.backup_file_count,
        "backup_progress": backup_progress,
        "restore_progress": restore_progress,
        "restore_total_size_bytes": row.restore_total_size_bytes,
        "restore_processed_size_bytes": row.restore_processed_size_bytes,
        "restore_total_file_count": row.restore_total_file_count,
        "restore_processed_file_count": row.restore_processed_file_count,
        "backup_item_activity": backup_item_activity,
        "backup_network": backup_network,
        "bbm_network": bbm_network,
        "borg_compatibility": ({
            "version": compatibility.version, "supported": compatibility.supported,
            "level": compatibility.level, "title": compatibility.title, "message": compatibility.message,
        } if compatibility else None),
    }


def diagnose_run(output: str, error: str) -> dict | None:
    text = f"{output}\n{error}".lower()
    connection_closed = "connection closed by remote host" in text and "is borg working on the server" in text
    if connection_closed:
        banner_seen = any(marker in text for marker in (
            "remote protocol version", "remote software version", "server host key",
        ))
        authenticated = "authenticated to " in text
        if not banner_seen:
            return {
                "title": "Repository-SSH vor Banner beendet",
                "detail": "Die TCP-Verbindung wurde angenommen, aber beendet, bevor ein SSH-Banner oder Hostschlüssel empfangen wurde. Borg, authorized_keys und der Geräteschlüssel wurden noch nicht erreicht.",
                "action": "Systemdiagnose prüfen: repository_sshd/SSH-Banner muss OK sein. Zusätzlich Portweiterleitung und sshd-Log prüfen; danach den Verbindungstest erneut starten.",
            }
        if authenticated:
            return {
                "title": "Repository-SSH angemeldet, Borg-Server beendet",
                "detail": "Die SSH-Anmeldung war erfolgreich; der Abbruch liegt danach beim Forced Command, borg serve oder Repository-Pfad.",
                "action": "borg-serve-Log, Forced Command, Repository-Berechtigungen und Borg-Versionen prüfen.",
            }
        return {
            "title": "Repository-SSH-Aushandlung oder Anmeldung beendet",
            "detail": "Der SSH-Server hat geantwortet, die Verbindung wurde aber vor einer bestätigten Anmeldung geschlossen.",
            "action": "sshd-Log, Hostschlüssel, authorized_keys und den repositoryspezifischen Geräteschlüssel prüfen.",
        }
    if "archive-spoofing-schwachstelle" in text or "kritische sicherheitswarnung" in text:
        return {
            "title": "Borg-Version mit kritischer Sicherheitswarnung",
            "detail": "Der Client bleibt wie gewünscht nutzbar, verwendet aber Borg 1.2.0 bis 1.2.4 mit bekannter Archive-Spoofing-Schwachstelle.",
            "action": "Zeitnah auf Borg 1.2.8 oder 1.4.x aktualisieren. Bis dahin Repository-Zugänge nur vertrauenswürdigen Clients geben.",
        }
    if "nutzbar, aber veraltet" in text:
        return {
            "title": "Borg-Version veraltet",
            "detail": "Der Client ist kompatibel und wird nicht blockiert, liegt aber unter dem empfohlenen Stand.",
            "action": "Bei Gelegenheit auf Borg 1.4.x aktualisieren.",
        }
    if "was previously located at" in text and ("do you want to continue" in text or "repository access aborted" in text):
        return {
            "title": "Repository-Standort geändert",
            "detail": "Borg hat dieselbe Repository-ID unter einer anderen URL erkannt und wartet auf eine einmalige Sicherheitsbestätigung.",
            "action": "Im Backup-Job unter Mehr → Prüfen den geänderten Repository-Standort bestätigen und danach den Verbindungstest erneut starten.",
        }
    passphrase_errors = (
        "incorrect passphrase",
        "passphrase is incorrect",
        "passphrase supplied in borg_passcommand is incorrect",
        "passphrase supplied is incorrect",
        "repository passphrase is incorrect",
    )
    if any(marker in text for marker in passphrase_errors):
        return {
            "title": "Passphrase abgelehnt",
            "detail": "Die gespeicherte Repository-Passphrase passt nicht.",
            "action": "Passphrase des Repositorys prüfen und neu hinterlegen.",
        }
    cache_lock = "failed to create/acquire the lock" in text and "lock.exclusive" in text
    manager_cache = any(marker in text for marker in (
        "/data/borg-cache/",
        "/repositories/.cache/borg/",
    ))
    source_cache = not manager_cache and any(marker in text for marker in (
        "/.cache/borgbackup-manager/",
        "/.cache/borg/",
    ))
    if cache_lock and source_cache:
        return {
            "title": "Lokaler Borg-Cache auf dem Gerät gesperrt",
            "detail": (
                "Die Sperre liegt im Benutzer-Cache des Quellgeräts und nicht im Repository. "
                "Bei /root/.cache/... ist /root das Home-Verzeichnis des per SSH verwendeten Benutzers root."
            ),
            "action": (
                "Auf dem Gerät prüfen, ob noch ein Borg-Prozess läuft. Neue BBM-Läufe verwenden einen "
                "eigenen Cache je Repository unter ~/.cache/borgbackup-manager und bereinigen dort nach "
                "bestätigtem Prozessende verbliebene Cache-Locks. Für diesen Fehler kein borg break-lock ausführen."
            ),
        }
    cases = [
        (("wird nicht unterstützt", "borg 2.x"), "Borg-Version nicht kompatibel", "Unterstützt werden Borg 1.2.0 bis 1.4.x. Borg 2.x ist nicht mit Borg-1.x-Repositories kompatibel.", "Borg 1.4 auf dem Client einsetzen und danach Verbindungstest sowie Repositoryprüfung wiederholen."),
        (("permission denied",), "Zugriff verweigert", "SSH-Schlüssel oder Dateiberechtigungen erlauben den Zugriff nicht.", "Repository-Zugang des Geräts erneut einrichten und UID/GID des Repository-Verzeichnisses prüfen."),
        (("repository is already locked", "failed to create/acquire the lock"), "Repository gesperrt", "Ein anderer Borg-Prozess hält die Repository-Sperre.", "Laufende Jobs prüfen; nur bei sicher verwaister Sperre break-lock verwenden."),
        (("no space left on device",), "Speicherplatz erschöpft", "Das Repository-Dateisystem hat keinen freien Speicherplatz.", "Speicher bereinigen oder Repository-Verzeichnis vergrößern."),
        (("unsupported version", "invalid rpc method"), "Borg-Versionen inkompatibel", "Client und Repository-Server sprechen kein kompatibles Borg-Protokoll.", "Auf Gerät und Manager dieselbe Borg-Hauptversion einsetzen und den Versions-Test wiederholen."),
    ]
    for alternatives, title, detail, action in cases:
        if any(marker in text for marker in alternatives):
            return {"title": title, "detail": detail, "action": action}
    return None


@app.get("/api/runs", dependencies=protected)
def list_runs(limit: int | None = None, offset: int = 0, status: str = "all"):
    effective_limit = min(limit or load_settings().runs_list_limit, 500)
    allowed = {"all", "active", "failed", "success", "warning", "cancelled", "queued", "running"}
    if status not in allowed:
        raise HTTPException(400, "Unsupported run status filter")
    query = select(Run).options(joinedload(Run.job))
    if status == "active":
        query = query.where(Run.status.in_(["queued", "running"]))
    elif status != "all":
        query = query.where(Run.status == status)
    query = query.order_by(Run.id.desc()).offset(max(offset, 0)).limit(effective_limit)
    with SessionLocal() as db:
        rows = db.scalars(query).all()
        available_logs = available_run_log_ids() if rows else set()
        protected_ids = retained_run_ids_for_existing_jobs(db) if rows else set()
        return [
            run_json(
                row, include_details=False,
                log_file_available=row.id in available_logs,
                retention_protected=row.id in protected_ids,
            )
            for row in rows
        ]


@app.get("/api/runs/storage", dependencies=admin_protected)
def run_storage():
    return run_storage_info()


@app.post("/api/runs/cleanup", dependencies=admin_protected)
def cleanup_runs(data: RunCleanupIn):
    before = run_storage_info()
    removed = cleanup_run_history(all_finished=data.mode == "all_finished")
    storage = run_storage_info()
    removed_deliveries = max(0, int(before.get("notification_deliveries") or 0) - int(storage.get("notification_deliveries") or 0))
    vacuumed = vacuum_database() if data.vacuum and (removed or removed_deliveries) else False
    return {
        "removed": removed,
        "notification_deliveries_removed": removed_deliveries,
        "vacuumed": vacuumed,
        "storage": storage,
    }


@app.get("/api/runs/{run_id}", dependencies=admin_protected)
def get_run(run_id: int, include_details: bool = True, live: bool = False, log_offset: int | None = None):
    with SessionLocal() as db:
        row = db.scalar(select(Run).options(joinedload(Run.job)).where(Run.id == run_id))
        if not row: raise HTTPException(404, "Run not found")
        return run_json(
            row,
            include_details=include_details,
            # Active live polling needs a representative head/tail window, not
            # the complete configured multi-megabyte view on every request.
            log_max_bytes=256 * 1024 if live else None,
            log_offset=log_offset if live else None,
            retention_protected=row.id in retained_run_ids_for_existing_jobs(db),
        )


@app.get("/api/backups", dependencies=admin_protected)
def backups() -> list[dict]:
    return list_full_backups()


@app.get("/api/backups/borg-cache/status", dependencies=admin_protected)
def borg_cache_status() -> dict:
    from app.manager_cache import manager_borg_cache_status
    return manager_borg_cache_status()


@app.post("/api/backups/borg-cache/cleanup", dependencies=admin_protected)
def cleanup_borg_cache(data: ManagerBorgCacheCleanupIn) -> dict:
    from app.manager_cache import cleanup_orphaned_manager_borg_data
    return cleanup_orphaned_manager_borg_data(data.entries)


@app.get("/api/backups/client-cache/status", dependencies=admin_protected)
def client_borg_cache_status() -> dict:
    from app.client_cache import scan_client_borg_caches
    return scan_client_borg_caches()


@app.post("/api/backups/client-cache/scan", dependencies=admin_protected)
def scan_selected_client_borg_cache(data: ClientBorgCacheScanIn) -> dict:
    from app.client_cache import scan_client_borg_caches
    return scan_client_borg_caches(data.host_ids)


@app.post("/api/backups/client-cache/cleanup", dependencies=admin_protected)
def cleanup_client_borg_cache(data: ClientBorgCacheCleanupIn) -> dict:
    from app.client_cache import cleanup_client_borg_caches
    entries = [item.model_dump() for item in data.entries]
    return cleanup_client_borg_caches(data.kind, entries)


def _validate_cache_backup_idle() -> None:
    with SessionLocal() as db:
        active = db.scalar(select(func.count()).select_from(Run).where(Run.status.in_(["queued", "running"]))) or 0
    if active:
        raise HTTPException(409, "Cache-Backups können nur ohne laufende oder wartende Ausführungen erstellt werden")


def _manager_backup_task_worker(
    task_id: str, *, label: str, passphrase: str, compression: str,
) -> None:
    try:
        update_manager_backup_task(task_id, status="running", stage="prepare", message="Manager-Backup wird vorbereitet …", percent=1.0)

        def progress(payload: dict) -> None:
            update_manager_backup_task(task_id, status="running", **payload)

        path = create_full_backup(
            APP_VERSION, label, passphrase, compression=compression, progress=progress,
        )
        backup = next(item for item in list_full_backups() if item["name"] == path.name)
        finish_manager_backup_task(task_id, backup=backup)
    except Exception as exc:
        error_id = log_unexpected_exception(
            f"Manager backup task {task_id} failed", exc=exc, logger_name="bbm.background",
        )
        fail_manager_backup_task(task_id, public_error_message(error_id))


def _cache_backup_task_worker(
    task_id: str, *, label: str, passphrase: str | None, encrypted: bool,
    include_manager_borg_cache: bool, include_client_borg_cache: bool,
    client_host_ids: list[int] | None, compression: str,
) -> None:
    try:
        update_manager_backup_task(task_id, status="running", stage="prepare", message="Cache-Backup wird vorbereitet …", percent=1.0)

        def progress(payload: dict) -> None:
            update_manager_backup_task(task_id, status="running", **payload)

        result = create_cache_backup_set(
            APP_VERSION,
            label,
            passphrase,
            encrypted=encrypted,
            include_manager_borg_cache=include_manager_borg_cache,
            include_client_borg_cache=include_client_borg_cache,
            client_host_ids=client_host_ids,
            compression=compression,
            progress=progress,
        )
        names = {path.name for path in result["paths"]}
        backups = [item for item in list_full_backups() if item["name"] in names]
        backups.sort(key=lambda item: item["name"])
        warning = " ".join(result.get("warnings") or []) or None
        finish_manager_backup_task(
            task_id,
            backup=backups[0] if backups else None,
            backups=backups,
            warning=warning,
        )
    except Exception as exc:
        error_id = log_unexpected_exception(
            f"Cache backup task {task_id} failed", exc=exc, logger_name="bbm.background",
        )
        fail_manager_backup_task(task_id, public_error_message(error_id))


@app.post("/api/backups/start", status_code=202, dependencies=admin_protected)
def start_backup(data: ManagerBackupCreateIn) -> dict:
    passphrase = data.passphrase.get_secret_value() if data.passphrase else None
    if not passphrase:
        raise HTTPException(400, "Neue Manager-Backups müssen verschlüsselt werden")
    task_id = secrets.token_hex(12)
    try:
        task = begin_manager_backup_task(task_id, label=data.label.strip() or "Manuell", backup_type="manager")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    thread = threading.Thread(
        target=_manager_backup_task_worker,
        kwargs={
            "task_id": task_id,
            "label": data.label,
            "passphrase": passphrase,
            "compression": data.compression,
        },
        name=f"bbm-manager-backup-{task_id[:8]}", daemon=True,
    )
    thread.start()
    return task


@app.post("/api/cache-backups", status_code=201, dependencies=admin_protected)
def create_cache_backup_sync(data: CacheBackupCreateIn) -> dict:
    """Synchronous cache-only backup endpoint."""
    try:
        if current_manager_backup_task(include_last=False):
            raise HTTPException(409, "Es wird bereits ein Backup erstellt")
        _validate_cache_backup_idle()
        passphrase = data.passphrase.get_secret_value() if data.passphrase else None
        result = create_cache_backup_set(
            APP_VERSION,
            data.label,
            passphrase,
            encrypted=data.encrypted,
            include_manager_borg_cache=data.include_manager_borg_cache,
            include_client_borg_cache=data.include_client_borg_cache,
            client_host_ids=data.client_host_ids,
            compression=data.compression,
        )
        names = {path.name for path in result["paths"]}
        backups = [item for item in list_full_backups() if item["name"] in names]
        return {"backups": backups, "warnings": result.get("warnings") or []}
    except (OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/cache-backups/start", status_code=202, dependencies=admin_protected)
def start_cache_backup(data: CacheBackupCreateIn) -> dict:
    _validate_cache_backup_idle()
    passphrase = data.passphrase.get_secret_value() if data.passphrase else None
    task_id = secrets.token_hex(12)
    try:
        task = begin_manager_backup_task(
            task_id,
            label=data.label.strip() or "Manuell",
            backup_type="cache",
            include_borg_cache=data.include_manager_borg_cache,
            include_client_borg_cache=data.include_client_borg_cache,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    thread = threading.Thread(
        target=_cache_backup_task_worker,
        kwargs={
            "task_id": task_id,
            "label": data.label,
            "passphrase": passphrase,
            "encrypted": data.encrypted,
            "include_manager_borg_cache": data.include_manager_borg_cache,
            "include_client_borg_cache": data.include_client_borg_cache,
            "client_host_ids": data.client_host_ids,
            "compression": data.compression,
        },
        name=f"bbm-cache-backup-{task_id[:8]}", daemon=True,
    )
    thread.start()
    return task


@app.get("/api/backups/tasks/current", dependencies=admin_protected)
def get_current_backup_task() -> dict:
    return current_manager_backup_task(include_last=False) or {"status": "idle"}


@app.get("/api/backups/tasks/{task_id}", dependencies=admin_protected)
def get_backup_task(task_id: str) -> dict:
    task = get_manager_backup_task(task_id)
    if not task:
        raise HTTPException(404, "Manager-Backup-Task nicht gefunden")
    return task


@app.post("/api/backups/{name}/client-caches/inspect", dependencies=admin_protected)
def inspect_manager_backup_client_caches(name: str, data: ManagerClientCacheInspectIn) -> dict:
    try:
        source = backup_path(name)
        passphrase = data.passphrase.get_secret_value() if data.passphrase else None
        return client_borg_cache_inventory(source, passphrase)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Backup not found") from exc
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/backups/{name}/client-caches/{host_id}/{repository_id}/restore", dependencies=admin_protected)
def restore_manager_backup_client_cache(
    name: str, host_id: int, repository_id: int, data: ManagerClientCacheRestoreIn
) -> dict:
    target_host_id = int(data.target_host_id or host_id)
    with SessionLocal() as db:
        active = db.scalar(
            select(func.count()).select_from(Run).where(Run.status.in_(["queued", "running"]))
        ) or 0
        if active:
            raise HTTPException(409, "Client-Cache kann nur ohne laufende oder wartende Ausführungen wiederhergestellt werden")
        target_host = db.get(Host, target_host_id)
        repository = db.get(Repository, repository_id)
        assigned = db.scalar(
            select(Job.id).where(Job.host_id == target_host_id, Job.repository_id == repository_id).limit(1)
        )
        if not target_host:
            raise HTTPException(404, "Zielgerät nicht gefunden")
        if not repository:
            raise HTTPException(404, "Repository nicht gefunden")
        if not assigned:
            raise HTTPException(409, "Zielgerät ist keinem Backup-Job dieses Repositorys zugeordnet")
        if not target_host.enabled:
            raise HTTPException(409, "Zielgerät ist deaktiviert; vor der Client-Cache-Wiederherstellung aktivieren")
        target_host_name = target_host.name
        repository_name = repository.name
    try:
        source = backup_path(name)
        passphrase = data.passphrase.get_secret_value() if data.passphrase else None
        result = restore_client_borg_cache_from_backup(
            source,
            passphrase,
            target_host,
            repository_id,
            source_host_id=host_id,
            source_repository_id=repository_id,
        )
        source_name = result.get("source_host_name") or f"Gerät #{host_id}"
        result["message"] = (
            f"Client-Borg-Cache von Gerät „{source_name}“ wurde auf Zielgerät „{target_host_name}“ "
            f"für Repository „{repository_name}“ wiederhergestellt."
        )
        if result.get("security_restore", {}).get("status") == "restored":
            result["message"] += " Fehlender Borg-Sicherheitsstatus wurde ebenfalls wiederhergestellt."
        elif result.get("security_restore", {}).get("status") == "kept_existing":
            result["message"] += " Vorhandener Borg-Sicherheitsstatus wurde aus Sicherheitsgründen beibehalten."
        return result
    except FileNotFoundError as exc:
        raise HTTPException(404, "Backup not found") from exc
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/backups/{name}/manager-cache/restore", dependencies=admin_protected)
def restore_manager_cache_backup(name: str, data: ManagerCacheRestoreIn) -> dict:
    with SessionLocal() as db:
        active = db.scalar(
            select(func.count()).select_from(Run).where(Run.status.in_(["queued", "running"]))
        ) or 0
    if active:
        raise HTTPException(409, "Manager-Cache kann nur ohne laufende oder wartende Ausführungen wiederhergestellt werden")
    try:
        source = backup_path(name)
        passphrase = data.passphrase.get_secret_value() if data.passphrase else None
        result = restore_manager_borg_cache_from_backup(source, passphrase)
        result["message"] = "Manager-Borg-Cache und Borg-Sicherheitsstatus wurden wiederhergestellt."
        return result
    except FileNotFoundError as exc:
        raise HTTPException(404, "Backup not found") from exc
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/backups/upload", status_code=201, dependencies=admin_protected)
async def upload_manager_backup(
    request: Request,
    x_bbm_backup_name: str = Header(..., alias="X-BBM-Backup-Name"),
) -> dict:
    name = x_bbm_backup_name.strip()
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max(BACKUP_MAX_FILE_BYTES, BACKUP_CACHE_MAX_FILE_BYTES):
                raise HTTPException(413, f"Backup-Datei überschreitet die zulässige Upload-Größe von {max(BACKUP_MAX_FILE_BYTES, BACKUP_CACHE_MAX_FILE_BYTES)} Bytes")
        except ValueError as exc:
            raise HTTPException(400, "Ungültige Content-Length") from exc
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    temporary = BACKUP_DIR / f".upload-{secrets.token_hex(16)}"
    written = 0
    try:
        with temporary.open("xb") as handle:
            os.chmod(temporary, 0o600)
            async for chunk in request.stream():
                written += len(chunk)
                if written > max(BACKUP_MAX_FILE_BYTES, BACKUP_CACHE_MAX_FILE_BYTES):
                    raise HTTPException(413, f"Backup-Datei überschreitet die zulässige Upload-Größe von {max(BACKUP_MAX_FILE_BYTES, BACKUP_CACHE_MAX_FILE_BYTES)} Bytes")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            return store_uploaded_backup(temporary, name)
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc)) from exc
    finally:
        temporary.unlink(missing_ok=True)


@app.get("/api/backups/{name}/download", dependencies=admin_protected)
def download_backup(name: str) -> FileResponse:
    try:
        path = backup_path(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "Backup not found") from exc
    media_type = "application/zip" if path.suffix == ".zip" else "application/octet-stream"
    return FileResponse(path, filename=path.name, media_type=media_type)


def _apply_manager_restore_and_restart(staging: Path) -> None:
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    engine.dispose()
    apply_prepared_restore(staging)
    os._exit(0)


@app.post("/api/backups/{name}/restore", dependencies=admin_protected)
def restore_manager_backup(name: str, data: ManagerBackupRestoreIn):
    with SessionLocal() as db:
        active = db.scalar(
            select(func.count()).select_from(Run).where(Run.status.in_(["queued", "running"]))
        ) or 0
    if active:
        raise HTTPException(409, "Manager-Backup kann während laufender oder wartender Ausführungen nicht wiederhergestellt werden")
    try:
        source = backup_path(name)
        passphrase = data.passphrase.get_secret_value()
        staging, manifest = prepare_full_backup_restore(source, passphrase)
        try:
            # The pre-restore snapshot contains the current master key and SSH
            # credentials and is therefore always encrypted with a separately
            # confirmed passphrase supplied for this restore operation.
            safety = create_full_backup(APP_VERSION, "vor-wiederherstellung", passphrase)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    except FileNotFoundError as exc:
        raise HTTPException(404, "Backup not found") from exc
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, str(exc)) from exc
    payload = {
        "status": "restoring",
        "backup": name,
        "backup_version": manifest.get("app_version"),
        "safety_backup": safety.name,
        "message": "Wiederherstellung vorbereitet. Der Container startet automatisch neu.",
    }
    return JSONResponse(payload, status_code=202, background=BackgroundTask(_apply_manager_restore_and_restart, staging))


@app.delete("/api/backups/{name}", status_code=204, dependencies=admin_protected)
def delete_backup(name: str) -> Response:
    try:
        backup_path(name).unlink()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "Backup not found") from exc
    return Response(status_code=204)


@app.delete("/api/runs/{run_id}", status_code=204, dependencies=admin_protected)
def delete_execution(run_id: int):
    with SessionLocal() as db:
        row = db.get(Run, run_id)
        if not row:
            raise HTTPException(404, "Run not found")
        if row.status in {"queued", "running"}:
            raise HTTPException(400, "Active runs cannot be deleted")
        if row.id in retained_run_ids_for_existing_jobs(db):
            raise HTTPException(409, "Dieses Protokoll ist der letzte aufbewahrte Backup-Stand eines vorhandenen Jobs. Verwende 'Alle Protokolle löschen', um auch geschützte letzte Stände zu entfernen.")
        db.delete(row)
        db.commit()
    delete_run_log(run_id)
    return Response(status_code=204)


@app.post("/api/runs/{run_id}/cancel", status_code=202, dependencies=admin_protected)
async def cancel_execution(run_id: int):
    try:
        task = cancel_run(run_id)
        try:
            # Keep the request open until the controlled Borg shutdown has
            # normally completed. This prevents the UI from offering a new run
            # while wrappers or repository locks are still being released.
            await asyncio.wait_for(asyncio.shield(task), timeout=30)
            return {"status": "cancelled"}
        except TimeoutError:
            return {"status": "cancelling"}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/runs/{run_id}/retry", status_code=202, dependencies=admin_protected)
async def retry_execution(run_id: int):
    try:
        return {"run_id": retry_run(run_id)}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
