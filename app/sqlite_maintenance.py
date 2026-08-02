from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from sqlalchemy.engine import Engine

from app.config import DATA_DIR

T = TypeVar("T")
MANAGER_VACUUM_PENDING_PATH = DATA_DIR / ".manager-db-vacuum-pending"


def _is_locked(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return "database is locked" in text or "database table is locked" in text


def retry_sqlite(operation: Callable[[], T], *, attempts: int = 8, delay_seconds: float = 0.25) -> T:
    last_error: BaseException | None = None
    for attempt in range(max(1, attempts)):
        try:
            return operation()
        except (sqlite3.OperationalError, Exception) as exc:
            # SQLAlchemy wraps sqlite3 errors, therefore check the message for
            # both raw and wrapped exceptions. Non-locking failures must not be
            # hidden behind retries.
            if not _is_locked(exc):
                raise
            last_error = exc
            if attempt + 1 >= attempts:
                break
            time.sleep(delay_seconds * (attempt + 1))
    assert last_error is not None
    raise last_error


def sqlite_database_path(target_engine: Engine) -> Path | None:
    if target_engine.dialect.name != "sqlite":
        return None
    database = target_engine.url.database
    if not database or database == ":memory:":
        return None
    return Path(database)


def mark_manager_vacuum_pending() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MANAGER_VACUUM_PENDING_PATH.write_text("pending\n", encoding="utf-8")
    try:
        MANAGER_VACUUM_PENDING_PATH.chmod(0o600)
    except OSError:
        pass


def manager_vacuum_pending() -> bool:
    return MANAGER_VACUUM_PENDING_PATH.exists()


def sanitize_sqlite_database(target_engine: Engine, *, analyze: bool = True) -> dict[str, Any]:
    """Checkpoint and rebuild a SQLite database outside active ORM sessions.

    For file databases all pooled connections are closed first and the work is
    performed through a single autocommit sqlite3 connection. This function is
    intended for application startup, before HTTP requests are accepted.
    """
    if target_engine.dialect.name != "sqlite":
        return {"supported": False, "vacuumed": False, "checkpointed": False}

    path = sqlite_database_path(target_engine)
    if path is None:
        def memory_operation() -> dict[str, Any]:
            with target_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                try:
                    connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
                    checkpointed = True
                except Exception:
                    checkpointed = False
                connection.exec_driver_sql("VACUUM")
                if analyze:
                    connection.exec_driver_sql("ANALYZE")
            return {"supported": True, "vacuumed": True, "checkpointed": checkpointed}
        result = retry_sqlite(memory_operation)
        MANAGER_VACUUM_PENDING_PATH.unlink(missing_ok=True)
        return result

    path.parent.mkdir(parents=True, exist_ok=True)
    target_engine.dispose()

    def file_operation() -> dict[str, Any]:
        connection = sqlite3.connect(path, timeout=60, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout=60000")
            connection.execute("PRAGMA secure_delete=ON")
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            checkpointed = bool(checkpoint is not None and int(checkpoint[0]) == 0)
            connection.execute("VACUUM")
            if analyze:
                connection.execute("ANALYZE")
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if not quick_check or str(quick_check[0]).casefold() != "ok":
                raise ValueError("SQLite-Datenbank ist nach der Bereinigung nicht konsistent")
            return {"supported": True, "vacuumed": True, "checkpointed": checkpointed}
        finally:
            connection.close()

    result = retry_sqlite(file_operation, attempts=10, delay_seconds=0.4)
    MANAGER_VACUUM_PENDING_PATH.unlink(missing_ok=True)
    return result


def run_pending_manager_vacuum(target_engine: Engine) -> dict[str, Any]:
    if not manager_vacuum_pending():
        return {"pending": False, "vacuumed": False}
    result = sanitize_sqlite_database(target_engine)
    return {"pending": True, **result}
