from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.schedules import normalize_schedule


ENCRYPTION_MODES = {
    "none", "authenticated", "authenticated-blake2", "repokey", "repokey-blake2",
    "keyfile", "keyfile-blake2",
}
FILES_CACHE_MODES = {
    "ctime,size,inode", "mtime,size,inode", "ctime,size", "mtime,size",
    "rechunk,ctime", "rechunk,mtime", "disabled",
}
TEMP_EXCLUDE_PATH = PurePosixPath("/", "tmp").as_posix()
VAR_TEMP_EXCLUDE_PATH = PurePosixPath("/", "var", "tmp").as_posix()


DEFAULT_CREATE_OPTIONS: dict[str, Any] = {
    "one_file_system": True,
    "exclude_caches": True,
    "exclude_nodump": True,
    "numeric_ids": False,
    "list_files": True,
    "files_cache": "ctime,size,inode",
    "checkpoint_interval": 1800,
}


def validate_compression_spec(value: str) -> str:
    """Validate Borg 1.2 compression syntax without invoking a shell."""
    tokens = value.split(",")

    def parse(index: int) -> int:
        if index >= len(tokens):
            raise ValueError("compression specification is incomplete")
        algorithm = tokens[index]
        if algorithm in {"none", "lz4"}:
            return index + 1
        if algorithm in {"zstd", "zlib", "lzma"}:
            next_index = index + 1
            if next_index < len(tokens) and tokens[next_index].isdigit():
                level = int(tokens[next_index])
                minimum, maximum = ((1, 22) if algorithm == "zstd" else (0, 9))
                if not minimum <= level <= maximum:
                    raise ValueError(f"{algorithm} level must be between {minimum} and {maximum}")
                next_index += 1
            return next_index
        if algorithm == "auto":
            return parse(index + 1)
        if algorithm == "obfuscate":
            if index + 1 >= len(tokens) or not tokens[index + 1].isdigit():
                raise ValueError("obfuscate requires a numeric mode")
            mode = int(tokens[index + 1])
            if mode not in {*range(1, 7), *range(110, 124)}:
                raise ValueError("unsupported obfuscate mode for Borg 1.2")
            return parse(index + 2)
        raise ValueError("unsupported Borg compression algorithm")

    if not value or any(token != token.strip() or not token for token in tokens) or parse(0) != len(tokens):
        raise ValueError("invalid Borg compression specification")
    return value


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EnabledStateIn(BaseModel):
    enabled: bool


class HostIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    host_key: str | None = None

    @field_validator("name", "address", "username")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("must be a single line")
        return value

    @field_validator("address", "username")
    @classmethod
    def safe_ssh_fields(cls, value: str) -> str:
        if any(c.isspace() for c in value) or value.startswith("-"):
            raise ValueError("must not contain whitespace or start with '-'")
        return value

    @field_validator("host_key")
    @classmethod
    def valid_host_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "\n" in value or "\r" in value:
            raise ValueError("must contain exactly one known_hosts line")
        parts = value.strip().split()
        if len(parts) != 3 or parts[1] != "ssh-ed25519":
            raise ValueError("must be an ssh-keyscan ed25519 known_hosts line")
        return value.strip()


class HostOut(HostIn, ORMModel):
    id: int
    repository_ready: bool = False
    borg_version: str | None = None
    borg_version_status: str | None = None
    borg_checked_at: datetime | None = None


class HostSshActionIn(BaseModel):
    host_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    command: str = Field(min_length=1, max_length=4000)
    timeout_seconds: int = Field(default=300, ge=5, le=3600)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def normalize_action_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(c in value for c in "\x00\r\n"):
            raise ValueError("action name must be a non-empty single-line value")
        return value

    @field_validator("command")
    @classmethod
    def normalize_action_command(cls, value: str) -> str:
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("SSH command must not be empty or contain NUL")
        return value


class HostSshActionOut(HostSshActionIn, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime


class HostScanIn(BaseModel):
    address: str = Field(min_length=1, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)

    @field_validator("address")
    @classmethod
    def safe_address(cls, value: str) -> str:
        value = value.strip()
        if any(c.isspace() for c in value) or value.startswith("-"):
            raise ValueError("must not contain whitespace or start with '-'")
        return value


class RepositoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    location: str | None = Field(default=None, max_length=500)
    passphrase_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    passphrase: SecretStr | None = None
    encryption_mode: str = "repokey-blake2"
    managed: bool = True
    external_ssh_private_key: SecretStr | None = None
    external_known_hosts: SecretStr | None = None
    generate_external_ssh_key: bool = True
    scan_external_host_key: bool = True
    keyfile: SecretStr | None = None
    extra_env: dict[str, str] = Field(default_factory=dict)
    storage_guard_enabled: bool | None = None
    storage_guard_threshold_percent: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def valid_repository_mode(self):
        secret = self.passphrase.get_secret_value() if self.passphrase is not None else None
        if secret is not None and (not secret or any(c in secret for c in "\x00\r\n")):
            raise ValueError("passphrase must be non-empty and single-line")
        if not self.managed and not self.location:
            raise ValueError("external repositories require a location")
        if self.managed and any((self.external_ssh_private_key, self.external_known_hosts)):
            raise ValueError("managed repositories must not define external SSH credentials")
        keyfile = self.keyfile.get_secret_value() if self.keyfile is not None else None
        if keyfile is not None and (not keyfile or "\x00" in keyfile):
            raise ValueError("keyfile must be non-empty")
        if self.managed and self.location:
            raise ValueError("managed repository locations are generated automatically")
        if self.passphrase_env:
            raise ValueError("Passwort-Umgebungsvariablen werden aus Sicherheitsgründen nicht mehr unterstützt")
        if self.managed and self.encryption_mode == "none" and self.passphrase:
            raise ValueError("unencrypted repositories must not define a passphrase")
        if self.managed and self.encryption_mode != "none" and not self.passphrase:
            raise ValueError("this encryption mode requires a passphrase")
        return self

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(c in value for c in "\x00\r\n"):
            raise ValueError("invalid repository name")
        return value

    @field_validator("location")
    @classmethod
    def safe_location(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or any(c in value for c in "\x00\r\n") or value.startswith("-"):
            raise ValueError("invalid repository location")
        return value

    @field_validator("external_ssh_private_key")
    @classmethod
    def safe_external_private_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        text = value.get_secret_value().strip()
        if not text or "\x00" in text or ("BEGIN OPENSSH " + "PRIVATE KEY") not in text:
            raise ValueError("external SSH key must be an OpenSSH private key")
        return SecretStr(text + "\n")

    @field_validator("external_known_hosts")
    @classmethod
    def safe_external_known_hosts(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        text = value.get_secret_value().strip()
        if not text or "\x00" in text:
            raise ValueError("known_hosts must not be empty")
        return SecretStr(text + "\n")

    @field_validator("encryption_mode")
    @classmethod
    def valid_encryption_mode(cls, value: str) -> str:
        if value not in ENCRYPTION_MODES:
            raise ValueError("unsupported Borg encryption mode")
        return value

    @field_validator("extra_env")
    @classmethod
    def safe_environment(cls, values: dict[str, str]) -> dict[str, str]:
        import re
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) for key in values):
            raise ValueError("environment variable names must be uppercase identifiers")
        if any("\x00" in value or "\n" in value or "\r" in value for value in values.values()):
            raise ValueError("environment values must be single-line strings")
        reserved = {
            "BORG_REPO", "BORG_RSH", "BORG_PASSPHRASE", "BORG_PASSPHRASE_FD",
            "BORG_PASSCOMMAND", "BORG_KEY_FILE", "BORG_CACHE_DIR", "BORG_SECURITY_DIR",
            "BORG_RELOCATED_REPO_ACCESS_IS_OK", "TZ", "PATH", "HOME", "SHELL", "USER", "LOGNAME",
            "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
            "ENV", "BASH_ENV", "IFS", "SSH_AUTH_SOCK", "SSH_AGENT_PID",
        }
        if reserved.intersection(values):
            raise ValueError("reserved Borg environment variables cannot be overridden")
        return values


class RepositoryOut(BaseModel):
    id: int
    name: str
    enabled: bool = True
    location: str
    passphrase_env: str | None = None
    encryption_mode: str
    managed: bool
    initialized: bool
    repository_present: bool = False
    has_passphrase: bool
    has_keyfile: bool = False
    has_external_ssh_key: bool = False
    external_ssh_public_key: str | None = None
    has_external_known_hosts: bool = False
    external_host_fingerprint: str | None = None
    validation_error: str | None = None
    validation_details: str | None = None
    validated_at: Any | None = None
    extra_env: dict[str, str] = Field(default_factory=dict)
    size_bytes: int | None = None
    original_size_bytes: int | None = None
    compressed_size_bytes: int | None = None
    deduplicated_size_bytes: int | None = None
    size_checked_at: Any | None = None
    storage_guard_enabled: bool | None = None
    storage_guard_threshold_percent: int | None = None
    mount_path: str | None = None
    storage_guard_effective_enabled: bool = False
    storage_guard_effective_threshold_percent: int = 95
    storage_guard_source: str = "global"
    storage_usage_total_bytes: int | None = None
    storage_usage_used_bytes: int | None = None
    storage_usage_free_bytes: int | None = None
    storage_usage_percent: float | None = None
    storage_usage_path: str | None = None
    storage_usage_checked_at: Any | None = None
    storage_usage_error: str | None = None
    storage_usage_source: str | None = None
    storage_guard_blocked: bool = False
    external_parallel_key: str | None = None
    external_parallel_label: str | None = None


class RepositoryImportIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    directory_name: str = Field(min_length=1, max_length=255)
    passphrase: SecretStr | None = None
    encryption_mode: str = "repokey-blake2"
    keyfile: SecretStr | None = None
    storage_guard_enabled: bool | None = None
    storage_guard_threshold_percent: int | None = Field(default=None, ge=1, le=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return RepositoryIn.normalize_name(value)

    @field_validator("directory_name")
    @classmethod
    def safe_directory_name(cls, value: str) -> str:
        value = value.strip()
        if value.startswith("/"):
            raise ValueError("directory_name must be relative to /repositories")
        value = value.strip("/")
        if not value or "\\" in value or any(c in value for c in "\x00\r\n"):
            raise ValueError("directory_name must be a safe relative path below /repositories")
        parts = value.split("/")
        if any(not part or part in {".", ".."} for part in parts):
            raise ValueError("directory_name contains an unsafe path segment")
        if len(parts) > 12:
            raise ValueError("directory_name is nested too deeply")
        return "/".join(parts)

    @field_validator("encryption_mode")
    @classmethod
    def valid_encryption_mode(cls, value: str) -> str:
        return RepositoryIn.valid_encryption_mode(value)

    @model_validator(mode="after")
    def validate_secrets(self):
        passphrase = self.passphrase.get_secret_value() if self.passphrase else None
        keyfile = self.keyfile.get_secret_value() if self.keyfile else None
        if passphrase is not None and (not passphrase or any(c in passphrase for c in "\x00\r\n")):
            raise ValueError("passphrase must be non-empty and single-line")
        if keyfile is not None and (not keyfile or "\x00" in keyfile):
            raise ValueError("keyfile must be non-empty")
        if self.encryption_mode == "none" and passphrase is not None:
            raise ValueError("unencrypted repositories must not define a passphrase")
        if self.encryption_mode != "none" and passphrase is None:
            raise ValueError("this encryption mode requires a passphrase")
        if self.encryption_mode.startswith("keyfile") and keyfile is None:
            raise ValueError("importing a keyfile repository requires the Borg keyfile content")
        if not self.encryption_mode.startswith("keyfile") and keyfile is not None:
            raise ValueError("keyfile content is only valid for keyfile repositories")
        return self


DEFAULT_EXCLUDE_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Linux-Systempfade",
        "patterns": ["/proc", "/sys", "/dev", "/run", TEMP_EXCLUDE_PATH, VAR_TEMP_EXCLUDE_PATH],
    },
]


class ExcludeTemplate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    patterns: list[str] = Field(min_length=1, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(c in value for c in "\x00\r\n"):
            raise ValueError("template name must be a non-empty single-line value")
        return value

    @field_validator("patterns")
    @classmethod
    def normalize_patterns(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in values:
            value = raw.strip()
            if not value:
                continue
            if any(c in value for c in "\x00\r\n"):
                raise ValueError("exclude template patterns must be single-line values")
            if value not in normalized:
                normalized.append(value)
        if not normalized:
            raise ValueError("exclude template must contain at least one pattern")
        return normalized


class SettingsIn(BaseModel):
    dashboard_recent_runs_limit: int = Field(default=10, ge=1, le=200)
    runs_list_limit: int = Field(default=100, ge=10, le=500)
    auto_refresh_seconds: int = Field(default=15, ge=5, le=300)
    list_max_height: int = Field(default=520, ge=240, le=1200)
    density: str = Field(default="comfortable", pattern=r"^(comfortable|compact)$")
    appearance: str = Field(default="auto", pattern=r"^(light|dark|auto)$")
    max_parallel_runs: int = Field(default=0, ge=0, le=64)
    source_stats_parallel_limit: int = Field(default=1, ge=1, le=64)
    update_check_enabled: bool = True
    update_check_interval_hours: int = Field(default=24, ge=1, le=720)
    mount_parallel_limits: dict[str, int] = Field(default_factory=dict)
    external_storage_parallel_limits: dict[str, int] = Field(default_factory=dict)
    repository_size_after_run: bool = True
    compact_after_prune: bool = True
    storage_guard_enabled: bool = True
    storage_guard_threshold_percent: int = Field(default=95, ge=1, le=100)
    run_retention_days: int = Field(default=90, ge=0, le=3650)
    run_log_max_mib: int = Field(default=50, ge=1, le=2048)
    run_log_view_kib: int = Field(default=2048, ge=256, le=65536)
    session_idle_timeout_seconds: int = Field(default=3600, ge=60, le=604800)
    header_network_enabled: bool = False
    header_network_source: str = Field(default="manager", pattern=r"^(manager|host)$")
    header_network_host_id: int | None = Field(default=None, ge=1)
    header_network_interfaces: list[str] = Field(default_factory=list)
    header_network_max_interfaces: int = Field(default=3, ge=1, le=5)
    header_network_interval_seconds: int = Field(default=5, ge=2, le=60)
    exclude_templates: list[ExcludeTemplate] = Field(
        default_factory=lambda: [ExcludeTemplate.model_validate(item) for item in DEFAULT_EXCLUDE_TEMPLATES],
        max_length=50,
    )

    @field_validator("mount_parallel_limits")
    @classmethod
    def safe_mount_parallel_limits(cls, values: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for raw_path, raw_limit in values.items():
            path = str(raw_path).strip().rstrip("/") or "/"
            pure = PurePosixPath(path)
            if not pure.is_absolute() or ".." in pure.parts or not (path == "/repositories" or path.startswith("/repositories/")):
                raise ValueError("mount parallel limit paths must stay below /repositories")
            limit = int(raw_limit)
            if not 0 <= limit <= 64:
                raise ValueError("mount parallel limits must be between 0 and 64")
            if limit > 0:
                normalized[path] = limit
        return normalized

    @field_validator("external_storage_parallel_limits")
    @classmethod
    def safe_external_storage_parallel_limits(cls, values: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for raw_key, raw_limit in values.items():
            key = str(raw_key).strip()
            if (
                not key.startswith("external:")
                or len(key) > 1000
                or any(char in key for char in "\x00\r\n")
            ):
                raise ValueError("external filesystem parallel limit key is invalid")
            limit = int(raw_limit)
            if not 0 <= limit <= 64:
                raise ValueError("external filesystem parallel limits must be between 0 and 64")
            if limit > 0:
                normalized[key] = limit
        return normalized

    @field_validator("header_network_interfaces")
    @classmethod
    def safe_header_network_interfaces(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in values:
            name = str(raw or "").strip().split("@", 1)[0]
            if not name or name == "lo" or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", name):
                raise ValueError("header network interface name is invalid")
            if name not in normalized:
                normalized.append(name)
        if len(normalized) > 5:
            raise ValueError("at most five header network interfaces are allowed")
        return normalized

    @model_validator(mode="after")
    def header_network_selection_within_limit(self):
        if len(self.header_network_interfaces) > int(self.header_network_max_interfaces):
            raise ValueError("selected header network interfaces exceed configured display limit")
        return self

    @field_validator("exclude_templates")
    @classmethod
    def unique_template_names(cls, values: list[ExcludeTemplate]) -> list[ExcludeTemplate]:
        names: set[str] = set()
        for template in values:
            key = template.name.casefold()
            if key in names:
                raise ValueError("exclude template names must be unique")
            names.add(key)
        return values


class RunCleanupIn(BaseModel):
    mode: str = Field(default="expired", pattern=r"^(expired|all_finished)$")
    vacuum: bool = True


class RepositoryUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    enabled: bool | None = None
    location: str | None = Field(default=None, max_length=500)
    passphrase_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    passphrase: SecretStr | None = None
    encryption_mode: str = "repokey-blake2"
    managed: bool
    external_ssh_private_key: SecretStr | None = None
    external_known_hosts: SecretStr | None = None
    generate_external_ssh_key: bool = False
    scan_external_host_key: bool = False
    keyfile: SecretStr | None = None
    extra_env: dict[str, str] = Field(default_factory=dict)
    storage_guard_enabled: bool | None = None
    storage_guard_threshold_percent: int | None = Field(default=None, ge=1, le=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return RepositoryIn.normalize_name(value)

    @field_validator("location")
    @classmethod
    def safe_location(cls, value: str | None) -> str | None:
        return RepositoryIn.safe_location(value)

    @field_validator("external_ssh_private_key")
    @classmethod
    def safe_external_private_key(cls, value: SecretStr | None) -> SecretStr | None:
        return RepositoryIn.safe_external_private_key(value)

    @field_validator("external_known_hosts")
    @classmethod
    def safe_external_known_hosts(cls, value: SecretStr | None) -> SecretStr | None:
        return RepositoryIn.safe_external_known_hosts(value)

    @field_validator("encryption_mode")
    @classmethod
    def valid_encryption_mode(cls, value: str) -> str:
        return RepositoryIn.valid_encryption_mode(value)

    @field_validator("extra_env")
    @classmethod
    def safe_environment(cls, values: dict[str, str]) -> dict[str, str]:
        return RepositoryIn.safe_environment(values)

    @model_validator(mode="after")
    def valid_update(self):
        secret = self.passphrase.get_secret_value() if self.passphrase is not None else None
        if secret is not None and (not secret or any(c in secret for c in "\x00\r\n")):
            raise ValueError("passphrase must be non-empty and single-line")
        if not self.managed and not self.location:
            raise ValueError("external repositories require a location")
        if self.managed and any((self.external_ssh_private_key, self.external_known_hosts, self.generate_external_ssh_key, self.scan_external_host_key)):
            raise ValueError("managed repositories must not define external SSH credentials")
        keyfile = self.keyfile.get_secret_value() if self.keyfile is not None else None
        if keyfile is not None and (not keyfile or "\x00" in keyfile):
            raise ValueError("keyfile must be non-empty")
        if self.encryption_mode == "none" and (self.passphrase or self.passphrase_env):
            raise ValueError("unencrypted repositories must not define a passphrase")
        return self


def validate_create_options(values: dict[str, Any]) -> dict[str, Any]:
    merged = {**DEFAULT_CREATE_OPTIONS, **values}
    unknown = set(merged) - set(DEFAULT_CREATE_OPTIONS)
    if unknown:
        raise ValueError(f"unsupported create option: {sorted(unknown)[0]}")
    for key in ("one_file_system", "exclude_caches", "exclude_nodump", "numeric_ids", "list_files"):
        if not isinstance(merged[key], bool):
            raise ValueError(f"{key} must be boolean")
    if merged["files_cache"] not in FILES_CACHE_MODES:
        raise ValueError("unsupported Borg files-cache mode")
    checkpoint = merged["checkpoint_interval"]
    if isinstance(checkpoint, bool) or not isinstance(checkpoint, int) or not 60 <= checkpoint <= 86400:
        raise ValueError("checkpoint_interval must be between 60 and 86400 seconds")
    return merged


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    host_id: int = Field(gt=0)
    repository_id: int = Field(gt=0)
    source_paths: list[str] = Field(min_length=1)
    exclude_patterns: list[str] = Field(default_factory=list)
    archive_template: str = Field(default="{hostname}-{now:%Y-%m-%dT%H:%M:%S}", min_length=1, max_length=200)
    compression: str = Field(default="zstd,6", max_length=100)
    prune_options: dict[str, int] = Field(default_factory=dict)
    create_options: dict[str, Any] = Field(default_factory=lambda: dict(DEFAULT_CREATE_OPTIONS))
    manual_prune_after_backup: bool = False
    manual_compact_after_prune: bool = False
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(c in value for c in "\x00\r\n"):
            raise ValueError("invalid job name")
        return value

    @field_validator("source_paths")
    @classmethod
    def absolute_sources(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in values:
            value = raw.strip()
            path = PurePosixPath(value)
            if not value.startswith("/") or value.startswith("-") or ".." in path.parts:
                raise ValueError("source paths must be safe absolute POSIX paths")
            if any(c in value for c in "\x00\r\n"):
                raise ValueError("source paths must be single-line values")
            if value not in normalized:
                normalized.append(value)
        return normalized

    @field_validator("exclude_patterns")
    @classmethod
    def safe_excludes(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in values:
            value = raw.strip()
            if not value:
                continue
            if any(c in value for c in "\x00\r\n"):
                raise ValueError("exclude patterns must be single-line values")
            if value not in normalized:
                normalized.append(value)
        return normalized

    @field_validator("archive_template")
    @classmethod
    def valid_archive_template(cls, value: str) -> str:
        value = value.strip()
        if any(c in value for c in "\x00\r\n/") or "::" in value or value.startswith("-"):
            raise ValueError("archive template contains unsafe characters")
        if "{now" not in value and "{utcnow" not in value:
            raise ValueError("archive template must contain {now...} or {utcnow...} to avoid collisions")
        return value

    @field_validator("compression")
    @classmethod
    def valid_compression(cls, value: str) -> str:
        return validate_compression_spec(value)

    @field_validator("prune_options")
    @classmethod
    def valid_prune_options(cls, values: dict[str, int]) -> dict[str, int]:
        allowed = {"last", "hourly", "daily", "weekly", "monthly", "yearly"}
        if set(values) - allowed:
            raise ValueError("unsupported prune retention key")
        normalized: dict[str, int] = {}
        for key, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 10000:
                raise ValueError("prune retention values must be integers between 0 and 10000")
            if value > 0:
                normalized[key] = value
        return normalized

    @field_validator("create_options")
    @classmethod
    def valid_create_options(cls, values: dict[str, Any]) -> dict[str, Any]:
        return validate_create_options(values)

    @model_validator(mode="after")
    def valid_manual_maintenance(self):
        if self.manual_compact_after_prune and not self.manual_prune_after_backup:
            raise ValueError("manual compact requires manual prune")
        if self.manual_prune_after_backup and not self.prune_options:
            raise ValueError("manual prune requires at least one positive retention rule")
        return self


class JobOut(JobIn):
    id: int
    repository_enabled: bool = True
    archive_prefix: str
    archive_prefixes: list[str] = Field(default_factory=list)
    schedule_mode: str = "manual"
    schedule_names: list[str] = Field(default_factory=list)
    repository_access_ready: bool = False
    source_size_bytes: int | None = None
    source_file_count: int | None = None
    source_stats_checked_at: datetime | None = None
    source_stats_origin: str | None = None
    source_stats_limitations: list[dict[str, Any]] = Field(default_factory=list)


class BackupScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expressions: str = Field(min_length=1, max_length=2048)
    target_mode: str = Field(pattern=r"^(hosts|repository|jobs)$")
    target_host_ids: list[int] = Field(default_factory=list, max_length=500)
    target_repository_id: int | None = Field(default=None, gt=0)
    target_job_ids: list[int] = Field(default_factory=list, max_length=500)
    parallel_limit: int = Field(default=0, ge=0, le=64)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(c in value for c in "\x00\r\n"):
            raise ValueError("Ungültiger Zeitplanname")
        return value

    @field_validator("expressions")
    @classmethod
    def normalize_expressions(cls, value: str) -> str:
        try:
            return normalize_schedule(value) or ""
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("target_host_ids", "target_job_ids")
    @classmethod
    def normalize_ids(cls, values: list[int]) -> list[int]:
        result: list[int] = []
        for value in values:
            if value <= 0:
                raise ValueError("IDs müssen positiv sein")
            if value not in result:
                result.append(value)
        return result

    @model_validator(mode="after")
    def validate_target(self):
        if self.target_mode == "hosts" and not self.target_host_ids:
            raise ValueError("Mindestens ein Gerät auswählen")
        if self.target_mode == "repository" and not self.target_repository_id:
            raise ValueError("Repository auswählen")
        if self.target_mode == "jobs" and not self.target_job_ids:
            raise ValueError("Mindestens einen Backup-Job auswählen")
        return self


class BackupScheduleOut(BackupScheduleIn):
    id: int
    assigned_job_ids: list[int] = Field(default_factory=list)
    assigned_job_count: int = 0
    runnable_job_count: int = 0
    repository_disabled_job_count: int = 0


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr


class PasswordChangeIn(BaseModel):
    current_password: SecretStr
    new_password: SecretStr
    new_password_confirm: SecretStr

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password.get_secret_value() != self.new_password_confirm.get_secret_value():
            raise ValueError("Neue Passwörter stimmen nicht überein")
        return self


class UserCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: SecretStr
    password_confirm: SecretStr
    role: str = Field(default="user", pattern=r"^(admin|user)$")
    must_change_password: bool = True

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password.get_secret_value() != self.password_confirm.get_secret_value():
            raise ValueError("Passwörter stimmen nicht überein")
        return self


class UserUpdateIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    role: str = Field(pattern=r"^(admin|user)$")
    enabled: bool = True


class UserPreferencesIn(BaseModel):
    language: str = Field(default="de", pattern=r"^(de|en)$")
    appearance: str = Field(default="auto", pattern=r"^(auto|light|dark)$")


class UserPasswordResetIn(BaseModel):
    password: SecretStr
    password_confirm: SecretStr
    must_change_password: bool = True

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password.get_secret_value() != self.password_confirm.get_secret_value():
            raise ValueError("Passwörter stimmen nicht überein")
        return self


class RestoreIn(BaseModel):
    archive: str = Field(min_length=1, max_length=300)
    paths: list[str] = Field(default_factory=list)
    restore_mode: str = Field(default="original", pattern="^(original|target)$")
    target_directory: str | None = Field(default=None, max_length=500)
    target_layout: str = Field(default="selection-root", pattern="^(selection-root|archive-paths)$")
    dry_run: bool = True
    overwrite_existing: bool = False
    allow_legacy_archive: bool = False

    @field_validator("paths")
    @classmethod
    def valid_paths(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            value = value.strip().strip("/")
            path = PurePosixPath(value)
            if not value or value.startswith("-") or ".." in path.parts or any(c in value for c in "\x00\r\n"):
                raise ValueError("restore paths must be relative archive paths without '..'")
            normalized.append(value)
        return normalized

    @model_validator(mode="after")
    def valid_destination(self):
        if self.restore_mode == "original":
            if not self.paths:
                raise ValueError("restoring to original locations requires at least one selected file or directory")
            self.target_directory = None
            if not self.dry_run and not self.overwrite_existing:
                raise ValueError("in-place restore requires explicit overwrite confirmation")
        else:
            target = (self.target_directory or "").strip()
            if not target:
                raise ValueError("target directory is required for an alternative restore destination")
            path = PurePosixPath(target)
            if not target.startswith("/") or ".." in path.parts or any(c in target for c in "\x00\r\n"):
                raise ValueError("restore target must be a safe absolute path")
            self.target_directory = target
            self.overwrite_existing = False
        return self


class ArchiveExportIn(BaseModel):
    archive: str = Field(min_length=1, max_length=300)
    paths: list[str] = Field(min_length=1, max_length=5000)

    @field_validator("archive")
    @classmethod
    def valid_archive(cls, value: str) -> str:
        value = value.strip()
        if not value or value.startswith("-") or "::" in value or any(c in value for c in "\x00\r\n/"):
            raise ValueError("invalid archive name")
        return value

    @field_validator("paths")
    @classmethod
    def valid_paths(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            value = value.strip().strip("/")
            path = PurePosixPath(value)
            if not value or value.startswith("-") or ".." in path.parts or any(c in value for c in "\x00\r\n"):
                raise ValueError("export paths must be relative archive paths without '..'")
            normalized.append(value)
        if not normalized:
            raise ValueError("at least one archive path must be selected")
        return normalized


class ArchiveDeleteIn(BaseModel):
    archive: str = Field(min_length=1, max_length=300)
    compact_after: bool = True

    @field_validator("archive")
    @classmethod
    def valid_archive(cls, value: str) -> str:
        value = value.strip()
        if (
            not value
            or value.startswith("-")
            or "::" in value
            or any(c in value for c in "\x00\r\n/")
        ):
            raise ValueError("invalid archive name")
        return value


class ArchiveBulkDeleteIn(BaseModel):
    archives: list[str] = Field(min_length=1, max_length=200)
    compact_after: bool = True

    @field_validator("archives")
    @classmethod
    def valid_archives(cls, values: list[str]) -> list[str]:
        normalized = [ArchiveDeleteIn.valid_archive(value) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("archive names must be unique")
        return normalized


class ArchiveMountIn(BaseModel):
    archive: str = Field(min_length=1, max_length=300)

    @field_validator("archive")
    @classmethod
    def valid_archive(cls, value: str) -> str:
        return ArchiveDeleteIn.valid_archive(value)


class ArchiveRenameIn(BaseModel):
    archive: str = Field(min_length=1, max_length=300)
    new_name: str = Field(min_length=1, max_length=300)

    @field_validator("archive", "new_name")
    @classmethod
    def valid_archive(cls, value: str) -> str:
        return ArchiveDeleteIn.valid_archive(value)

    @model_validator(mode="after")
    def names_must_differ(self):
        if self.archive == self.new_name:
            raise ValueError("new archive name must differ from the current name")
        return self


class ArchiveDiffIn(BaseModel):
    archive: str = Field(min_length=1, max_length=300)
    second_archive: str = Field(min_length=1, max_length=300)
    paths: list[str] = Field(default_factory=list)
    content_only: bool = False

    @field_validator("archive", "second_archive")
    @classmethod
    def valid_archive(cls, value: str) -> str:
        return ArchiveDeleteIn.valid_archive(value)

    @field_validator("paths")
    @classmethod
    def valid_paths(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            value = value.strip()
            path = PurePosixPath(value)
            if not value or value.startswith(("-", "/")) or ".." in path.parts or any(c in value for c in "\x00\r\n"):
                raise ValueError("diff paths must be relative archive paths without '..'")
            normalized.append(value)
        return normalized

    @model_validator(mode="after")
    def archives_must_differ(self):
        if self.archive == self.second_archive:
            raise ValueError("two different archives are required")
        return self


class ControllerKeyRotateIn(BaseModel):
    confirmation: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def confirmed(self):
        if self.confirmation.strip() != "CONTROLLER-SCHLÜSSEL ERNEUERN":
            raise ValueError("Zur Bestätigung exakt CONTROLLER-SCHLÜSSEL ERNEUERN eingeben")
        return self


class ManagerBackupCreateIn(BaseModel):
    # Manager and cache backups are separate API objects. Reject unknown legacy
    # cache fields rather than silently implying that cache data was included.
    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="", max_length=48)
    encrypted: bool = True
    compression: str = "standard"

    @field_validator("compression")
    @classmethod
    def valid_compression(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"none", "fast", "standard", "maximum"}:
            raise ValueError("unsupported manager backup compression")
        return normalized

    @field_validator("label")
    @classmethod
    def safe_label(cls, value: str) -> str:
        value = value.strip()
        if any(c in value for c in "\x00\r\n"):
            raise ValueError("backup label must be single-line")
        return value
    passphrase: SecretStr | None = None
    passphrase_confirm: SecretStr | None = None

    @model_validator(mode="after")
    def validate_encryption(self):
        secret = self.passphrase.get_secret_value() if self.passphrase else None
        confirmation = self.passphrase_confirm.get_secret_value() if self.passphrase_confirm else None
        if not self.encrypted:
            raise ValueError("new manager backups must be encrypted")
        if self.encrypted:
            if not secret or len(secret) < 12:
                raise ValueError("encrypted backups require a passphrase with at least 12 characters")
            if secret != confirmation:
                raise ValueError("backup passphrase confirmation does not match")
            if any(c in secret for c in "\x00\r\n"):
                raise ValueError("backup passphrase must be single-line")
        elif secret or confirmation:
            raise ValueError("backup passphrase is only valid when encryption is enabled")
        return self


class CacheBackupCreateIn(BaseModel):
    label: str = Field(default="", max_length=48)
    encrypted: bool = True
    include_manager_borg_cache: bool = True
    include_client_borg_cache: bool = True
    compression: str = "standard"
    passphrase: SecretStr | None = None
    passphrase_confirm: SecretStr | None = None

    @field_validator("compression")
    @classmethod
    def valid_compression(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"none", "fast", "standard", "maximum"}:
            raise ValueError("unsupported cache backup compression")
        return normalized

    @field_validator("label")
    @classmethod
    def safe_label(cls, value: str) -> str:
        value = value.strip()
        if any(c in value for c in "\x00\r\n"):
            raise ValueError("backup label must be single-line")
        return value

    @model_validator(mode="after")
    def validate_cache_backup(self):
        if not (self.include_manager_borg_cache or self.include_client_borg_cache):
            raise ValueError("cache backup requires manager cache or client caches")
        secret = self.passphrase.get_secret_value() if self.passphrase else None
        confirmation = self.passphrase_confirm.get_secret_value() if self.passphrase_confirm else None
        if self.encrypted:
            if not secret or len(secret) < 12:
                raise ValueError("encrypted cache backups require a passphrase with at least 12 characters")
            if secret != confirmation:
                raise ValueError("cache backup passphrase confirmation does not match")
            if any(c in secret for c in "\x00\r\n"):
                raise ValueError("backup passphrase must be single-line")
        elif secret or confirmation:
            raise ValueError("backup passphrase is only valid when encryption is enabled")
        return self


class ManagerBorgCacheCleanupIn(BaseModel):
    entries: list[str] | None = Field(default=None, max_length=2000)
    confirm: bool = False

    @model_validator(mode="after")
    def confirmed(self):
        if not self.confirm:
            raise ValueError("cache cleanup requires explicit confirmation")
        if self.entries is not None and not self.entries:
            raise ValueError("cache cleanup requires at least one selected entry")
        return self


class ClientBorgCacheScanIn(BaseModel):
    host_ids: list[int] | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def valid_hosts(self):
        if self.host_ids is not None:
            if not self.host_ids:
                raise ValueError("at least one host must be selected")
            if any(isinstance(value, bool) or int(value) <= 0 for value in self.host_ids):
                raise ValueError("host ids must be positive integers")
            self.host_ids = sorted(set(int(value) for value in self.host_ids))
        return self


class ClientBorgCacheCleanupTarget(BaseModel):
    host_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=220)
    path: str | None = Field(default=None, max_length=4096)


class ClientBorgCacheCleanupIn(BaseModel):
    kind: str
    entries: list[ClientBorgCacheCleanupTarget] = Field(min_length=1, max_length=1000)
    confirm: bool = False

    @model_validator(mode="after")
    def valid_cleanup(self):
        if self.kind not in {"orphan", "rollback", "security", "security_orphan", "user_cache", "reset"}:
            raise ValueError("client cache cleanup kind must be orphan, rollback, security, security_orphan, user_cache or reset")
        if not self.confirm:
            raise ValueError("client cache cleanup requires explicit confirmation")
        return self


class ManagerClientCacheInspectIn(BaseModel):
    passphrase: SecretStr | None = None

    @model_validator(mode="after")
    def valid_passphrase(self):
        secret = self.passphrase.get_secret_value() if self.passphrase else None
        if secret is not None and (not secret or any(c in secret for c in "\x00\r\n")):
            raise ValueError("backup passphrase must be a non-empty single-line value")
        return self


class ManagerCacheRestoreIn(ManagerClientCacheInspectIn):
    confirm: bool = False

    @model_validator(mode="after")
    def confirmed_restore(self):
        if not self.confirm:
            raise ValueError("manager cache restore requires explicit confirmation")
        return self


class ManagerClientCacheRestoreIn(ManagerClientCacheInspectIn):
    confirm: bool = False

    @model_validator(mode="after")
    def confirmed_restore(self):
        if not self.confirm:
            raise ValueError("client cache restore requires explicit confirmation")
        return self



class ManagerBackupRestoreIn(BaseModel):
    passphrase: SecretStr | None = None
    safety_passphrase: SecretStr
    safety_passphrase_confirm: SecretStr
    confirm: bool = False

    @model_validator(mode="after")
    def confirmed(self):
        if not self.confirm:
            raise ValueError("restore requires explicit confirmation")
        secret = self.passphrase.get_secret_value() if self.passphrase else None
        if secret is not None and any(c in secret for c in "\x00\r\n"):
            raise ValueError("backup passphrase must be single-line")
        safety = self.safety_passphrase.get_secret_value()
        confirmation = self.safety_passphrase_confirm.get_secret_value()
        if len(safety) < 12 or any(c in safety for c in "\x00\r\n"):
            raise ValueError("safety backup passphrase must contain at least 12 single-line characters")
        if safety != confirmation:
            raise ValueError("safety backup passphrase confirmation does not match")
        return self
