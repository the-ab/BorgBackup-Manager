from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tarfile
import unicodedata
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError

from app.archive_cache import invalidate_archive_cache, load_archive_cache, store_archive_cache
from app.archive_metadata import annotate_archive_devices, sort_archives_newest_first
from app.borg_compat import classify_borg_version, parse_borg_version, version_tuple
from app.borg_warnings import (
    parse_borg_warnings,
    unresolved_warning_summary,
    warning_diagnosis,
    warning_summary_from_json,
)
from app.backup_stats import parse_backup_statistics
from app.borg_stats import load_borg_json_document, merge_archive_statistics, parse_borg_info
from app.config import (
    BACKUP_DIR,
    BACKUP_MAX_FILE_BYTES,
    DATA_DIR,
    EXPORT_DIR,
    RUN_LOG_DIR,
    REPOSITORY_PUBLIC_HOST,
    REPOSITORY_ROOT,
    REPOSITORY_SSH_PORT,
    REPOSITORY_AUTHORIZED_KEYS_PATH,
    RUNTIME_SECRET_DIR,
    HEALTH_REQUIRE_SSHD,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SECURE_MODE,
    SESSION_TTL_SECONDS,
)
from app.backups import (
    apply_prepared_restore,
    backup_path,
    create_full_backup,
    list_full_backups,
    prepare_full_backup_restore,
    store_uploaded_backup,
)
from app.database import Base, SessionLocal, engine, migrate_schema
from app.external_repository import (
    fingerprint_known_hosts, generate_ed25519_keypair, normalize_known_hosts,
    public_key_from_private, repository_location_uses_ssh, scan_repository_host_key,
)
from app.repository_diagnostics import compact_repository_diagnostic
from app.notifications import (
    NotificationSettingsInput, NotificationSettingsOut, NotificationTestIn,
    clear_deliveries, list_deliveries, notification_settings_out,
    save_notification_settings, send_test_notification,
)
from app.repository_state import managed_repository_present
from app.log_filter import extract_error_output
from app.models import ArchiveMount, BackupSchedule, Host, HostRepositoryAccess, Job, JobIdReservation, Repository, Run
from app.runner import (
    archive_export_command,
    archive_info_command,
    browse_archive_command,
    browse_mount_command,
    mount_archive_command,
    host_version_command,
    repository_command,
    repository_keyfile_path,
    repository_validation_command,
    repository_size_command,
    repository_list_command,
    repository_archive_info_command,
    repository_archives_info_command,
    repository_browse_archive_command,
    job_archive_prefixes,
    manager_borg_argv,
    scan_host_key,
    unmount_archive_command,
)
from app.schemas import (
    ArchiveDeleteIn,
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
    JobIn,
    JobOut,
    BackupScheduleIn,
    BackupScheduleOut,
    LoginIn,
    PasswordChangeIn,
    ManagerBackupCreateIn,
    ManagerBackupRestoreIn,
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
)
from app.repository_sizes import (
    managed_repository_filesystem_size, repository_statistics_from_borg_info,
    store_repository_statistics,
)
from app.run_logs import append_run_log, cleanup_orphan_run_logs, delete_run_log, read_run_log, run_log_path, run_log_storage_bytes
from app.settings import load_settings, save_settings
from app.storage_guard import effective_storage_guard, repository_storage_filesystems
from app.time_utils import APP_TIMEZONE, APP_TIMEZONE_NAME, iso_utc, normalize_borg_timestamp
from app.schedules import (
    migrate_legacy_job_schedules, schedule_assignments, schedule_expressions,
    schedule_target_job_ids, validate_job_schedule_conflicts, validate_schedule_conflicts,
    validate_schedule_targets_exist,
)
from app.security_bootstrap import bootstrap_security_material
from app.security_migrate import migrate_repository_secrets
from app.security_store import (
    AuthUser, authenticate_user, change_own_password, consume_login_attempt, create_session, create_session_reload_token, create_user,
    delete_user as delete_security_user, get_session_user, get_session_user_by_reload_token, get_user, initialize_security_store,
    list_users, reset_login_rate_limit, revoke_session, revoke_session_by_reload_token, security_status, authentication_readiness, set_user_password, update_user, update_user_preferences,
)
from app.vault import (
    delete_repository_secrets, get_repository_secret, repository_secret_exists,
    set_repository_secret, store_repository_environment,
)
from app.config import LEGACY_ADMIN_TOKEN
from app.security import require_authenticated_user, require_token, session_cookie_values
from app.request_security import (
    browser_origin,
    client_address,
    forwarded_request_scheme,
    origin_matches_request,
    request_uses_https,
)
from app.service import (
    bootstrap_host_repository,
    clear_repository_cache,
    execute_interactive,
    cancel_run,
    controller_public_key,
    rotate_controller_key,
    queue_job_action,
    queue_repository_action,
    queue_repository_init,
    reset_managed_repository_state,
    retry_run,
    revoke_host_repository_access,
    scheduled_backup,
    sync_repository_access_assignments,
    trust_host_key,
)


STATIC = Path(__file__).parent / "static"
VERSION_FILE = Path(__file__).parent.parent / "VERSION"
APP_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.is_file() else "0.0.0"
scheduler = AsyncIOScheduler(timezone=APP_TIMEZONE)
_archive_cache_locks: dict[tuple[int, int, bool], asyncio.Lock] = {}


def _forwarded_request_scheme(request: Request) -> str:
    return forwarded_request_scheme(request)


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
    # v1.0.21 changes the default cookie name so a stale Secure cookie from an
    # older proxy configuration cannot mask the new browser session.
    if SESSION_COOKIE_NAME != "bbm_session":
        response.delete_cookie("bbm_session", path="/", httponly=True, samesite="strict")


def _delete_session_cookie(response: Response, request: Request) -> None:
    secure = _request_uses_https(request)
    for name in dict.fromkeys((SESSION_COOKIE_NAME, "bbm_session")):
        response.delete_cookie(
            name,
            path="/",
            secure=secure,
            httponly=True,
            samesite="strict",
        )


def _archive_cache_lock(repository_id: int, consider_checkpoints: bool) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = (id(loop), int(repository_id), bool(consider_checkpoints))
    lock = _archive_cache_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _archive_cache_locks[key] = lock
    return lock


def host_out(row: Host) -> HostOut:
    return HostOut.model_validate(row)


def repo_out(row: Repository) -> RepositoryOut:
    repository_present = managed_repository_present(row)
    settings = load_settings()
    effective_enabled, effective_threshold, guard_source = effective_storage_guard(row, settings)
    return RepositoryOut(
        id=row.id, name=row.name, location=row.location,
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
        storage_guard_effective_enabled=effective_enabled,
        storage_guard_effective_threshold_percent=effective_threshold,
        storage_guard_source=guard_source,
        storage_usage_total_bytes=None,
        storage_usage_used_bytes=None,
        storage_usage_free_bytes=None,
        storage_usage_percent=None,
        storage_guard_blocked=False,
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


def migrate_legacy_external_repository_access() -> None:
    """Retire the 0.9.3 access-client model without deleting repositories."""
    with SessionLocal() as db:
        changed = False
        for row in db.scalars(select(Repository).where(Repository.storage_path.is_(None))):
            if row.access_host_id or row.external_ssh_key_path or row.external_known_hosts_path:
                row.access_host_id = None
                row.external_ssh_key_path = None
                row.external_known_hosts_path = None
                if not repository_secret_exists(row, "external_ssh_private_key"):
                    row.initialized = False
                    row.validation_error = (
                        "Die frühere Zugriffs-Client-Konfiguration wurde entfernt. "
                        "Bitte einen Manager-SSH-Schlüssel und known_hosts hinterlegen."
                    )
                changed = True
        if changed:
            db.commit()


def migrate_repository_validation_diagnostics() -> None:
    """Condense verbose legacy SSH/Borg errors while retaining copyable details."""
    with SessionLocal() as db:
        changed = False
        for row in db.scalars(select(Repository).where(Repository.validation_error.is_not(None))):
            raw = (row.validation_details or row.validation_error or "").strip()
            if not raw:
                continue
            if (
                not row.validation_details
                and len(raw) <= 600
                and not re.search(r"(?:Remote:\s*)?debug\d+:|KEX algorithms:|SSH2_MSG_KEXINIT", raw, re.IGNORECASE)
            ):
                # Already actionable legacy text, for example a migration hint.
                row.validation_details = raw
                changed = True
                continue
            summary, details = compact_repository_diagnostic("", raw, 2)
            if row.validation_error != summary or row.validation_details != details:
                row.validation_error = summary
                row.validation_details = details
                changed = True
        if changed:
            db.commit()


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
    with SessionLocal() as db:
        changed = False
        for repository in db.scalars(select(Repository).where(Repository.storage_path.is_not(None))):
            slug = Path(repository.storage_path).name
            expected = managed_repository_location(slug)
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
        create_options=json.loads(row.create_options_json or "{}"), enabled=row.enabled,
        schedule_mode="scheduled" if names else "manual", schedule_names=names,
        repository_access_ready=repository_access_ready,
        source_size_bytes=row.source_size_bytes,
        source_file_count=row.source_file_count,
        source_stats_checked_at=row.source_stats_checked_at,
        source_stats_origin=row.source_stats_origin,
    )


def schedule_out(row: BackupSchedule, db) -> BackupScheduleOut:
    job_ids = schedule_target_job_ids(db, row, enabled_jobs_only=False)
    return BackupScheduleOut(
        id=row.id, name=row.name, expressions=row.expressions, target_mode=row.target_mode,
        target_host_ids=json.loads(row.target_host_ids_json or "[]"),
        target_repository_id=row.target_repository_id,
        target_job_ids=json.loads(row.target_job_ids_json or "[]"),
        parallel_limit=row.parallel_limit or 0,
        enabled=row.enabled, assigned_job_ids=job_ids, assigned_job_count=len(job_ids),
    )


def managed_repository_candidates() -> list[dict]:
    """Find Borg repositories directly below the managed storage root."""
    REPOSITORY_ROOT.mkdir(parents=True, exist_ok=True)
    root = REPOSITORY_ROOT.resolve()
    with SessionLocal() as db:
        registered = {
            Path(value).resolve()
            for value in db.scalars(select(Repository.storage_path).where(Repository.storage_path.is_not(None)))
            if value
        }
    candidates: list[dict] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if child.is_symlink() or not child.is_dir() or not (child / "config").is_file():
            continue
        resolved = child.resolve()
        if resolved in registered:
            continue
        repository_id = None
        try:
            for line in (child / "config").read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("id") and "=" in line:
                    repository_id = line.split("=", 1)[1].strip() or None
                    break
        except OSError:
            pass
        candidates.append({
            "directory_name": child.name,
            "path": str(resolved),
            "suggested_name": child.name.replace("-", " ").strip().title() or child.name,
            "repository_id": repository_id,
        })
    return candidates


def parse_archive_listing(output: str) -> list[dict]:
    try:
        payload = load_borg_json_document(output, expected_keys={"archives"})
    except json.JSONDecodeError as exc:
        raise ValueError("Borg returned an invalid archive list") from exc
    archives = payload.get("archives", []) if isinstance(payload, dict) else []
    if not isinstance(archives, list):
        raise ValueError("Borg archive list has an unexpected structure")
    result: list[dict] = []
    for item in archives:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        start_value = normalize_borg_timestamp(item.get("start") or item.get("time"))
        end_value = normalize_borg_timestamp(item.get("end"))
        duration = item.get("duration") if isinstance(item.get("duration"), (int, float)) else None
        if duration is None and isinstance(start_value, str) and isinstance(end_value, str):
            try:
                start_dt = datetime.fromisoformat(start_value.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_value.replace("Z", "+00:00"))
                duration = max(0.0, (end_dt - start_dt).total_seconds())
            except (ValueError, TypeError):
                duration = None
        result.append({
            "name": str(item["name"]),
            "id": item.get("id"),
            "start": start_value,
            "end": end_value,
            "duration": duration,
            "hostname": item.get("hostname"),
            "username": item.get("username"),
            "comment": item.get("comment") or "",
            "nfiles": item.get("nfiles"),
            "original_size": item.get("original_size"),
            "compressed_size": item.get("compressed_size"),
            "deduplicated_size": item.get("deduplicated_size"),
            "checkpoint": bool(re.search(r"\.checkpoint(?:\.\d+)?$", str(item["name"]))),
        })
    return sort_archives_newest_first(result)


def load_job_with_connections(db, job_id: int, require_client_access: bool = True) -> Job:
    job = db.scalar(
        select(Job)
        .options(joinedload(Job.host), joinedload(Job.repository))
        .where(Job.id == job_id)
    )
    if not job:
        raise HTTPException(404, "Job not found")
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


def borg_operation_error(output: str, error: str, return_code: int) -> HTTPException:
    summary, _details = compact_repository_diagnostic(output, error, return_code)
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
    row.schedule = None
    row.compression = data.compression
    row.prune_options_json = json.dumps(data.prune_options)
    row.create_options_json = create_options_json
    row.enabled = data.enabled
    if statistics_inputs_changed:
        row.source_size_bytes = None
        row.source_file_count = None
        row.source_stats_checked_at = None
        row.source_stats_origin = None


def repair_invalid_stored_borg_versions() -> int:
    """Remove impossible values produced by the old free-form log parser."""
    repaired = 0
    with SessionLocal() as db:
        for host in db.scalars(select(Host).where(Host.borg_version.is_not(None))):
            if version_tuple(host.borg_version) is None:
                host.borg_version = None
                host.borg_version_status = "unknown"
                host.borg_checked_at = None
                repaired += 1
        for run in db.scalars(select(Run).where(Run.borg_version.is_not(None))):
            if version_tuple(run.borg_version) is None:
                run.borg_version = None
                repaired += 1
        if repaired:
            db.commit()
    return repaired


def sync_job_archive_prefixes() -> None:
    with SessionLocal() as db:
        changed = False
        reserved_ids = set(db.scalars(select(JobIdReservation.id)))
        historical_ids = {
            value for value in db.scalars(select(Run.job_id).where(Run.job_id.is_not(None))) if value is not None
        }
        jobs = list(db.scalars(select(Job)))
        for job_id in sorted(historical_ids | {row.id for row in jobs}):
            if job_id not in reserved_ids:
                db.add(JobIdReservation(id=job_id))
                reserved_ids.add(job_id)
                changed = True
        for row in jobs:
            compact_prefix = f"bbm-{row.id}-"
            current_prefix = row.archive_prefix or f"bbm-job-{row.id}-"
            try:
                history = json.loads(row.archive_prefix_history_json or "[]")
            except (TypeError, json.JSONDecodeError):
                history = []
            if not isinstance(history, list):
                history = []
            history = [value for value in history if isinstance(value, str) and value]
            if current_prefix != compact_prefix and current_prefix not in history:
                history.append(current_prefix)
                changed = True
            if row.archive_prefix != compact_prefix:
                row.archive_prefix = compact_prefix
                changed = True
            serialized = json.dumps(history)
            if row.archive_prefix_history_json != serialized:
                row.archive_prefix_history_json = serialized
                changed = True
        if changed:
            db.commit()


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


def cleanup_run_history(days: int | None = None, *, all_finished: bool = False) -> int:
    retention_days = load_settings().run_retention_days if days is None else days
    if not all_finished and retention_days <= 0:
        return 0
    with SessionLocal() as db:
        query = select(Run.id).where(Run.status.notin_(["queued", "running"]))
        if not all_finished:
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            query = query.where(Run.created_at < cutoff)
        run_ids = list(db.scalars(query))
        if not run_ids:
            return 0
        db.execute(delete(Run).where(Run.id.in_(run_ids)))
        db.commit()
    for run_id in run_ids:
        delete_run_log(run_id)
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
        "log_file_bytes": run_log_storage_bytes(),
        "database_log_payload_bytes": database_payload,
        "database_file_bytes": database_file_bytes,
        "log_directory": str(RUN_LOG_DIR),
        "retention_days": load_settings().run_retention_days,
    }


def migrate_run_payloads_to_files() -> int:
    """Move legacy/full run output out of SQLite and keep only small previews.

    Older releases stored up to several MiB three times per execution. Existing
    data is copied to the persistent file log when no file exists, then reduced
    to bounded previews. The operation is idempotent.
    """
    migrated = 0
    preview_log = 16 * 1024
    preview_stdout = 4 * 1024
    preview_stderr = 8 * 1024
    max_file_bytes = load_settings().run_log_max_mib * 1024 * 1024
    with SessionLocal() as db:
        rows = db.scalars(
            select(Run).where(
                (Run.output != "") | (Run.error != "") | (Run.log_output != "")
            )
        ).all()
        for row in rows:
            combined = row.log_output or (row.output + ("\n" if row.output and row.error else "") + row.error)
            if combined and not run_log_path(row.id).is_file():
                append_run_log(row.id, combined, max_file_bytes)
            new_output = (row.output or "")[-preview_stdout:]
            new_error = extract_error_output(row.error or "")[-preview_stderr:]
            new_log = (combined or "")[-preview_log:]
            if row.output != new_output or row.error != new_error or row.log_output != new_log:
                row.output = new_output
                row.error = new_error
                row.log_output = new_log
                migrated += 1
        if migrated:
            db.commit()
    return migrated


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
            for job_id in job_ids:
                for index, expression in enumerate(expressions, start=1):
                    trigger = CronTrigger.from_crontab(expression, timezone=APP_TIMEZONE)
                    scheduler.add_job(
                        scheduled_backup, trigger, args=[job_id, schedule.name],
                        kwargs={"schedule_id": schedule.id, "schedule_parallel_limit": schedule.parallel_limit or 0},
                        id=f"schedule-{schedule.id}-job-{job_id}-{index}",
                        max_instances=1, coalesce=True, misfire_grace_time=3600, replace_existing=True,
                    )


def recover_interrupted_runs() -> None:
    """Close stale process state after an application/container restart."""
    with SessionLocal() as db:
        rows = db.scalars(select(Run).where(Run.status.in_(["queued", "running"]))).all()
        for row in rows:
            row.status = "failed"
            row.error = ((row.error + "\n") if row.error else "") + "Manager restarted while execution was active"
            row.finished_at = datetime.now(timezone.utc)
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global scheduler
    # AsyncIOScheduler binds itself to the current event loop when started.
    # Build a fresh instance for every application lifecycle so reloads and
    # clean restarts never reuse a scheduler attached to a closed loop.
    scheduler = AsyncIOScheduler(timezone=APP_TIMEZONE)
    _archive_cache_locks.clear()
    Base.metadata.create_all(engine)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    migrate_schema()
    initialize_security_store(LEGACY_ADMIN_TOKEN)
    # The container entrypoint materializes runtime TLS and SSH material as root
    # before dropping privileges.  Do not repeat that privileged operation in
    # the unprivileged Web API process.  Direct development/test starts still
    # bootstrap normally when the marker is absent.
    if os.getenv("BBM_RUNTIME_SECURITY_PREPARED") != "1":
        bootstrap_security_material()
    migrate_repository_secrets()
    migrate_legacy_external_repository_access()
    migrate_repository_validation_diagnostics()
    sync_managed_repository_locations()
    sync_job_archive_prefixes()
    with SessionLocal() as db:
        migrate_legacy_job_schedules(db)
    repair_invalid_stored_borg_versions()
    migrated_run_payloads = migrate_run_payloads_to_files()
    if migrated_run_payloads:
        vacuum_database()
    with SessionLocal() as db:
        cleanup_orphan_run_logs(set(db.scalars(select(Run.id))))
    sync_repository_access_assignments()
    recover_interrupted_runs()
    cleanup_run_history()
    scheduler.start()
    sync_schedules()
    yield
    scheduler.shutdown(wait=False)
    _archive_cache_locks.clear()


app = FastAPI(title="BorgBackup Manager", version=APP_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
protected = [Depends(require_token)]


def require_admin_access(user: AuthUser = Depends(require_token)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator permission required")
    return user


admin_protected = [Depends(require_admin_access)]


@app.middleware("http")
async def browser_security_headers(request: Request, call_next):
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
        authorization = request.headers.get("authorization", "")
        legacy_bearer = authorization.startswith("Bearer ")
        if not legacy_bearer:
            if request.headers.get("x-bbm-request", "") != "1":
                return JSONResponse({"detail": "Missing anti-CSRF request header"}, status_code=403)
            if not origin_matches_request(request):
                return JSONResponse({"detail": "Request origin does not match this BorgBackup Manager"}, status_code=403)
    response = await call_next(request)
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
    if request.url.path == "/" or request.url.path.startswith("/api/") or request.url.path.endswith(("/app.js", "/style.css", "/index.html")):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.post("/api/auth/login")
def login(data: LoginIn, request: Request, response: Response) -> dict:
    remote_address = client_address(request)
    allowed, retry_after = consume_login_attempt(data.username, remote_address)
    if not allowed:
        raise HTTPException(
            429,
            "Zu viele Anmeldeversuche von dieser Quelle. Bitte später erneut versuchen.",
            headers={"Retry-After": str(retry_after)},
        )
    user = authenticate_user(
        data.username, data.password.get_secret_value(), remote_address,
    )
    if user is None:
        raise HTTPException(401, "Benutzername oder Passwort ist falsch")
    reset_login_rate_limit(data.username, remote_address)
    token = create_session(
        user, SESSION_TTL_SECONDS, remote_address,
        request.headers.get("user-agent"),
    )
    _set_session_cookie(response, request, token)
    reload_token = create_session_reload_token(token, SESSION_TTL_SECONDS, request.headers.get("user-agent"))
    return {
        "status": "ok", "username": user.username, "role": user.role,
        "must_change_password": user.must_change_password,
        "language": user.language, "appearance": user.appearance,
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


@app.get("/api/users", dependencies=admin_protected)
def users_list() -> list[dict]:
    return list_users()


@app.get("/api/users/security-status", dependencies=admin_protected)
def users_security_status() -> dict:
    status = security_status()
    with SessionLocal() as db:
        legacy_rows = db.scalar(
            select(func.count()).select_from(Repository).where(or_(
                Repository.passphrase_env.is_not(None),
                Repository.encrypted_passphrase.is_not(None),
                Repository.encrypted_keyfile.is_not(None),
                Repository.encrypted_external_ssh_key.is_not(None),
                Repository.encrypted_external_known_hosts.is_not(None),
                Repository.external_ssh_key_path.is_not(None),
                Repository.external_known_hosts_path.is_not(None),
            ))
        ) or 0
    obsolete_private_files = []
    for path in (
        DATA_DIR / "ssh" / "id_ed25519",
        DATA_DIR / "repository-ssh" / "ssh_host_ed25519_key",
        DATA_DIR / "tls" / "privkey.pem",
    ):
        if path.is_file():
            obsolete_private_files.append(str(path))
    status.update({
        "legacy_repository_secret_rows": legacy_rows,
        "obsolete_private_files": obsolete_private_files,
        "sensitive_storage_ok": legacy_rows == 0 and not obsolete_private_files,
        "secret_database": status.get("database"),
        "master_key_note": "Der Master-Key bleibt als einziges externes Vertrauensanker-Geheimnis unter /data/security/master.key.",
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


def component_health_payload() -> tuple[dict, bool]:
    sshd = repository_sshd_listening()
    healthy = scheduler.running and (sshd or not HEALTH_REQUIRE_SSHD)
    return {
        "status": "ok" if healthy else "degraded",
        "scheduler": scheduler.running,
        "repository_sshd": sshd,
    }, healthy


@app.get("/api/health")
def health():
    """Public compatibility probe without internal component disclosure.

    This endpoint intentionally returns HTTP 200 even for a degraded
    repository-SSH probe because older update scripts treat every non-2xx
    response as a failed installation. Detailed diagnostics require an
    administrator session at `/api/system/health`.
    """
    _payload, healthy = component_health_payload()
    return {"status": "ok" if healthy else "degraded"}


@app.get("/api/health/strict")
def strict_health():
    """Public strict probe without internal component disclosure."""
    _payload, healthy = component_health_payload()
    result = {"status": "ok" if healthy else "degraded"}
    return result if healthy else JSONResponse(result, status_code=503)


@app.get("/api/system/health", dependencies=admin_protected)
def detailed_system_health():
    """Administrator-only component health details."""
    payload, healthy = component_health_payload()
    return payload if healthy else JSONResponse(payload, status_code=503)


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
            .where(HostRepositoryAccess.public_key.is_not(None))
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
            "runs": [run_json(run, include_details=False) for run in runs],
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
        "controller_public_key": public_key,
        "repository_endpoint": f"{REPOSITORY_PUBLIC_HOST}:{REPOSITORY_SSH_PORT}",
        "backup_directory": str(BACKUP_DIR),
        "timezone": APP_TIMEZONE_NAME,
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


@app.get("/api/settings", response_model=SettingsIn, dependencies=protected)
def get_settings() -> SettingsIn:
    return load_settings()


@app.put("/api/settings", response_model=SettingsIn, dependencies=admin_protected)
def update_settings(data: SettingsIn) -> SettingsIn:
    saved = save_settings(data)
    cleanup_run_history()
    return saved


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
    candidates = [Path(__file__).parent / filename, Path(__file__).parent.parent / filename]
    fallback = Path(__file__).parent / "RELEASE_NOTES.md"
    path = next((candidate for candidate in candidates if candidate.is_file()), fallback)
    return {
        "version": APP_VERSION,
        "language": "de" if german and path.name.endswith(".de.md") else "en",
        "content": path.read_text(encoding="utf-8") if path.is_file() else "",
    }


@app.get("/api/system/diagnostics", dependencies=admin_protected)
def system_diagnostics() -> dict:
    try:
        borg_version = subprocess.run(
            ["borg", "--version"], capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip() or "nicht verfügbar"
    except (OSError, subprocess.TimeoutExpired):
        borg_version = "nicht verfügbar"
    settings = load_settings()
    with SessionLocal() as db:
        managed_repositories = list(db.scalars(
            select(Repository).where(Repository.storage_path.is_not(None)).order_by(Repository.name)
        ))
    filesystems = repository_storage_filesystems(managed_repositories, REPOSITORY_ROOT, settings)
    storage = next((item for item in filesystems if Path(item["path"]) == REPOSITORY_ROOT.resolve()), None)
    if storage is not None:
        storage = {
            **storage,
            "guard_enabled": settings.storage_guard_enabled,
            "guard_threshold_percent": settings.storage_guard_threshold_percent,
            "guard_blocked": settings.storage_guard_enabled
            and float(storage["percent"]) >= settings.storage_guard_threshold_percent,
        }
    borg_log_path = Path("/data/logs/borg-serve.log")
    sshd_log_path = Path("/data/logs/sshd.log")
    server_log = borg_log_path.read_text(encoding="utf-8", errors="replace")[-20_000:] if borg_log_path.is_file() else ""
    sshd_log = sshd_log_path.read_text(encoding="utf-8", errors="replace")[-20_000:] if sshd_log_path.is_file() else ""
    checks = {}
    # The production API already runs as the unprivileged ``borg`` user.
    # Only a root caller may use runuser; manager_borg_argv therefore executes
    # these access checks directly in production and retains root-side
    # compatibility for development and maintenance contexts.
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
    checks["authorized_device_keys"] = len(authorized_lines)
    key_format_valid = all(
        line.startswith('restrict,command="/usr/local/bin/bbm-borg-serve --repository /repositories/')
        and " bbm-access-h" in line
        for line in authorized_lines
    )
    checks["repository_access_rows"] = 0
    checks["repository_access_ready_rows"] = 0
    checks["managed_repositories_shared_across_hosts"] = 0
    with SessionLocal() as db:
        checks["repository_access_rows"] = db.scalar(select(func.count()).select_from(HostRepositoryAccess)) or 0
        checks["repository_access_ready_rows"] = db.scalar(
            select(func.count()).select_from(HostRepositoryAccess).where(HostRepositoryAccess.public_key.is_not(None))
        ) or 0
        shared = db.execute(
            select(Job.repository_id, func.count(func.distinct(Job.host_id)))
            .join(Repository, Repository.id == Job.repository_id)
            .where(Repository.storage_path.is_not(None))
            .group_by(Job.repository_id)
            .having(func.count(func.distinct(Job.host_id)) > 1)
        ).all()
        checks["managed_repositories_shared_across_hosts"] = len(shared)
    checks["all_keys_use_forced_command"] = key_format_valid and (
        len(authorized_lines) == checks["repository_access_ready_rows"]
    )
    checks["repository_access_complete"] = (
        checks["repository_access_rows"]
        == checks["repository_access_ready_rows"]
        == len(authorized_lines)
    ) and checks["all_keys_use_forced_command"]
    return {
        "borg_version": borg_version, "repository_storage": storage,
        "repository_storage_filesystems": filesystems,
        "repository_server_checks": checks, "borg_serve_log": server_log,
        "sshd_log": sshd_log,
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
    sync_repository_access_assignments(); sync_schedules()
    return Response(status_code=204)


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


@app.post("/api/hosts/{host_id}/bootstrap-repository", dependencies=admin_protected)
async def bootstrap_repository(host_id: int) -> dict:
    try:
        keys = await bootstrap_host_repository(host_id)
        return {"status": "ready", "repository_keys": sorted(keys), "configured": len(keys)}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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
    with SessionLocal() as db:
        return [repo_out(x) for x in db.scalars(select(Repository).order_by(Repository.name))]


@app.get("/api/repositories/discover", dependencies=admin_protected)
def discover_repositories() -> list[dict]:
    try:
        return managed_repository_candidates()
    except OSError as exc:
        raise HTTPException(400, f"Repository directory cannot be scanned: {exc}") from exc


@app.post("/api/repositories/import", response_model=RepositoryOut, status_code=201, dependencies=admin_protected)
async def import_repository(data: RepositoryImportIn):
    root = REPOSITORY_ROOT.resolve()
    storage_path = (root / data.directory_name).resolve()
    if root not in storage_path.parents or not storage_path.is_dir() or not (storage_path / "config").is_file():
        raise HTTPException(400, "Selected directory is not a Borg repository below the managed storage root")
    secret = data.passphrase.get_secret_value() if data.passphrase else None
    keyfile = data.keyfile.get_secret_value() if data.keyfile else None
    with SessionLocal() as db:
        if db.scalar(select(Repository.id).where(Repository.storage_path == str(storage_path))):
            raise HTTPException(409, "Repository directory is already registered")
        row = Repository(
            name=data.name,
            location=managed_repository_location(storage_path.name),
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
            raise ValueError(error.strip() or output.strip() or f"Borg exit code {code}")
        with SessionLocal() as db:
            row = db.get(Repository, repository_id)
            if not row:
                raise ValueError("Repository registration disappeared")
            row.initialized = True
            db.commit()
            return repo_out(row)
    except Exception as exc:
        with SessionLocal() as db:
            row = db.get(Repository, repository_id)
            if row:
                db.delete(row)
                db.commit()
        delete_repository_secrets(repository_id)
        raise HTTPException(400, f"Existing repository could not be opened: {exc}") from exc
    finally:
        if key_path:
            key_path.unlink(missing_ok=True)


@app.post("/api/repositories/{repository_id}/refresh-size", dependencies=admin_protected)
async def refresh_size(repository_id: int) -> dict:
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        if not repository:
            raise HTTPException(404, "Repository not found")
        managed = bool(repository.storage_path)
        initialized = repository.initialized
        if not initialized:
            raise HTTPException(400, "Repository zuerst erfolgreich prüfen")
        try:
            command = repository_size_command(repository)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    filesystem_size = None
    if managed:
        try:
            filesystem_size = managed_repository_filesystem_size(repository_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    code, output, error = await execute_interactive(repository_id, command)
    if code not in {0, 1}:
        summary, details = compact_repository_diagnostic(output, error, code)
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
        "size_type": "filesystem-and-borg" if managed else "borg-deduplicated-compressed",
    }


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
            location=location,
            passphrase_env=None,
            encryption_mode=data.encryption_mode,
            storage_path=storage_path,
            access_host_id=None,
            external_ssh_key_path=None,
            external_known_hosts_path=None,
            external_ssh_public_key=external_credentials.get("external_ssh_public_key"),
            external_host_fingerprint=external_credentials.get("external_host_fingerprint"),
            initialized=False,
            validation_error=None,
            validation_details=None,
            storage_guard_enabled=data.storage_guard_enabled if data.managed else None,
            storage_guard_threshold_percent=data.storage_guard_threshold_percent if data.managed else None,
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

    if data.managed:
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
        external_credentials: dict[str, str | None] = {}
        if not data.managed:
            try:
                external_credentials = await prepare_external_repository_credentials(data, row)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        row.name = data.name
        row.passphrase_env = None
        row.encryption_mode = data.encryption_mode
        row.storage_guard_enabled = data.storage_guard_enabled if data.managed else None
        row.storage_guard_threshold_percent = data.storage_guard_threshold_percent if data.managed else None
        if not data.managed:
            row.location = data.location or row.location
            row.access_host_id = None
            row.external_ssh_key_path = None
            row.external_known_hosts_path = None
            row.external_ssh_public_key = external_credentials.get("external_ssh_public_key")
            row.external_host_fingerprint = external_credentials.get("external_host_fingerprint")
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

    invalidate_archive_cache(row_id)
    if data.managed:
        with SessionLocal() as db:
            return repo_out(db.get(Repository, row_id))

    with SessionLocal() as db:
        return repo_out(db.get(Repository, row_id))



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
        if db.scalar(select(func.count()).select_from(ArchiveMount).where(ArchiveMount.repository_id == row_id)):
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
            select(ArchiveMount.id).where(ArchiveMount.repository_id == repository_id).limit(1)
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
            .where(HostRepositoryAccess.public_key.is_not(None))
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
        if db.scalar(select(func.count()).select_from(ArchiveMount).where(ArchiveMount.job_id == row_id)):
            raise HTTPException(409, "Unmount all archives of this job before deleting it")
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
    try: return {"run_id": queue_job_action(job_id, action)}
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
    """Return the full repository archive dataset, preferably from persistent cache."""
    with SessionLocal() as db:
        repository = db.get(Repository, repository_id) if allow_unvalidated_external else load_repository_with_access(db, repository_id)
        if not repository:
            raise HTTPException(404, "Repository not found")
        repository_jobs = list(db.scalars(
            select(Job).options(joinedload(Job.host)).where(Job.repository_id == repository_id)
        ))

    if not force_refresh:
        cached = load_archive_cache(repository_id, consider_checkpoints)
        if cached:
            return copy.deepcopy(cached["data"]), repository_jobs, "cache", cached.get("generated_at")

    async with _archive_cache_lock(repository_id, consider_checkpoints):
        # A second request may have waited while the first request populated the
        # persistent cache.  Recheck before starting another expensive Borg scan.
        if not force_refresh:
            cached = load_archive_cache(repository_id, consider_checkpoints)
            if cached:
                return copy.deepcopy(cached["data"]), repository_jobs, "cache", cached.get("generated_at")

        info_command = repository_archives_info_command(repository)
        list_command = repository_list_command(repository, consider_checkpoints=consider_checkpoints)
        info_code, info_output, info_error = await execute_interactive(repository_id, info_command)
        if info_code not in {0, 1}:
            summary, _details = compact_repository_diagnostic(info_output, info_error, info_code)
            raise HTTPException(400, summary)
        try:
            normalized = parse_borg_info(info_output + "\n" + info_error)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        repository_statistics = normalized.get("repository", {})
        archives = normalized.get("archives", [])

        # Borg info contains the detailed statistics used by the compact archive
        # rows. A list call is only necessary for checkpoints or compatibility
        # fallbacks where Borg did not return an archive array.
        if consider_checkpoints or not archives:
            code, output, error = await execute_interactive(repository_id, list_command)
            if code not in {0, 1}:
                summary, _details = compact_repository_diagnostic(output, error, code)
                raise HTTPException(400, summary)
            try:
                listed = parse_archive_listing(output + "\n" + error)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            archives = merge_archive_statistics(listed, archives)

        archives = sort_archives_newest_first(archives)
        dataset = {"repository_statistics": repository_statistics, "archives": archives}
        cached = store_archive_cache(repository_id, consider_checkpoints, dataset)
        if repository_statistics.get("deduplicated_size") is not None:
            store_repository_statistics(
                repository_id,
                original_size=repository_statistics.get("original_size"),
                compressed_size=repository_statistics.get("compressed_size"),
                deduplicated_size=repository_statistics.get("deduplicated_size"),
            )
        return copy.deepcopy(dataset), repository_jobs, "repository", cached.get("generated_at")


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
    }


@app.get("/api/repositories/{repository_id}/archives/{archive}/info", dependencies=admin_protected)
async def repository_archive_info(repository_id: int, archive: str) -> dict:
    with SessionLocal() as db:
        repository = load_repository_with_access(db, repository_id)
        command = repository_archive_info_command(repository, archive)
    code, output, error = await execute_interactive(repository_id, command)
    if code not in {0, 1}:
        summary, _details = compact_repository_diagnostic(output, error, code)
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
            select(ArchiveMount.archive).where(
                ArchiveMount.repository_id == repository_id,
                ArchiveMount.archive.in_(data.archives),
            )
        ))
        if mounted:
            raise HTTPException(409, f"Mounted archives must be unmounted first: {', '.join(sorted(mounted))}")
        repository_jobs = list(db.scalars(
            select(Job).options(joinedload(Job.host)).where(Job.repository_id == repository_id)
        ))
        command = repository_list_command(repository, consider_checkpoints=True)
        repository_name = repository.name

    code, output, error = await execute_interactive(repository_id, command)
    if code not in {0, 1}:
        raise borg_operation_error(output, error, code)
    try:
        archives = parse_archive_listing(output + "\n" + error)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    archive_map = {archive["name"]: archive for archive in archives}
    missing = [archive for archive in data.archives if archive not in archive_map]
    if missing:
        raise HTTPException(404, f"Archives not found in this repository: {', '.join(missing)}")

    selected = [archive_map[name] for name in data.archives]
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


@app.post("/api/jobs/{job_id}/archive-delete", status_code=202, dependencies=admin_protected)
async def delete_archive(job_id: int, data: ArchiveDeleteIn) -> dict:
    """Backward-compatible single-delete endpoint using repository administration."""
    with SessionLocal() as db:
        job = load_job_with_connections(db, job_id, require_client_access=False)
        repository_id = job.repository_id
        subject = f"Gerät: {job.host.name}"
        if db.scalar(
            select(ArchiveMount.id).where(
                ArchiveMount.repository_id == repository_id,
                ArchiveMount.archive == data.archive,
            )
        ):
            raise HTTPException(409, "Archive is currently mounted and must be unmounted first")
    if not await archive_exists(job, data.archive):
        raise HTTPException(404, "Archive not found in this repository")
    try:
        return {
            "run_id": queue_repository_action(
                repository_id,
                "delete-archive",
                {"archives": [data.archive], "compact_after": data.compact_after},
                subject=subject,
            )
        }
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        status = 409 if "queued or running" in str(exc) else 400
        raise HTTPException(status, str(exc)) from exc


@app.post("/api/jobs/{job_id}/archive-rename", status_code=202, dependencies=admin_protected)
async def rename_archive(job_id: int, data: ArchiveRenameIn) -> dict:
    with SessionLocal() as db:
        job = load_job_with_connections(db, job_id, require_client_access=False)
        repository_jobs = list(db.scalars(select(Job).where(Job.repository_id == job.repository_id)))
        if db.scalar(
            select(ArchiveMount.id).where(
                ArchiveMount.repository_id == job.repository_id,
                ArchiveMount.archive == data.archive,
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
        job = load_job_with_connections(db, job_id, require_client_access=False)
    names = await repository_archive_names(job)
    missing = [name for name in (data.archive, data.second_archive) if name not in names]
    if missing:
        raise HTTPException(404, f"Archive not found: {', '.join(missing)}")
    try:
        return {"run_id": queue_job_action(job_id, "diff-archives", data.model_dump())}
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


def mount_json(row: ArchiveMount, job_name: str | None = None) -> dict:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "job_name": job_name or (row.job.name if row.job else None),
        "repository_id": row.repository_id,
        "host_id": row.host_id,
        "archive": row.archive,
        "mount_path": row.mount_path,
        "created_at": row.created_at,
    }


@app.get("/api/mounts", dependencies=admin_protected)
def list_mounts() -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(ArchiveMount).options(joinedload(ArchiveMount.job)).order_by(ArchiveMount.id.desc())
        ).all()
        return [mount_json(row) for row in rows]


@app.post("/api/jobs/{job_id}/mounts", status_code=201, dependencies=admin_protected)
async def mount_archive(job_id: int, data: ArchiveMountIn) -> dict:
    with SessionLocal() as db:
        job = load_job_with_connections(db, job_id)
        existing = db.scalar(
            select(ArchiveMount).where(
                ArchiveMount.job_id == job_id,
                ArchiveMount.archive == data.archive,
            )
        )
        if existing:
            return mount_json(existing, job.name)
    if not await archive_exists(job, data.archive):
        raise HTTPException(404, "Archive not found in this repository")
    command = mount_archive_command(job, data.archive)
    code, output, error = await execute_interactive(job.repository_id, command)
    if code != 0:
        raise borg_operation_error(output, error, code)
    match = re.search(r"^BBM_MOUNT_PATH=(.+)$", output, flags=re.MULTILINE)
    if not match:
        raise HTTPException(400, "Client did not return the archive mount path")
    mount_path = match.group(1).strip()
    with SessionLocal() as db:
        row = ArchiveMount(
            job_id=job_id,
            repository_id=job.repository_id,
            host_id=job.host_id,
            archive=data.archive,
            mount_path=mount_path,
        )
        db.add(row)
        db.commit()
        return mount_json(row, job.name)


@app.get("/api/mounts/{mount_id}/browse", dependencies=admin_protected)
async def browse_mount(mount_id: int, path: str = "") -> dict:
    with SessionLocal() as db:
        row = db.get(ArchiveMount, mount_id)
        if not row:
            raise HTTPException(404, "Archive mount not found")
        job = load_job_with_connections(db, row.job_id)
        command = browse_mount_command(job, row.mount_path, path)
        repository_id = row.repository_id
        archive = row.archive
    code, output, error = await execute_interactive(repository_id, command)
    if code != 0:
        raise borg_operation_error(output, error, code)
    fields = output.split("\x00")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 5:
        raise HTTPException(400, "Client returned an incomplete archive directory listing")
    entries = []
    type_names = {"d": "directory", "f": "file", "l": "symlink"}
    current = path.strip("/")
    for index in range(0, len(fields), 5):
        name, file_type, size, mtime, target = fields[index:index + 5]
        relative = f"{current}/{name}" if current else name
        entries.append({
            "name": name,
            "path": relative,
            "type": type_names.get(file_type, "other"),
            "size": int(size) if size.isdigit() else 0,
            "mtime": float(mtime) if mtime else None,
            "target": target or None,
        })
    entries.sort(key=lambda item: (item["type"] != "directory", item["name"].casefold()))
    parent = "/".join(current.split("/")[:-1]) if current else None
    return {"mount_id": mount_id, "archive": archive, "path": current, "parent": parent, "entries": entries}


@app.delete("/api/mounts/{mount_id}", status_code=204, dependencies=admin_protected)
async def unmount_archive(mount_id: int):
    with SessionLocal() as db:
        row = db.get(ArchiveMount, mount_id)
        if not row:
            raise HTTPException(404, "Archive mount not found")
        job = load_job_with_connections(db, row.job_id)
        command = unmount_archive_command(job, row.mount_path)
        repository_id = row.repository_id
    code, output, error = await execute_interactive(repository_id, command)
    if code != 0:
        raise borg_operation_error(output, error, code)
    with SessionLocal() as db:
        row = db.get(ArchiveMount, mount_id)
        if row:
            db.delete(row)
            db.commit()
    return Response(status_code=204)


def run_json(row: Run, *, include_details: bool = True) -> dict:
    file_log = None
    if include_details:
        settings = load_settings()
        file_log = read_run_log(row.id, settings.run_log_view_kib * 1024)
        combined = file_log or row.log_output or ((row.output or "") + ("\n" if row.output and row.error else "") + (row.error or ""))
    else:
        # Lists use only the bounded SQLite preview. The complete output is
        # read from /data/run-logs exclusively for the selected execution.
        combined = (row.log_output or row.error or row.output)[-16384:]
    active = row.status in {"queued", "running"}
    # The complete file log can be compacted and the bounded database log keeps
    # only a tail. The separately filtered stderr preview therefore remains an
    # important source for warning causes such as ``C``/``E`` item lines.
    diagnostic_text = combined + ("\n" + row.error if row.error else "")
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
    version = row.borg_version if version_tuple(row.borg_version) else parse_borg_version(combined)
    compatibility = classify_borg_version(version) if version else None
    display_error = extract_error_output(row.error or "")
    if not display_error and row.status in {"failed", "warning"}:
        display_error = extract_error_output(diagnostic_text)
    backup_statistics = {}
    if row.action == "backup":
        backup_statistics = parse_backup_statistics(combined)
    return {
        "id": row.id, "job_id": row.job_id,
        "job_name": row.job.name if row.job else row.job_name_snapshot,
        "action": row.action, "status": row.status,
        "command_preview": row.command_preview if include_details else "",
        "output": row.output if include_details else "", "error": display_error if include_details else "",
        "log_output": combined if include_details else "", "log_file_available": bool(file_log),
        "created_at": iso_utc(row.created_at), "started_at": iso_utc(row.started_at), "finished_at": iso_utc(row.finished_at),
        "duration_seconds": duration, "diagnosis": diagnosis,
        "warning_summary": warning_summary,
        "trigger_type": row.trigger_type or "manual",
        "schedule_name": row.schedule_name_snapshot,
        "archive_name": row.archive_name_snapshot or backup_statistics.get("archive_name"),
        "backup_original_size_bytes": row.backup_original_size_bytes if row.backup_original_size_bytes is not None else backup_statistics.get("original_size_bytes"),
        "backup_compressed_size_bytes": row.backup_compressed_size_bytes if row.backup_compressed_size_bytes is not None else backup_statistics.get("compressed_size_bytes"),
        "backup_deduplicated_size_bytes": row.backup_deduplicated_size_bytes if row.backup_deduplicated_size_bytes is not None else backup_statistics.get("deduplicated_size_bytes"),
        "backup_file_count": row.backup_file_count if row.backup_file_count is not None else backup_statistics.get("file_count"),
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
        return [run_json(x, include_details=False) for x in rows]


@app.get("/api/runs/storage", dependencies=admin_protected)
def run_storage():
    return run_storage_info()


@app.post("/api/runs/cleanup", dependencies=admin_protected)
def cleanup_runs(data: RunCleanupIn):
    removed = cleanup_run_history(all_finished=data.mode == "all_finished")
    vacuumed = vacuum_database() if data.vacuum and removed else False
    return {"removed": removed, "vacuumed": vacuumed, "storage": run_storage_info()}


@app.get("/api/runs/{run_id}", dependencies=admin_protected)
def get_run(run_id: int):
    with SessionLocal() as db:
        row = db.scalar(select(Run).options(joinedload(Run.job)).where(Run.id == run_id))
        if not row: raise HTTPException(404, "Run not found")
        return run_json(row)


@app.get("/api/backups", dependencies=admin_protected)
def backups() -> list[dict]:
    return list_full_backups()


@app.post("/api/backups", status_code=201, dependencies=admin_protected)
def create_backup(data: ManagerBackupCreateIn) -> dict:
    try:
        passphrase = data.passphrase.get_secret_value() if data.passphrase else None
        path = create_full_backup(APP_VERSION, data.label, passphrase)
        return next(item for item in list_full_backups() if item["name"] == path.name)
    except (OSError, ValueError) as exc:
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
            if int(content_length) > BACKUP_MAX_FILE_BYTES:
                raise HTTPException(413, f"Backup-Datei überschreitet die zulässige Größe von {BACKUP_MAX_FILE_BYTES} Bytes")
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
                if written > BACKUP_MAX_FILE_BYTES:
                    raise HTTPException(413, f"Backup-Datei überschreitet die zulässige Größe von {BACKUP_MAX_FILE_BYTES} Bytes")
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
        _archive_cache_locks.clear()
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
        passphrase = data.passphrase.get_secret_value() if data.passphrase else None
        safety_passphrase = data.safety_passphrase.get_secret_value()
        staging, manifest = prepare_full_backup_restore(source, passphrase)
        try:
            # The pre-restore snapshot contains the current master key and SSH
            # credentials and is therefore always encrypted with a separately
            # confirmed passphrase supplied for this restore operation.
            safety = create_full_backup(APP_VERSION, "vor-wiederherstellung", safety_passphrase)
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
