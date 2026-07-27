from __future__ import annotations

from pathlib import Path

from app import archive_cache


def test_archive_cache_is_persistent_variant_scoped_and_invalidated(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(archive_cache, "ARCHIVE_CACHE_DIR", tmp_path)
    regular = {"repository_statistics": {"deduplicated_size": 123}, "archives": [{"name": "one"}]}
    checkpoints = {"repository_statistics": {}, "archives": [{"name": "one.checkpoint"}]}

    first = archive_cache.store_archive_cache(7, False, regular)
    second = archive_cache.store_archive_cache(7, True, checkpoints)

    assert archive_cache.load_archive_cache(7, False)["data"] == regular
    assert archive_cache.load_archive_cache(7, True)["data"] == checkpoints
    assert first["generated_at"]
    assert second["generated_at"]
    assert archive_cache.archive_cache_size(7) > 0

    assert archive_cache.invalidate_archive_cache(7) == 2
    assert archive_cache.load_archive_cache(7, False) is None
    assert archive_cache.load_archive_cache(7, True) is None
    assert archive_cache.archive_cache_size(7) == 0


def test_archive_listing_accepts_wrapper_text_around_borg_json():
    import json
    from app.main import parse_archive_listing

    output = "informational prefix\n" + json.dumps({
        "archives": [{"name": "host-2026-07-19T09:00:00", "time": "2026-07-19T09:00:00+02:00"}],
    }) + "\nremote wrapper finished"
    archives = parse_archive_listing(output)
    assert [item["name"] for item in archives] == ["host-2026-07-19T09:00:00"]


def _create_archive_refresh_run(*, suffix: str):
    from app.database import Base, SessionLocal, engine
    from app.models import Repository, Run

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        repository = Repository(
            name=f"archive-refresh-{suffix}",
            location=f"/tmp/archive-refresh-{suffix}",
            encryption_mode="none",
            initialized=True,
            enabled=True,
        )
        db.add(repository)
        db.flush()
        run = Run(
            repository_id=repository.id,
            job_name_snapshot=f"Archivliste: {repository.name}",
            action="archive-refresh",
            status="queued",
            command_preview="borg info --json --glob-archives *",
        )
        db.add(run)
        db.commit()
        return int(repository.id), int(run.id)


def test_archive_refresh_endpoint_code_is_cache_only():
    from pathlib import Path

    main = (Path(__file__).resolve().parents[1] / "app/main.py").read_text(encoding="utf-8")
    dataset = main.split("async def _repository_archive_dataset", 1)[1].split(
        '@app.post("/api/repositories/{repository_id}/archives/refresh"', 1
    )[0]
    assert "execute_interactive" not in dataset
    assert "repository_archives_info_command" not in dataset
    assert '"missing"' in dataset


def test_archive_refresh_frontend_queues_post_instead_of_force_get():
    from pathlib import Path

    javascript = (Path(__file__).resolve().parents[1] / "app/static/app.js").read_text(encoding="utf-8")
    load_archives = javascript.split("async function loadArchives(options = {})", 1)[1].split(
        "function archiveSelectionDeviceLabel", 1
    )[0]
    assert "/archives/refresh?consider_checkpoints=" in load_archives
    assert "{method: 'POST'}" in load_archives
    assert "force_refresh=" not in load_archives
    assert "watchRunCompletion(result.run_id" in load_archives


import pytest


@pytest.mark.asyncio
async def test_background_archive_refresh_populates_cache_without_storing_borg_json(monkeypatch, tmp_path):
    import json
    from uuid import uuid4
    from app import archive_cache, service
    from app.database import SessionLocal
    from app.models import Run

    monkeypatch.setattr(archive_cache, "ARCHIVE_CACHE_DIR", tmp_path)
    repository_id, run_id = _create_archive_refresh_run(suffix=uuid4().hex[:10])
    payload = {
        "cache": {"stats": {
            "total_size": 123456,
            "total_csize": 100000,
            "unique_csize": 54321,
            "unique_size": 60000,
            "total_chunks": 10,
            "total_unique_chunks": 8,
        }},
        "archives": [{
            "name": "host-2026-07-27T12:00:00",
            "id": "abc",
            "start": "2026-07-27T12:00:00+02:00",
            "end": "2026-07-27T12:10:00+02:00",
            "stats": {"nfiles": 42, "original_size": 1000, "compressed_size": 800, "deduplicated_size": 400},
        }],
    }
    calls = []

    async def fake_execute(repo_id, command):
        calls.append((repo_id, command.preview))
        return 0, json.dumps(payload), ""

    monkeypatch.setattr(service, "execute_interactive", fake_execute)
    await service.execute_repository_archive_refresh(run_id, repository_id, False)

    cached = archive_cache.load_archive_cache(repository_id, False)
    assert cached is not None
    assert [item["name"] for item in cached["data"]["archives"]] == ["host-2026-07-27T12:00:00"]
    assert len(calls) == 1
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run.status == "success"
        assert "1 Archiv(e)" in run.output
        assert '"archives"' not in (run.output or "")
        assert '"archives"' not in (run.log_output or "")


@pytest.mark.asyncio
async def test_background_archive_refresh_checkpoint_variant_uses_second_list_pass(monkeypatch, tmp_path):
    import json
    from uuid import uuid4
    from app import archive_cache, service

    monkeypatch.setattr(archive_cache, "ARCHIVE_CACHE_DIR", tmp_path)
    repository_id, run_id = _create_archive_refresh_run(suffix=uuid4().hex[:10])
    responses = [
        (0, json.dumps({"archives": [{"name": "regular", "stats": {"nfiles": 1}}]}), ""),
        (0, json.dumps({"archives": [
            {"name": "regular", "time": "2026-07-27T10:00:00+02:00"},
            {"name": "regular.checkpoint", "time": "2026-07-27T10:01:00+02:00"},
        ]}), ""),
    ]

    async def fake_execute(_repo_id, _command):
        return responses.pop(0)

    monkeypatch.setattr(service, "execute_interactive", fake_execute)
    await service.execute_repository_archive_refresh(run_id, repository_id, True)

    cached = archive_cache.load_archive_cache(repository_id, True)
    assert cached is not None
    assert {item["name"] for item in cached["data"]["archives"]} == {"regular", "regular.checkpoint"}
    assert not responses


@pytest.mark.asyncio
async def test_background_archive_refresh_persists_actionable_failure(monkeypatch, tmp_path):
    from uuid import uuid4
    from app import archive_cache, service
    from app.database import SessionLocal
    from app.models import Run

    monkeypatch.setattr(archive_cache, "ARCHIVE_CACHE_DIR", tmp_path)
    repository_id, run_id = _create_archive_refresh_run(suffix=uuid4().hex[:10])
    error = """Traceback (most recent call last):\nPermissionError: [Errno 13] Permission denied: '/repositories/borg/data/69/69536'\nPlatform: Linux bbm\n"""

    async def denied(_repository_id, _command):
        return 2, "", error

    monkeypatch.setattr(service, "execute_interactive", denied)
    await service.execute_repository_archive_refresh(run_id, repository_id, False)

    assert archive_cache.load_archive_cache(repository_id, False) is None
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run.status == "failed"
        assert "Zugriff auf Repository-Datei verweigert" in run.error
        assert "/repositories/borg/data/69/69536" in run.error
        assert "Traceback" not in run.error
        assert "Platform:" not in run.error
