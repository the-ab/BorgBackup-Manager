from app.log_filter import extract_error_output


def test_borg_file_list_and_statistics_are_not_reported_as_errors():
    raw = """A home/user/file.txt
U home/user/unchanged.txt
d home/user/Documents
------------------------------------------------------------------------------
Archive name: bbm-job-1-host-2026-07-16T18:00:00
Time (start): Thu, 2026-07-16 18:00:00
Number of files: 42
                       Original size      Compressed size    Deduplicated size
This archive:                3.75 GB              3.72 GB                876 B
terminating with success status, rc 0
"""
    assert extract_error_output(raw) == ""


def test_real_borg_errors_and_file_level_errors_are_preserved():
    raw = """A home/user/ok.txt
E home/user/unreadable.txt
Remote: Permission denied
Connection closed by remote host. Is borg working on the server?
terminating with error status, rc 2
"""
    filtered = extract_error_output(raw)
    assert "A home/user/ok.txt" not in filtered
    assert "E home/user/unreadable.txt" in filtered
    assert "Permission denied" in filtered
    assert "Connection closed by remote host" in filtered
    assert "rc 2" in filtered


def test_traceback_context_remains_available():
    raw = """Traceback (most recent call last):
  File \"/usr/lib/python3/dist-packages/borg/archiver.py\", line 1, in main
    run()
borg.remote.ConnectionClosedWithHint: Connection closed by remote host
Platform: Linux host
Borg: 1.2.8
"""
    filtered = extract_error_output(raw)
    assert "Traceback" in filtered
    assert "archiver.py" in filtered
    assert "ConnectionClosedWithHint" in filtered
    assert "Borg: 1.2.8" in filtered


def test_permission_traceback_is_reduced_to_actual_filesystem_cause():
    raw = """Exception ignored in: <function Repository.__del__ at 0x123>
Traceback (most recent call last):
  File "/usr/lib/python3/dist-packages/borg/repository.py", line 1, in open_fd
PermissionError: [Errno 13] Permission denied: '/repositories/borg/data/69/69536'
Platform: Linux bbm
Borg: 1.4.0
"""
    assert extract_error_output(raw) == "PermissionError: [Errno 13] Permission denied: '/repositories/borg/data/69/69536'"


def test_changed_file_status_and_warning_message_are_preserved():
    raw = """A home/user/normal.txt
C var/lib/app/live.db
var/lib/app/live.db: file changed while we backed it up
terminating with warning status, rc 1
"""
    filtered = extract_error_output(raw)
    assert "A home/user/normal.txt" not in filtered
    assert "C var/lib/app/live.db" in filtered
    assert "file changed while we backed it up" in filtered
    assert "rc 1" in filtered


def test_database_preview_strips_all_borg_item_status_paths():
    from app.log_filter import strip_borg_item_lines

    raw = """==============================================================================
BACKUP-JOB: demo
------------------------------------------------------------------------------
A srv/data/normal.txt
Remote: M srv/data/modified.txt
C var/lib/app/live.db
E var/lib/app/unreadable.db
Archive name: bbm-demo
Number of files: 4
"""
    filtered = strip_borg_item_lines(raw)
    assert "BACKUP-JOB: demo" in filtered
    assert "Archive name: bbm-demo" in filtered
    assert "Number of files: 4" in filtered
    assert "normal.txt" not in filtered
    assert "modified.txt" not in filtered
    assert "live.db" not in filtered
    assert "unreadable.db" not in filtered
