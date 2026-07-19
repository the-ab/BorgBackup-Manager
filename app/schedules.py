from __future__ import annotations

import json
from collections import defaultdict

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.models import BackupSchedule, Host, Job, Repository

MAX_SCHEDULE_EXPRESSIONS = 24


def schedule_expressions(value: str | None) -> list[str]:
    """Return normalized five-field cron expressions from a stored schedule."""
    if value is None or not value.strip():
        return []
    raw_items = value.replace("\r", "\n").replace(";", "\n").split("\n")
    expressions: list[str] = []
    for raw in raw_items:
        expression = " ".join(raw.split())
        if not expression or expression in expressions:
            continue
        try:
            CronTrigger.from_crontab(expression)
        except ValueError as exc:
            raise ValueError(f"Ungültiger Cron-Ausdruck: {expression}") from exc
        expressions.append(expression)
    if len(expressions) > MAX_SCHEDULE_EXPRESSIONS:
        raise ValueError(f"Maximal {MAX_SCHEDULE_EXPRESSIONS} Zeitpunkte pro Zeitplan sind erlaubt")
    return expressions


def normalize_schedule(value: str | None) -> str | None:
    expressions = schedule_expressions(value)
    return ";".join(expressions) if expressions else None


def schedule_target_job_ids(db, schedule: BackupSchedule, *, enabled_jobs_only: bool = True) -> list[int]:
    query = select(Job.id).join(Host, Host.id == Job.host_id)
    if enabled_jobs_only:
        query = query.where(Job.enabled.is_(True), Host.enabled.is_(True))
    if schedule.target_mode == "hosts":
        host_ids = [int(value) for value in json.loads(schedule.target_host_ids_json or "[]")]
        if not host_ids:
            return []
        query = query.where(Job.host_id.in_(host_ids))
    elif schedule.target_mode == "repository":
        if not schedule.target_repository_id:
            return []
        query = query.where(Job.repository_id == schedule.target_repository_id)
    elif schedule.target_mode == "jobs":
        job_ids = [int(value) for value in json.loads(schedule.target_job_ids_json or "[]")]
        if not job_ids:
            return []
        query = query.where(Job.id.in_(job_ids))
    else:
        return []
    return list(db.scalars(query.order_by(Job.id)))


def schedule_assignments(db, *, enabled_only: bool = True) -> dict[int, list[BackupSchedule]]:
    query = select(BackupSchedule).order_by(BackupSchedule.name)
    if enabled_only:
        query = query.where(BackupSchedule.enabled.is_(True))
    result: dict[int, list[BackupSchedule]] = defaultdict(list)
    for schedule in db.scalars(query):
        for job_id in schedule_target_job_ids(db, schedule, enabled_jobs_only=False):
            result[job_id].append(schedule)
    return dict(result)



def validate_schedule_targets_exist(db, schedule: BackupSchedule) -> None:
    """Reject stale or forged target IDs while allowing valid targets without jobs yet."""
    if schedule.target_mode == "hosts":
        values = [int(value) for value in json.loads(schedule.target_host_ids_json or "[]")]
        existing = set(db.scalars(select(Host.id).where(Host.id.in_(values)))) if values else set()
        missing = sorted(set(values) - existing)
        if missing:
            raise ValueError("Unbekannte Geräte-ID(s): " + ", ".join(map(str, missing)))
    elif schedule.target_mode == "repository":
        if not schedule.target_repository_id or db.get(Repository, schedule.target_repository_id) is None:
            raise ValueError("Repository nicht gefunden")
    elif schedule.target_mode == "jobs":
        values = [int(value) for value in json.loads(schedule.target_job_ids_json or "[]")]
        existing = set(db.scalars(select(Job.id).where(Job.id.in_(values)))) if values else set()
        missing = sorted(set(values) - existing)
        if missing:
            raise ValueError("Unbekannte Backup-Job-ID(s): " + ", ".join(map(str, missing)))
    else:
        raise ValueError("Unbekannter Zeitplan-Zieltyp")

def validate_schedule_conflicts(db, candidate: BackupSchedule, *, exclude_schedule_id: int | None = None) -> None:
    if not candidate.enabled:
        return
    target_ids = set(schedule_target_job_ids(db, candidate, enabled_jobs_only=False))
    if not target_ids:
        return
    conflicts: dict[int, str] = {}
    for schedule in db.scalars(select(BackupSchedule).where(BackupSchedule.enabled.is_(True))):
        if exclude_schedule_id and schedule.id == exclude_schedule_id:
            continue
        overlap = target_ids.intersection(schedule_target_job_ids(db, schedule, enabled_jobs_only=False))
        for job_id in overlap:
            conflicts[job_id] = schedule.name
    if conflicts:
        jobs = {row.id: row.name for row in db.scalars(select(Job).where(Job.id.in_(conflicts)))}
        details = ", ".join(f"{jobs.get(job_id, job_id)} → {name}" for job_id, name in sorted(conflicts.items()))
        raise ValueError(f"Backup-Jobs dürfen nur einem aktiven Zeitplan zugeordnet sein: {details}")


def validate_job_schedule_conflicts(db, job: Job, *, exclude_job_id: int | None = None) -> None:
    """Ensure a newly created/changed job would not match multiple schedules."""
    matches: list[str] = []
    for schedule in db.scalars(select(BackupSchedule).where(BackupSchedule.enabled.is_(True))):
        if schedule.target_mode == "hosts":
            if job.host_id in [int(v) for v in json.loads(schedule.target_host_ids_json or "[]")]:
                matches.append(schedule.name)
        elif schedule.target_mode == "repository" and job.repository_id == schedule.target_repository_id:
            matches.append(schedule.name)
        elif schedule.target_mode == "jobs" and job.id and job.id in [int(v) for v in json.loads(schedule.target_job_ids_json or "[]")]:
            matches.append(schedule.name)
    if len(matches) > 1:
        raise ValueError("Der Backup-Job würde mehreren aktiven Zeitplänen zugeordnet: " + ", ".join(matches))


def migrate_legacy_job_schedules(db) -> int:
    migrated = 0
    existing_names = {name.casefold() for name in db.scalars(select(BackupSchedule.name))}
    for job in db.scalars(select(Job).where(Job.schedule.is_not(None))):
        normalized = normalize_schedule(job.schedule)
        if not normalized:
            job.schedule = None
            continue
        base = f"Migriert – {job.name}"[:100]
        name = base
        index = 2
        while name.casefold() in existing_names:
            suffix = f" ({index})"
            name = (base[:100-len(suffix)] + suffix)
            index += 1
        schedule = BackupSchedule(
            name=name,
            expressions=normalized,
            target_mode="jobs",
            target_job_ids_json=json.dumps([job.id]),
            target_host_ids_json="[]",
            enabled=job.enabled,
        )
        db.add(schedule)
        existing_names.add(name.casefold())
        job.schedule = None
        migrated += 1
    if migrated:
        db.commit()
    return migrated
