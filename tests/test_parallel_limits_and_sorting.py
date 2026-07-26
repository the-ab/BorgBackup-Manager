from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, inspect

os.environ.setdefault("BBM_ADMIN_TOKEN", "test-token")
os.environ.setdefault("BBM_ALLOW_LEGACY_TOKEN_AUTH", "1")
os.environ.setdefault("BBM_DATABASE_URL", "sqlite://")

from app import service
from app.database import Base, SessionLocal, engine, migrate_schema
from app.models import Repository, Run
from app.runner import Command


PROJECT_ROOT = Path(__file__).parents[1]


def _settings(limit: int, mount_limits: dict[str, int] | None = None, *, source_stats_limit: int = 1):
    return SimpleNamespace(
        max_parallel_runs=limit,
        source_stats_parallel_limit=source_stats_limit,
        mount_parallel_limits=mount_limits or {},
        run_log_max_mib=50,
        repository_size_after_run=False,
        compact_after_prune=False,
    )


def _repository(name: str) -> Repository:
    return Repository(name=name, location=f"/tmp/{name}", extra_env_json="{}", initialized=True)


def test_global_parallel_limit_serializes_different_repositories(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        first_repository = _repository(f"global-a-{suffix}")
        second_repository = _repository(f"global-b-{suffix}")
        db.add_all([first_repository, second_repository]); db.flush()
        first = Run(repository_id=first_repository.id, action="info", status="queued")
        second = Run(repository_id=second_repository.id, action="info", status="queued")
        db.add_all([first, second]); db.commit()
        first_id, second_id = first.id, second.id

    active = 0
    maximum_active = 0

    async def controlled_execute(_command, **_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.03)
        active -= 1
        return 0, "ok", ""

    monkeypatch.setattr(service, "load_settings", lambda: _settings(1))
    monkeypatch.setattr(service, "execute", controlled_execute)

    async def run_both():
        await asyncio.gather(
            service.execute_run(first_id, Command(["true"], "true"), refresh_size_after=False),
            service.execute_run(second_id, Command(["true"], "true"), refresh_size_after=False),
        )

    asyncio.run(run_both())
    assert maximum_active == 1




def test_source_statistics_have_dedicated_parallel_limit(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        first_repository = _repository(f"stats-a-{suffix}")
        second_repository = _repository(f"stats-b-{suffix}")
        db.add_all([first_repository, second_repository]); db.flush()
        first = Run(repository_id=first_repository.id, action="source-stats", status="queued")
        second = Run(repository_id=second_repository.id, action="source-stats", status="queued")
        db.add_all([first, second]); db.commit()
        run_ids = [first.id, second.id]

    active = 0
    maximum_active = 0

    async def controlled_execute(_command, **_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.04)
        active -= 1
        return 0, "ok", ""

    monkeypatch.setattr(service, "load_settings", lambda: _settings(0, source_stats_limit=1))
    monkeypatch.setattr(service, "execute", controlled_execute)

    async def run_all():
        await asyncio.gather(*[
            service.execute_run(run_id, Command(["true"], "true"), refresh_size_after=False)
            for run_id in run_ids
        ])

    asyncio.run(run_all())
    assert maximum_active == 1


def test_source_statistics_do_not_reserve_repository_capacity(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        repository = _repository(f"stats-independent-{suffix}")
        repository.parallel_limit = 1
        db.add(repository); db.flush()
        stats = Run(repository_id=repository.id, action="source-stats", status="queued")
        backup = Run(repository_id=repository.id, action="backup", status="queued")
        db.add_all([stats, backup]); db.commit()
        run_ids = [stats.id, backup.id]

    active = 0
    maximum_active = 0

    async def controlled_execute(_command, **_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.04)
        active -= 1
        return 0, "ok", ""

    monkeypatch.setattr(service, "load_settings", lambda: _settings(0, source_stats_limit=1))
    monkeypatch.setattr(service, "execute", controlled_execute)

    async def run_all():
        await asyncio.gather(*[
            service.execute_run(run_id, Command(["true"], "true"), refresh_size_after=False)
            for run_id in run_ids
        ])

    asyncio.run(run_all())
    assert maximum_active == 2

def test_orphaned_active_rows_do_not_consume_global_capacity(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        orphan_repository = _repository(f"orphan-{suffix}")
        current_repository = _repository(f"current-{suffix}")
        db.add_all([orphan_repository, current_repository]); db.flush()
        # Simulates a task that disappeared between normal recovery cycles.
        db.add(Run(repository_id=orphan_repository.id, action="info", status="running"))
        current = Run(repository_id=current_repository.id, action="info", status="queued")
        db.add(current); db.commit()
        current_id = current.id

    calls = 0

    async def controlled_execute(_command, **_kwargs):
        nonlocal calls
        calls += 1
        return 0, "ok", ""

    monkeypatch.setattr(service, "load_settings", lambda: _settings(1))
    monkeypatch.setattr(service, "execute", controlled_execute)
    asyncio.run(service.execute_run(
        current_id, Command(["true"], "true"), refresh_size_after=False,
    ))

    assert calls == 1
    with SessionLocal() as db:
        assert db.get(Run, current_id).status == "success"


def test_schedule_parallel_limit_serializes_different_repositories(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        first_repository = _repository(f"schedule-a-{suffix}")
        second_repository = _repository(f"schedule-b-{suffix}")
        db.add_all([first_repository, second_repository]); db.flush()
        common = dict(
            action="backup", status="queued", trigger_type="schedule",
            schedule_name_snapshot="Nachtlauf", schedule_id_snapshot=991,
            schedule_parallel_limit_snapshot=1,
        )
        first = Run(repository_id=first_repository.id, **common)
        second = Run(repository_id=second_repository.id, **common)
        db.add_all([first, second]); db.commit()
        first_id, second_id = first.id, second.id

    active = 0
    maximum_active = 0

    async def controlled_execute(_command, **_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.03)
        active -= 1
        return 0, "ok", ""

    monkeypatch.setattr(service, "load_settings", lambda: _settings(0))
    monkeypatch.setattr(service, "execute", controlled_execute)

    async def run_both():
        await asyncio.gather(
            service.execute_run(first_id, Command(["true"], "true"), refresh_size_after=False),
            service.execute_run(second_id, Command(["true"], "true"), refresh_size_after=False),
        )

    asyncio.run(run_both())
    assert maximum_active == 1


def test_busy_repository_does_not_leave_other_global_slot_unused(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        first_repository = _repository(f"eligible-a-{suffix}")
        second_repository = _repository(f"eligible-b-{suffix}")
        db.add_all([first_repository, second_repository]); db.flush()
        first = Run(repository_id=first_repository.id, action="info", status="queued")
        blocked_same_repository = Run(repository_id=first_repository.id, action="check", status="queued")
        independent = Run(repository_id=second_repository.id, action="info", status="queued")
        db.add_all([first, blocked_same_repository, independent]); db.commit()
        run_ids = [first.id, blocked_same_repository.id, independent.id]

    active = 0
    maximum_active = 0

    async def controlled_execute(_command, **_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.04)
        active -= 1
        return 0, "ok", ""

    monkeypatch.setattr(service, "load_settings", lambda: _settings(2))
    monkeypatch.setattr(service, "execute", controlled_execute)

    async def run_all():
        await asyncio.gather(*[
            service.execute_run(run_id, Command(["true"], "true"), refresh_size_after=False)
            for run_id in run_ids
        ])

    asyncio.run(run_all())
    assert maximum_active == 2



def test_repository_parallel_limit_allows_two_backup_runs(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        repository = _repository(f"repo-parallel-{suffix}")
        repository.parallel_limit = 2
        db.add(repository); db.flush()
        runs = [Run(repository_id=repository.id, action="backup", status="queued") for _ in range(3)]
        db.add_all(runs); db.commit()
        run_ids = [row.id for row in runs]

    active = 0
    maximum_active = 0

    async def controlled_execute(_command, **_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.04)
        active -= 1
        return 0, "ok", ""

    monkeypatch.setattr(service, "load_settings", lambda: _settings(0))
    monkeypatch.setattr(service, "execute", controlled_execute)

    async def run_all():
        await asyncio.gather(*[
            service.execute_run(run_id, Command(["true"], "true"), refresh_size_after=False)
            for run_id in run_ids
        ])

    asyncio.run(run_all())
    assert maximum_active == 2


def test_mount_parallel_limit_serializes_different_repositories(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        first_repository = _repository(f"mount-a-{suffix}")
        second_repository = _repository(f"mount-b-{suffix}")
        first_repository.parallel_limit = 2
        second_repository.parallel_limit = 2
        db.add_all([first_repository, second_repository]); db.flush()
        first = Run(repository_id=first_repository.id, action="backup", status="queued")
        second = Run(repository_id=second_repository.id, action="backup", status="queued")
        db.add_all([first, second]); db.commit()
        run_ids = [first.id, second.id]

    active = 0
    maximum_active = 0

    async def controlled_execute(_command, **_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.04)
        active -= 1
        return 0, "ok", ""

    monkeypatch.setattr(service, "load_settings", lambda: _settings(0, {"/repositories/offline": 1}))
    monkeypatch.setattr(service, "_repository_mount_key", lambda repository, mounts=None: "/repositories/offline")
    monkeypatch.setattr(service, "execute", controlled_execute)

    async def run_all():
        await asyncio.gather(*[
            service.execute_run(run_id, Command(["true"], "true"), refresh_size_after=False)
            for run_id in run_ids
        ])

    asyncio.run(run_all())
    assert maximum_active == 1


def test_non_backup_repository_action_remains_exclusive(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        repository = _repository(f"repo-exclusive-{suffix}")
        repository.parallel_limit = 3
        db.add(repository); db.flush()
        first = Run(repository_id=repository.id, action="backup", status="queued")
        check = Run(repository_id=repository.id, action="check", status="queued")
        second = Run(repository_id=repository.id, action="backup", status="queued")
        db.add_all([first, check, second]); db.commit()
        run_ids = [first.id, check.id, second.id]

    timeline: list[tuple[str, int]] = []
    active = 0

    async def controlled_execute(command, **_kwargs):
        nonlocal active
        active += 1
        timeline.append(("start", active))
        await asyncio.sleep(0.025)
        timeline.append(("end", active))
        active -= 1
        return 0, "ok", ""

    monkeypatch.setattr(service, "load_settings", lambda: _settings(0))
    monkeypatch.setattr(service, "execute", controlled_execute)

    async def run_all():
        await asyncio.gather(*[
            service.execute_run(run_id, Command(["true"], "true"), refresh_size_after=False)
            for run_id in run_ids
        ])

    asyncio.run(run_all())
    # The check run sits between the two backups in FIFO order and must execute alone.
    assert any(kind == "start" and count == 1 for kind, count in timeline)


def test_parallel_limit_columns_are_added_by_migration(tmp_path):
    database = tmp_path / "manager.db"
    target = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(target)
    migrate_schema(target)
    inspector = inspect(target)
    repositories = {column["name"] for column in inspector.get_columns("repositories")}
    schedules = {column["name"] for column in inspector.get_columns("backup_schedules")}
    runs = {column["name"] for column in inspector.get_columns("runs")}
    assert "parallel_limit" in repositories
    assert "parallel_limit" in schedules
    jobs = {column["name"] for column in inspector.get_columns("jobs")}
    assert {"manual_prune_after_backup", "manual_compact_after_prune"}.issubset(jobs)
    assert {"schedule_id_snapshot", "schedule_parallel_limit_snapshot"}.issubset(runs)


def test_sort_controls_and_user_scoped_persistence_are_present():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    for control in ("dashboard-job-sort", "job-sort", "repo-sort", "host-sort"):
        assert f'id="{control}"' in html
    assert "bbm-sort-preferences-${user}" in javascript
    assert "sortedDashboardJobs" in javascript
    assert "sortedJobs" in javascript
    assert "sortedRepositories" in javascript
    assert "sortedHosts" in javascript


def test_manual_maintenance_chain_blocks_later_repository_runs(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        repository = _repository(f"manual-chain-{suffix}")
        repository.parallel_limit = 3
        db.add(repository); db.flush()
        root = Run(repository_id=repository.id, action="backup", status="queued")
        later = Run(repository_id=repository.id, action="backup", status="queued")
        db.add_all([root, later]); db.commit()
        root_id, later_id = root.id, later.id
        service._register_repository_chain(repository, root_id, "chain-test")

    monkeypatch.setattr(service, "load_settings", lambda: _settings(0))
    with service._active_run_lock:
        service._executing_run_ids.update({root_id, later_id})
    try:
        with SessionLocal() as db:
            selected, blockers = service._execution_plan(db, current_run_id=root_id)
        assert root_id in selected
        assert later_id not in selected
        assert blockers[later_id]["kind"] == "maintenance-chain"
        service._mark_repository_chain_started(root_id)
        with SessionLocal() as db:
            selected, blockers = service._execution_plan(db, current_run_id=later_id)
        assert later_id not in selected
        assert blockers[later_id]["kind"] == "maintenance-chain"
    finally:
        service._release_repository_chain("chain-test")
        with service._active_run_lock:
            service._executing_run_ids.discard(root_id)
            service._executing_run_ids.discard(later_id)


def test_manager_side_borg_commands_share_single_cache_slot(monkeypatch):
    active = 0
    peak = 0

    async def fake_execute(_command, **_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.03)
        active -= 1
        return 0, "", ""

    async def scenario():
        service._manager_borg_locks.clear()
        monkeypatch.setattr(service, "_mount_lock", lambda _repository_id: None)
        monkeypatch.setattr(service, "_repository_lock", lambda _repository_id: None)
        monkeypatch.setattr(
            service,
            "_cleanup_external_manager_cache_locks",
            lambda _repository_id: {"lock_directories_removed": 0, "lock_files_removed": 0},
        )
        monkeypatch.setattr(service, "execute", fake_execute)
        first = Command(argv=["true"], preview="first", manager_cache_repository_id=77)
        second = Command(argv=["true"], preview="second", manager_cache_repository_id=77)
        await asyncio.gather(
            service.execute_interactive(77, first),
            service.execute_interactive(77, second),
        )

    asyncio.run(scenario())
    assert peak == 1
