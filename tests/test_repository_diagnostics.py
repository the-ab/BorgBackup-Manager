from app.repository_diagnostics import compact_repository_diagnostic


def test_public_key_failure_is_condensed_and_keeps_relevant_details():
    error = "\n".join([
        "Remote: debug1: Reading configuration data /etc/ssh/ssh_config",
        "Remote: debug2: KEX algorithms: curve25519-sha256",
        "Remote: debug1: Authenticating to storage.example:23 as 'user'",
        "Remote: user@storage.example: Permission denied (publickey,password).",
        "Connection closed by remote host. Is borg working on the server?",
    ])
    summary, details = compact_repository_diagnostic("", error, 2)
    assert "SSH-Anmeldung abgelehnt" in summary
    assert "Permission denied" in details
    assert "KEX algorithms" not in details
    assert "Reading configuration" not in details


def test_timeout_failure_has_actionable_summary():
    summary, _ = compact_repository_diagnostic("", "ssh: connect to host example port 23: Connection timed out", 2)
    assert "Zeitlimit" in summary


def test_local_cache_lock_failure_recommends_repository_cache_action():
    summary, details = compact_repository_diagnostic(
        "",
        "Failed to create/acquire the lock /repositories/.cache/borg/abc/lock.exclusive (timeout).",
        2,
    )
    assert "lokale Borg-Cache" in summary
    assert "Cache löschen" in summary
    assert "lock.exclusive" in details


def test_user_home_cache_lock_is_not_reported_as_repository_lock():
    summary, details = compact_repository_diagnostic(
        "",
        "Failed to create/acquire the lock /root/.cache/borg/abc/lock.exclusive (timeout).",
        2,
    )
    assert "ausführenden Benutzers" in summary
    assert "nicht der Repository-Pfad" in summary
    assert "lock.exclusive" in details


def test_relocated_repository_failure_recommends_explicit_confirmation():
    summary, details = compact_repository_diagnostic(
        "",
        "Warning: The repository at location ssh://new/repo was previously located at ssh://old/repo\n"
        "Do you want to continue? [yN] Aborting.\nRepository access aborted",
        2,
    )
    assert "früheren URL" in summary
    assert "einmalig bestätigen" in summary
    assert "previously located" in details


def test_local_repository_permission_failure_is_concise_and_actionable(monkeypatch):
    monkeypatch.setenv("BBM_BORG_UID", "1000")
    monkeypatch.setenv("BBM_BORG_GID", "1000")
    summary, details = compact_repository_diagnostic(
        "",
        "Traceback (most recent call last):\nPermissionError: [Errno 13] Permission denied: '/repositories/borg/data/69/69536'\nPlatform: Linux bbm",
        2,
    )
    assert "Zugriff auf Repository-Datei verweigert" in summary
    assert "/repositories/borg/data/69/69536" in summary
    assert "1000:1000" in summary
    assert details == "PermissionError: [Errno 13] Permission denied: '/repositories/borg/data/69/69536'"
    assert "Traceback" not in details
