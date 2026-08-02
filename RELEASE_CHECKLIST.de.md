# Release-Checkliste – BorgBackup Manager

Diese Checkliste ist bei jeder Version vollständig abzuarbeiten. Nicht zutreffende Punkte werden bewusst als „nicht zutreffend“ dokumentiert, statt stillschweigend übersprungen zu werden.

## 1. Ausgangsstand und Umfang

- [ ] Ausgangs-ZIP und vorhandene SHA-256-Prüfsumme verifiziert.
- [ ] Änderungen ausschließlich auf dem vorgesehenen letzten Release aufgebaut.
- [ ] Gewünschter Funktionsumfang, Fehlerkorrekturen und bewusst nicht enthaltene Punkte festgehalten.
- [ ] Datenbank-, Backup-, Restore-, Update- und Rollback-Auswirkungen bewertet.

## 2. Version und Release-Metadaten

- [ ] `VERSION` aktualisiert.
- [ ] `app/release.py` mit korrektem Veröffentlichungsdatum aktualisiert.
- [ ] Versionsnummern in WebUI, Login, Cache-Busting-URLs und integrierter Hilfe aktualisiert.
- [ ] Versionsbeispiele in README, Installation, Compose-Dokumentation und `.env.example` aktualisiert.
- [ ] Paket-, ZIP-, SHA-256- und GHCR-Tag-Beispiele auf die neue Version umgestellt.
- [ ] Keine veralteten Versionsmarker mehr im Projekt vorhanden.

## 3. Code, Datenmodell und Migrationen

- [ ] Neue und geänderte Abläufe besitzen Regressionstests.
- [ ] Bestehende Installationen werden automatisch und idempotent migriert.
- [ ] Migrationen kopieren und prüfen Daten vor dem Entfernen alter Strukturen.
- [ ] Abbruch-, Neustart- und Wiederholungsfälle einer Migration sind abgesichert.
- [ ] SQLite-WAL/SHM-, Freelist- und Klartextreste wurden bei sicherheitsrelevanten Migrationen berücksichtigt.
- [ ] Vertrauliche Altdaten wurden in aktiven Tabellen, historischen Laufvorschauen, Ausgabe-/Fehler-/Logfeldern, Benachrichtigungsdetails, dateibasierten Laufprotokollen und Wartungskopien geprüft.
- [ ] Lösch-, Geräte-, Repository-, Backup- und Wartungsabläufe berücksichtigen das neue Datenmodell.
- [ ] Keine ungenutzten Module, Importe, Routen oder Frontend-Handler zurückgelassen.

## 4. Sicherheit und Geheimnisse

- [ ] Keine Passwörter, Tokens, Passphrasen, TOTP-Geheimnisse, Wiederherstellungscodes oder vertraulichen Befehle in Logs/Previews.
- [ ] Neue Geheimnisse werden authentifiziert verschlüsselt und mit dem vorhandenen Master-Key verwaltet.
- [ ] Manager-Backup enthält alle benötigten Sicherheitsdaten und prüft deren Entschlüsselbarkeit.
- [ ] Restore stellt zusammengehörige Datenbank- und Schlüsselstände konsistent wieder her.
- [ ] Dateirechte, temporäre Dateien, Fehler- und Abbruchbereinigung geprüft.
- [ ] Sicherheitskopien werden erst nach einer erforderlichen Geheimnisbereinigung dauerhaft abgelegt und führen entfernte Klartextdaten nicht wieder ein.
- [ ] Rollen- und API-Berechtigungen für neue Funktionen geprüft.
- [ ] Neue Abhängigkeiten auf Herkunft, feste Version, Hash und Lizenz geprüft.

## 5. WebUI, Bedienung und Übersetzung

- [ ] Desktop-, schmale und mobile Darstellung geprüft.
- [ ] Dialoge besitzen eigenen Scrollbereich und blockieren nicht unbeabsichtigt die Bedienung.
- [ ] Beschriftungen, Warnungen, leere Zustände, Fehlertexte und Bestätigungen sind eindeutig.
- [ ] Alle neuen sichtbaren Texte in `app/static/i18n.js` übersetzt.
- [ ] Deutsche und englische Oberfläche inhaltlich gleichwertig geprüft.
- [ ] Navigation, Profil, Formulare, Fokus, Tastaturbedienung und ARIA-Beschriftungen geprüft.
- [ ] Keine entfernten DOM-IDs oder alten Event-Handler mehr referenziert.

## 6. Dokumentation

- [ ] `README.de.md` und `README.md` aktualisiert.
- [ ] `INSTALLATION.de.md` und `INSTALLATION.md` aktualisiert.
- [ ] Integrierte WebUI-Hilfe `help.de.html` und `help.en.html` aktualisiert.
- [ ] `SECURITY.md`, `THIRD-PARTY-NOTICES.md` und Compose-Dokumentation bei Bedarf aktualisiert.
- [ ] Root- und App-Kopien der Release Notes aktualisiert und byte-identisch.
- [ ] Update-, Restore-, Migrations- und Sicherheitshinweise enthalten konkrete Pfade und Auswirkungen.

## 7. Automatisierte und statische Prüfungen

- [ ] Vollständige `pytest`-Suite bestanden.
- [ ] Python-Kompilierung für Anwendung, Tests und Prüfscripte erfolgreich.
- [ ] JavaScript-Syntax für `app.js`, `i18n.js` und `theme-init.js` erfolgreich.
- [ ] Shell-Syntax für Installations-, Update-, Recovery-, Restore- und Docker-Scripte erfolgreich.
- [ ] Beide Compose-Dateien als YAML geprüft.
- [ ] `scripts/project-audit.py` bestanden.
- [ ] Sicherheitskritische Abläufe zusätzlich mit gezielten Tests geprüft.

## 8. Paketinhalt und Reproduzierbarkeit

- [ ] Keine `.venv`, `.pytest_cache`, `__pycache__`, Testlaufzeiten oder lokalen Konfigurationen im ZIP.
- [ ] Keine Datenbanken, WAL/SHM-Dateien, Logs, Backups, Exporte, Schlüssel oder Secrets im ZIP.
- [ ] Festes oberstes Verzeichnis `BorgBackup-Manager/` erhalten.
- [ ] ZIP-Integrität geprüft.
- [ ] Vollständige Tests zusätzlich direkt aus dem finalen ZIP ausgeführt.
- [ ] SHA-256-Datei erzeugt und mit `sha256sum -c` verifiziert.
- [ ] Endgültige Dateinamen und Update-Befehle mit dem tatsächlichen Artefakt abgeglichen.

## 9. Abschluss

- [ ] Release-Zusammenfassung enthält Version, Download, SHA-256, Update-Befehle, umgesetzte Punkte und Prüfungen.
- [ ] Nicht real ausführbare Infrastrukturtests werden ausdrücklich benannt.
- [ ] Bekannte Einschränkungen oder notwendige manuelle Schritte sind dokumentiert.
