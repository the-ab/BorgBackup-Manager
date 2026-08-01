from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_standalone_ghcr_compose_bundle_is_complete():
    compose_path = ROOT / "docker-compose/compose.yaml"
    env_path = ROOT / "docker-compose/.env.example"
    readme_de_path = ROOT / "docker-compose/README.de.md"
    readme_en_path = ROOT / "docker-compose/README.md"
    for path in (compose_path, env_path, readme_de_path, readme_en_path):
        assert path.is_file(), path
    compose = compose_path.read_text(encoding="utf-8")
    sample = env_path.read_text(encoding="utf-8")
    assert "image: ghcr.io/the-ab/borgbackup-manager:${BBM_IMAGE_TAG:-latest}" in compose
    assert "build:" not in compose
    assert "pull_policy: always" in compose
    assert "BBM_IMAGE_TAG=latest" in sample
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert f"v{version}" in sample
    assert "BBM_DEBUG_LOG_LEVEL" not in sample
    assert "BBM_SHOW_INITIAL_ADMIN_ON_START=1" in sample
    assert "BBM_SHOW_INITIAL_ADMIN_ON_START: ${BBM_SHOW_INITIAL_ADMIN_ON_START:-1}" in compose
    assert "${BBM_REPOSITORY_PATH:-/docker_data/borgbackup-manager/repositories}:/repositories:rslave" in compose
    assert "./.env:/run/bbm-host.env" not in compose
    assert "README.de.md or README.md" in compose
    assert "README.de.md / README.md" in sample
    assert "BBM_ARCHIVE_MOUNT_PATH=" in sample
    assert "BBM_ARCHIVE_MOUNTS_ENABLED: '1'" in compose
    assert "/dev/fuse:/dev/fuse" in compose
    assert "SYS_ADMIN" in compose
    assert "apparmor:unconfined" in compose
    assert "propagation: rshared" in compose
    assert not (ROOT / "compose.archive-mounts.yaml").exists()
    assert not (ROOT / "docker-compose/compose.archive-mounts.yaml").exists()



def test_standalone_env_reference_documents_every_compose_variable():
    compose = (ROOT / "docker-compose/compose.yaml").read_text(encoding="utf-8")
    german = (ROOT / "docker-compose/README.de.md").read_text(encoding="utf-8")
    english = (ROOT / "docker-compose/README.md").read_text(encoding="utf-8")
    variables = sorted(set(__import__("re").findall(r"\$\{((?:BBM_[A-Z0-9_]+)|TZ)", compose)))
    assert variables
    for variable in variables:
        assert variable in german, variable
        assert variable in english, variable
    assert "Zwingend erforderlich" in german
    assert "Required" in english
    assert "BBM_REPOSITORY_PUBLIC_HOST" in german
    assert "BBM_REPOSITORY_PUBLIC_HOST" in english


def test_empty_repository_mount_is_initialized_without_recursive_chown():
    entrypoint = (ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")
    initialization = entrypoint.index("Initializing empty repository directory /repositories")
    final_check = entrypoint.index("Repository directory /repositories lacks -$access access")
    assert initialization < final_check
    assert 'find /repositories -mindepth 1 -maxdepth 1 -print -quit' in entrypoint
    assert 'chown "${borg_uid}:${borg_gid}" /repositories' in entrypoint
    assert 'chmod u+rwx /repositories' in entrypoint
    assert "automatic recursive ownership changes are disabled" in entrypoint
    assert "chown -R borg:borg /repositories" not in entrypoint
    assert 'chown -R "${borg_uid}:${borg_gid}" /repositories' not in entrypoint


def test_documentation_exposes_both_installation_modes():
    german = (ROOT / "README.de.md").read_text(encoding="utf-8")
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    install_de = (ROOT / "INSTALLATION.de.md").read_text(encoding="utf-8")
    install_en = (ROOT / "INSTALLATION.md").read_text(encoding="utf-8")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    for text in (german, english, install_de, install_en):
        assert "ghcr.io/the-ab/borgbackup-manager:latest" in text
        assert "docker-compose/" in text
        assert f"v{version}" in text
        assert "BBM_SHOW_INITIAL_ADMIN_ON_START" in text
    assert "docker-compose/README.de.md" in german
    assert "docker-compose/README.md" in english
    assert "Installation mit dem veröffentlichten GHCR-Image" in german
    assert "Published GHCR image" in english
    assert "kein `chown -R`" in install_de
    assert "never runs recursive `chown`" in install_en


def test_updater_preserves_standalone_compose_bundle():
    updater = (ROOT / "update.sh").read_text(encoding="utf-8")
    release_check = (ROOT / "scripts/release-check.sh").read_text(encoding="utf-8")
    assert "app docker docker-compose tests" in updater
    assert "compose.yaml" in updater and "Dockerfile" in updater
    assert '"compose.yaml", "docker-compose", "Dockerfile"' in updater
    assert '"VERSION", "compose.yaml", "docker-compose"' in updater
    assert "docker-compose/compose.yaml docker-compose/.env.example" in release_check
    assert "docker-compose/README.de.md docker-compose/README.md" in release_check
    assert "Runtime directory must not be released" in release_check
    assert "data repositories archive-mounts" in release_check
    assert "docker-compose/.env" in release_check
