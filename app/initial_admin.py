from __future__ import annotations

import argparse

from app.security_store import delete_secret, get_secret


def main() -> int:
    parser = argparse.ArgumentParser(description="Einmalige Zugangsdaten des BorgBackup Managers ausgeben")
    parser.add_argument("--consume", action="store_true", help="verschlüsselten Abrufwert nach der Ausgabe entfernen")
    args = parser.parse_args()
    password = get_secret("bootstrap", "initial_admin_password")
    if not password:
        print("Keine ausstehenden Erstanmeldedaten vorhanden.")
        return 1
    print("BorgBackup Manager – einmalige Erstanmeldung")
    print("Benutzername: admin")
    print(f"Temporäres Passwort: {password}")
    print("Das Passwort muss nach der ersten Anmeldung geändert werden.")
    if args.consume:
        delete_secret("bootstrap", "initial_admin_password")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
