import json

from app.backup_eta import (
    ASSUMED_TRANSFER_BYTES_PER_SECOND,
    estimate_fixed_baseline_remaining,
    source_for_archive_path,
    source_stats_limitations,
)


def test_source_matching_prefers_longest_configured_source():
    sources = ["/", "/mnt/nas", "/mnt/nas/projects"]
    assert source_for_archive_path("mnt/nas/projects/a.bin", sources) == "/mnt/nas/projects"
    assert source_for_archive_path("mnt/nas/other.bin", sources) == "/mnt/nas"
    assert source_for_archive_path("etc/hosts", sources) == "/"


def test_fixed_eta_uses_frozen_bytes_and_nominal_1g_assumption():
    tib = 1024 ** 4
    total = 16 * tib
    current = 8 * tib
    result = estimate_fixed_baseline_remaining(
        progress={"original_bytes": current, "files": 50, "path": "srv/a"},
        source_paths=["/srv"],
        total_bytes=total,
        total_files=100,
        total_origin="backup",
    )
    remaining = 8 * tib
    expected = round(remaining / ASSUMED_TRANSFER_BYTES_PER_SECOND)
    assert result["estimated_remaining_bytes"] == remaining
    assert result["estimate_file_factor"] == 1.0
    assert result["estimated_eta_seconds"] == expected
    assert result["estimate_assumed_interface_gbps"] == 1.0
    assert result["estimate_assumed_utilization_percent"] == 80
    assert result["estimate_basis"] == "fixed-1g-source-baseline"


def test_fixed_eta_applies_small_file_penalty_from_remaining_file_count():
    gib = 1024 ** 3
    total = 100 * gib
    current = 50 * gib
    result = estimate_fixed_baseline_remaining(
        progress={"original_bytes": current, "files": 500_000, "path": "srv/a"},
        source_paths=["/srv"],
        total_bytes=total,
        total_files=1_000_000,
        total_origin="scan",
    )
    # 50 GiB across 500k remaining files is well below 1 MiB per file.
    assert result["estimate_file_factor"] == 1.5
    raw = (50 * gib) / ASSUMED_TRANSFER_BYTES_PER_SECOND
    assert result["estimated_eta_seconds"] == round(raw * 1.5)


def test_progress_percent_is_simple_average_of_bytes_and_files():
    result = estimate_fixed_baseline_remaining(
        progress={"original_bytes": 7500, "files": 500, "path": "srv/a"},
        source_paths=["/srv"],
        total_bytes=10_000,
        total_files=1000,
        total_origin="scan",
    )
    assert result["estimated_percent"] == 62.5
    assert result["estimated_remaining_bytes"] == 2500
    assert result["estimated_remaining_files"] == 500


def test_fixed_eta_depends_only_on_current_progress_and_frozen_baseline():
    progress = {"original_bytes": 8_000_000_000, "files": 8000, "path": "srv/a"}
    common = dict(
        progress=progress,
        source_paths=["/srv"],
        total_bytes=10_000_000_000,
        total_files=10_000,
        total_origin="backup",
    )
    first = estimate_fixed_baseline_remaining(**common)
    second = estimate_fixed_baseline_remaining(**common)
    assert first == second

def test_eta_is_unavailable_when_frozen_byte_baseline_is_exceeded():
    result = estimate_fixed_baseline_remaining(
        progress={"original_bytes": 11_000, "files": 80, "path": "srv/new-large-file"},
        source_paths=["/srv"],
        total_bytes=10_000,
        total_files=100,
        total_origin="backup",
    )
    assert result["estimate_baseline_exceeded"] is True
    assert result["estimate_byte_baseline_exceeded"] is True
    assert result["estimated_remaining_bytes"] is None
    assert result["estimated_eta_seconds"] is None
    # File progress remains usable for the percent display.
    assert result["estimated_percent"] == 80.0


def test_eta_falls_back_to_size_when_file_baseline_is_exceeded():
    result = estimate_fixed_baseline_remaining(
        progress={"original_bytes": 812 * 1024 ** 3, "files": 1_300_000, "path": "srv/a"},
        source_paths=["/srv"],
        total_bytes=int(1.2 * 1024 ** 4),
        total_files=1_200_000,
        total_origin="scan",
    )
    assert result["estimate_file_baseline_exceeded"] is True
    assert result["estimate_byte_baseline_exceeded"] is False
    assert result["estimate_baseline_exceeded"] is False
    assert result["estimate_byte_fallback_active"] is True
    assert result["estimated_remaining_files"] is None
    assert result["estimate_file_factor"] == 1.0
    assert result["estimated_remaining_bytes"] > 0
    assert result["estimated_eta_seconds"] is not None
    assert 0 < result["estimated_percent"] < 100


def test_eta_stays_unavailable_without_known_source_size():
    result = estimate_fixed_baseline_remaining(
        progress={"original_bytes": 1000, "files": 10, "path": "srv/a"},
        source_paths=["/srv"],
        total_bytes=None,
        total_files=None,
        total_origin=None,
    )
    assert result["estimated_percent"] is None
    assert result["estimated_eta_seconds"] is None
    assert result["estimated_remaining_bytes"] is None


def test_current_source_is_derived_from_current_path_only():
    result = estimate_fixed_baseline_remaining(
        progress={"original_bytes": 7000, "files": 70, "path": "mnt/nas/c"},
        source_paths=["/srv", "/mnt/nas"],
        total_bytes=10_000,
        total_files=100,
        total_origin="scan",
    )
    assert result["current_source"] == "/mnt/nas"
    assert "current_source_percent" not in result
    assert "completed_source_count" not in result
    assert "total_source_count" not in result


def test_source_statistics_hide_normal_quality_and_expose_only_real_limitations():
    assert source_stats_limitations(json.dumps({"quality": "high", "scan_method": "python-borg-excludes"})) == []
    assert source_stats_limitations(json.dumps({"quality": "observed"})) == []
    assert source_stats_limitations(json.dumps({"quality": "high", "warning_count": 1})) == [
        {"code": "read-warnings", "count": 1},
    ]
    assert source_stats_limitations(json.dumps({
        "quality": "partial",
        "scan_method": "find-stat-fallback",
        "unsupported_patterns": ["re:("],
        "nodump_supported": False,
        "warning_count": 2,
    })) == [
        {"code": "fallback"},
        {"code": "unsupported-patterns", "count": 1},
        {"code": "nodump-unavailable"},
        {"code": "read-warnings", "count": 2},
    ]
