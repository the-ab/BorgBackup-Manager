from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import ArchiveBulkDeleteIn, ArchiveDeleteIn, BackupScheduleIn, JobIn, RepositoryImportIn, RepositoryIn, validate_compression_spec


@pytest.mark.parametrize(
    "value",
    [
        "none", "lz4", "zstd", "zstd,22", "zlib,0", "lzma,9",
        "auto,zstd,6", "auto,lzma,6", "obfuscate,110,none", "obfuscate,3,auto,zstd,10",
    ],
)
def test_borg_12_compression_families_are_accepted(value):
    assert validate_compression_spec(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "zstd,0", "zstd,23", "zlib,10", "auto", "obfuscate,7,zstd,3",
        "obfuscate,250,zstd,3", "gzip",
    ],
)
def test_invalid_or_borg2_only_compression_specs_are_rejected(value):
    with pytest.raises(ValueError):
        validate_compression_spec(value)


def test_job_schema_rejects_invalid_compression():
    with pytest.raises(ValidationError):
        JobIn(name="bad", host_id=1, repository_id=1, source_paths=["/srv"], compression="shell;command")


def test_central_schedule_schema_rejects_invalid_cron_immediately():
    with pytest.raises(ValidationError):
        BackupScheduleIn(
            name="bad-cron", expressions="not a cron", target_mode="jobs", target_job_ids=[1]
        )


def test_legacy_job_schedule_field_is_ignored_for_update_compatibility():
    job = JobIn(
        name="legacy-client", host_id=1, repository_id=1, source_paths=["/srv"], schedule="0 2 * * *"
    )
    assert not hasattr(job, "schedule")


def test_archive_template_must_avoid_collisions():
    with pytest.raises(ValidationError):
        JobIn(
            name="collision",
            host_id=1,
            repository_id=1,
            source_paths=["/srv"],
            archive_template="static-name",
        )


def test_default_create_options_are_safe_for_root_backups():
    job = JobIn(name="root", host_id=1, repository_id=1, source_paths=["/"])
    assert job.create_options["one_file_system"] is True
    assert job.create_options["exclude_caches"] is True
    assert job.create_options["exclude_nodump"] is True
    assert job.create_options["list_files"] is True
    assert job.create_options["checkpoint_interval"] == 1800
    assert job.create_options["files_cache"] == "ctime,size,inode"


def test_files_cache_modes_match_borg_12_documentation():
    accepted = [
        "ctime,size,inode", "mtime,size,inode", "ctime,size", "mtime,size",
        "rechunk,ctime", "rechunk,mtime", "disabled",
    ]
    for mode in accepted:
        job = JobIn(
            name=f"cache-{mode.replace(',', '-')}", host_id=1, repository_id=1,
            source_paths=["/srv"], create_options={"files_cache": mode},
        )
        assert job.create_options["files_cache"] == mode
    with pytest.raises(ValidationError):
        JobIn(
            name="bad-cache", host_id=1, repository_id=1, source_paths=["/srv"],
            create_options={"files_cache": "rechunk,ctime,size,inode"},
        )


def test_unencrypted_managed_repository_needs_no_passphrase():
    repository = RepositoryIn(name="plain", managed=True, encryption_mode="none")
    assert repository.passphrase is None


@pytest.mark.parametrize(
    "mode",
    ["authenticated", "authenticated-blake2", "repokey", "repokey-blake2", "keyfile", "keyfile-blake2"],
)
def test_protected_repository_modes_require_passphrase(mode):
    with pytest.raises(ValidationError):
        RepositoryIn(name="protected", managed=True, encryption_mode=mode)


def test_ui_contains_scoped_archives_and_advanced_borg_options():
    root = Path(__file__).parents[1]
    html = (root / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (root / "app/static/app.js").read_text(encoding="utf-8")
    stylesheet = (root / "app/static/style.css").read_text(encoding="utf-8")

    assert 'value="none">none – unverschlüsselt' in html
    assert 'value="keyfile-blake2"' in html
    assert 'value="obfuscate,110,zstd,3"' in html
    assert 'Unterstützt unter Borg 1.2 bis 1.4' in html
    assert 'name="one_file_system"' in html
    assert 'name="files_cache"' in html
    assert 'name="list_files"' in html
    assert 'Verarbeitete Dateien im Live-Protokoll anzeigen' in html
    assert "all_archives" in javascript
    assert "data-archive-browse" in javascript
    assert "markArchivesStale" in javascript
    assert "if (current === 'archives'" not in javascript
    assert "kein FUSE erforderlich" in javascript
    assert "Alte FUSE-Mounts" in html
    assert "renderLegacyMounts" in javascript
    assert "location.hash" in javascript
    assert "verify" in javascript
    assert "function editHost" in javascript
    assert "function editJob" in javascript
    assert "function pollRun" in javascript
    assert "Systemdiagnose" in html
    assert "function goToView" in javascript
    assert '[data-theme="dark"]' in stylesheet


def test_prune_zero_values_are_normalized_away():
    job = JobIn(
        name="retention", host_id=1, repository_id=1, source_paths=["/srv"],
        prune_options={"last": 3, "hourly": 0, "daily": 7, "weekly": 0},
    )
    assert job.prune_options == {"last": 3, "daily": 7}


def test_prune_rejects_negative_values():
    with pytest.raises(ValidationError):
        JobIn(
            name="bad-retention", host_id=1, repository_id=1, source_paths=["/srv"],
            prune_options={"daily": -1},
        )

@pytest.mark.parametrize("value", ["", "line1\nline2", "nul\x00value"])
def test_repository_passphrase_must_be_nonempty_single_line(value):
    with pytest.raises(ValidationError):
        RepositoryIn(
            name="invalid-secret",
            managed=True,
            encryption_mode="repokey-blake2",
            passphrase=value,
        )


def test_archive_schema_accepts_borg_iso_timestamp_names():
    archive = ArchiveDeleteIn(archive="bbm-job-1-host-2026-07-13T22:00:00")
    assert archive.archive.endswith("T22:00:00")


def test_repository_import_allows_multiline_keyfile_but_not_multiline_passphrase():
    imported = RepositoryImportIn(
        name="Existing",
        directory_name="existing-repo",
        encryption_mode="keyfile-blake2",
        passphrase="secret",
        keyfile="BORG_KEY 0000\nline-two\n",
    )
    assert imported.keyfile.get_secret_value().startswith("BORG_KEY")
    with pytest.raises(ValidationError):
        RepositoryImportIn(
            name="Existing",
            directory_name="existing-repo",
            encryption_mode="repokey-blake2",
            passphrase="line-one\nline-two",
        )


def test_archive_schema_accepts_internal_spaces_for_imported_repositories():
    archive = ArchiveDeleteIn(archive="monthly backup 2026-07-13T22:00:00")
    assert archive.archive == "monthly backup 2026-07-13T22:00:00"


@pytest.mark.parametrize("value", ["bad/name", "bad::name", "-option", "line\nbreak"])
def test_archive_schema_rejects_ambiguous_or_unsafe_names(value):
    with pytest.raises(ValidationError):
        ArchiveDeleteIn(archive=value)


def test_default_exclusion_template_contains_linux_virtual_paths():
    from app.schemas import SettingsIn

    settings = SettingsIn()
    template = settings.exclude_templates[0]
    assert template.name == "Linux-Systempfade"
    assert template.patterns == ["/proc", "/sys", "/dev", "/run", "/tmp", "/var/tmp"]


def test_exclusion_template_names_are_unique_and_patterns_are_normalized():
    from app.schemas import SettingsIn

    settings = SettingsIn(exclude_templates=[
        {"name": " Linux ", "patterns": ["/proc", "/proc", " /sys "]},
    ])
    assert settings.exclude_templates[0].name == "Linux"
    assert settings.exclude_templates[0].patterns == ["/proc", "/sys"]

    with pytest.raises(ValidationError):
        SettingsIn(exclude_templates=[
            {"name": "Linux", "patterns": ["/proc"]},
            {"name": "linux", "patterns": ["/sys"]},
        ])


def test_bulk_archive_delete_requires_unique_exact_names():
    payload = ArchiveBulkDeleteIn(
        archives=[
            "bbm-job-1-host-a-2026-07-18T10:00:00",
            "legacy host b 2026-07-18T11:00:00",
        ],
        compact_after=False,
    )
    assert payload.compact_after is False
    assert len(payload.archives) == 2

    with pytest.raises(ValidationError):
        ArchiveBulkDeleteIn(archives=["same-archive", "same-archive"])

    with pytest.raises(ValidationError):
        ArchiveBulkDeleteIn(archives=["../unsafe"])
