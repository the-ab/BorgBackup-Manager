# Mitwirken am BorgBackup Manager

Vielen Dank für deine Unterstützung bei der Verbesserung des Projekts.

[English version](CONTRIBUTING.md)

## Vor einer Änderung

- Für normale Fehler und Funktionsvorschläge ein öffentliches Issue verwenden.
- Für sicherheitsrelevante Funde `SECURITY.de.md` beachten.
- Zuerst vorhandene Issues und Pull Requests durchsuchen.
- Änderungen klar begrenzen und unnötige Formatierungsänderungen vermeiden.
- Niemals produktive Daten, Zugangsdaten, private Schlüssel, Datenbanken oder Logs einfügen.

## Entwicklungsumgebung

BorgBackup Manager verwendet Python 3.13 und die in `requirements.txt` festgelegten Abhängigkeiten.

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.txt
python -m pip install pytest==9.0.2 httpx==0.28.1 pytest-asyncio==1.4.0
python -m pytest -q
```

Zusätzlich die lokalen Repository-Prüfungen ausführen:

```bash
bash scripts/release-check.sh
```

## Pull Requests

Ein Pull Request soll:

- Problem und umgesetztes Verhalten erklären;
- Regressionstests ergänzen oder aktualisieren;
- englische Standarddokumentation und deutsche `.de.md`-Fassungen synchron halten;
- Release Notes bei sichtbaren Verhaltensänderungen aktualisieren;
- das feste oberste Release-Verzeichnis `BorgBackup-Manager/` erhalten;
- Datenbankmigrationen vermeiden, sofern sie nicht erforderlich und dokumentiert sind;
- lokale Syntaxprüfungen und die vollständige automatisierte Testsuite bestehen.

Umfangreiche KI-gestützte Entwicklung soll im Pull Request offengelegt werden. KI-generierte Änderungen müssen vom Mitwirkenden geprüft, angepasst und getestet werden.

Mit dem Einreichen bestätigst du, dass du zur Bereitstellung der Änderung berechtigt bist und der Veröffentlichung unter der Apache License 2.0 zustimmst.
