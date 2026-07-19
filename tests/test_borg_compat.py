from app.borg_compat import classify_borg_version, parse_borg_version, version_probe_shell


def test_parse_version_from_multiple_outputs():
    assert parse_borg_version("borg 1.2.0") == "1.2.0"
    assert parse_borg_version("BorgBackup version 1.4.0") == "1.4.0"
    assert parse_borg_version("BBM_BORG_VERSION=1.2.4") == "1.2.4"
    assert parse_borg_version("BORG AUF CLIENT: 1.2.8") == "1.2.8"
    noisy = "A home/releases/1.02.1/file\nBORG AUF CLIENT: 1.2.8\nA home/releases/1.03.2/other"
    assert parse_borg_version(noisy) == "1.2.8"
    assert parse_borg_version("A home/releases/1.02.1/file") is None
    assert parse_borg_version("BORG AUF CLIENT: 1.02.1") is None
    assert classify_borg_version("1.02.1").level == "unknown"


def test_old_borg_versions_are_warned_not_blocked():
    result = classify_borg_version("1.2.0")
    assert result.supported is True
    assert result.level == "critical"
    result = classify_borg_version("1.2.7")
    assert result.supported is True
    assert result.level == "warning"


def test_supported_and_incompatible_versions():
    assert classify_borg_version("1.2.8").level == "ok"
    assert classify_borg_version("1.4.0").level == "ok"
    assert classify_borg_version("1.1.18").supported is False
    assert classify_borg_version("2.0.0").supported is False


def test_probe_has_fallbacks_and_warning_path():
    script = version_probe_shell()
    assert "borg --version" in script
    assert "borg -V" in script
    assert "borg --show-version help" in script
    assert "Archive-Spoofing-Schwachstelle" in script
    assert "BORG AUF CLIENT" in script
    assert "BBM_BORG_VERSION=" not in script
