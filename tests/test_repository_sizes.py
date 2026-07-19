import json

import pytest

from app.borg_stats import merge_archive_statistics, parse_borg_info
from app.repository_sizes import repository_size_from_borg_info, repository_statistics_from_borg_info


def test_repository_size_uses_unique_compressed_chunks_from_borg_12_json():
    output = json.dumps({"cache": {"stats": {"unique_csize": 4223, "unique_size": 8812}}})
    assert repository_size_from_borg_info(output) == 4223


def test_repository_size_accepts_repository_stats_variant():
    output = json.dumps({"repository": {"stats": {"unique_csize": 987654}}})
    assert repository_size_from_borg_info(output) == 987654


def test_repository_size_rejects_missing_statistics():
    with pytest.raises(ValueError, match="keine repositoryweite"):
        repository_size_from_borg_info(json.dumps({"repository": {"id": "abc"}}))


def test_repository_statistics_expose_original_compressed_and_deduplicated_sizes():
    output = json.dumps({
        "cache": {"stats": {
            "total_size": 50_000,
            "total_csize": 30_000,
            "unique_size": 12_000,
            "unique_csize": 7_000,
        }}
    })
    assert repository_statistics_from_borg_info(output) == {
        "original_size": 50_000,
        "compressed_size": 30_000,
        "deduplicated_size": 7_000,
    }


def test_borg_info_normalizes_archive_duration_and_sizes():
    output = json.dumps({
        "archives": [{
            "name": "client-2026-07-17",
            "id": "abc",
            "start": "2026-07-17T01:00:00+00:00",
            "end": "2026-07-17T01:02:30+00:00",
            "stats": {
                "nfiles": 123,
                "original_size": 10_000,
                "compressed_size": 8_000,
                "deduplicated_size": 500,
            },
        }],
        "cache": {"stats": {"total_size": 100_000, "total_csize": 80_000, "unique_csize": 20_000}},
    })
    parsed = parse_borg_info(output)
    archive = parsed["archives"][0]
    assert archive["duration"] == 150.0
    assert archive["nfiles"] == 123
    assert archive["original_size"] == 10_000
    assert archive["compressed_size"] == 8_000
    assert archive["deduplicated_size"] == 500
    assert parsed["repository"]["original_size"] == 100_000
    assert parsed["repository"]["compressed_size"] == 80_000
    assert parsed["repository"]["deduplicated_size"] == 20_000


def test_borg_naive_archive_time_is_interpreted_as_berlin_local_time():
    summer = parse_borg_info(json.dumps({
        "archive": {"name": "summer", "start": "2026-07-17T18:15:00"}
    }))["archives"][0]
    winter = parse_borg_info(json.dumps({
        "archive": {"name": "winter", "start": "2026-01-17T18:15:00"}
    }))["archives"][0]

    assert summer["start"] == "2026-07-17T18:15:00+02:00"
    assert winter["start"] == "2026-01-17T18:15:00+01:00"


def test_borg_archive_time_with_explicit_offset_is_preserved():
    archive = parse_borg_info(json.dumps({
        "archive": {"name": "utc", "start": "2026-07-17T16:15:00Z"}
    }))["archives"][0]
    assert archive["start"] == "2026-07-17T16:15:00+00:00"


def test_archive_statistics_merge_into_repository_listing():
    listing = [{"name": "one", "start": "2026-07-17T01:00:00", "checkpoint": False}]
    details = [{"name": "one", "duration": 12.5, "nfiles": 8, "original_size": 100, "compressed_size": 80, "deduplicated_size": 5}]
    merged = merge_archive_statistics(listing, details)
    assert merged[0]["duration"] == 12.5
    assert merged[0]["nfiles"] == 8
    assert merged[0]["deduplicated_size"] == 5


def test_borg_json_parser_accepts_informational_text_around_document():
    output = "runuser: informational prefix\n" + json.dumps({
        "repository": {"stats": {"total_size": 12, "total_csize": 8, "unique_csize": 4}},
        "archives": [{"name": "host-2026-07-19T08:00:00", "stats": {"nfiles": 1}}],
    }) + "\nwrapper completed\n"
    parsed = parse_borg_info(output)
    assert parsed["repository"]["deduplicated_size"] == 4
    assert parsed["archives"][0]["name"] == "host-2026-07-19T08:00:00"


def test_borg_json_parser_still_rejects_output_without_borg_document():
    with pytest.raises(ValueError, match="kein gültiges JSON"):
        parse_borg_info("wrapper text only")
