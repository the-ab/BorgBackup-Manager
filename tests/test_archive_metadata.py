from __future__ import annotations

from app.archive_metadata import infer_archive_device, sort_archives_newest_first


def test_device_is_inferred_from_current_historical_and_generic_archive_names():
    assert infer_archive_device("bbm-12-web-01-2026-07-17T22:00:00") == "web-01"
    assert infer_archive_device("bbm-job-1-13984bc980b20426-db-server-2026-07-17T21:00:00") == "db-server"
    assert infer_archive_device("fileserver-2026-07-17_20-30-00") == "fileserver"
    assert infer_archive_device("docker-2026-07-17_03-20") == "docker"
    assert infer_archive_device("docker-host-2026-07-17_03-20.checkpoint") == "docker-host"
    assert infer_archive_device("fileserver-2026-07-17_20-30-00.checkpoint") == "fileserver"
    assert infer_archive_device("manuell-benanntes-archiv") is None


def test_archives_are_sorted_newest_first_with_name_timestamp_fallback():
    archives = [
        {"name": "host-a-2026-07-16T23:00:00", "start": "2026-07-16T23:00:00+02:00"},
        {"name": "host-a-2026-07-18T01:00:00", "start": None},
        {"name": "host-a-2026-07-17T10:00:00", "start": "2026-07-17T10:00:00+02:00"},
        {"name": "docker-2026-07-17_03-20", "start": None},
        {"name": "ohne-zeit", "start": None},
    ]

    sorted_archives = sort_archives_newest_first(archives)

    assert [item["name"] for item in sorted_archives] == [
        "host-a-2026-07-18T01:00:00",
        "host-a-2026-07-17T10:00:00",
        "docker-2026-07-17_03-20",
        "host-a-2026-07-16T23:00:00",
        "ohne-zeit",
    ]


def test_archive_browser_listing_exposes_file_metadata():
    import json
    from app.main import parse_archive_browser_listing
    output = json.dumps({
        "path": "etc/config.ini", "type": "f", "size": 42,
        "mtime": "2026-07-19T10:11:12.000000", "mode": "-rw-r-----",
        "user": "root", "group": "backup", "uid": 0, "gid": 1000,
    })
    entry = parse_archive_browser_listing(output, "etc")[0]
    assert entry["mode"] == "-rw-r-----"
    assert entry["user"] == "root" and entry["group"] == "backup"
    assert entry["uid"] == 0 and entry["gid"] == 1000
