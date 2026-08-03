# Hinweise zu Drittanbieterkomponenten

Der eigene Quellcode des BorgBackup Managers steht unter der Apache License 2.0. Diese Datei fasst wichtige Drittanbieterkomponenten der Anwendung zusammen. Sie ersetzt nicht die vollständigen Lizenztexte der jeweiligen Projekte, Python-Pakete oder Debian-Pakete.

[English version](THIRD-PARTY-NOTICES.md)

## Zentrale Laufzeitkomponenten

| Komponente | Zweck | Lizenz |
|---|---|---|
| BorgBackup | Backup-Engine im Container | BSD-3-Clause |
| OpenSSH | SSH-Dienst für verwaltete Repositories und Client-Transport | BSD-artige Lizenzen |
| OpenSSL | TLS- und Kryptografieunterstützung | Apache-2.0 |
| Python | Anwendungslaufzeit | Python Software Foundation License |
| Debian | Betriebssystempakete des Containers | Paketspezifische freie Lizenzen |

## Direkte Python-Abhängigkeiten

| Paket | Lizenz |
|---|---|
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| SQLAlchemy | MIT |
| APScheduler | MIT |
| Pydantic | MIT |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| qrcode | BSD |

Der vollständig aufgelöste Abhängigkeitsstand ist in `requirements.txt` festgeschrieben. Transitive Python-Pakete behalten ihre eigenen Lizenzen und Hinweise. Installierte Paketinformationen können im Image mit `python -m pip show PAKET` eingesehen werden. Debian-Lizenz- und Copyright-Dateien befinden sich im Container unter `/usr/share/doc`.

## Browser-Ressourcen

Die Weboberfläche lädt keine JavaScript-, CSS-, Schrift- oder Analyse-Ressourcen von externen Content-Delivery-Netzwerken. Die ausgelieferten statischen Dateien werden als Teil dieses Projekts gepflegt, sofern eine Datei nichts anderes angibt.

## Marken und Unabhängigkeit

BorgBackup und zugehörige Namen sind Marken oder Projektnamen ihrer jeweiligen Eigentümer. BorgBackup Manager ist ein unabhängiges Community-Projekt eines Drittanbieters und weder mit dem BorgBackup-Projekt verbunden noch von diesem unterstützt oder gepflegt.

## Aktualisierung dieser Datei

Beim Hinzufügen einer Abhängigkeit, eingebetteten Ressource oder Betriebssystemkomponente ist deren Lizenzkompatibilität zu prüfen und dieser Hinweis zu aktualisieren, sofern die Komponente für die ausgelieferte Anwendung relevant ist.
