from __future__ import annotations

import os
from pathlib import Path


DATA_DIR = Path(os.getenv("BBM_DATA_DIR", "data"))
BACKUP_DIR = DATA_DIR / "backups"
EXPORT_DIR = DATA_DIR / "exports"
RUN_LOG_DIR = DATA_DIR / "run-logs"
ARCHIVE_CACHE_DIR = Path(os.getenv("BBM_ARCHIVE_CACHE_DIR", str(DATA_DIR / "archive-cache")))
SETTINGS_PATH = DATA_DIR / "settings.json"
NOTIFICATION_SETTINGS_PATH = DATA_DIR / "notifications.json"
DATABASE_URL = os.getenv("BBM_DATABASE_URL", f"sqlite:///{DATA_DIR / 'manager.db'}")
LEGACY_ADMIN_TOKEN = os.getenv("BBM_ADMIN_TOKEN", "")
LEGACY_SECRET_KEY = os.getenv("BBM_SECRET_KEY", "")
SECURITY_DIR = DATA_DIR / "security"
SECURITY_DATABASE_PATH = SECURITY_DIR / "security.db"
MASTER_KEY_PATH = SECURITY_DIR / "master.key"
INITIAL_ADMIN_PATH = SECURITY_DIR / "initial-admin.txt"
ALLOW_LEGACY_TOKEN_AUTH = os.getenv("BBM_ALLOW_LEGACY_TOKEN_AUTH", "0").lower() in {"1", "true", "yes"}
RUNTIME_SECRET_DIR = Path(os.getenv("BBM_RUNTIME_SECRET_DIR", "/run/bbm-secrets"))
REPOSITORY_ROOT = Path(os.getenv("BBM_REPOSITORY_ROOT", "/repositories"))
MANAGER_BORG_CACHE_DIR = Path(os.getenv("BBM_MANAGER_BORG_CACHE_DIR", str(DATA_DIR / "borg-cache")))
MANAGER_BORG_SECURITY_DIR = Path(os.getenv("BBM_MANAGER_BORG_SECURITY_DIR", str(DATA_DIR / "borg-security")))
REPOSITORY_KEYFILES_PATH = Path(os.getenv("BBM_REPOSITORY_KEYFILES_PATH", str(RUNTIME_SECRET_DIR / "repository-keys")))
REPOSITORY_PUBLIC_HOST = os.getenv("BBM_REPOSITORY_PUBLIC_HOST", "localhost")
REPOSITORY_SSH_PORT = int(os.getenv("BBM_REPOSITORY_SSH_PORT", "2222"))
REPOSITORY_AUTHORIZED_KEYS_PATH = Path(
    os.getenv("BBM_REPOSITORY_AUTHORIZED_KEYS_PATH", str(DATA_DIR / "repository-ssh" / "authorized_keys"))
)
REPOSITORY_HOST_KEY_PUBLIC_PATH = Path(
    os.getenv(
        "BBM_REPOSITORY_HOST_KEY_PUBLIC_PATH",
        str(RUNTIME_SECRET_DIR / "repository-ssh" / "ssh_host_ed25519_key.pub"),
    )
)
COMMAND_TIMEOUT = int(os.getenv("BBM_COMMAND_TIMEOUT", "86400"))
STORAGE_GUARD_ENABLED = os.getenv("BBM_STORAGE_GUARD_ENABLED", "1").lower() not in {"0", "false", "no"}
STORAGE_GUARD_THRESHOLD_PERCENT = int(os.getenv("BBM_STORAGE_GUARD_THRESHOLD_PERCENT", "95"))
HEALTH_REQUIRE_SSHD = os.getenv("BBM_HEALTH_REQUIRE_SSHD", "0").lower() not in {"0", "false", "no"}
SESSION_TTL_SECONDS = int(os.getenv("BBM_SESSION_TTL_SECONDS", "86400"))
SESSION_IDLE_TIMEOUT_SECONDS = int(os.getenv("BBM_SESSION_IDLE_TIMEOUT_SECONDS", "3600"))
if SESSION_TTL_SECONDS < 300:
    raise ValueError("BBM_SESSION_TTL_SECONDS must be at least 300")
if SESSION_IDLE_TIMEOUT_SECONDS < 60 or SESSION_IDLE_TIMEOUT_SECONDS > SESSION_TTL_SECONDS:
    raise ValueError("BBM_SESSION_IDLE_TIMEOUT_SECONDS must be between 60 and BBM_SESSION_TTL_SECONDS")
_CONFIGURED_SESSION_COOKIE_NAME = os.getenv("BBM_SESSION_COOKIE_NAME", "").strip()
# Treat the historical untouched default as the v2 name even during the first
# start with an updater that cannot rewrite its own already-running logic.
SESSION_COOKIE_NAME = (
    "bbm_session_v2"
    if _CONFIGURED_SESSION_COOKIE_NAME in {"", "bbm_session"}
    else _CONFIGURED_SESSION_COOKIE_NAME
)
SESSION_COOKIE_SECURE_MODE = os.getenv("BBM_SESSION_COOKIE_SECURE", "always").strip().lower() or "always"
if SESSION_COOKIE_SECURE_MODE not in {"auto", "always", "never"}:
    raise ValueError("BBM_SESSION_COOKIE_SECURE must be auto, always or never")
TRUSTED_PROXY_CIDRS = os.getenv("BBM_TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128").strip()
LOGIN_RATE_WINDOW_SECONDS = int(os.getenv("BBM_LOGIN_RATE_WINDOW_SECONDS", "300"))
LOGIN_RATE_BLOCK_SECONDS = int(os.getenv("BBM_LOGIN_RATE_BLOCK_SECONDS", "900"))
LOGIN_RATE_MAX_PER_IP = int(os.getenv("BBM_LOGIN_RATE_MAX_PER_IP", "20"))
LOGIN_RATE_MAX_PER_IP_USER = int(os.getenv("BBM_LOGIN_RATE_MAX_PER_IP_USER", "5"))
SECURITY_EVENT_RETENTION_DAYS = int(os.getenv("BBM_SECURITY_EVENT_RETENTION_DAYS", "90"))
SECURITY_EVENT_MAX_ROWS = int(os.getenv("BBM_SECURITY_EVENT_MAX_ROWS", "10000"))
BACKUP_MAX_FILE_BYTES = int(os.getenv("BBM_BACKUP_MAX_FILE_BYTES", str(256 * 1024 * 1024)))
BACKUP_MAX_UNCOMPRESSED_BYTES = int(os.getenv("BBM_BACKUP_MAX_UNCOMPRESSED_BYTES", str(1024 * 1024 * 1024)))
BACKUP_MAX_ENTRIES = int(os.getenv("BBM_BACKUP_MAX_ENTRIES", "5000"))
BACKUP_MAX_COMPRESSION_RATIO = int(os.getenv("BBM_BACKUP_MAX_COMPRESSION_RATIO", "250"))
for _name, _value in {
    "BBM_LOGIN_RATE_WINDOW_SECONDS": LOGIN_RATE_WINDOW_SECONDS,
    "BBM_LOGIN_RATE_BLOCK_SECONDS": LOGIN_RATE_BLOCK_SECONDS,
    "BBM_LOGIN_RATE_MAX_PER_IP": LOGIN_RATE_MAX_PER_IP,
    "BBM_LOGIN_RATE_MAX_PER_IP_USER": LOGIN_RATE_MAX_PER_IP_USER,
    "BBM_SECURITY_EVENT_RETENTION_DAYS": SECURITY_EVENT_RETENTION_DAYS,
    "BBM_SECURITY_EVENT_MAX_ROWS": SECURITY_EVENT_MAX_ROWS,
    "BBM_BACKUP_MAX_FILE_BYTES": BACKUP_MAX_FILE_BYTES,
    "BBM_BACKUP_MAX_UNCOMPRESSED_BYTES": BACKUP_MAX_UNCOMPRESSED_BYTES,
    "BBM_BACKUP_MAX_ENTRIES": BACKUP_MAX_ENTRIES,
    "BBM_BACKUP_MAX_COMPRESSION_RATIO": BACKUP_MAX_COMPRESSION_RATIO,
}.items():
    if _value <= 0:
        raise ValueError(f"{_name} must be greater than zero")
APP_TIMEZONE_NAME = os.getenv("TZ", "Europe/Berlin") or "Europe/Berlin"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SECURITY_DIR.mkdir(parents=True, exist_ok=True)
    MANAGER_BORG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MANAGER_BORG_SECURITY_DIR.mkdir(parents=True, exist_ok=True)
