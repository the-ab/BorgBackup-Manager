from __future__ import annotations

import argparse

from app.security_store import delete_secret, get_secret, set_secret


def main() -> int:
    parser = argparse.ArgumentParser(description="Einmalige Zugangsdaten des BorgBackup Managers ausgeben")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--consume", action="store_true", help="verschlüsselten Abrufwert nach der Ausgabe entfernen")
    mode.add_argument(
        "--announce-once",
        action="store_true",
        help="Zugangsdaten nur beim ersten automatischen Containerstart ausgeben",
    )
    args = parser.parse_args()
    if args.announce_once and get_secret("bootstrap", "initial_admin_startup_announced"):
        return 0
    password = get_secret("bootstrap", "initial_admin_password")
    if not password:
        if not args.announce_once:
            print("Keine ausstehenden Erstanmeldedaten vorhanden.")
            return 1
        return 0
    print("BorgBackup Manager – einmalige Erstanmeldung")
    print("Benutzername: admin")
    print(f"Temporäres Passwort: {password}")
    print("Das Passwort muss nach der ersten Anmeldung geändert werden.")
    if args.announce_once:
        print("Diese Ausgabe erscheint automatisch nur einmal im lokalen Container-Startprotokoll.")
        print("Bis zum Passwortwechsel können die Daten mit python -m app.initial_admin erneut angezeigt werden.")
        set_secret("bootstrap", "initial_admin_startup_announced", "1")
    if args.consume:
        delete_secret("bootstrap", "initial_admin_password")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
