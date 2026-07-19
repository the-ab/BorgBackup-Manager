from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )


def test_all_shell_scripts_have_valid_syntax():
    bash_scripts = [
        "install.sh",
        "update.sh",
        "recovery.sh",
        "restore-backup.sh",
    ]
    posix_scripts = ["docker/entrypoint.sh", "docker/borg-serve.sh"]

    for relative in bash_scripts:
        result = _run(["bash", "-n", relative], cwd=PROJECT_ROOT)
        assert result.returncode == 0, f"{relative}: {result.stdout}"
    for relative in posix_scripts:
        result = _run(["sh", "-n", relative], cwd=PROJECT_ROOT)
        assert result.returncode == 0, f"{relative}: {result.stdout}"


def test_install_config_only_initializes_timezone_before_validation(tmp_path: Path):
    project = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT, project, ignore=shutil.ignore_patterns(".pytest_cache", "__pycache__", "*.pyc"))
    data_path = tmp_path / "data"
    repository_path = tmp_path / "repositories"
    data_path.mkdir()
    repository_path.mkdir()

    env = os.environ.copy()
    env.pop("TZ", None)
    env.update(
        {
            "BBM_INSTALL_NONINTERACTIVE": "1",
            "BBM_DATA_PATH": str(data_path),
            "BBM_REPOSITORY_PATH": str(repository_path),
            "BBM_REPOSITORY_PUBLIC_HOST": "bbm.test.local",
            "BBM_HTTPS_PORT": "8443",
            "BBM_REPOSITORY_SSH_PORT": "2222",
            "BBM_STORAGE_GUARD_ENABLED": "1",
            "BBM_STORAGE_GUARD_THRESHOLD_PERCENT": "95",
            "BBM_BORG_UID": str(os.getuid() or 1000),
            "BBM_BORG_GID": str(os.getgid() or 1000),
        }
    )

    result = _run(["bash", "install.sh", "--config-only"], cwd=project, env=env)
    assert result.returncode == 0, result.stdout
    generated = (project / ".env").read_text(encoding="utf-8")
    assert "TZ=Europe/Berlin\n" in generated
    assert f"BBM_DATA_PATH={data_path}\n" in generated
    assert f"BBM_REPOSITORY_PATH={repository_path}\n" in generated


def test_installer_defines_complete_new_install_defaults():
    installer = (PROJECT_ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'DEFAULT_BASE_PATH="/docker_data/borgbackup-manager"' in installer
    assert 'DEFAULT_DATA_PATH="$DEFAULT_BASE_PATH/data"' in installer
    assert 'DEFAULT_REPOSITORY_PATH="$DEFAULT_BASE_PATH/repositories"' in installer
    assert 'DEFAULT_TIMEZONE="Europe/Berlin"' in installer
    assert 'timezone="${TZ:-${existing_timezone:-$DEFAULT_TIMEZONE}}"' in installer
    assert installer.index('timezone="${TZ:-${existing_timezone:-$DEFAULT_TIMEZONE}}"') < installer.index('validate_timezone "$timezone"')


def test_help_and_error_paths_do_not_trigger_unbound_variables(tmp_path: Path):
    cases = [
        (["bash", str(PROJECT_ROOT / "install.sh"), "--invalid"], 2),
        (["bash", str(PROJECT_ROOT / "update.sh"), "--help"], 0),
        (["bash", str(PROJECT_ROOT / "recovery.sh"), "--help"], 0),
        (["bash", str(PROJECT_ROOT / "restore-backup.sh")], 1),
    ]
    for command, expected in cases:
        result = _run(command, cwd=tmp_path)
        assert result.returncode == expected, f"{command}: {result.stdout}"
        assert "unbound variable" not in result.stdout.lower()



def test_recovery_uses_project_directory_and_detects_compose_from_other_cwd(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_path = tmp_path / "docker.log"
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s|%s\\n' \"$PWD\" \"$*\" >> \"${FAKE_DOCKER_LOG:?}\"\n"
        "if [[ \"${1:-}\" == info ]]; then exit 0; fi\n"
        "if [[ \"${1:-} ${2:-}\" == 'compose version' ]]; then exit 0; fi\n"
        "if [[ \"${1:-} ${2:-} ${3:-}\" == 'compose config --quiet' ]]; then exit 0; fi\n"
        "if [[ \"${1:-} ${2:-}\" == 'compose ps' ]]; then echo borg-manager; exit 0; fi\n"
        "if [[ \"${1:-} ${2:-}\" == 'compose exec' ]]; then exit 0; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_DOCKER_LOG"] = str(log_path)

    result = _run(["bash", str(PROJECT_ROOT / "recovery.sh"), "status"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stdout
    calls = log_path.read_text(encoding="utf-8")
    assert f"{PROJECT_ROOT}|" in calls


def test_install_rejects_invalid_timezone_without_unbound_variable(tmp_path: Path):
    project = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT, project, ignore=shutil.ignore_patterns(".pytest_cache", "__pycache__", "*.pyc"))
    data_path = tmp_path / "data"
    repository_path = tmp_path / "repositories"
    data_path.mkdir()
    repository_path.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "TZ": "../invalid",
            "BBM_INSTALL_NONINTERACTIVE": "1",
            "BBM_DATA_PATH": str(data_path),
            "BBM_REPOSITORY_PATH": str(repository_path),
            "BBM_REPOSITORY_PUBLIC_HOST": "bbm.test.local",
            "BBM_BORG_UID": str(os.getuid() or 1000),
            "BBM_BORG_GID": str(os.getgid() or 1000),
        }
    )
    result = _run(["bash", "install.sh", "--config-only"], cwd=project, env=env)
    assert result.returncode == 1
    assert "Zeitzone ist ungültig" in result.stdout
    assert "unbound variable" not in result.stdout.lower()


def test_restore_rejects_permission_path_traversal_before_prompt(tmp_path: Path):
    import json
    import zipfile

    backup = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "borgbackup-manager-full-backup"}))
        archive.writestr("migration.env", "TZ=Europe/Berlin\n")
        archive.writestr("data/manager.db", b"db")
        archive.writestr("permissions.json", json.dumps({"../outside": 0o600}))

    result = _run(["bash", str(PROJECT_ROOT / "restore-backup.sh"), str(backup)], cwd=tmp_path)
    assert result.returncode != 0
    assert "Unsicherer Berechtigungspfad" in result.stdout



def test_restore_missing_file_has_clear_error(tmp_path: Path):
    missing = tmp_path / "missing.bbm"
    result = _run(["bash", str(PROJECT_ROOT / "restore-backup.sh"), str(missing)], cwd=tmp_path)
    assert result.returncode == 1
    assert f"Backup-Datei nicht gefunden: {missing}" in result.stdout
    assert "unbound variable" not in result.stdout.lower()


def test_posix_wrappers_fail_cleanly_without_runtime_environment(tmp_path: Path):
    entrypoint_env = os.environ.copy()
    entrypoint_env["BBM_BORG_UID"] = "invalid"
    entrypoint = _run(["sh", str(PROJECT_ROOT / "docker/entrypoint.sh")], cwd=tmp_path, env=entrypoint_env)
    assert entrypoint.returncode == 1
    assert "Invalid BBM_BORG_UID or BBM_BORG_GID" in entrypoint.stdout
    assert "unbound variable" not in entrypoint.stdout.lower()

    borg_serve = _run(["sh", str(PROJECT_ROOT / "docker/borg-serve.sh")], cwd=tmp_path)
    assert borg_serve.returncode == 122
    assert "No repository restriction was supplied" in borg_serve.stdout
    assert "cannot create" not in borg_serve.stdout.lower()
    assert "unbound variable" not in borg_serve.stdout.lower()

def test_release_build_context_remains_compatible_with_v1_0_25_updater(tmp_path: Path):
    """The 1.0.25 updater did not copy top-level RELEASE_NOTES.en.md."""
    target = tmp_path / "old-updater-target"
    target.mkdir()
    old_allowed = (
        ".dockerignore", ".env.example", ".gitattributes", ".gitignore",
        "compose.yaml", "Dockerfile", "install.sh", "update.sh", "recovery.sh",
        "restore-backup.sh", "INSTALLATION.md", "README.md", "RELEASE_NOTES.md",
        "VERSION", "requirements.txt", "requirements-dev.txt", "app", "docker", "tests",
    )
    for name in old_allowed:
        source = PROJECT_ROOT / name
        destination = target / name
        if source.is_dir():
            shutil.copytree(source, destination)
        elif source.exists():
            shutil.copy2(source, destination)

    assert not (target / "RELEASE_NOTES.en.md").exists()
    assert (target / "app/RELEASE_NOTES.en.md").is_file()

    dockerfile = (target / "Dockerfile").read_text(encoding="utf-8")
    copy_line = next(line for line in dockerfile.splitlines() if line.startswith("COPY README.md"))
    sources = copy_line.removeprefix("COPY ").split()[:-1]
    missing = [source for source in sources if not (target / source).exists()]
    assert missing == []



def test_restore_rejects_archive_entry_limit_before_prompt(tmp_path: Path):
    import json
    import zipfile

    backup = tmp_path / "too-many.zip"
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "borgbackup-manager-full-backup"}))
        archive.writestr("migration.env", "TZ=Europe/Berlin\n")
        archive.writestr("data/manager.db", b"db")

    env = os.environ.copy()
    env["BBM_BACKUP_MAX_ENTRIES"] = "2"
    result = _run(["bash", str(PROJECT_ROOT / "restore-backup.sh"), str(backup)], cwd=tmp_path, env=env)
    assert result.returncode != 0
    assert "mehr als 2 ZIP-Einträge" in result.stdout


def test_update_rejects_wrong_checksum_before_opening_release(tmp_path: Path):
    project = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT, project, ignore=shutil.ignore_patterns(".pytest_cache", "__pycache__", "*.pyc"))
    data_path = tmp_path / "data"
    repository_path = tmp_path / "repositories"
    data_path.mkdir()
    repository_path.mkdir()
    (project / ".env").write_text(
        f"BBM_DATA_PATH={data_path}\nBBM_REPOSITORY_PATH={repository_path}\n",
        encoding="utf-8",
    )
    release = tmp_path / "release.zip"
    release.write_bytes(b"not-even-a-zip")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == info ]]; then exit 0; fi\n"
        "if [[ \"${1:-} ${2:-}\" == 'compose version' ]]; then exit 0; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = _run(
        ["bash", "update.sh", "--file", str(release), "--sha256", "0" * 64, "--yes", "--no-build"],
        cwd=project,
        env=env,
    )
    assert result.returncode == 1
    assert "SHA-256-Prüfung fehlgeschlagen" in result.stdout
    assert "VERSION im ZIP" not in result.stdout
