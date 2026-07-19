from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Host(Base):
    __tablename__ = "hosts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    address: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    host_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    repository_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    borg_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    borg_version_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    borg_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Repository(Base):
    __tablename__ = "repositories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    location: Mapped[str] = mapped_column(String(500))
    passphrase_env: Mapped[str | None] = mapped_column(String(150), nullable=True)
    encrypted_passphrase: Mapped[str | None] = mapped_column(Text, nullable=True)
    encryption_mode: Mapped[str] = mapped_column(String(40), default="repokey-blake2")
    encrypted_keyfile: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    access_host_id: Mapped[int | None] = mapped_column(ForeignKey("hosts.id"), nullable=True)
    external_ssh_key_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_known_hosts_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    encrypted_external_ssh_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_ssh_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_external_known_hosts: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_host_fingerprint: Mapped[str | None] = mapped_column(String(120), nullable=True)
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    initialized: Mapped[bool] = mapped_column(Boolean, default=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compressed_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deduplicated_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    storage_guard_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    storage_guard_threshold_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra_env_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id"))
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"))
    source_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    exclude_patterns_json: Mapped[str] = mapped_column(Text, default="[]")
    archive_template: Mapped[str] = mapped_column(String(200), default="{hostname}-{now:%Y-%m-%dT%H:%M:%S}")
    archive_prefix: Mapped[str | None] = mapped_column(String(80), nullable=True)
    archive_prefix_history_json: Mapped[str] = mapped_column(Text, default="[]")
    schedule: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    compression: Mapped[str] = mapped_column(String(100), default="zstd,6")
    prune_options_json: Mapped[str] = mapped_column(Text, default="{}")
    create_options_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    host: Mapped[Host] = relationship()
    repository: Mapped[Repository] = relationship()


class JobIdReservation(Base):
    """Persist every allocated job ID so compact archive series are never reused."""
    __tablename__ = "job_id_reservations"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BackupSchedule(Base):
    __tablename__ = "backup_schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    expressions: Mapped[str] = mapped_column(String(2048))
    target_mode: Mapped[str] = mapped_column(String(20), default="hosts")
    target_host_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    target_repository_id: Mapped[int | None] = mapped_column(ForeignKey("repositories.id"), nullable=True)
    target_job_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    parallel_limit: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    repository: Mapped[Repository | None] = relationship()


class HostRepositoryAccess(Base):
    __tablename__ = "host_repository_access"
    __table_args__ = (UniqueConstraint("host_id", "repository_id", name="uq_host_repository_access"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    host: Mapped[Host] = relationship()
    repository: Mapped[Repository] = relationship()


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    job_name_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    repository_id: Mapped[int | None] = mapped_column(ForeignKey("repositories.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    command_preview: Mapped[str] = mapped_column(Text, default="")
    output: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    log_output: Mapped[str] = mapped_column(Text, default="")
    warning_summary_json: Mapped[str] = mapped_column(Text, default="")
    borg_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(20), default="manual")
    schedule_name_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    schedule_id_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_parallel_limit_snapshot: Mapped[int] = mapped_column(Integer, default=0)
    archive_name_snapshot: Mapped[str | None] = mapped_column(String(300), nullable=True)
    backup_original_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backup_compressed_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backup_deduplicated_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    job: Mapped[Job | None] = relationship()
    repository: Mapped[Repository | None] = relationship()


class ArchiveMount(Base):
    __tablename__ = "archive_mounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"))
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id"))
    archive: Mapped[str] = mapped_column(String(300))
    mount_path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    job: Mapped[Job] = relationship()
    repository: Mapped[Repository] = relationship()
    host: Mapped[Host] = relationship()
