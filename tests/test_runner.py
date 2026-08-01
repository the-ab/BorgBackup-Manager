from __future__ import annotations

import asyncio
import base64
import json
import os
import shlex
import shutil
import subprocess

import pytest

from app.config import EXPORT_DIR, MANAGER_BORG_CACHE_DIR, MANAGER_BORG_SECURITY_DIR
from app.models import Host, Job, Repository
from app.runner import (
    archive_export_command,
    archive_info_command,
    backup_command,
    browse_archive_command,
    delete_archive_command,
    delete_archives_command,
    diff_archives_command,
    host_repository_bootstrap_command,
    prune_command,
    repository_command,
    repository_validation_command,
    repository_init_command,
    repository_compact_command,
    rename_archive_command,
    restore_command,
    Command,
    CommandCancelled,
    _SECRET_WRAPPER,
    execute,
    _replace_temp_file_placeholders,
    job_archive_prefixes,
    manager_borg_argv,
)


@pytest.fixture(scope="module", autouse=True)
def isolated_runner_security_store(tmp_path_factory):
    """Keep runner tests independent from security-store setup in other modules."""
    from app import secret_crypto, security_store

    security_dir = tmp_path_factory.mktemp("runner-security")
    original = (
        security_store.SECURITY_DIR,
        security_store.SECURITY_DATABASE_PATH,
        security_store.INITIAL_ADMIN_PATH,
        secret_crypto.MASTER_KEY_PATH,
    )
    security_store.SECURITY_DIR = security_dir
    security_store.SECURITY_DATABASE_PATH = security_dir / "security.db"
    security_store.INITIAL_ADMIN_PATH = security_dir / "initial-admin.txt"
    secret_crypto.MASTER_KEY_PATH = security_dir / "master.key"
    security_store.initialize_security_store()
    try:
        yield
    finally:
        (
            security_store.SECURITY_DIR,
            security_store.SECURITY_DATABASE_PATH,
            security_store.INITIAL_ADMIN_PATH,
            secret_crypto.MASTER_KEY_PATH,
        ) = original


@pytest.fixture
def job(monkeypatch) -> Job:
    monkeypatch.setattr("app.runner.get_system_secret", lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default)
    monkeypatch.setenv("BORG_SECRET_TEST", "super secret value")
    host = Host(id=3, name="host", address="10.0.0.4", port=22, username="backup", enabled=True, host_key="host.example ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEtesthostkeymaterial")
    repo = Repository(
        id=7,
        name="repo",
        location="ssh://borg@nas:2222/./repo",
        passphrase_env="BORG_SECRET_TEST",
        storage_path="/repositories/repo",
        extra_env_json="{}",
    )
    return Job(
        id=42,
        name="job",
        host=host,
        repository=repo,
        source_paths_json=json.dumps(["/home", "/etc"]),
        exclude_patterns_json=json.dumps(["*/.cache"]),
        archive_template="host-{now}",
        archive_prefix="bbm-job-42-",
        compression="zstd,6",
        prune_options_json="{}",
        create_options_json=json.dumps({
            "one_file_system": True,
            "exclude_caches": True,
            "exclude_nodump": True,
            "numeric_ids": False,
            "list_files": True,
            "files_cache": "ctime,size,inode",
            "checkpoint_interval": 1800,
        }),
        enabled=True,
    )


def test_controller_known_hosts_placeholder_is_replaced_inside_ssh_option():
    resolved = _replace_temp_file_placeholders(
        [
            "ssh", "-i", "__BBM_CONTROLLER_KEY__",
            "-o", "UserKnownHostsFile=__BBM_CONTROLLER_KNOWN_HOSTS__",
        ],
        {
            "__BBM_CONTROLLER_KEY__": "/tmp/controller-key",
            "__BBM_CONTROLLER_KNOWN_HOSTS__": "/tmp/controller-known-hosts",
        },
    )

    assert "/tmp/controller-key" in resolved
    assert "UserKnownHostsFile=/tmp/controller-known-hosts" in resolved
    assert all("__BBM_CONTROLLER_" not in argument for argument in resolved)




def test_manager_borg_argv_uses_runuser_only_for_root(monkeypatch):
    monkeypatch.setattr("app.runner.os.geteuid", lambda: 0)
    assert manager_borg_argv(["borg", "info"]) == [
        "runuser", "-u", "borg", "--", "borg", "info",
    ]

    monkeypatch.setattr("app.runner.os.geteuid", lambda: 1000)
    assert manager_borg_argv(["borg", "info"]) == ["borg", "info"]


def test_unprivileged_manager_repository_command_does_not_call_runuser(monkeypatch):
    repository = Repository(
        id=188,
        name="external",
        location="/repositories/external",
        storage_path="/repositories/external",
        encryption_mode="none",
        extra_env_json="{}",
    )
    monkeypatch.setattr("app.runner.os.geteuid", lambda: 1000)
    monkeypatch.setattr("app.runner._repository_secret", lambda _repository: None)
    monkeypatch.setattr("app.runner.load_repository_environment", lambda _repository: {})
    command = repository_validation_command(repository)
    assert command.argv[0] == "borg"
    assert "runuser" not in command.argv

def test_manager_repository_operations_use_data_cache_not_repository_mount():
    repository = Repository(
        id=88,
        name="nfs-repository",
        location="/repositories/nfs-repository",
        storage_path="/repositories/nfs-repository",
        encryption_mode="none",
        extra_env_json="{}",
    )

    command = repository_validation_command(repository)

    assert command.env["BORG_CACHE_DIR"] == str(MANAGER_BORG_CACHE_DIR.resolve() / "repository-88")
    assert command.env["BORG_SECURITY_DIR"] == str(MANAGER_BORG_SECURITY_DIR)
    assert not str(command.env["BORG_CACHE_DIR"]).startswith("/repositories/")


def test_job_archive_prefixes_include_historical_series(job):
    job.archive_prefix = "bbm-42-"
    job.archive_prefix_history_json = json.dumps(["bbm-job-42-abcdef0123456789-"])
    assert job_archive_prefixes(job) == ["bbm-42-", "bbm-job-42-abcdef0123456789-"]


def test_prune_keeps_current_and_historical_archive_series(job):
    job.archive_prefix = "bbm-42-"
    job.archive_prefix_history_json = json.dumps(["bbm-job-42-abcdef0123456789-"])
    job.prune_options_json = json.dumps({"daily": 7})
    command = prune_command(job)
    assert "bbm-42-*" in command.preview
    assert "bbm-job-42-abcdef0123456789-*" in command.preview
    assert command.preview.count("--keep-daily 7") == 2


def test_check_keeps_current_and_historical_archive_series(job):
    job.archive_prefix = "bbm-42-"
    job.archive_prefix_history_json = json.dumps(["bbm-job-42-abcdef0123456789-"])
    command = repository_command(job, "check")
    assert "bbm-42-*" in command.preview
    assert "bbm-job-42-abcdef0123456789-*" in command.preview
    assert command.preview.count("borg --lock-wait 600 check") == 2


def test_execute_uses_embedded_known_hosts_temp_file():
    command = Command(
        argv=[
            "sh", "-c", 'cat -- "${1#UserKnownHostsFile=}"', "--",
            "UserKnownHostsFile=__BBM_CONTROLLER_KNOWN_HOSTS__",
        ],
        preview="embedded known_hosts test",
        temp_files={"__BBM_CONTROLLER_KNOWN_HOSTS__": "client ssh-ed25519 AAAATEST\n"},
    )

    return_code, stdout, stderr = asyncio.run(execute(command))

    assert return_code == 0
    assert stdout == "client ssh-ed25519 AAAATEST\n"
    assert stderr == ""


def test_backup_command_is_argument_based_scoped_and_redacts_secret(job):
    command = backup_command(job)
    remote = command.argv[-1]
    assert command.argv[0] == "ssh"
    assert "borg --lock-wait 600 create" in remote
    assert "--stats" in remote
    assert "--progress" in remote
    assert "--list" in remote
    assert "DATEIVERARBEITUNG (Borg-Status und Pfad):" in remote
    assert "BORG AUF CLIENT:" in remote
    assert "BBM_BORG_VERSION=" not in remote
    assert "--json" not in remote
    assert "BACKUP-JOB:" in remote
    assert "ERGEBNIS: Backup" in remote
    assert "::bbm-job-42-host-{now}" in remote
    assert "--one-file-system" in remote
    assert "--exclude-caches" in remote
    assert "--exclude-nodump" in remote
    assert "--checkpoint-interval 1800" in remote
    assert "super secret value" not in remote
    assert "super secret value" not in command.preview
    assert "super secret value" not in command.preview
    assert command.stdin_data is not None
    assert b"super secret value" not in command.stdin_data
    assert len(command.stdin_data.splitlines()) == 4


def test_backup_file_listing_can_be_reduced_to_warning_relevant_items(job):
    options = json.loads(job.create_options_json)
    options["list_files"] = False
    job.create_options_json = json.dumps(options)
    remote = backup_command(job).argv[-1]
    assert "--list --filter AMCE" in remote
    assert "DATEIVERARBEITUNG (Borg-Status und Pfad):" not in remote
    assert "BBMNET" in remote
    assert "ip route get" in remote
    assert "/sys/class/net/$bbm_iface/statistics/rx_bytes" in remote


def test_restore_dry_run_does_not_create_target(job):
    command = restore_command(
        job,
        "bbm-job-42-host-2026",
        ["home/user/file"],
        "/srv/restore",
        True,
    )
    remote = command.argv[-1]
    assert "--dry-run" in remote
    assert 'dry_run="$2"' in remote
    assert 'if [ "$dry_run" = "1" ]' in remote
    assert remote.endswith("-- /srv/restore 1 target archive-paths")




def test_real_restore_requires_empty_non_symlink_target(job):
    command = restore_command(
        job,
        "bbm-job-42-host-2026",
        [],
        "/srv/restore",
        False,
    )
    remote = command.argv[-1]
    assert 'Restore-Ziel darf kein symbolischer Link sein' in remote
    assert 'Restore-Ziel ist nicht leer' in remote
    assert 'find "$target" -mindepth 1 -maxdepth 1 -print -quit' in remote
    assert remote.endswith("-- /srv/restore 0 target archive-paths")



def test_restore_to_original_location_uses_filesystem_root_and_confirmation(job):
    with pytest.raises(ValueError, match="selected archive paths"):
        restore_command(job, "bbm-job-42-host-2026", [], None, True, restore_mode="original")
    with pytest.raises(ValueError, match="overwrite confirmation"):
        restore_command(
            job, "bbm-job-42-host-2026", ["home/user/file"], None, False,
            restore_mode="original", overwrite_existing=False,
        )
    command = restore_command(
        job, "bbm-job-42-host-2026", ["home/user/file"], None, False,
        restore_mode="original", overwrite_existing=True,
    )
    remote = command.argv[-1]
    assert 'cd -- /' in remote
    assert remote.endswith("-- / 0 original archive-paths")


def test_restore_selection_root_strips_common_parent(job):
    command = restore_command(
        job, "bbm-job-42-host-2026", ["home/user/Documents/report.pdf"],
        "/srv/restore", True, restore_mode="target", target_layout="selection-root",
    )
    remote = command.argv[-1]
    assert "--strip-components 3" in remote
    assert remote.endswith("-- /srv/restore 1 target selection-root")


def test_restore_legacy_archive_requires_explicit_override(job):
    with pytest.raises(ValueError, match="legacy restore"):
        restore_command(job, "host-2026", [], "/srv/restore", True)
    command = restore_command(job, "host-2026", [], "/srv/restore", True, allow_legacy_archive=True)
    assert "::host-2026" in command.argv[-1]


def test_archive_export_runs_locally_and_flattens_selected_parent(job):
    job.repository.storage_path = "/repositories/main"
    command = archive_export_command(
        job, "bbm-job-42-host-2026", ["home/user/Documents/report.pdf"],
        str(EXPORT_DIR.resolve() / ".work-test"),
    )
    assert command.argv[0:4] == ["runuser", "-u", "borg", "--"]
    preview = command.preview
    assert "ssh " not in preview
    assert "--strip-components 3" in preview
    assert str(EXPORT_DIR.resolve() / ".work-test") in preview


def test_managed_repository_uses_repository_specific_device_key(job):
    job.repository.storage_path = "/repositories/main"
    command = backup_command(job)
    assert "bbm_repository_7_ed25519" in command.argv[-1]
    assert "bbm_repository_known_hosts" in command.argv[-1]
    assert "IdentitiesOnly=yes" in command.argv[-1]
    assert "ServerAliveInterval=10" in command.argv[-1]


def test_borg_version_check_supports_old_cli_variants_without_repository(job):
    command = repository_command(job, "version")
    remote = command.argv[-1]
    assert "borg --version" in remote
    assert "borg -V" in remote
    assert "borg --show-version help" in remote
    assert "BORG_REPO" not in remote
    assert "borg version" not in remote


def test_unencrypted_repository_init_has_no_secret(job):
    job.repository.storage_path = "/repositories/public"
    job.repository.passphrase_env = None
    job.repository.encryption_mode = "none"
    command = repository_init_command(job.repository)
    assert "--encryption=none" in command.argv
    assert command.stdin_data is None
    assert command.env == {
        "BORG_CACHE_DIR": str(MANAGER_BORG_CACHE_DIR.resolve() / "repository-7"),
        "BORG_SECURITY_DIR": str(MANAGER_BORG_SECURITY_DIR),
    }


@pytest.mark.parametrize("target", ["relative/path", "/srv/../etc"])
def test_restore_rejects_unsafe_target(job, target):
    with pytest.raises(ValueError):
        restore_command(job, "bbm-job-42-host-2026", [], target, True)


def test_repository_probe_checks_banner_files_and_borg(job):
    job.repository.storage_path = "/repositories/main"
    command = repository_command(job, "probe")
    remote = command.argv[-1]
    assert "bbm_repository_7_ed25519" in remote
    assert "bbm_repository_known_hosts" in remote
    assert "ssh-keyscan -T 10" in remote
    assert "Repository-SSH-Banner/Hostkey" in remote
    assert "Borg 1.2.0 bis 1.4.x" in remote
    assert "Archive-Spoofing-Schwachstelle" in remote
    assert "exit 76" in remote
    assert "borg --debug --lock-wait 30 info" in remote
    assert "ssh -vv" in remote
    assert "BORG_REPO" in remote


def test_prune_is_scoped_and_ignores_zero_retention_values(job):
    job.prune_options_json = json.dumps({"last": 3, "hourly": 0, "daily": 7, "weekly": 0})
    command = prune_command(job)
    preview = command.preview
    assert "--glob-archives 'bbm-job-42-*'" in preview
    assert "--keep-last 3" in preview
    assert "--keep-daily 7" in preview
    assert "--keep-hourly" not in preview
    assert "--keep-weekly" not in preview


def test_list_and_check_are_job_scoped_but_list_all_is_explicit(job):
    scoped = repository_command(job, "list").preview
    check = repository_command(job, "check").preview
    unscoped = repository_command(job, "list-all").preview
    assert "--glob-archives" in scoped
    assert "--glob-archives" in check
    assert "--glob-archives" not in unscoped


def test_bootstrap_generates_one_key_per_repository(job):
    command = host_repository_bootstrap_command(
        job.host,
        "[backup.example]:2222 ssh-ed25519 AAAATEST",
        [7, 9],
    )
    remote = command.argv[-1]
    assert "bbm_repository_${repository_id}_ed25519" in remote
    assert "BBM_REPOSITORY_KEY" in remote
    assert " 7 9" in remote

@pytest.mark.parametrize("mode", ["none", "authenticated", "authenticated-blake2"])
def test_unencrypted_or_authenticated_modes_are_acknowledged_noninteractively(job, mode):
    job.repository.encryption_mode = mode
    job.repository.passphrase_env = None
    command = repository_command(job, "info")
    assert command.env["BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK"] == "yes"


def test_bootstrap_replaces_dedicated_repository_known_hosts_file(job):
    command = host_repository_bootstrap_command(
        job.host,
        "[new.example]:2222 ssh-ed25519 AAAATEST",
        [7],
    )
    remote = command.argv[-1]
    assert '> "$known"' in remote
    assert 'ssh-keygen -f "$known" -R' not in remote


def test_archive_rename_preserves_exact_names_and_diff_supports_paths(job):
    first = "bbm-job-42-host-2026-07-12T22:00:00"
    second = "bbm-job-42-host-2026-07-13T22:00:00"
    renamed = "bbm-job-42-host-2026-07-12T22:00:00-renamed"
    rename = rename_archive_command(job, first, renamed)
    diff = diff_archives_command(job, first, second, ["home/user"], content_only=True)
    assert f"::{first}" in rename.preview
    assert renamed in rename.preview
    assert "borg --lock-wait 600 diff --content-only" in diff.preview
    assert "ARCHIVVERGLEICH" in diff.preview
    assert "ÄLTERES ARCHIV" in diff.preview
    assert f"::{first}" in diff.preview
    assert second in diff.preview
    assert "home/user" in diff.preview


def test_managed_archive_management_uses_local_repository_path(job):
    job.repository.storage_path = "/repositories/main"
    command = repository_command(job, "list-all")
    assert command.argv[:5] == ["runuser", "-u", "borg", "--", "borg"]
    assert command.env["BORG_REPO"] == "/repositories/main"
    assert command.preview.startswith("[direkt im Manager]")
    assert "ssh" not in command.argv[:5]




def test_managed_backup_still_runs_on_source_client(job):
    job.repository.storage_path = "/repositories/main"
    job.repository.encryption_mode = "none"
    job.repository.passphrase_env = None
    command = backup_command(job)
    assert command.argv[0] == "ssh"
    assert "bbm_repository_7_ed25519" in command.argv[-1]
    assert command.stdin_data == b"-\n-\n-\n-\n"
    assert command.stdin_controlled_cancel is True
    assert "repository-7" in command.argv[-1]
    assert "borgbackup-manager" in command.argv[-1]
    assert "while IFS= read -r _ <&4" in command.argv[-1]


def test_archive_browser_uses_borg_list_without_fuse(job):
    job.repository.storage_path = "/repositories/main"
    archive = "bbm-job-42-host-2026-07-13T22:00:00"
    command = browse_archive_command(job, archive, "home/user")
    joined = " ".join(command.argv)
    assert command.argv[0] == "runuser"
    assert "--json-lines" in command.argv
    assert "--pattern" in command.argv
    assert "+ re:^home/user/[^/]+$" in command.argv
    assert f"::{archive}" in command.argv
    assert "mount" not in joined
    assert "fuse" not in joined.lower()
    with pytest.raises(ValueError):
        browse_archive_command(job, archive, "../etc")


def test_repository_archive_info_command_loads_all_regular_archive_statistics(job):
    from app.runner import repository_archives_info_command

    command = repository_archives_info_command(job.repository)
    assert command.argv[:4] == ["runuser", "-u", "borg", "--"]
    assert "borg --lock-wait 30 info --json --glob-archives '*'" in command.preview
    assert command.argv[-2:] == ["--glob-archives", "*"]


def test_repository_archive_listing_can_include_checkpoint_archives(job):
    command = repository_command(job, "list-all", consider_checkpoints=True)
    joined = " ".join(command.argv)
    assert "borg --lock-wait 600 list --json --consider-checkpoints" in joined

    normal = repository_command(job, "list-all")
    assert "--consider-checkpoints" not in normal.argv


def test_remote_wrapper_does_not_depend_on_gnu_env_default_signal():
    assert "env --default-signal" not in _SECRET_WRAPPER
    assert "python3 -S -c" in _SECRET_WRAPPER
    assert 'graceful_signal="INT"' in _SECRET_WRAPPER
    assert 'graceful_signal="TERM"' in _SECRET_WRAPPER


@pytest.mark.asyncio
async def test_remote_wrapper_ignores_non_gnu_env_implementation(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_env = fake_bin / "env"
    fake_env.write_text(
        "#!/bin/sh\nprintf '%s\n' 'env: unrecognized option --default-signal' >&2\nexit 125\n",
        encoding="utf-8",
    )
    fake_env.chmod(0o755)
    command = Command(
        argv=["sh", "-c", _SECRET_WRAPPER, "--", "0", "-", "sh", "-c", "printf portable"],
        preview="portable signal reset test",
        stdin_data=b"-\n-\n-\n-\n",
        env={"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
        stdin_controlled_cancel=True,
    )

    return_code, stdout, stderr = await execute(command)

    assert return_code == 0
    assert stdout == "portable"
    assert "unrecognized option" not in stderr


@pytest.mark.asyncio
async def test_secret_wrapper_reopens_passphrase_for_each_borg_process(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_borg = fake_bin / "borg"
    fake_borg.write_text(
        "#!/bin/sh\n"
        "actual=$(sh -c \"$BORG_PASSCOMMAND\")\n"
        "[ \"$actual\" = \"bulk-delete-secret\" ] || { "
        "printf 'wrong passphrase: %s\n' \"$actual\" >&2; exit 2; }\n"
        "printf 'borg-ok\n'\n",
        encoding="utf-8",
    )
    fake_borg.chmod(0o755)
    secret_payload = base64.b64encode(b"bulk-delete-secret") + b"\n"
    command = Command(
        argv=[
            "sh", "-c", _SECRET_WRAPPER, "--", "0", "-",
            "sh", "-c", "borg delete first && borg delete second && borg compact",
        ],
        preview="bulk delete passphrase reuse test",
        stdin_data=b"-\n-\n-\n" + secret_payload,
        env={"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
        stdin_controlled_cancel=True,
    )

    return_code, stdout, stderr = await execute(command)

    assert return_code == 0
    assert stdout.splitlines() == ["borg-ok", "borg-ok", "borg-ok"]
    assert stderr == ""
    assert "BORG_PASSCOMMAND" in _SECRET_WRAPPER
    assert "BORG_PASSPHRASE_FD=3" not in _SECRET_WRAPPER


@pytest.mark.asyncio
async def test_remote_wrapper_starts_without_python3(tmp_path):
    fake_bin = tmp_path / "minimal-bin"
    fake_bin.mkdir()
    for name in ("mktemp", "rm", "setsid", "sh"):
        source = shutil.which(name)
        assert source is not None
        (fake_bin / name).symlink_to(source)
    command = Command(
        argv=[str(fake_bin / "sh"), "-c", _SECRET_WRAPPER, "--", "0", "-", "sh", "-c", "printf fallback"],
        preview="remote wrapper without python test",
        stdin_data=b"-\n-\n-\n-\n",
        env={"PATH": str(fake_bin), "HOME": str(tmp_path / "home")},
        stdin_controlled_cancel=True,
    )

    return_code, stdout, stderr = await execute(command)

    assert return_code == 0
    assert stdout == "fallback"
    assert stderr == ""


def test_repository_location_confirmation_is_explicit_and_one_shot(job):
    confirmation = repository_command(job, "confirm-location")
    normal_probe = repository_command(job, "probe")

    assert "BORG_RELOCATED_REPO_ACCESS_IS_OK=yes" in confirmation.argv[-1]
    assert "BORG_RELOCATED_REPO_ACCESS_IS_OK=yes" in confirmation.preview
    assert "Repository-Standort wurde für diesen Client bestätigt" in confirmation.argv[-1]
    assert "borg --lock-wait 600 info" in confirmation.argv[-1]
    assert "BORG_RELOCATED_REPO_ACCESS_IS_OK" not in normal_probe.argv[-1]


def test_repository_environment_cannot_permanently_auto_accept_relocation(job):
    job.repository.extra_env_json = json.dumps({"BORG_RELOCATED_REPO_ACCESS_IS_OK": "yes"})
    with pytest.raises(ValueError, match="reserved Borg variable"):
        repository_command(job, "probe")


def test_compact_command_requests_freed_space_estimate(job):
    command = repository_command(job, "compact")
    assert "compact --verbose --show-rc" in command.preview


@pytest.mark.asyncio
async def test_cancel_sends_sigint_to_complete_process_group(tmp_path):
    marker = tmp_path / "sigint-received"
    command = Command(
        argv=[
            "bash", "-c",
            f"trap 'printf received > {marker}; exit 130' INT; while :; do sleep 1; done",
        ],
        preview="controlled cancellation test",
    )

    task = asyncio.create_task(execute(command))
    await asyncio.sleep(0.15)
    task.cancel()

    with pytest.raises(CommandCancelled) as cancelled:
        await task

    assert cancelled.value.forced is False
    assert cancelled.value.remote_cleanup_confirmed is False
    assert marker.read_text(encoding="utf-8") == "received"


@pytest.mark.asyncio
async def test_stdin_controlled_cancel_waits_for_remote_wrapper_cleanup(tmp_path):
    ready = tmp_path / "remote-ready"
    marker = tmp_path / "remote-sigint-received"
    child_script = (
        f"trap 'printf received > {marker}; exit 130' INT; "
        f"printf ready > {ready}; while :; do sleep 1; done"
    )
    command = Command(
        argv=["sh", "-c", _SECRET_WRAPPER, "--", "0", "-", "bash", "-c", child_script],
        preview="remote wrapper cancellation test",
        stdin_data=b"-\n-\n-\n-\n",
        stdin_controlled_cancel=True,
    )

    task = asyncio.create_task(execute(command))
    for _ in range(100):
        if ready.exists():
            break
        await asyncio.sleep(0.02)
    assert ready.exists()
    task.cancel()

    with pytest.raises(CommandCancelled) as cancelled:
        await task

    assert cancelled.value.forced is False
    assert cancelled.value.remote_cleanup_confirmed is True
    assert marker.read_text(encoding="utf-8") == "received"


@pytest.mark.asyncio
async def test_private_client_cache_lock_is_removed_after_child_exit(tmp_path):
    cache_home = tmp_path / "cache-home"
    child_script = (
        'mkdir -p "$BORG_CACHE_DIR/' + ('a' * 64) + '/lock.exclusive"; '
        'printf stale > "$BORG_CACHE_DIR/' + ('a' * 64) + '/lock.roster"'
    )
    command = Command(
        argv=["sh", "-c", _SECRET_WRAPPER, "--", "0", "repository-77", "sh", "-c", child_script],
        preview="private cache cleanup test",
        stdin_data=b"-\n-\n-\n-\n",
        env={"HOME": str(tmp_path / "home"), "XDG_CACHE_HOME": str(cache_home)},
        stdin_controlled_cancel=True,
    )

    return_code, stdout, stderr = await execute(command)

    repository_cache = cache_home / "borgbackup-manager" / "repository-77" / ("a" * 64)
    assert return_code == 0
    assert stdout == ""
    assert stderr == ""
    assert repository_cache.is_dir()
    assert not (repository_cache / "lock.exclusive").exists()
    assert not (repository_cache / "lock.roster").exists()


def test_execute_starts_commands_in_dedicated_process_session():
    import inspect
    source = inspect.getsource(execute)
    assert "start_new_session=True" in source
    assert "signal.SIGINT" in source
    assert "os.killpg" in source


def test_repository_bulk_delete_uses_exact_names_and_compacts_once(job):
    archives = [
        "bbm-job-42-host-a-2026-07-18T10:00:00",
        "legacy-host-b-2026-07-18T11:00:00",
    ]
    command = delete_archives_command(job.repository, archives, compact_after=True)

    for archive in archives:
        assert f"::{archive}" in command.preview
    assert command.preview.count(" compact --verbose --show-rc") == 1
    assert command.preview.count(" delete --stats --show-rc") == 2
    assert "sh -c" in command.preview


def test_repository_compact_does_not_require_a_backup_job(job):
    command = repository_compact_command(job.repository)

    assert "borg --lock-wait 600 compact --verbose --show-rc" in command.preview
    assert "ssh backup@10.0.0.4" not in command.preview


def test_source_stats_command_uses_repository_independent_live_scan(job):
    from app.runner import source_stats_command
    command = source_stats_command(job)
    assert "BBM_SOURCE_STATS_JSON" in command.preview
    assert "Live-Scan" in command.preview
    assert "Borg-Pfadausschlüsse" in command.preview
    assert "python-borg-excludes" in command.preview
    assert "borg --lock-wait" not in command.preview
    assert "--dry-run --stats" not in command.preview
    assert command.stdin_controlled_cancel is True


def test_source_stats_command_reports_mount_handling(job):
    from app.runner import source_stats_command

    command = source_stats_command(job)
    assert "eingehängte Unterverzeichnisse werden wie beim Backup übersprungen" in command.preview
    assert "skipped_mount_count" in command.preview
    assert "included_mount_count" in command.preview
    assert "os.scandir" in command.preview
    assert command.preview.index("if excluded_by_pattern(path):") < command.preview.index("item_stat = entry.stat")


def test_source_stats_live_scan_counts_files_without_repository_access(job, tmp_path):
    from app.runner import source_stats_command

    (tmp_path / "one.txt").write_bytes(b"abc")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "two.bin").write_bytes(b"12345")
    (tmp_path / "link").symlink_to("one.txt")
    job.source_paths_json = json.dumps([str(tmp_path)])

    command = source_stats_command(job)
    remote_parts = shlex.split(command.preview.split(" -- ", 1)[1])
    result = subprocess.run(remote_parts, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    marker = next(line for line in result.stdout.splitlines() if line.startswith("BBM_SOURCE_STATS_JSON="))
    payload = json.loads(marker.split("=", 1)[1])
    assert payload["file_count"] == 3
    assert payload["size_bytes"] == 8



def test_source_stats_live_scan_applies_excludes_and_reports_each_source(job, tmp_path):
    from app.runner import source_stats_command

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir(); second.mkdir()
    (first / "keep.bin").write_bytes(b"12345")
    (first / "skip.tmp").write_bytes(b"x" * 20)
    (second / "keep.txt").write_bytes(b"abc")
    cache_dir = second / "cache"; cache_dir.mkdir()
    (cache_dir / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55")
    (cache_dir / "large.bin").write_bytes(b"x" * 100)
    job.source_paths_json = json.dumps([str(first), str(second)])
    # Borg archive paths are absolute paths without the leading slash.
    job.exclude_patterns_json = json.dumps([f"pf:{str(first / 'skip.tmp').lstrip('/')}"])

    command = source_stats_command(job)
    remote_parts = shlex.split(command.preview.split(" -- ", 1)[1])
    result = subprocess.run(remote_parts, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    marker = next(line for line in result.stdout.splitlines() if line.startswith("BBM_SOURCE_STATS_JSON="))
    payload = json.loads(marker.split("=", 1)[1])
    assert payload["quality"] == "high"
    assert payload["size_bytes"] == 8
    assert payload["file_count"] == 2
    assert payload["path_excluded_count"] == 1
    assert payload["excluded_size_bytes"] == 0
    assert payload["sources"] == [
        {"path": str(first), "size_bytes": 5, "file_count": 1},
        {"path": str(second), "size_bytes": 3, "file_count": 1},
    ]

def test_archive_browser_command_requests_owner_and_mode(job):
    from app.runner import browse_archive_command
    command = browse_archive_command(job, "archive-one", "etc")
    assert "{mode}{user}{group}{uid}{gid}" in command.preview


def test_execute_capture_limit_keeps_exact_byte_tail():
    command = Command(
        argv=[
            "python", "-c",
            "import os; os.write(2, b'x' * 20000 + b'FINAL-TAIL')",
        ],
        preview="bounded capture test",
    )

    return_code, stdout, stderr = asyncio.run(execute(command, capture_limit_bytes=1024))

    assert return_code == 0
    assert stdout == ""
    assert stderr.endswith("FINAL-TAIL")
    assert len(stderr.encode()) == 1024


def test_execute_prefers_raw_byte_callback_for_high_volume_output():
    text_calls = []
    byte_calls = []

    async def on_text(stream, text):
        text_calls.append((stream, text))

    async def on_bytes(stream, data):
        byte_calls.append((stream, data))

    command = Command(
        argv=["python", "-c", "import sys; sys.stderr.buffer.write(b'A file-1\\nC live.db\\n')"],
        preview="raw byte callback",
    )
    return_code, stdout, stderr = asyncio.run(execute(
        command,
        on_output=on_text,
        on_output_bytes=on_bytes,
    ))

    assert return_code == 0
    assert stdout == ""
    assert stderr == "A file-1\nC live.db\n"
    assert text_calls == []
    assert b"".join(data for stream, data in byte_calls if stream == "stderr") == b"A file-1\nC live.db\n"


def test_execute_byte_callback_can_filter_bounded_capture():
    command = Command(argv=["sh", "-c", "printf 'raw-progress' >&2"], preview="filter capture")

    async def filter_output(stream, chunk):
        assert stream == "stderr"
        assert chunk == b"raw-progress"
        return b"clean-warning"

    return_code, stdout, stderr = asyncio.run(execute(command, on_output_bytes=filter_output))
    assert return_code == 0
    assert stdout == ""
    assert stderr == "clean-warning"


def test_external_manager_side_repository_commands_expose_manager_cache_scope(job, monkeypatch):
    monkeypatch.setattr(
        "app.runner.get_repository_secret",
        lambda _repo, name: (
            "PRIVATE" if name == "external_ssh_private_key" else
            "host ssh-ed25519 AAAA" if name == "external_known_hosts" else None
        ),
    )
    monkeypatch.setattr("app.runner.load_repository_environment", lambda *_args, **_kwargs: {})
    job.repository.storage_path = None
    command = prune_command(job)
    assert command.manager_cache_repository_id == job.repository.id


def test_managed_manager_side_repository_commands_keep_existing_locking(job, monkeypatch):
    monkeypatch.setattr("app.runner.get_repository_secret", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.runner.load_repository_environment", lambda *_args, **_kwargs: {})
    command = prune_command(job)
    assert command.manager_cache_repository_id is None


def test_external_storage_probe_resolves_relative_ssh_repository(monkeypatch):
    from app.runner import external_repository_storage_command

    repository = Repository(
        id=900,
        name="storagebox",
        location="ssh://backup@example.invalid:2222/./borg/repository",
        storage_path=None,
        encryption_mode="none",
        extra_env_json="{}",
    )
    monkeypatch.setattr("app.runner.get_repository_secret", lambda _repository, kind: {
        "external_ssh_private_key": "PRIVATE",
        "external_known_hosts": "example.invalid ssh-ed25519 AAAA",
    }.get(kind))
    monkeypatch.setattr("app.runner.os.geteuid", lambda: 1000)

    command = external_repository_storage_command(repository)

    assert command.stdin_data is not None
    assert "backup@example.invalid" in command.preview
    assert "./borg/repository" in command.preview
    assert "df -m" in command.preview
    assert "Fallback: df -m" in command.preview
    assert "LC_ALL=C" not in command.preview
    assert "2222" in command.preview
    assert command.timeout_seconds == 20


def test_external_storage_probe_brackets_ipv6_destination(monkeypatch):
    from app.runner import external_repository_storage_command

    repository = Repository(
        id=901,
        name="ipv6-storage",
        location="ssh://backup@[2001:db8::10]:2222/./borg/repository",
        storage_path=None,
        encryption_mode="none",
        extra_env_json="{}",
    )
    monkeypatch.setattr("app.runner.get_repository_secret", lambda _repository, kind: {
        "external_ssh_private_key": "PRIVATE",
        "external_known_hosts": "[2001:db8::10]:2222 ssh-ed25519 AAAA",
    }.get(kind))
    monkeypatch.setattr("app.runner.os.geteuid", lambda: 1000)

    command = external_repository_storage_command(repository)

    assert "backup@[2001:db8::10]" in command.preview



def test_external_storage_probe_absolute_path_has_no_pathless_fallback(monkeypatch):
    from app.runner import external_repository_storage_command

    repository = Repository(
        id=902,
        name="absolute-storage",
        location="ssh://backup@example.invalid:22/var/backups/borg",
        storage_path=None,
        encryption_mode="none",
        extra_env_json="{}",
    )
    monkeypatch.setattr("app.runner.get_repository_secret", lambda _repository, kind: {
        "external_ssh_private_key": "PRIVATE",
        "external_known_hosts": "example.invalid ssh-ed25519 AAAA",
    }.get(kind))
    monkeypatch.setattr("app.runner.os.geteuid", lambda: 1000)

    command = external_repository_storage_command(repository)

    assert "df -m /var/backups/borg" in command.preview
    assert "Fallback: df -m" not in command.preview


def test_external_storage_probe_wrapper_is_restricted_shell_compatible():
    from app.runner import _EXTERNAL_STORAGE_SSH_WRAPPER

    assert 'run_ssh "df -m"' in _EXTERNAL_STORAGE_SSH_WRAPPER
    assert "LC_ALL=C" not in _EXTERNAL_STORAGE_SSH_WRAPPER
    assert "df -Pk" not in _EXTERNAL_STORAGE_SSH_WRAPPER
    assert "|" not in _EXTERNAL_STORAGE_SSH_WRAPPER.split("run_ssh()", 1)[-1].split("# Restricted SSH services", 1)[-1]

def test_external_storage_df_parser_uses_capacity_and_mountpoint():
    from app.runner import parse_external_repository_storage

    usage = parse_external_repository_storage(
        "Filesystem 1M-blocks Used Available Capacity Mounted on\n"
        "/dev/storage 1024 768 256 75% /home/backup\n",
        "./borg/repository",
    )

    assert usage["total"] == 1024 * 1024 * 1024
    assert usage["used"] == 768 * 1024 * 1024
    assert usage["free"] == 256 * 1024 * 1024
    assert usage["percent"] == 75.0
    assert usage["path"] == "./borg/repository"
    assert usage["mount_point"] == "/home/backup"



def test_external_storage_df_parser_accepts_hetzner_storagebox_df_m_sample():
    from app.runner import parse_external_repository_storage

    usage = parse_external_repository_storage(
        "Filesystem   1M-blocks Used  Avail Capacity  Mounted on\n"
        "u500             102400    0 102399     0%    /home\n",
        "./borg",
    )

    assert usage["total"] == 102400 * 1024 * 1024
    assert usage["used"] == 0
    assert usage["free"] == 102399 * 1024 * 1024
    assert usage["percent"] == 0.0
    assert usage["mount_point"] == "/home"

def test_execute_can_be_aborted_by_safety_monitor():
    async def scenario():
        event = asyncio.Event()
        reason = {"value": "storage threshold reached"}
        command = Command(argv=["sh", "-c", "sleep 30"], preview="sleep")
        task = asyncio.create_task(execute(command, abort_event=event, abort_reason=lambda: reason["value"]))
        await asyncio.sleep(0.05)
        event.set()
        return await task

    code, _output, error = asyncio.run(scenario())
    assert code == 75
    assert error == "storage threshold reached"
