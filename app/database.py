from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import DATABASE_URL, ensure_data_dir


MINIMUM_BASELINE_VERSION = "1.3.5"
CURRENT_MANAGER_SCHEMA_VERSION = 137

ensure_data_dir()
_is_sqlite = DATABASE_URL.startswith("sqlite")
_is_memory_sqlite = DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}
connect_args = {"check_same_thread": False, "timeout": 30} if _is_sqlite else {}
engine_options = {"connect_args": connect_args, "pool_pre_ping": True}
if _is_memory_sqlite:
    engine_options["poolclass"] = StaticPool
engine = create_engine(DATABASE_URL, **engine_options)


if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
            if not _is_memory_sqlite:
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).casefold():
                        raise
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA secure_delete=ON")
        finally:
            cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _load_model_metadata() -> None:
    # Importing models registers every current table on Base.metadata. Keeping
    # this local avoids an import cycle while making standalone schema checks
    # independent of app.main import order.
    import app.models  # noqa: F401


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_digest(connection: sqlite3.Connection, table_name: str, columns: list[str]) -> tuple[int, str]:
    quoted_columns = ",".join(_quoted_identifier(column) for column in columns)
    order_by = _quoted_identifier(columns[0]) if columns else "rowid"
    digest = hashlib.sha256()
    count = 0
    cursor = connection.execute(
        f"SELECT {quoted_columns} FROM {_quoted_identifier(table_name)} ORDER BY {order_by}"
    )
    while True:
        rows = cursor.fetchmany(1000)
        if not rows:
            break
        for row in rows:
            digest.update(
                json.dumps(list(row), ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
            )
            digest.update(b"\n")
            count += 1
    return count, digest.hexdigest()


def _manager_schema_state(target_engine=engine) -> dict[str, object]:
    _load_model_metadata()
    expected_tables = {
        table.name: [column.name for column in table.columns]
        for table in Base.metadata.sorted_tables
    }
    with target_engine.connect() as connection:
        inspector = inspect(connection)
        actual_tables = {
            name for name in inspector.get_table_names()
            if not name.startswith("sqlite_")
        }
        missing_tables = sorted(set(expected_tables) - actual_tables)
        extra_tables = sorted(actual_tables - set(expected_tables))
        missing_columns: dict[str, list[str]] = {}
        extra_columns: dict[str, list[str]] = {}
        table_columns: dict[str, list[str]] = {}
        for table_name in sorted(actual_tables):
            columns = [str(column["name"]) for column in inspector.get_columns(table_name)]
            table_columns[table_name] = columns
        for table_name, expected_columns in expected_tables.items():
            if table_name not in actual_tables:
                continue
            actual_columns = set(table_columns[table_name])
            missing = sorted(set(expected_columns) - actual_columns)
            extra = sorted(actual_columns - set(expected_columns))
            if missing:
                missing_columns[table_name] = missing
            if extra:
                extra_columns[table_name] = extra
        user_version = int(connection.exec_driver_sql("PRAGMA user_version").scalar() or 0)
        unsafe_ssh_history = 0
        if "runs" in actual_tables and not missing_columns.get("runs"):
            unsafe_ssh_history = int(connection.execute(text(
                """
                SELECT COUNT(*) FROM runs
                 WHERE action='ssh-command'
                   AND instr(COALESCE(command_preview,''), '[bbm-controller-key]') > 0
                   AND instr(COALESCE(command_preview,''), '-- sh -lc') > 0
                """
            )).scalar() or 0)
        plaintext_ssh_action_rows = 0
        if "host_ssh_actions" in actual_tables:
            columns = set(table_columns.get("host_ssh_actions", []))
            if "command" in columns:
                plaintext_ssh_action_rows = int(connection.execute(text(
                    "SELECT COUNT(*) FROM host_ssh_actions WHERE COALESCE(command, '') <> ''"
                )).scalar() or 0)
    return {
        "expected_tables": expected_tables,
        "missing_tables": missing_tables,
        "extra_tables": extra_tables,
        "missing_columns": missing_columns,
        "extra_columns": extra_columns,
        "table_columns": table_columns,
        "user_version": user_version,
        "unsafe_ssh_history": unsafe_ssh_history,
        "plaintext_ssh_action_rows": plaintext_ssh_action_rows,
    }


def _database_has_user_tables(target_engine=engine) -> bool:
    with target_engine.connect() as connection:
        return bool([
            name for name in inspect(connection).get_table_names()
            if not name.startswith("sqlite_")
        ])


def _baseline_backup_path(source_path: Path) -> Path:
    backup_dir = source_path.parent / "maintenance-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        backup_dir.chmod(0o700)
    except OSError:
        pass
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return backup_dir / f"manager-before-baseline-v{CURRENT_MANAGER_SCHEMA_VERSION}-{stamp}.sqlite3"


def _rebuild_manager_database_baseline(target_engine, state: dict[str, object]) -> dict[str, object]:
    database = target_engine.url.database
    if not database or database == ":memory:":
        raise RuntimeError(
            "Die automatische v1.3.5-Baseline-Übernahme benötigt eine dateibasierte SQLite-Datenbank"
        )

    source_path = Path(database)
    source_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = source_path.with_name(source_path.name + ".baseline-new")
    backup_path = _baseline_backup_path(source_path)
    for path in (temporary_path, Path(str(temporary_path) + "-wal"), Path(str(temporary_path) + "-shm")):
        path.unlink(missing_ok=True)

    target_engine.dispose()
    source = sqlite3.connect(source_path, timeout=60)
    try:
        source.execute("PRAGMA busy_timeout=60000")
        source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        backup = sqlite3.connect(backup_path)
        try:
            source.backup(backup)
            check = backup.execute("PRAGMA quick_check").fetchone()
            if not check or str(check[0]).casefold() != "ok":
                raise RuntimeError("Die Baseline-Sicherheitskopie der Manager-Datenbank ist nicht konsistent")
        finally:
            backup.close()
    finally:
        source.close()
    try:
        backup_path.chmod(0o600)
    except OSError:
        pass

    temporary_engine = create_engine(
        f"sqlite:///{temporary_path}",
        connect_args={"check_same_thread": False, "timeout": 60},
    )
    try:
        Base.metadata.create_all(temporary_engine)
    finally:
        temporary_engine.dispose()

    expected_tables = state["expected_tables"]
    assert isinstance(expected_tables, dict)
    source = sqlite3.connect(source_path, timeout=60)
    destination = sqlite3.connect(temporary_path, timeout=60)
    try:
        source.row_factory = sqlite3.Row
        destination.execute("PRAGMA foreign_keys=OFF")
        for table in Base.metadata.sorted_tables:
            columns = list(expected_tables[table.name])
            quoted_columns = ",".join(_quoted_identifier(column) for column in columns)
            placeholders = ",".join("?" for _ in columns)
            cursor = source.execute(
                f"SELECT {quoted_columns} FROM {_quoted_identifier(table.name)}"
            )
            while True:
                rows = cursor.fetchmany(1000)
                if not rows:
                    break
                destination.executemany(
                    f"INSERT INTO {_quoted_identifier(table.name)} ({quoted_columns}) VALUES ({placeholders})",
                    [tuple(row[column] for column in columns) for row in rows],
                )
        destination.execute(f"PRAGMA user_version={CURRENT_MANAGER_SCHEMA_VERSION}")
        destination.commit()
        destination.execute("PRAGMA foreign_keys=ON")
        violations = destination.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"Die v1.3.5-Baseline-Übernahme erzeugte {len(violations)} Fremdschlüsselverletzungen"
            )
        check = destination.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).casefold() != "ok":
            raise RuntimeError("Die neu aufgebaute Manager-Datenbank ist nicht konsistent")
        for table in Base.metadata.sorted_tables:
            columns = list(expected_tables[table.name])
            before = _table_digest(source, table.name, columns)
            after = _table_digest(destination, table.name, columns)
            if before != after:
                raise RuntimeError(f"Datenvergleich für Tabelle {table.name} ist fehlgeschlagen")
    finally:
        destination.close()
        source.close()

    for suffix in ("-wal", "-shm"):
        Path(str(source_path) + suffix).unlink(missing_ok=True)
    temporary_path.replace(source_path)
    try:
        source_path.chmod(0o600)
    except OSError:
        pass

    backup_dir = backup_path.parent
    backups = sorted(
        backup_dir.glob("manager-before-baseline-v*.sqlite3"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for old in backups[2:]:
        old.unlink(missing_ok=True)

    return {"rebuilt": True, "backup": str(backup_path)}


def _baseline_error(state: dict[str, object]) -> RuntimeError:
    details: list[str] = []
    missing_tables = state["missing_tables"]
    missing_columns = state["missing_columns"]
    if missing_tables:
        details.append("fehlende Tabellen: " + ", ".join(missing_tables))
    if missing_columns:
        formatted = [
            f"{table}.{column}"
            for table, columns in missing_columns.items()
            for column in columns
        ]
        details.append("fehlende Spalten: " + ", ".join(formatted))
    return RuntimeError(
        "Der Manager-Datenbankstand ist älter als die unterstützte Baseline "
        f"BorgBackup Manager v{MINIMUM_BASELINE_VERSION} ("
        + "; ".join(details)
        + "). Aktualisieren Sie zuerst auf v1.3.5 oder verwenden Sie eine Neuinstallation mit einem "
          "unterstützten v1.3.5+-Manager-Backup."
    )


def validate_current_schema(target_engine=engine) -> None:
    """Validate the normalized current schema after the v1.3.5 baseline adoption."""
    state = _manager_schema_state(target_engine)
    if state["missing_tables"] or state["missing_columns"]:
        raise _baseline_error(state)
    if state["extra_tables"] or state["extra_columns"]:
        raise RuntimeError(
            "Die Manager-Datenbank enthält noch nicht normalisierte v1.3.5-Altobjekte: "
            + ", ".join(state["extra_tables"] or sorted(state["extra_columns"]))
        )
    if int(state["unsafe_ssh_history"] or 0) > 0 or int(state["plaintext_ssh_action_rows"] or 0) > 0:
        raise RuntimeError(
            "Vertraulicher SSH-Altbestand erkannt. Die Sicherheitsbereinigung unter v1.3.5 muss vollständig "
            "abgeschlossen sein."
        )


def initialize_manager_database(target_engine=engine) -> dict[str, object]:
    """Create a fresh database or normalize every valid v1.3.5 database once.

    A database that has successfully run v1.3.5 already contains every current
    table and column. Earlier releases may nevertheless have left unused tables
    such as ``archive_mounts`` or surplus columns behind. Those objects are not
    rejected: the database is copied into the exact current schema, every
    current table is compared before and after, and only then is the original
    file atomically replaced. Missing current fields still identify a genuinely
    older, unsupported database and stop startup.
    """
    _load_model_metadata()
    if not _database_has_user_tables(target_engine):
        Base.metadata.create_all(target_engine)
        with target_engine.begin() as connection:
            connection.exec_driver_sql(f"PRAGMA user_version={CURRENT_MANAGER_SCHEMA_VERSION}")
        return {"schema_version": CURRENT_MANAGER_SCHEMA_VERSION, "rebuilt": False, "backup": None}

    state = _manager_schema_state(target_engine)
    if state["missing_tables"] or state["missing_columns"]:
        raise _baseline_error(state)
    if int(state["unsafe_ssh_history"] or 0) > 0 or int(state["plaintext_ssh_action_rows"] or 0) > 0:
        raise RuntimeError(
            "Vertraulicher SSH-Altbestand erkannt. Vor dem Update muss die Sicherheitsbereinigung unter "
            "v1.3.5 vollständig abgeschlossen werden."
        )

    rebuilt = False
    backup = None
    if state["extra_tables"] or state["extra_columns"]:
        result = _rebuild_manager_database_baseline(target_engine, state)
        rebuilt = bool(result["rebuilt"])
        backup = result["backup"]
    else:
        with target_engine.begin() as connection:
            connection.exec_driver_sql(f"PRAGMA user_version={CURRENT_MANAGER_SCHEMA_VERSION}")

    validate_current_schema(target_engine)
    return {
        "schema_version": CURRENT_MANAGER_SCHEMA_VERSION,
        "rebuilt": rebuilt,
        "backup": backup,
    }
