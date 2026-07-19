from __future__ import annotations

import argparse
import json

from app.security_store import authentication_readiness, initialize_security_store, list_users, recover_account, unlock_account


def main() -> int:
    parser = argparse.ArgumentParser(description="Lokale Kontodiagnose und Wiederherstellung des BorgBackup Managers")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="nicht sensible Kontostatus anzeigen")
    status.add_argument("--json", action="store_true")
    unlock = sub.add_parser("unlock", help="Kontosperre zurücksetzen")
    unlock.add_argument("username")
    reset = sub.add_parser("reset", help="temporäres Passwort erzeugen und Konto entsperren")
    reset.add_argument("username")
    reset.add_argument("--admin", action="store_true", help="Konto zusätzlich als Administrator aktivieren")
    args = parser.parse_args()
    initialize_security_store()

    if args.command == "status":
        payload = {"readiness": authentication_readiness(), "users": list_users()}
        if args.json:
            print(json.dumps(payload["readiness"], ensure_ascii=False))
        else:
            r = payload["readiness"]
            print(f"Authentifizierung bereit: {'ja' if r['ready'] else 'nein'}")
            print(f"Benutzer: {r['users']} · aktive Administratoren: {r['active_administrators']} · gesperrte Administratoren: {r['locked_administrators']}")
            for user in payload["users"]:
                lock = f" · gesperrt bis {user['locked_until']}" if user.get("locked_until") else ""
                print(f"- {user['username']} · {user['role']} · {'aktiv' if user['enabled'] else 'inaktiv'}{lock}")
        return 0 if payload["readiness"]["ready"] else 2
    if args.command == "unlock":
        if not unlock_account(args.username):
            print("Benutzer nicht gefunden.")
            return 1
        print(f"Konto {args.username} wurde entsperrt.")
        return 0
    password = recover_account(args.username, make_admin=args.admin)
    print("BorgBackup Manager – lokale Kontowiederherstellung")
    print(f"Benutzername: {args.username}")
    print(f"Temporäres Passwort: {password}")
    print("Das Konto ist aktiviert und entsperrt. Nach der Anmeldung muss das Passwort geändert werden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
