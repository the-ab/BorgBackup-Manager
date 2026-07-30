from __future__ import annotations

from pathlib import Path

from app import initial_admin


def test_automatic_initial_credentials_are_announced_only_once(monkeypatch, capsys):
    values = {"initial_admin_password": "Aa1!temporary-password"}

    monkeypatch.setattr(initial_admin, "get_secret", lambda _scope, name: values.get(name))
    monkeypatch.setattr(initial_admin, "set_secret", lambda _scope, name, value: values.__setitem__(name, value))
    monkeypatch.setattr(initial_admin, "delete_secret", lambda _scope, name: values.pop(name, None))
    monkeypatch.setattr("sys.argv", ["initial_admin", "--announce-once"])

    assert initial_admin.main() == 0
    first = capsys.readouterr().out
    assert "Benutzername: admin" in first
    assert "Temporäres Passwort: Aa1!temporary-password" in first
    assert values["initial_admin_startup_announced"] == "1"

    assert initial_admin.main() == 0
    assert capsys.readouterr().out == ""


def test_manual_initial_credentials_remain_retrievable_after_automatic_announcement(monkeypatch, capsys):
    values = {
        "initial_admin_password": "Aa1!temporary-password",
        "initial_admin_startup_announced": "1",
    }
    monkeypatch.setattr(initial_admin, "get_secret", lambda _scope, name: values.get(name))
    monkeypatch.setattr(initial_admin, "set_secret", lambda _scope, name, value: values.__setitem__(name, value))
    monkeypatch.setattr(initial_admin, "delete_secret", lambda _scope, name: values.pop(name, None))
    monkeypatch.setattr("sys.argv", ["initial_admin"])

    assert initial_admin.main() == 0
    output = capsys.readouterr().out
    assert "Benutzername: admin" in output
    assert "Temporäres Passwort: Aa1!temporary-password" in output


def test_entrypoint_defaults_to_no_automatic_password_log_for_local_build():
    entrypoint = Path("docker/entrypoint.sh").read_text(encoding="utf-8")
    assert 'BBM_SHOW_INITIAL_ADMIN_ON_START:-0' in entrypoint
    assert 'python -m app.initial_admin --announce-once' in entrypoint
    assert 'BBM_SHOW_INITIAL_ADMIN_ON_START must be 0 or 1' in entrypoint
