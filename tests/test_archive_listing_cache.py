from __future__ import annotations

from pathlib import Path

from app import archive_cache


def test_archive_cache_is_persistent_variant_scoped_and_invalidated(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(archive_cache, "ARCHIVE_CACHE_DIR", tmp_path)
    regular = {"repository_statistics": {"deduplicated_size": 123}, "archives": [{"name": "one"}]}
    checkpoints = {"repository_statistics": {}, "archives": [{"name": "one.checkpoint"}]}

    first = archive_cache.store_archive_cache(7, False, regular)
    second = archive_cache.store_archive_cache(7, True, checkpoints)

    assert archive_cache.load_archive_cache(7, False)["data"] == regular
    assert archive_cache.load_archive_cache(7, True)["data"] == checkpoints
    assert first["generated_at"]
    assert second["generated_at"]
    assert archive_cache.archive_cache_size(7) > 0

    assert archive_cache.invalidate_archive_cache(7) == 2
    assert archive_cache.load_archive_cache(7, False) is None
    assert archive_cache.load_archive_cache(7, True) is None
    assert archive_cache.archive_cache_size(7) == 0


def test_archive_listing_accepts_wrapper_text_around_borg_json():
    import json
    from app.main import parse_archive_listing

    output = "informational prefix\n" + json.dumps({
        "archives": [{"name": "host-2026-07-19T09:00:00", "time": "2026-07-19T09:00:00+02:00"}],
    }) + "\nremote wrapper finished"
    archives = parse_archive_listing(output)
    assert [item["name"] for item in archives] == ["host-2026-07-19T09:00:00"]
