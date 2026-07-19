from app.borg_warnings import (
    BorgWarningCollector,
    parse_borg_warnings,
    unresolved_warning_summary,
    warning_diagnosis,
    warning_summary_from_json,
)


def test_changed_and_error_items_are_extracted_with_paths():
    summary = parse_borg_warnings(
        """C var/lib/app/database.sqlite
E var/lib/app/secret.key
stat: var/lib/app/disappeared.tmp: [Errno 2] No such file or directory
open: var/lib/app/private.key: [Errno 13] Permission denied
terminating with warning status, rc 1
"""
    )

    assert summary is not None
    assert summary["total_count"] == 4
    assert summary["changed_count"] == 1
    assert summary["missing_count"] == 1
    assert summary["permission_count"] == 1
    assert summary["error_count"] == 1
    assert summary["items"][0]["path"] == "var/lib/app/database.sqlite"
    assert all("terminating with warning" not in item["reason"] for item in summary["items"])


def test_changed_warning_message_is_deduplicated_against_status_line():
    summary = parse_borg_warnings(
        """C srv/data/live.db
srv/data/live.db: file changed while we backed it up
terminating with warning status, rc 1
"""
    )

    assert summary is not None
    assert summary["changed_count"] == 1
    assert summary["total_count"] == 1
    diagnosis = warning_diagnosis(summary)
    assert diagnosis is not None
    assert diagnosis["title"] == "1 Datei wurde während der Sicherung verändert"


def test_generic_warning_is_retained_without_final_rc_line():
    summary = parse_borg_warnings(
        """WARNING: backup source returned inconsistent metadata
terminating with warning status, rc 1
"""
    )

    assert summary is not None
    assert summary["other_count"] == 1
    assert summary["items"][0]["reason"] == "backup source returned inconsistent metadata"


def test_success_only_output_has_no_warning_summary():
    assert parse_borg_warnings("terminating with success status, rc 0") is None


def test_streaming_collector_keeps_split_warning_before_large_later_output():
    collector = BorgWarningCollector(max_items=10)
    assert collector.feed("C var/lib/app/live", stream="stderr") is False
    assert collector.feed(".db\n", stream="stderr") is True
    collector.feed("x" * (300 * 1024) + "\n", stream="stderr")
    collector.feed("terminating with warning status, rc 1\n", stream="stderr")
    collector.finalize()

    summary = collector.summary()
    assert summary is not None
    assert summary["changed_count"] == 1
    assert summary["items"][0]["path"] == "var/lib/app/live.db"


def test_unresolved_warning_is_serializable_and_has_specific_diagnosis():
    summary = unresolved_warning_summary()
    stored = warning_summary_from_json(__import__("json").dumps(summary))
    assert stored is not None
    assert stored["unresolved"] is True
    assert stored["unknown_count"] == 1
    diagnosis = warning_diagnosis(stored)
    assert diagnosis is not None
    assert diagnosis["title"] == "Borg meldete eine Warnung ohne Detailzeile"


def test_remote_status_and_unmatched_pattern_are_detected():
    summary = parse_borg_warnings("Remote: C srv/live.db\nInclude pattern '/missing/*' never matched.\n")
    assert summary is not None
    assert summary["changed_count"] == 1
    assert summary["other_count"] == 1


def test_lowercase_file_type_status_is_not_misclassified_as_changed():
    assert parse_borg_warnings("c dev/ttyS0\n") is None
