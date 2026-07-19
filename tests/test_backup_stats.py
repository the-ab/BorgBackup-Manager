from app.backup_stats import parse_backup_statistics, parse_human_size, parse_source_scan_statistics


def test_human_sizes_support_borg_decimal_and_binary_units():
    assert parse_human_size("876 B") == 876
    assert parse_human_size("3.75 GB") == 3_750_000_000
    assert parse_human_size("1.5 GiB") == 1_610_612_736


def test_backup_statistics_extract_final_archive_row():
    raw = """Archive name: bbm-7-server01-2026-07-18T08:00:00
                       Original size      Compressed size    Deduplicated size
This archive:               12.50 GB               8.25 GB              65.00 MB
All archives:              220.00 GB             140.00 GB              90.00 GB
"""
    stats = parse_backup_statistics(raw)
    assert stats == {
        "archive_name": "bbm-7-server01-2026-07-18T08:00:00",
        "original_size_bytes": 12_500_000_000,
        "compressed_size_bytes": 8_250_000_000,
        "deduplicated_size_bytes": 65_000_000,
    }


def test_parse_backup_statistics_includes_file_count():
    raw = """
Archive name: bbm-7-test
Number of files: 1,234
This archive: 10.00 MB  8.00 MB  2.00 MB
"""
    # Borg normally emits plain digits; grouping separators are deliberately not accepted.
    assert parse_backup_statistics(raw).get("file_count") is None
    raw = raw.replace("1,234", "1234")
    assert parse_backup_statistics(raw)["file_count"] == 1234


def test_parse_source_scan_statistics_from_mixed_remote_output():
    raw = """Wrapper information
BBM_SOURCE_STATS_JSON={"size_bytes":12345,"file_count":17,"warning_count":1,"method":"python-lstat"}
ERGEBNIS: Quellenstatistik mit Warnungen aktualisiert.
"""
    assert parse_source_scan_statistics(raw) == {
        "original_size_bytes": 12345,
        "file_count": 17,
        "scan_method": "python-lstat",
        "warning_count": 1,
    }


def test_invalid_source_scan_marker_is_ignored():
    assert parse_source_scan_statistics("BBM_SOURCE_STATS_JSON={invalid}") == {}
