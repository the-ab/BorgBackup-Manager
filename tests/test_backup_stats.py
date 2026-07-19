from app.backup_stats import parse_backup_statistics, parse_human_size


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
