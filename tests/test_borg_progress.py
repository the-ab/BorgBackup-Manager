from app.borg_progress import (
    BorgCreateProgress,
    BorgItemActivityStreamFilter,
    BorgNetworkStreamFilter,
    BorgProgressStreamFilter,
    clear_run_progress,
    get_run_progress,
    parse_borg_create_progress,
    set_run_progress,
)


def test_parse_borg_create_progress_example():
    progress = parse_borg_create_progress(
        b"5.50 GB O 5.10 GB C 23.95 kB D 15600 N /path/to/current/file"
    )
    assert progress is not None
    assert progress.original_bytes == 5_500_000_000
    assert progress.compressed_bytes == 5_100_000_000
    assert progress.deduplicated_bytes == 23_950
    assert progress.files == 15600
    assert progress.path == "/path/to/current/file"


def test_progress_filter_has_zero_work_fast_path_for_file_list_chunks():
    payload = (b"A srv/data/file.txt\n" * 5000)
    filtered, progress = BorgProgressStreamFilter().feed(payload)
    assert filtered is payload
    assert progress is None


def test_progress_filter_strips_only_carriage_return_progress_frame():
    filter_ = BorgProgressStreamFilter()
    payload = (
        b"warning before\n"
        b"5.50 GB O 5.10 GB C 23.95 kB D 15600 N /path/to/current/file\r"
        b"warning after\n"
    )
    filtered, progress = filter_.feed(payload)
    assert filtered == b"warning before\nwarning after\n"
    assert progress is not None
    assert progress.files == 15600


def test_live_progress_store_is_process_local_and_clearable():
    clear_run_progress(123)
    set_run_progress(123, BorgCreateProgress(1000, 800, 50, 12, "/srv/file"))
    assert get_run_progress(123) == {
        "original_bytes": 1000,
        "compressed_bytes": 800,
        "deduplicated_bytes": 50,
        "files": 12,
        "path": "/srv/file",
    }
    clear_run_progress(123)
    assert get_run_progress(123) is None


def test_item_activity_filter_counts_amce_and_strips_added_modified_when_compact():
    filter_ = BorgItemActivityStreamFilter(strip_added_modified=True)
    filtered, activity = filter_.feed(b"A /srv/new\nM /srv/changed\nC /srv/racing\nE /srv/error\nwarning\n")
    assert filtered == b"C /srv/racing\nE /srv/error\nwarning\n"
    assert activity is not None
    assert activity.added == 1
    assert activity.modified == 1
    assert activity.changed == 1
    assert activity.error == 1
    assert activity.last_status == "E"
    assert activity.last_path == "/srv/error"


def test_item_activity_filter_handles_chunk_boundary_without_losing_output():
    filter_ = BorgItemActivityStreamFilter(strip_added_modified=True)
    first, activity = filter_.feed(b"A /srv/new")
    assert first == b""
    assert activity is None
    second, activity = filter_.feed(b"-file\nC /srv/race\n")
    assert second == b"C /srv/race\n"
    assert activity is not None
    assert activity.added == 1
    assert activity.changed == 1


def test_item_activity_filter_passes_full_list_through_byte_for_byte():
    payload = b"U /srv/unchanged\nA /srv/new\nM /srv/changed\n"
    filtered, activity = BorgItemActivityStreamFilter(strip_added_modified=False).feed(payload)
    assert filtered is payload
    assert activity is not None
    assert activity.added == 1
    assert activity.modified == 1


def test_network_filter_handles_prefix_split_across_chunks(monkeypatch):
    timestamps = iter([10.0, 11.0])
    monkeypatch.setattr("app.borg_progress.time.monotonic", lambda: next(timestamps))
    filter_ = BorgNetworkStreamFilter()

    filtered, activity = filter_.feed(b"normal output\n\x1eBB")
    assert filtered == b"normal output\n"
    assert activity is None

    filtered, activity = filter_.feed(b"MNET\teth9\t10.0.0.9\t100\t200\t1\n")
    assert filtered == b""
    assert activity is not None
    assert activity.interfaces[0].interface == "eth9"
    assert activity.interfaces[0].ip_address == "10.0.0.9"
    assert activity.download_bytes == 0
    assert activity.upload_bytes == 0

    filtered, activity = filter_.feed(b"\x1eBBMNET\teth9\t10.0.0.9\t150\t300\t1\n")
    assert filtered == b""
    assert activity is not None
    assert activity.interfaces[0].download_bits_per_second == 400.0
    assert activity.interfaces[0].upload_bits_per_second == 800.0
    assert activity.download_bytes == 50
    assert activity.upload_bytes == 100


def test_network_filter_strips_telemetry_tracks_three_interfaces_and_route_totals(monkeypatch):
    timestamps = iter([10.0, 10.0, 10.0, 12.0, 12.0, 12.0])
    monkeypatch.setattr("app.borg_progress.time.monotonic", lambda: next(timestamps))
    filter_ = BorgNetworkStreamFilter()
    first_payload = (
        b"before\n"
        b"\x1eBBMNET\teth1\t10.0.0.5\t1000\t2000\t1\n"
        b"\x1eBBMNET\teth2\t10.0.1.5\t4000\t5000\t0\n"
        b"\x1eBBMNET\teth3\t10.0.2.5\t7000\t8000\t0\n"
        b"after\n"
    )
    filtered, first = filter_.feed(first_payload)
    assert filtered == b"before\nafter\n"
    assert first is not None
    assert [item.interface for item in first.interfaces] == ["eth1", "eth2", "eth3"]
    assert first.interfaces[0].route_selected is True
    assert first.download_bytes == 0
    assert first.upload_bytes == 0

    second_payload = (
        b"\x1eBBMNET\teth1\t10.0.0.5\t3000\t5000\t1\n"
        b"\x1eBBMNET\teth2\t10.0.1.5\t4500\t5500\t0\n"
        b"\x1eBBMNET\teth3\t10.0.2.5\t9000\t10000\t0\n"
    )
    filtered, second = filter_.feed(second_payload)
    assert filtered == b""
    assert second is not None
    assert second.interfaces[0].download_bits_per_second == 8000.0
    assert second.interfaces[0].upload_bits_per_second == 12000.0
    assert second.download_bytes == 2000
    assert second.upload_bytes == 3000
