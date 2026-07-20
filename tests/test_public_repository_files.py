from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_public_repository_governance_files_exist():
    required = [
        "LICENSE", "NOTICE", "SECURITY.md", "CONTRIBUTING.md",
        "THIRD-PARTY-NOTICES.md", ".github/dependabot.yml",
        ".github/workflows/ci.yml", "scripts/release-check.sh",
    ]
    for relative in required:
        path = ROOT / relative
        assert path.is_file(), relative
        assert path.stat().st_size > 0, relative


def test_readmes_disclose_independence_ai_assistance_and_license():
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    german = (ROOT / "README.de.md").read_text(encoding="utf-8")
    assert "independent third-party" in english
    assert "not affiliated" in english
    assert "OpenAI ChatGPT" in english
    assert "Apache License 2.0" in english
    assert "unabhängiges Community-Projekt" in german
    assert "OpenAI ChatGPT" in german
    assert "Apache License 2.0" in german


def test_ignore_files_cover_local_runtime_and_release_artifacts():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for pattern in [
        ".env", "install-config.env", "docker-compose.override.yml",
        "data/", "backup/", "backups/", "*.db", "*.sqlite3",
        "*.log", "updates/",
    ]:
        assert pattern in gitignore
    for pattern in [
        ".env", "install-config.env", "data", "backups", "*.db",
        "*.sqlite3", "*.log", "updates",
    ]:
        assert pattern in dockerignore


def test_synthetic_private_key_markers_are_not_contiguous_in_source():
    scanned = [
        ROOT / "app/static/index.html",
        ROOT / "app/schemas.py",
        ROOT / "tests/test_runner.py",
    ]
    marker = "BEGIN OPENSSH " + "PRIVATE KEY"
    for path in scanned:
        assert marker not in path.read_text(encoding="utf-8"), path


def test_updater_preserves_public_repository_files_and_ci_configuration():
    update = (ROOT / "update.sh").read_text(encoding="utf-8")
    for name in [
        "LICENSE", "NOTICE", "SECURITY.md", "CONTRIBUTING.md",
        "THIRD-PARTY-NOTICES.md", ".github", "pytest.ini", "scripts",
    ]:
        assert name in update


def test_container_image_includes_license_and_notice_files():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY LICENSE NOTICE SECURITY.md CONTRIBUTING.md THIRD-PARTY-NOTICES.md ./" in dockerfile
