from __future__ import annotations

from pathlib import Path

import pytest

from app import archive_mounts
from app.models import Repository
from app.runner import manager_archive_mount_command, manager_archive_unmount_command


def test_archive_mount_path_is_confined_and_deterministic(tmp_path, monkeypatch):
    root = tmp_path / "archive-mounts"
    root.mkdir()
    monkeypatch.setattr(archive_mounts, "ARCHIVE_MOUNT_ROOT", root)

    first = archive_mounts.archive_mount_path(7, "NAS / Haupt-Repo", "server-2026-07-31T22:00:00")
    second = archive_mounts.archive_mount_path(7, "NAS / Haupt-Repo", "server-2026-07-31T22:00:00")

    assert first == second
    assert first.parent.parent == root
    assert first.parent.name.endswith("-r7")
    assert first.name.startswith("server-2026-07-31T22-00-00-")
    assert root in first.parents


@pytest.mark.parametrize("archive", ["", "-danger", "repo::archive", "folder/archive", "bad\nname"])
def test_archive_mount_path_rejects_unsafe_archive_names(tmp_path, monkeypatch, archive):
    root = tmp_path / "archive-mounts"
    root.mkdir()
    monkeypatch.setattr(archive_mounts, "ARCHIVE_MOUNT_ROOT", root)
    with pytest.raises(ValueError):
        archive_mounts.archive_mount_path(3, "repo", archive)


def test_prepare_archive_mount_path_rejects_nonempty_target(tmp_path, monkeypatch):
    root = tmp_path / "archive-mounts"
    target = root / "repo-r1" / "archive-123"
    target.mkdir(parents=True)
    (target / "unexpected-file").write_text("do not reuse", encoding="utf-8")
    monkeypatch.setattr(archive_mounts, "ARCHIVE_MOUNT_ROOT", root)
    monkeypatch.setattr(archive_mounts, "archive_mount_is_active", lambda _path: False)

    with pytest.raises(ValueError, match="not empty"):
        archive_mounts.prepare_archive_mount_path(target)


def test_prepare_archive_mount_path_rejects_symlink_component(tmp_path, monkeypatch):
    root = tmp_path / "archive-mounts"
    outside = tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    (root / "repo-r1").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(archive_mounts, "ARCHIVE_MOUNT_ROOT", root)

    with pytest.raises(ValueError, match="symbolic link"):
        archive_mounts.prepare_archive_mount_path(root / "repo-r1" / "archive-123")


def test_manager_archive_mount_commands_are_read_only_lifecycle_commands(monkeypatch):
    monkeypatch.setattr("app.runner.os.geteuid", lambda: 1000)
    monkeypatch.setattr("app.runner.get_repository_secret", lambda _repository, _name: None)
    monkeypatch.setattr("app.runner.load_repository_environment", lambda _repository: {})
    repository = Repository(
        id=7,
        name="repo",
        location="/repositories/repo",
        storage_path="/repositories/repo",
        encryption_mode="none",
        initialized=True,
        enabled=True,
    )

    mount = manager_archive_mount_command(repository, "archive-1", "/archive-mounts/repo-r7/archive-1")
    assert mount.allow_active_archive_mount is True
    assert mount.argv == ["borg", "--lock-wait", "600", "mount", "-o", "allow_other", "::archive-1", "/archive-mounts/repo-r7/archive-1"]
    assert mount.timeout_seconds == 900

    unmount = manager_archive_unmount_command("/archive-mounts/repo-r7/archive-1")
    assert unmount.allow_active_archive_mount is True
    assert "fusermount3 -u" in unmount.argv[2]
    assert "borg umount" in unmount.argv[2]
    assert "fusermount3 -uz" in unmount.argv[2]
    assert "timeout -k 1 5" in unmount.argv[2]
    assert unmount.timeout_seconds == 18


def test_archive_mounts_are_enabled_in_default_compose_files():
    root = Path(__file__).parents[1]
    compose_files = [
        (root / "compose.yaml").read_text(encoding="utf-8"),
        (root / "docker-compose/compose.yaml").read_text(encoding="utf-8"),
    ]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "fuse3" in dockerfile
    assert "python3-pyfuse3" in dockerfile
    assert "user_allow_other" in dockerfile
    assert not (root / "compose.archive-mounts.yaml").exists()
    assert not (root / "docker-compose/compose.archive-mounts.yaml").exists()
    for text in compose_files:
        assert "BBM_ARCHIVE_MOUNTS_ENABLED: '1'" in text
        assert "/dev/fuse:/dev/fuse" in text
        assert "SYS_ADMIN" in text
        assert "apparmor:unconfined" in text
        assert "propagation: rshared" in text
        assert "target: /archive-mounts" in text


def test_archive_mount_ui_and_backend_routes_are_present():
    root = Path(__file__).parents[1]
    main = (root / "app/main.py").read_text(encoding="utf-8")
    service = (root / "app/service.py").read_text(encoding="utf-8")
    frontend = (root / "app/static/app.js").read_text(encoding="utf-8")
    html = (root / "app/static/index.html").read_text(encoding="utf-8")

    assert '@app.get("/api/archive-mounts/capability"' in main
    assert '@app.post("/api/repositories/{repository_id}/archive-mounts"' in main
    assert '@app.delete("/api/archive-mounts/{mount_id}"' in main
    assert "nur für lokal verwaltete Repositories" in main
    assert "ActiveArchiveMountError" in service
    assert 'reason.get("kind") == "archive-mount"' in service
    assert "data-archive-mount" in frontend
    assert "data-manager-unmount" in frontend
    assert 'id="archive-mount-panel"' in html
    assert "/data/exports" not in frontend[frontend.index("function mountManagerArchive"):len(frontend)]


def test_fuse_allow_other_configuration_is_required(tmp_path):
    fuse_conf = tmp_path / "fuse.conf"
    fuse_conf.write_text("# user_allow_other\n", encoding="utf-8")
    assert archive_mounts._fuse_user_allow_other_enabled(fuse_conf) is False
    fuse_conf.write_text("user_allow_other # BBM archive mounts\n", encoding="utf-8")
    assert archive_mounts._fuse_user_allow_other_enabled(fuse_conf) is True


def test_entrypoint_validates_allow_other_and_bounded_unmounts():
    root = Path(__file__).parents[1]
    entrypoint = (root / "docker/entrypoint.sh").read_text(encoding="utf-8")
    assert "user_allow_other" in entrypoint
    assert "timeout -k 1 5 runuser -u borg -- fusermount3 -u" in entrypoint
    assert "fusermount3 -uz" in entrypoint


def test_unmount_endpoint_bypasses_repository_execution_lock():
    root = Path(__file__).parents[1]
    main = (root / "app/main.py").read_text(encoding="utf-8")
    start = main.index('async def delete_manager_archive_mount(mount_id: int):')
    end = main.index('\n\ndef run_json(', start)
    endpoint = main[start:end]

    assert 'row.status = "unmounting"' in endpoint
    assert 'execute(command)' in endpoint
    assert 'execute_interactive(repository_id, command)' not in endpoint
    assert 'normal repository execution' in endpoint


def test_active_mount_blocking_uses_physical_fuse_state_after_unmount_errors():
    root = Path(__file__).parents[1]
    service = (root / "app/service.py").read_text(encoding="utf-8")
    start = service.index('def _active_manager_archive_mount(')
    end = service.index('\n\n_SQLITE_BORG_ITEM_LINE_BYTES_RE', start)
    helper = service[start:end]

    assert 'ManagerArchiveMount.status.in_' not in helper
    assert 'row.status == "mounting" or archive_mount_is_active(row.mount_path)' in helper
    assert 'including mounts whose previous unmount attempt ended in an error' in helper


def test_unmount_executes_without_entering_interactive_repository_scheduler(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import app.main as main_module

    row = SimpleNamespace(id=9, repository_id=21, mount_path="/archive-mounts/repo-r21/archive", status="mounted", error="")
    deleted = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, row_id):
            return row if row_id == row.id and not deleted else None

        def commit(self):
            return None

        def delete(self, value):
            deleted.append(value)

    active_states = iter([True, False])
    executed = []

    async def fake_execute(command):
        executed.append(command)
        return 0, "", ""

    async def forbidden_interactive(*_args, **_kwargs):
        raise AssertionError("unmount must not enter the repository execution scheduler")

    monkeypatch.setattr(main_module, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(main_module, "archive_mount_is_active", lambda _path: next(active_states))
    monkeypatch.setattr(main_module, "manager_archive_unmount_command", lambda path: SimpleNamespace(path=path))
    monkeypatch.setattr(main_module, "execute", fake_execute)
    monkeypatch.setattr(main_module, "execute_interactive", forbidden_interactive)
    monkeypatch.setattr(main_module, "cleanup_archive_mount_path", lambda _path: None)

    response = asyncio.run(main_module.delete_manager_archive_mount(row.id))

    assert response.status_code == 204
    assert len(executed) == 1
    assert deleted == [row]


def test_mount_state_wait_handles_delayed_kernel_visibility(monkeypatch):
    import asyncio

    import app.main as main_module

    states = iter([False, False, True])
    monkeypatch.setattr(main_module, "archive_mount_is_active", lambda _path: next(states))

    result = asyncio.run(main_module.wait_for_archive_mount_state(
        "/archive-mounts/repo-r1/archive",
        active=True,
        timeout_seconds=0.2,
        poll_seconds=0.001,
    ))

    assert result is True


def test_mount_endpoint_waits_for_fuse_visibility_and_frontend_shows_progress():
    root = Path(__file__).parents[1]
    main = (root / "app/main.py").read_text(encoding="utf-8")
    frontend = (root / "app/static/app.js").read_text(encoding="utf-8")

    start = main.index('async def create_manager_archive_mount(repository_id: int, data: ArchiveMountIn) -> dict:')
    end = main.index('\n\ndef archive_unmount_incident(', start)
    endpoint = main[start:end]

    assert 'await wait_for_archive_mount_activation(' in endpoint
    assert 'timeout_seconds=15.0, poll_seconds=0.2' in endpoint
    assert 'Borg meldete keinen aktiven FUSE-Mount am vorgesehenen Zielpfad' not in endpoint
    assert 'await asyncio.wait_for(execute(command), timeout=24)' in endpoint

    assert "status: 'mounting'" in frontend
    assert "markButtonBusy(button || actionButton(), english ? 'Mounting …' : 'Wird eingehängt …')" in frontend
    assert "Mounting archive “${archive}” …" in frontend
    assert "Archiv „${archive}“ wird eingehängt …" in frontend
    assert "mountedArchive?.status === 'mounting'" in frontend
    assert "mountManagerArchive(+button.dataset.repositoryId, button.dataset.archiveMount, button)" in frontend


def test_mount_transition_rows_are_not_marked_stale_immediately():
    root = Path(__file__).parents[1]
    main = (root / "app/main.py").read_text(encoding="utf-8")
    start = main.index('def list_manager_archive_mounts() -> list[dict]:')
    end = main.index('\n\n@app.post("/api/repositories/{repository_id}/archive-mounts"', start)
    endpoint = main[start:end]

    assert 'transition_recent' in endpoint
    assert 'timedelta(seconds=30)' in endpoint
    assert 'and not transition_recent' in endpoint



def test_mount_activation_wait_treats_concurrent_unmount_as_cancellation(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import app.main as main_module

    states = [SimpleNamespace(status="mounting"), None]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, _row_id):
            return states.pop(0) if states else None

    monkeypatch.setattr(main_module, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(main_module, "archive_mount_is_active", lambda _path: False)

    result = asyncio.run(main_module.wait_for_archive_mount_activation(
        17, "/archive-mounts/repo-r1/archive", timeout_seconds=0.2, poll_seconds=0.001,
    ))

    assert result == "cancelled"


def test_mount_frontend_suppresses_delayed_error_after_concurrent_unmount():
    root = Path(__file__).parents[1]
    main = (root / "app/main.py").read_text(encoding="utf-8")
    frontend = (root / "app/static/app.js").read_text(encoding="utf-8")
    assert 'if activation_state == "cancelled":' in main
    assert '"cancelled": True' in main
    assert "if (mounted?.cancelled)" in frontend
    assert "unmount result remains authoritative" in frontend
