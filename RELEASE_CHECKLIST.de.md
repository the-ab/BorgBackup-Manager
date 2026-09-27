# Technische Paketprüfung – BorgBackup Manager

[English version](RELEASE_CHECKLIST.md)

Diese öffentliche technische Checkliste gehört zum Releasepaket. Diese Datei und die englische Fassung in ZIP-Paketen erhalten: Bereits installierte Updater prüfen diese Dateinamen vor einem Update.

- `bash scripts/release-check.sh` in einem sauberen Quellbaum mit der dokumentierten Python-Testumgebung ausführen.
- Den festen obersten ZIP-Ordner `BorgBackup-Manager/` und alle versionierten öffentlichen Dateien erhalten.
- Lokale Konfiguration, Zugangsdaten, Datenbanken, Logs und Laufzeitverzeichnisse ausschließen.
- SHA-256-Begleitdatei für das ZIP erzeugen und vor Auslieferung prüfen.
- Image und ZIP aus demselben geprüften Quellcommit bauen und die Imageherkunft festhalten.
- Installation und Update ab unterstützter Baseline einschließlich Sicherung und Wiederherstellung mit Wegwerfdaten prüfen.
- Neue Version erst nach Funktionsprüfung und abgeschlossener Releaseprüfung veröffentlichen.
