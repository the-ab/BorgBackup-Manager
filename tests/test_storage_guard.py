from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app import storage_guard


def settings(enabled: bool = True, threshold: int = 95, mount_limits: dict[str, int] | None = None):
    return SimpleNamespace(
        storage_guard_enabled=enabled,
        storage_guard_threshold_percent=threshold,
        mount_parallel_limits=mount_limits or {},
    )


def repository(repository_id: int, name: str, path: Path, enabled=None, threshold=None):
    return SimpleNamespace(
        id=repository_id,
        name=name,
        storage_path=str(path),
        storage_guard_enabled=enabled,
        storage_guard_threshold_percent=threshold,
    )


def test_repository_status_uses_repository_path_and_repository_override(monkeypatch, tmp_path: Path):
    repo_path = tmp_path / "repositories" / "nfs-a"
    repo_path.mkdir(parents=True)
    seen = []
    usage = type("Usage", (), {"total": 1000, "used": 910, "free": 90})()
    monkeypatch.setattr(storage_guard.shutil, "disk_usage", lambda path: seen.append(Path(path)) or usage)

    status = storage_guard.repository_storage_status(
        repository(7, "NFS A", repo_path, enabled=True, threshold=90),
        settings(enabled=False, threshold=98),
    )

    assert seen == [repo_path]
    assert status["guard_source"] == "repository"
    assert status["guard_threshold_percent"] == 90
    assert status["guard_blocked"] is True


def test_repository_can_disable_global_guard(monkeypatch, tmp_path: Path):
    repo_path = tmp_path / "repositories" / "nfs-b"
    repo_path.mkdir(parents=True)
    usage = type("Usage", (), {"total": 100, "used": 99, "free": 1})()
    monkeypatch.setattr(storage_guard.shutil, "disk_usage", lambda _path: usage)

    status = storage_guard.repository_storage_status(
        repository(8, "NFS B", repo_path, enabled=False),
        settings(enabled=True, threshold=95),
    )

    assert status["guard_enabled"] is False
    assert status["guard_blocked"] is False


def test_diagnostics_include_every_nested_repository_mount(monkeypatch, tmp_path: Path):
    root = tmp_path / "repositories"
    nfs_a = root / "nfs-a"
    nfs_b = root / "nfs-b"
    nfs_a.mkdir(parents=True)
    nfs_b.mkdir()
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        f"10 1 0:1 / {root} rw - ext4 /dev/root rw\n"
        f"11 10 0:2 / {nfs_a} rw - nfs server:/a rw\n"
        f"12 10 0:3 / {nfs_b} rw - nfs server:/b rw\n",
        encoding="utf-8",
    )
    usage_by_path = {
        root.resolve(): type("Usage", (), {"total": 1000, "used": 100, "free": 900})(),
        nfs_a.resolve(): type("Usage", (), {"total": 200, "used": 191, "free": 9})(),
        nfs_b.resolve(): type("Usage", (), {"total": 500, "used": 100, "free": 400})(),
    }
    monkeypatch.setattr(storage_guard.shutil, "disk_usage", lambda path: usage_by_path[Path(path).resolve()])

    rows = storage_guard.repository_storage_filesystems(
        [
            repository(1, "A", nfs_a),
            repository(2, "B", nfs_b, enabled=True, threshold=80),
        ],
        root,
        settings(enabled=True, threshold=95, mount_limits={str(nfs_a.resolve()): 2}),
        mountinfo,
    )

    by_path = {row["path"]: row for row in rows}
    assert set(by_path) == {str(root.resolve()), str(nfs_a.resolve()), str(nfs_b.resolve())}
    assert by_path[str(nfs_a.resolve())]["guard_blocked"] is True
    assert by_path[str(nfs_a.resolve())]["parallel_limit"] == 2
    assert by_path[str(nfs_b.resolve())]["parallel_limit"] == 0
    assert by_path[str(nfs_a.resolve())]["repositories"][0]["guard_threshold_percent"] == 95
    assert by_path[str(nfs_b.resolve())]["repositories"][0]["guard_threshold_percent"] == 80
    assert by_path[str(nfs_b.resolve())]["guard_blocked"] is False


def test_webui_exposes_global_and_repository_storage_guard_controls():
    project = Path(__file__).resolve().parents[1]
    html = (project / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (project / "app/static/app.js").read_text(encoding="utf-8")
    main = (project / "app/main.py").read_text(encoding="utf-8")

    assert 'name="storage_guard_enabled"' in html
    assert 'name="storage_guard_threshold_percent"' in html
    assert 'name="storage_guard_mode"' in html
    assert "repository_storage_filesystems" in main
    assert "Repository-Dateisysteme" in javascript
    assert "global_parallel_limit" in main
    assert "item.parallel_limit" in javascript
    assert "wirksame Grenze für verschiedene Repositorys dieses Dateisystems" in javascript
    assert "storage_guard_threshold_percent" in javascript


def test_external_repository_guard_defaults_disabled_but_can_be_enabled():
    external = SimpleNamespace(
        id=90, name="external", storage_path=None,
        storage_guard_enabled=None, storage_guard_threshold_percent=None,
    )
    assert storage_guard.effective_storage_guard(external, settings(enabled=True, threshold=93)) == (
        False, 93, "external-default",
    )
    external.storage_guard_enabled = True
    assert storage_guard.effective_storage_guard(external, settings(enabled=False, threshold=93)) == (
        True, 93, "repository",
    )


def test_webui_exposes_external_storage_usage_and_dynamic_guard_text():
    project = Path(__file__).resolve().parents[1]
    html = (project / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (project / "app/static/app.js").read_text(encoding="utf-8")
    service = (project / "app/service.py").read_text(encoding="utf-8")

    assert "Externe SSH-Repositorys" in html
    assert "EXTERNAL_STORAGE_POLL_SECONDS = 15" in service
    assert "refresh_external_repository_storage" in service
    assert "SPEICHERPLATZ-SPERRE" in service
    assert 'data-label="Belegung"' in javascript
    assert "storage_usage_percent" in javascript
    assert "Status / ID" in javascript
