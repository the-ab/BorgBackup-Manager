from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import (
    INITIAL_ADMIN_PATH,
    LOGIN_RATE_BLOCK_SECONDS,
    LOGIN_RATE_MAX_PER_IP,
    LOGIN_RATE_MAX_PER_IP_USER,
    LOGIN_RATE_WINDOW_SECONDS,
    SECURITY_DATABASE_PATH,
    SECURITY_DIR,
    SECURITY_EVENT_MAX_ROWS,
    SECURITY_EVENT_RETENTION_DAYS,
    SESSION_IDLE_TIMEOUT_SECONDS,
)
from app.secret_crypto import decrypt_value, encrypt_value

PASSWORD_N = 2**15
PASSWORD_R = 8
PASSWORD_P = 1
PASSWORD_DKLEN = 64
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$")


def _generate_temporary_password() -> str:
    """Generate a bootstrap password that always satisfies validate_password()."""
    return f"Aa1!{secrets.token_urlsafe(24)}"


@dataclass(frozen=True)
class AuthUser:
    id: int
    username: str
    role: str
    enabled: bool
    must_change_password: bool
    language: str = "de"
    appearance: str = "auto"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _utcnow()).isoformat()


def _connect() -> sqlite3.Connection:
    SECURITY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SECURITY_DIR, 0o700)
    except OSError:
        pass
    connection = sqlite3.connect(SECURITY_DATABASE_PATH, timeout=30)
    try:
        os.chmod(SECURITY_DATABASE_PATH, 0o600)
    except OSError:
        pass
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    return connection


def initialize_security_store(legacy_admin_token: str | None = None) -> dict[str, Any]:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                enabled INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                remote_address TEXT,
                user_agent TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_sessions_expires_at ON sessions(expires_at);
            CREATE TABLE IF NOT EXISTS session_reload_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT NOT NULL UNIQUE,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                user_agent_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_session_reload_tokens_expires_at ON session_reload_tokens(expires_at);
            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                user_id INTEGER,
                username TEXT,
                event TEXT NOT NULL,
                remote_address TEXT,
                detail TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_security_events_created_at ON security_events(created_at);
            CREATE TABLE IF NOT EXISTS login_rate_limits (
                bucket_key TEXT PRIMARY KEY,
                window_started_at TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                blocked_until TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_login_rate_limits_updated_at ON login_rate_limits(updated_at);
            CREATE TABLE IF NOT EXISTS secrets (
                scope TEXT NOT NULL,
                name TEXT NOT NULL,
                encrypted_value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(scope, name)
            );
            CREATE INDEX IF NOT EXISTS ix_secrets_scope ON secrets(scope);
            """
        )
        user_columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(users)").fetchall()}
        if "language" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'de'")
        if "appearance" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN appearance TEXT NOT NULL DEFAULT 'auto'")
        connection.execute("UPDATE users SET language='de' WHERE language NOT IN ('de','en') OR language IS NULL")
        connection.execute("UPDATE users SET appearance='auto' WHERE appearance NOT IN ('auto','light','dark') OR appearance IS NULL")
        # Historical account-wide locks could be abused to deny access to a known
        # username. v1.0.38 replaces them with source-scoped rate limits.
        connection.execute("UPDATE users SET failed_attempts=0,locked_until=NULL WHERE failed_attempts<>0 OR locked_until IS NOT NULL")
        count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        created = False
        source = None
        if count == 0:
            legacy = (legacy_admin_token or "").strip()
            if legacy and legacy != "change-me":
                temporary_password = legacy
                source = "legacy-token"
            else:
                temporary_password = _generate_temporary_password()
                source = "generated"
            now = _iso()
            connection.execute(
                "INSERT INTO users(username,password_hash,role,enabled,must_change_password,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                ("admin", hash_password(temporary_password, enforce_policy=(source != "legacy-token")), "admin", 1, 1, now, now),
            )
            connection.commit()
            created = True
        cleanup_expired_sessions(connection)
        connection.execute("DELETE FROM session_reload_tokens WHERE expires_at < ?", (_iso(),))
        _cleanup_security_events(connection)
        _cleanup_login_rate_limits(connection)
        connection.commit()
    INITIAL_ADMIN_PATH.unlink(missing_ok=True)
    if created:
        set_secret("bootstrap", "initial_admin_password", temporary_password)
    try:
        os.chmod(SECURITY_DATABASE_PATH, 0o600)
    except OSError:
        pass
    return {"created": created, "source": source, "users": count + (1 if created else 0)}


def validate_username(username: str) -> str:
    value = username.strip()
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("Benutzername muss 3–64 Zeichen lang sein und darf nur Buchstaben, Zahlen, Punkt, Minus und Unterstrich enthalten")
    return value


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Das Passwort muss mindestens 12 Zeichen lang sein")
    if len(password) > 1024 or "\x00" in password:
        raise ValueError("Ungültiges Passwort")
    groups = sum(bool(re.search(pattern, password)) for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if groups < 3:
        raise ValueError("Das Passwort muss mindestens drei Gruppen aus Kleinbuchstaben, Großbuchstaben, Zahlen und Sonderzeichen enthalten")


def hash_password(password: str, *, enforce_policy: bool = True) -> str:
    if enforce_policy:
        validate_password(password)
    elif not password or len(password) > 4096 or "\x00" in password:
        raise ValueError("Ungültiges temporäres Passwort")
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=PASSWORD_N, r=PASSWORD_R, p=PASSWORD_P,
        maxmem=64 * 1024 * 1024, dklen=PASSWORD_DKLEN,
    )
    return "$".join((
        "scrypt", str(PASSWORD_N), str(PASSWORD_R), str(PASSWORD_P),
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(derived).decode("ascii").rstrip("="),
    ))


def _decode64(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_text, digest_text = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = _decode64(salt_text)
        expected = _decode64(digest_text)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p),
            maxmem=64 * 1024 * 1024, dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, OverflowError):
        return False


def _row_user(row: sqlite3.Row) -> AuthUser:
    return AuthUser(
        id=int(row["id"]), username=str(row["username"]), role=str(row["role"]),
        enabled=bool(row["enabled"]), must_change_password=bool(row["must_change_password"]),
        language=str(row["language"] or "de"), appearance=str(row["appearance"] or "auto"),
    )


def _cleanup_security_events(connection: sqlite3.Connection) -> None:
    cutoff = _iso(_utcnow() - timedelta(days=SECURITY_EVENT_RETENTION_DAYS))
    connection.execute("DELETE FROM security_events WHERE created_at < ?", (cutoff,))
    connection.execute(
        "DELETE FROM security_events WHERE id NOT IN (SELECT id FROM security_events ORDER BY id DESC LIMIT ?)",
        (SECURITY_EVENT_MAX_ROWS,),
    )


def _cleanup_login_rate_limits(connection: sqlite3.Connection) -> None:
    cutoff = _iso(_utcnow() - timedelta(seconds=max(LOGIN_RATE_WINDOW_SECONDS, LOGIN_RATE_BLOCK_SECONDS) * 2))
    connection.execute("DELETE FROM login_rate_limits WHERE updated_at < ?", (cutoff,))


def record_event(event: str, *, user_id: int | None = None, username: str | None = None, remote_address: str | None = None, detail: str | None = None) -> None:
    try:
        with _connect() as connection:
            connection.execute(
                "INSERT INTO security_events(created_at,user_id,username,event,remote_address,detail) VALUES(?,?,?,?,?,?)",
                (_iso(), user_id, username, event, remote_address, (detail or "")[:1000]),
            )
            _cleanup_security_events(connection)
            connection.commit()
    except sqlite3.Error:
        pass


def _rate_bucket_keys(username: str, remote_address: str | None) -> tuple[tuple[str, int], tuple[str, int]]:
    address = (remote_address or "unknown").strip().lower()[:128]
    normalized = username.strip().casefold()[:128]
    pair_hash = hashlib.sha256(f"{address}\0{normalized}".encode("utf-8", errors="ignore")).hexdigest()
    return (f"ip:{address}", LOGIN_RATE_MAX_PER_IP), (f"pair:{pair_hash}", LOGIN_RATE_MAX_PER_IP_USER)


def consume_login_attempt(username: str, remote_address: str | None) -> tuple[bool, int]:
    """Atomically reserve one expensive password verification for this source."""
    now = _utcnow()
    retry_after = 0
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for bucket_key, limit in _rate_bucket_keys(username, remote_address):
            row = connection.execute(
                "SELECT window_started_at,attempts,blocked_until FROM login_rate_limits WHERE bucket_key=?",
                (bucket_key,),
            ).fetchone()
            attempts = 0
            window_started = now
            blocked_until = None
            if row is not None:
                try:
                    window_started = datetime.fromisoformat(str(row["window_started_at"]))
                except ValueError:
                    window_started = now
                try:
                    blocked_until = datetime.fromisoformat(str(row["blocked_until"])) if row["blocked_until"] else None
                except ValueError:
                    blocked_until = None
                attempts = int(row["attempts"] or 0)
            if blocked_until and blocked_until > now:
                retry_after = max(retry_after, max(1, int((blocked_until - now).total_seconds())))
                continue
            if now - window_started >= timedelta(seconds=LOGIN_RATE_WINDOW_SECONDS):
                attempts = 0
                window_started = now
            if attempts >= limit:
                blocked_until = now + timedelta(seconds=LOGIN_RATE_BLOCK_SECONDS)
                retry_after = max(retry_after, LOGIN_RATE_BLOCK_SECONDS)
                connection.execute(
                    "INSERT INTO login_rate_limits(bucket_key,window_started_at,attempts,blocked_until,updated_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(bucket_key) DO UPDATE SET window_started_at=excluded.window_started_at,attempts=excluded.attempts,blocked_until=excluded.blocked_until,updated_at=excluded.updated_at",
                    (bucket_key, _iso(window_started), attempts, _iso(blocked_until), _iso(now)),
                )
            else:
                connection.execute(
                    "INSERT INTO login_rate_limits(bucket_key,window_started_at,attempts,blocked_until,updated_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(bucket_key) DO UPDATE SET window_started_at=excluded.window_started_at,attempts=excluded.attempts,blocked_until=NULL,updated_at=excluded.updated_at",
                    (bucket_key, _iso(window_started), attempts + 1, None, _iso(now)),
                )
        _cleanup_login_rate_limits(connection)
        connection.commit()
    return retry_after == 0, retry_after


def reset_login_rate_limit(username: str, remote_address: str | None) -> None:
    # A valid login clears only the account/source pair. The broader per-IP
    # budget intentionally remains in place so an attacker cannot reset the
    # expensive password-verification allowance with one known account.
    pair_key = _rate_bucket_keys(username, remote_address)[1][0]
    with _connect() as connection:
        connection.execute("DELETE FROM login_rate_limits WHERE bucket_key=?", (pair_key,))
        connection.commit()


_DUMMY_PASSWORD_HASH: str | None = None


def _dummy_password_hash() -> str:
    global _DUMMY_PASSWORD_HASH
    if _DUMMY_PASSWORD_HASH is None:
        _DUMMY_PASSWORD_HASH = hash_password("Invalid-Login-Password-1!")
    return _DUMMY_PASSWORD_HASH


def authenticate_user(username: str, password: str, remote_address: str | None = None) -> AuthUser | None:
    normalized = username.strip()
    with _connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (normalized,)).fetchone()
        encoded = str(row["password_hash"]) if row is not None and bool(row["enabled"]) else _dummy_password_hash()
        valid = verify_password(password, encoded)
        if row is None or not bool(row["enabled"]) or not valid:
            record_event("login_failed", username=normalized, remote_address=remote_address, detail="invalid")
            return None
        connection.execute(
            "UPDATE users SET failed_attempts=0,locked_until=NULL,last_login_at=?,updated_at=? WHERE id=?",
            (_iso(), _iso(), int(row["id"])),
        )
        connection.commit()
        user = _row_user(row)
    record_event("login_success", user_id=user.id, username=user.username, remote_address=remote_address)
    return user

def cleanup_expired_sessions(connection: sqlite3.Connection | None = None) -> int:
    own = connection is None
    connection = connection or _connect()
    try:
        now = _utcnow()
        idle_cutoff = _iso(now - timedelta(seconds=SESSION_IDLE_TIMEOUT_SECONDS))
        cursor = connection.execute(
            "DELETE FROM sessions WHERE expires_at < ? OR last_seen_at < ?",
            (_iso(now), idle_cutoff),
        )
        connection.commit()
        return int(cursor.rowcount or 0)
    finally:
        if own:
            connection.close()


def create_session(user: AuthUser, ttl_seconds: int, remote_address: str | None = None, user_agent: str | None = None) -> str:
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    now = _utcnow()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO sessions(token_hash,user_id,created_at,expires_at,last_seen_at,remote_address,user_agent) VALUES(?,?,?,?,?,?,?)",
            (token_hash, user.id, _iso(now), _iso(now + timedelta(seconds=ttl_seconds)), _iso(now), remote_address, (user_agent or "")[:500]),
        )
        connection.commit()
    return token


def get_session_user(token: str | None, touch: bool = True) -> AuthUser | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    with _connect() as connection:
        row = connection.execute(
            "SELECT u.*,s.id AS session_id,s.expires_at,s.last_seen_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",
            (token_hash,),
        ).fetchone()
        if row is None or not bool(row["enabled"]):
            return None
        try:
            expires = datetime.fromisoformat(str(row["expires_at"]))
        except ValueError:
            expires = datetime.min.replace(tzinfo=timezone.utc)
        try:
            last_seen = datetime.fromisoformat(str(row["last_seen_at"]))
        except ValueError:
            last_seen = datetime.min.replace(tzinfo=timezone.utc)
        now = _utcnow()
        if expires < now or now - last_seen > timedelta(seconds=SESSION_IDLE_TIMEOUT_SECONDS):
            connection.execute("DELETE FROM sessions WHERE id=?", (int(row["session_id"]),))
            connection.commit()
            return None
        if touch and now - last_seen > timedelta(minutes=1):
            connection.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (_iso(now), int(row["session_id"])))
            connection.commit()
        return _row_user(row)



def _user_agent_hash(user_agent: str | None) -> str:
    return hashlib.sha256((user_agent or "").encode("utf-8", errors="ignore")).hexdigest()


def create_session_reload_token(session_token: str, ttl_seconds: int, user_agent: str | None = None) -> str:
    token_hash = hashlib.sha256(session_token.encode("ascii", errors="ignore")).hexdigest()
    reload_token = secrets.token_urlsafe(48)
    reload_hash = hashlib.sha256(reload_token.encode("ascii")).hexdigest()
    now = _utcnow()
    with _connect() as connection:
        row = connection.execute("SELECT id,expires_at FROM sessions WHERE token_hash=?", (token_hash,)).fetchone()
        if row is None:
            raise ValueError("session not found")
        session_expires = datetime.fromisoformat(str(row["expires_at"]))
        expires = min(session_expires, now + timedelta(seconds=ttl_seconds))
        connection.execute(
            "INSERT INTO session_reload_tokens(token_hash,session_id,user_agent_hash,created_at,expires_at) VALUES(?,?,?,?,?)",
            (reload_hash, int(row["id"]), _user_agent_hash(user_agent), _iso(now), _iso(expires)),
        )
        connection.commit()
    return reload_token


def get_session_user_by_reload_token(token: str | None, user_agent: str | None = None) -> AuthUser | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    now = _utcnow()
    with _connect() as connection:
        row = connection.execute(
            "SELECT u.*,s.id AS session_id,s.expires_at AS session_expires,s.last_seen_at,r.expires_at AS reload_expires,r.user_agent_hash "
            "FROM session_reload_tokens r JOIN sessions s ON s.id=r.session_id "
            "JOIN users u ON u.id=s.user_id WHERE r.token_hash=?",
            (token_hash,),
        ).fetchone()
        if row is None or not bool(row["enabled"]):
            return None
        try:
            session_expires = datetime.fromisoformat(str(row["session_expires"]))
            reload_expires = datetime.fromisoformat(str(row["reload_expires"]))
        except ValueError:
            return None
        try:
            last_seen = datetime.fromisoformat(str(row["last_seen_at"]))
        except ValueError:
            last_seen = datetime.min.replace(tzinfo=timezone.utc)
        if min(session_expires, reload_expires) < now or now - last_seen > timedelta(seconds=SESSION_IDLE_TIMEOUT_SECONDS):
            connection.execute("DELETE FROM sessions WHERE id=?", (int(row["session_id"]),))
            connection.commit()
            return None
        if not hmac.compare_digest(str(row["user_agent_hash"]), _user_agent_hash(user_agent)):
            return None
        return _row_user(row)


def revoke_session_by_reload_token(token: str | None) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    with _connect() as connection:
        row = connection.execute("SELECT session_id FROM session_reload_tokens WHERE token_hash=?", (token_hash,)).fetchone()
        if row is not None:
            connection.execute("DELETE FROM sessions WHERE id=?", (int(row["session_id"]),))
            connection.commit()

def revoke_session(token: str | None) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    with _connect() as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
        connection.commit()


def revoke_user_sessions(user_id: int) -> int:
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        connection.commit()
        return int(cursor.rowcount or 0)


def list_users() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id,username,role,enabled,must_change_password,language,appearance,created_at,updated_at,last_login_at,locked_until FROM users ORDER BY username COLLATE NOCASE"
        ).fetchall()
    return [dict(row) | {"enabled": bool(row["enabled"]), "must_change_password": bool(row["must_change_password"])} for row in rows]


def create_user(username: str, password: str, role: str = "user", must_change_password: bool = True) -> dict[str, Any]:
    normalized = validate_username(username)
    if role not in {"admin", "user"}:
        raise ValueError("Ungültige Rolle")
    now = _iso()
    try:
        with _connect() as connection:
            cursor = connection.execute(
                "INSERT INTO users(username,password_hash,role,enabled,must_change_password,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (normalized, hash_password(password), role, 1, int(must_change_password), now, now),
            )
            connection.commit()
            user_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise ValueError("Benutzername ist bereits vorhanden") from exc
    record_event("user_created", user_id=user_id, username=normalized, detail=role)
    return get_user(user_id)


def get_user(user_id: int) -> dict[str, Any]:
    with _connect() as connection:
        row = connection.execute(
            "SELECT id,username,role,enabled,must_change_password,language,appearance,created_at,updated_at,last_login_at,locked_until FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
    if row is None:
        raise KeyError(user_id)
    return dict(row) | {"enabled": bool(row["enabled"]), "must_change_password": bool(row["must_change_password"])}


def update_user(user_id: int, username: str, role: str, enabled: bool) -> dict[str, Any]:
    normalized = validate_username(username)
    if role not in {"admin", "user"}:
        raise ValueError("Ungültige Rolle")
    with _connect() as connection:
        existing = connection.execute("SELECT id,role,enabled FROM users WHERE id=?", (user_id,)).fetchone()
        if existing is None:
            raise KeyError(user_id)
        if existing["role"] == "admin" and bool(existing["enabled"]) and (role != "admin" or not enabled):
            active_admins = int(connection.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1").fetchone()[0])
            if active_admins <= 1:
                raise ValueError("Der letzte aktive Administrator kann nicht deaktiviert oder herabgestuft werden")
        try:
            connection.execute(
                "UPDATE users SET username=?,role=?,enabled=?,updated_at=? WHERE id=?",
                (normalized, role, int(enabled), _iso(), user_id),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("Benutzername ist bereits vorhanden") from exc
    if not enabled:
        revoke_user_sessions(user_id)
    record_event("user_updated", user_id=user_id, username=normalized, detail=f"role={role},enabled={enabled}")
    return get_user(user_id)


def update_user_preferences(user_id: int, language: str, appearance: str) -> dict[str, Any]:
    if language not in {"de", "en"}:
        raise ValueError("Ungültige Sprache")
    if appearance not in {"auto", "light", "dark"}:
        raise ValueError("Ungültiges Farbschema")
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE users SET language=?,appearance=?,updated_at=? WHERE id=?",
            (language, appearance, _iso(), user_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(user_id)
        connection.commit()
    record_event("preferences_updated", user_id=user_id, detail=f"language={language},appearance={appearance}")
    return get_user(user_id)


def set_user_password(user_id: int, password: str, must_change_password: bool = True) -> None:
    encoded = hash_password(password)
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE users SET password_hash=?,must_change_password=?,failed_attempts=0,locked_until=NULL,updated_at=? WHERE id=?",
            (encoded, int(must_change_password), _iso(), user_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(user_id)
        connection.commit()
    revoke_user_sessions(user_id)
    record_event("password_reset", user_id=user_id)


def change_own_password(user_id: int, current_password: str, new_password: str) -> None:
    with _connect() as connection:
        row = connection.execute("SELECT username,password_hash FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(user_id)
        if not verify_password(current_password, str(row["password_hash"])):
            raise ValueError("Aktuelles Passwort ist falsch")
        encoded = hash_password(new_password)
        connection.execute(
            "UPDATE users SET password_hash=?,must_change_password=0,failed_attempts=0,locked_until=NULL,updated_at=? WHERE id=?",
            (encoded, _iso(), user_id),
        )
        connection.commit()
        username = str(row["username"])
    revoke_user_sessions(user_id)
    INITIAL_ADMIN_PATH.unlink(missing_ok=True)
    delete_secret("bootstrap", "initial_admin_password")
    record_event("password_changed", user_id=user_id, username=username)


def delete_user(user_id: int, current_user_id: int) -> None:
    if user_id == current_user_id:
        raise ValueError("Das eigene Benutzerkonto kann nicht gelöscht werden")
    with _connect() as connection:
        row = connection.execute("SELECT role,enabled,username FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(user_id)
        if row["role"] == "admin":
            administrator_count = int(connection.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0])
            if administrator_count <= 1:
                raise ValueError("Der letzte Administrator kann nicht gelöscht werden")
        connection.execute("DELETE FROM users WHERE id=?", (user_id,))
        connection.commit()
    record_event("user_deleted", user_id=user_id, username=str(row["username"]))


def authentication_readiness() -> dict[str, Any]:
    """Return non-sensitive authentication readiness information."""
    with _connect() as connection:
        users = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        active_administrators = int(connection.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1"
        ).fetchone()[0])
        locked_administrators = int(connection.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1 AND locked_until IS NOT NULL AND locked_until > ?",
            (_iso(),),
        ).fetchone()[0])
        invalid_hashes = int(connection.execute(
            "SELECT COUNT(*) FROM users WHERE password_hash NOT LIKE 'scrypt$%'"
        ).fetchone()[0])
    return {
        "ready": users > 0 and active_administrators > 0 and invalid_hashes == 0,
        "users": users,
        "active_administrators": active_administrators,
        "locked_administrators": locked_administrators,
        "invalid_password_hashes": invalid_hashes,
    }


def recover_account(username: str, *, make_admin: bool = False) -> str:
    """Reset and unlock an account from the local recovery CLI."""
    normalized = validate_username(username)
    temporary_password = secrets.token_urlsafe(18) + "!Aa1"
    encoded = hash_password(temporary_password)
    with _connect() as connection:
        row = connection.execute(
            "SELECT id,role FROM users WHERE username=? COLLATE NOCASE", (normalized,)
        ).fetchone()
        if row is None:
            role = "admin" if make_admin else "user"
            now = _iso()
            cursor = connection.execute(
                "INSERT INTO users(username,password_hash,role,enabled,must_change_password,failed_attempts,locked_until,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (normalized, encoded, role, 1, 1, 0, None, now, now),
            )
            user_id = int(cursor.lastrowid)
        else:
            user_id = int(row["id"])
            role = "admin" if make_admin else str(row["role"])
            connection.execute(
                "UPDATE users SET password_hash=?,role=?,enabled=1,must_change_password=1,failed_attempts=0,locked_until=NULL,updated_at=? WHERE id=?",
                (encoded, role, _iso(), user_id),
            )
        connection.commit()
    revoke_user_sessions(user_id)
    record_event("account_recovered", user_id=user_id, username=normalized, detail=f"role={role}")
    return temporary_password


def unlock_account(username: str) -> bool:
    normalized = validate_username(username)
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE users SET failed_attempts=0,locked_until=NULL,updated_at=? WHERE username=? COLLATE NOCASE",
            (_iso(), normalized),
        )
        connection.commit()
    if cursor.rowcount:
        record_event("account_unlocked", username=normalized)
    return bool(cursor.rowcount)


def security_status() -> dict[str, Any]:
    with _connect() as connection:
        users = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        administrators = int(connection.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0])
        active_administrators = int(connection.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1").fetchone()[0])
        sessions = int(connection.execute("SELECT COUNT(*) FROM sessions WHERE expires_at >= ?", (_iso(),)).fetchone()[0])
    secret_status = security_secret_status()
    return {
        "users": users,
        "administrators": administrators,
        "active_administrators": active_administrators,
        "sessions": sessions,
        "database": str(SECURITY_DATABASE_PATH),
        "initial_credentials_pending": secret_exists("bootstrap", "initial_admin_password"),
        "encrypted_secrets": secret_status["total"],
        "secret_scopes": secret_status["scopes"],
    }


_SECRET_SCOPE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_SECRET_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


def _validate_secret_key(scope: str, name: str) -> tuple[str, str]:
    scope = scope.strip()
    name = name.strip()
    if not _SECRET_SCOPE_RE.fullmatch(scope) or not _SECRET_NAME_RE.fullmatch(name):
        raise ValueError("Ungültiger Schlüssel für den Sicherheitsspeicher")
    return scope, name


def set_secret(scope: str, name: str, value: str) -> None:
    scope, name = _validate_secret_key(scope, name)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Geheimnis darf nicht leer sein")
    now = _iso()
    encrypted = encrypt_value(value)
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO secrets(scope,name,encrypted_value,created_at,updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(scope,name) DO UPDATE SET
              encrypted_value=excluded.encrypted_value,
              updated_at=excluded.updated_at
            """,
            (scope, name, encrypted, now, now),
        )
        connection.commit()


def get_secret(scope: str, name: str, default: str | None = None) -> str | None:
    scope, name = _validate_secret_key(scope, name)
    with _connect() as connection:
        row = connection.execute(
            "SELECT encrypted_value FROM secrets WHERE scope=? AND name=?",
            (scope, name),
        ).fetchone()
    if row is None:
        return default
    return decrypt_value(str(row["encrypted_value"]))


def secret_exists(scope: str, name: str) -> bool:
    scope, name = _validate_secret_key(scope, name)
    with _connect() as connection:
        return connection.execute(
            "SELECT 1 FROM secrets WHERE scope=? AND name=?",
            (scope, name),
        ).fetchone() is not None


def delete_secret(scope: str, name: str) -> bool:
    scope, name = _validate_secret_key(scope, name)
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM secrets WHERE scope=? AND name=?", (scope, name))
        connection.commit()
        return bool(cursor.rowcount)


def delete_secret_scope(scope: str) -> int:
    scope = scope.strip()
    if not _SECRET_SCOPE_RE.fullmatch(scope):
        raise ValueError("Ungültiger Bereich für den Sicherheitsspeicher")
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM secrets WHERE scope=?", (scope,))
        connection.commit()
        return int(cursor.rowcount or 0)


def list_secret_names(scope: str) -> list[str]:
    scope = scope.strip()
    if not _SECRET_SCOPE_RE.fullmatch(scope):
        raise ValueError("Ungültiger Bereich für den Sicherheitsspeicher")
    with _connect() as connection:
        rows = connection.execute("SELECT name FROM secrets WHERE scope=? ORDER BY name", (scope,)).fetchall()
    return [str(row["name"]) for row in rows]


def security_secret_status() -> dict[str, Any]:
    with _connect() as connection:
        total = int(connection.execute("SELECT COUNT(*) FROM secrets").fetchone()[0])
        rows = connection.execute("SELECT scope,COUNT(*) AS count FROM secrets GROUP BY scope ORDER BY scope").fetchall()
    return {"total": total, "scopes": {str(row["scope"]): int(row["count"]) for row in rows}}
