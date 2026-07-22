# Release Notes

## v1.0.63 – 22.07.2026

### Richtige Beschriftung bei Archivvergleichen

- Die sichtbare Bezeichnung einer Archivvergleich-Ausführung wird nun aus den tatsächlich ausgewählten Archivserien gebildet und nicht mehr aus dem technisch für den Repositoryzugriff verwendeten Backup-Job.
- Bei Archiven desselben Jobs wird dessen Name angezeigt. Bei Archiven aus zwei Jobs erscheint beispielsweise `OVPN-C-VPN0 ↔ OVPN-C-VPN1 · Archive vergleichen`.
- Für nicht eindeutig zugeordnete Archive wird ersatzweise die aus dem Archivnamen erkannte Gerätebezeichnung verwendet.
- Der Vergleichsbefehl, die Archivauswahl und die bereits lesbare Diff-Ausgabe bleiben unverändert.

### Projektweite Referenz- und Dateiprüfung

- Das neue lokale Prüfscript `scripts/project-audit.py` kontrolliert Python-Module, CLI-Einstiegspunkte, statische Webressourcen, Frontend-API-Verweise, Docker-`COPY`-Quellen, lokale Markdown-Links und die Release-Struktur.
- Die Prüfung ist in `scripts/release-check.sh` integriert und benötigt keine GitHub Actions.
- Die doppelten Release-Notes-Dateien unter `app/` bleiben bewusst als Kompatibilitätskopien für sehr alte Updater erhalten und werden nun auf bitgenaue Übereinstimmung geprüft.
- Es wurden keine ungenutzten Laufzeitmodule, fehlenden statischen Dateien, ungültigen API-Verweise oder verwaisten Projektdateien gefunden.

### Weitere Performanceoptimierungen ohne Funktionsverlust

- Die Ausführungsliste ermittelt vorhandene dateibasierte Protokolle mit einem gemeinsamen Verzeichnisscan statt mit einer einzelnen Dateisystemprüfung pro Tabellenzeile.
- Bereits in eigenen Datenbankfeldern gespeicherte Backup-Statistiken werden beim Laden der Ausführungsliste nicht erneut aus dem Protokolltext geparst. Der Parser bleibt als Fallback für ältere oder unvollständige Datensätze erhalten.
- Persistente Einstellungen werden nach Dateipfad, Änderungszeit und Größe zwischengespeichert. Änderungen aus der WebUI werden sofort übernommen; manuelle Dateiänderungen werden beim nächsten Zugriff erkannt.
- Versionsgebundene statische Webressourcen werden browserseitig unveränderlich zwischengespeichert. Das HTML-Dokument und API-Antworten bleiben weiterhin ungecacht.

### Prüfung

- 456 automatisierte Tests bestanden; zusätzlich Projekt-Audit sowie Python-, JavaScript-, Bash- und POSIX-Shell-Syntaxprüfungen erfolgreich.
- Update-Kompatibilität, Docker-Build-Quellen, deutsche und englische Dokumentation sowie alte Updater-Kompatibilitätskopien geprüft.
- Keine Datenbankschema-Migration erforderlich.

## v1.0.62 – 22.07.2026

### Update von v1.0.60 wieder kompatibel

- Der fehlgeschlagene Build von v1.0.61 wurde durch die neu eingeführte Datei `RELEASE_DATE` verursacht. Das noch laufende `update.sh` aus v1.0.60 kannte diese Datei nicht, kopierte aber bereits den neuen Dockerfile. Dadurch fehlte `RELEASE_DATE` im Docker-Build-Kontext.
- Das Release-Datum liegt nun als statische Metadaten in `app/release.py`. Der komplette Ordner `app/` wird auch von älteren Updatern zuverlässig übernommen.
- Der Dockerfile benötigt nur noch `VERSION` als separate Metadatendatei. Eine neue, dem alten Updater unbekannte Datei im Projektstamm ist nicht mehr erforderlich.
- `update.sh`, Release-Prüfung und Regressionstests wurden entsprechend angepasst.
- Der fehlgeschlagene v1.0.61-Updateversuch hat die bisherigen Projektdateien laut Updater erfolgreich wiederhergestellt; eine Datenbankmigration war nicht gestartet worden.

### Prüfung

- Update-Kompatibilität mit der Dateiauswahl von v1.0.60 simuliert.
- Docker-Build-Kontext enthält alle im Dockerfile verwendeten Quellen.
- Keine Datenbankschema-Migration erforderlich.

## v1.0.61 – 22.07.2026

### Fortlaufende Live-Ausgabe bei sparsamen Jobs

- Der dateibasierte Live-Log-Writer wird nun zusätzlich zeitgesteuert geleert. Dadurch erscheint der Backup-Kopf auch dann während des laufenden Jobs, wenn die vollständige Dateiliste deaktiviert ist und Borg bis zur Abschlussstatistik keine weiteren Zeilen ausgibt.
- Das normale Pufferlimit und das maximale Flush-Intervall bleiben erhalten; große Dateilisten behalten daher die CPU-Optimierungen aus v1.0.57 und v1.0.58.
- Leere inkrementelle Abfragen verändern die Ansicht weiterhin nicht und doppelte Kopfblöcke bleiben verhindert.

### Kompakterer Backup-Job-Editor

- Quellpfade, Ausschlussvorlage und Ausschlüsse beginnen weiterhin oben in der rechten Spalte.
- Archivnamensvorlage und Kompression wurden in die linke Grunddatenspalte verschoben. Dadurch wird der bisher freie Bereich unter Name, Gerät und Repository genutzt und der gesamte Formularblock kürzer.
- Unterhalb von 820 Pixeln wechselt das Formular weiterhin vollständig in eine einspaltige Mobilansicht.

### Korrekter und lesbarer Archivvergleich

- Für zwei Archive desselben Backup-Jobs wird nun der tatsächliche Eigentümerjob anhand des längsten passenden Archivpräfixes ermittelt. Der zuerst angelegte Job des Repositorys wird nicht mehr als Beschriftung verwendet.
- Die Archivauswahl zeigt den zugeordneten Job an; ein zusätzlicher Kontext nennt Backup-Job und Gerät beziehungsweise warnt bei unterschiedlichen oder nicht eindeutig zugeordneten Archiven.
- `borg diff` verwendet wieder die menschenlesbare Standardausgabe statt unformatierter JSON-Zeilen. Ein klarer Kopf zeigt älteres Archiv, neueres Archiv, Pfadbereich und Inhaltsfilter.
- Der Laufdialog zeigt für die Aktion die Bezeichnung **Archive vergleichen** und verwendet eine besser lesbare Zeilenhöhe.

### Version und Veröffentlichungsdatum

- Die Seitenleiste zeigt Version und Release-Datum gemeinsam als `v1.0.61 · 22.07.2026`.
- Das Release-Datum wird aus der neuen Datei `RELEASE_DATE` gelesen und durch Dockerfile sowie Updater übernommen.

### Prüfung

- 448 automatisierte Tests bestanden, einschließlich zeitgesteuertem Live-Log-Flush, korrekter Archivbesitzer-Ermittlung, lesbarer Diff-Ausgabe und responsivem Backup-Job-Formular.
- Python-, JavaScript-, Bash- und POSIX-Shell-Syntax erfolgreich geprüft.
- Keine Datenbankschema-Migration erforderlich. Geräte, Repositorys, Backup-Jobs, Zeitpläne, Archive, Benutzer und Einstellungen bleiben unverändert.

## v1.0.60

### Live-Protokoll ohne wiederholten Kopfblock

- Leere inkrementelle Live-Log-Antworten greifen nicht mehr auf die SQLite-Metadatenvorschau zurück. Dadurch wird der bereits angezeigte Backup-Kopf während eines laufenden Jobs nicht erneut angehängt.
- Der Platzhalter wird weiterhin beim ersten echten Logblock ersetzt; Abfragen ohne neue Bytes verändern die sichtbare Ausgabe nicht.
- Laufende Backup-Ausgaben werden für SQLite jetzt blockgrenzensicher gefiltert: normale Borg-Dateistatus und Pfade verbleiben ausschließlich im dateibasierten Protokoll, während kleine Metadaten weiterhin live verfügbar bleiben.

### Kompaktere Bedienoberfläche

- Backup-Jobs besitzen nun einen direkten **Bearbeiten**-Button zwischen **Archive** und **Mehr**.
- Der Editor für Backup-Jobs ordnet Name, Gerät und Repository links sowie Quellpfade, Ausschlussvorlage und Ausschlüsse rechts an.
- Der Editor für zentrale Zeitpläne ordnet Name, Zielgruppe, Rhythmus und Parallelitätsgrenze links sowie Zielauswahl und Ausführungszeiten rechts an.
- **Archive vergleichen** verwendet eine kompakte zweispaltige Anordnung und eine kleinere Pfadeingabe.
- Alle neuen Anordnungen wechseln auf Tablets und Mobilgeräten automatisch in eine einspaltige Ansicht; Aktionsflächen bleiben vollständig bedienbar.

### Prüfung

- 443 automatisierte Tests bestanden, einschließlich leerer Live-Log-Deltas, blockgrenzensicherer SQLite-Pfadfilterung, direktem Bearbeiten-Button und responsiven Formlayouts.

## v1.0.59

### Live-Protokoll ohne doppelte Startblöcke

- Beim Öffnen eines laufenden Jobs werden initiale Logabfrage und Hintergrund-Polling jetzt serialisiert. Beide können nicht mehr gleichzeitig denselben Dateioffset lesen und denselben Kopfblock mehrfach an die Ansicht anhängen.
- Verspätete Antworten einer älteren Live-Abfrage werden anhand von Sitzung und Dateioffset verworfen.
- Der Platzhalter **Noch keine Ausgabe vorhanden …** wird beim ersten echten Logblock ersetzt und nicht mehr vor die Ausgabe geschrieben.
- Rücksetzungen nach Logkürzung bleiben erhalten und ersetzen die Ansicht weiterhin kontrolliert.

### Keine vollständigen Dateipfade mehr in SQLite-Vorschauen

- Ein älterer Abschluss-Fallback schrieb trotz dateibasierter Protokolle noch einmal die letzten 16 KiB der rohen Borg-Ausgabe in `Run.log_output`. Dadurch konnten normale Dateipfade nach Laufende erneut in `manager.db` erscheinen. Dieser Fallback wurde entfernt.
- Vollständige Borg-Status- und Pfadausgaben liegen ausschließlich in `/data/run-logs/run-ID.log`. SQLite enthält nur kleine Metadaten- und Diagnosevorschauen sowie die strukturierte Warnungszusammenfassung.
- Normale Statuspfade werden aus `output`, `error` und `log_output` entfernt. Konkret betroffene Warnungspfade bleiben bewusst begrenzt in `warning_summary_json`, weil Ausführungsdetails und Benachrichtigungen davon abhängen.
- Beim Start werden vorhandene ältere SQLite-Vorschauen automatisch bereinigt. Fehlende dateibasierte Logs werden vorher aus den Altinhalten erzeugt; anschließend kann die Datenbank wie bisher automatisch mit `VACUUM` verkleinert werden.

### Prüfung

- 439 automatisierte Tests bestanden, einschließlich paralleler Live-Abfragen, Platzhalterwechsel, SQLite-Vorschau-Bereinigung, Altprotokollmigration und strukturierter Warnungspfade.
- Keine Schemaänderung erforderlich. Geräte, Repositorys, Jobs, Zeitpläne, Archive, Benutzer und Einstellungen bleiben unverändert.

## v1.0.58

### Zweite CPU-Optimierungsstufe für vollständige Dateilisten

- Der produktive Hochvolumenpfad verarbeitet `borg create --list` jetzt als rohe Byte-Blöcke. Normale Dateinamen werden im Manager nicht mehr vollständig nach UTF-8 dekodiert und nicht mehr zeilenweise in Python zerlegt.
- Ein schneller Byte-Block-Filter überspringt vollständige Blöcke mit normalen Borg-Statuszeilen in einem Schritt. Nur Blöcke mit `C`, `E` oder textuellen Warnungen werden für die strukturierte Warnungserfassung genauer ausgewertet.
- Normale Dateistatus werden nicht mehr fortlaufend in die SQLite-Vorschau gespiegelt. SQLite erhält während des Laufs nur kleine stdout-Metadaten und tatsächlich geänderte Warnungszusammenfassungen; das vollständige Protokoll bleibt unverändert unter `/data/run-logs` erhalten.
- Der Subprozessleser verwendet bis zu 256 KiB große Rohdatenblöcke. Der Log-Writer puffert bis zu 1 MiB beziehungsweise maximal 750 ms und hält die bekannte Dateigröße selbst nach, statt bei jedem Flush erneut `stat()` aufzurufen.
- Die Warnungserfassung bleibt vollständig erhalten: geänderte Dateien (`C`), Datei-Zugriffsfehler (`E`), Berechtigungs-, E/A-, fehlende Pfad- und textuelle Borg-Warnungen werden weiterhin strukturiert gespeichert.

### Inkrementelles Live-Protokoll

- Ein geöffnetes Live-Protokoll lädt nur noch die seit der letzten Abfrage neu hinzugekommenen Bytes anhand eines Dateioffsets.
- Die WebUI überträgt und rendert nicht mehr bei jedem Poll denselben 256-KiB-Ausschnitt erneut.
- Fällt der Browser hinter die Ausgabe zurück oder wurde die Logdatei zwischenzeitlich gekürzt, liefert der Server automatisch den neuesten begrenzten Ausschnitt und setzt die Live-Ansicht kontrolliert zurück.
- Die aktive Browseransicht ist auf 768 KiB begrenzt; die vollständige konfigurierte Kopf-/Endansicht wird nach Abschluss weiterhin einmalig geladen. Die Protokolldatei selbst bleibt davon unberührt.
- Bei geöffnetem Dialog wird alle 1,8 Sekunden, bei geschlossenem Dialog alle 1,5 Sekunden abgefragt.

### Prüfung

- Synthetischer Vergleich mit 500.000 normalen Dateizeilen sowie je einer `C`- und `E`-Warnung: Die reine Manager-Verarbeitung sank in der Prüfumgebung von etwa 0,76–0,91 Sekunden auf etwa 0,17–0,24 Sekunden. Zusätzlich entfielen in diesem Test 62 SQLite-Vorschau-Flushes vollständig.
- 436 automatisierte Tests bestanden, einschließlich Byte-Streaming, inkrementeller Log-Offsets, Log-Rücksetzung, Warnungserfassung und vollständigem Abschlusslauf.
- Keine Datenbankmigration erforderlich. Geräte, Repositorys, Jobs, Zeitpläne, Archive, Benutzer und Einstellungen bleiben unverändert.

## v1.0.57

### CPU-optimierte Verarbeitung vollständiger Dateilisten

- Die Option **Verarbeitete Dateien im Live-Protokoll anzeigen** bleibt vollständig erhalten, verarbeitet große `borg create --list`-Ausgaben aber jetzt gebündelt statt mit einem Dateizugriff je kleinem Prozessblock.
- Das Ausführungsprotokoll verwendet während eines Laufs einen gepufferten, dauerhaft geöffneten Writer. Schreibvorgänge, Dateirechteprüfung und Größenkontrolle erfolgen nur noch in begrenzten Intervallen beziehungsweise nach größeren Datenblöcken.
- Die gefilterte Fehleransicht wird nicht mehr für jeden einzelnen Borg-Ausgabeblock aus einem bis zu 256 KiB großen Textbereich neu berechnet, sondern nur beim begrenzten Datenbank-Flush.
- Normale Borg-Dateistatus wie `A`, `M`, `U` oder `d` überspringen die vollständige Warnungs-Regulärauswertung. Warnungsrelevante Status `C` und `E` sowie textuelle Borg-Warnungen werden weiterhin vollständig erkannt und strukturiert gespeichert.
- Der Subprozessleser verarbeitet größere Datenblöcke und hält bei begrenzter Ausgabeaufnahme weiterhin exakt das Ende von stdout und stderr fest.

### Reduzierte Live-Abfragen der WebUI

- Solange der Laufdialog geschlossen ist, fragt die WebUI nur Laufstatus und Metadaten ab und liest nicht mehr bei jedem Poll das dateibasierte Live-Protokoll.
- Bei geöffnetem Live-Log wird während des Laufs eine begrenzte 256-KiB-Kopf-/Endansicht übertragen. Nach Abschluss wird die konfigurierte vollständige Protokollansicht einmalig geladen.
- Das Live-Polling-Intervall wurde von 850 auf 1200 Millisekunden angehoben, ohne die Warnungserfassung oder den Laufstatus zu beeinflussen.

### Prüfung

- Ein synthetischer Vergleich mit 120.000 Borg-Dateizeilen und 4,2 MiB Ausgabe reduzierte die reine Manager-Verarbeitungszeit in der Prüfumgebung von rund 14,4 auf 0,46 Sekunden. Dies ist ein reproduzierbarer Belastungstest und keine Garantie für einen bestimmten Wert auf Produktivsystemen.
- Warnungsdateien mit Status `C` und `E` bleiben bei aktivierter und deaktivierter vollständiger Dateiliste erhalten.
- Keine Datenbankmigration erforderlich. Geräte, Repositorys, Jobs, Zeitpläne, Archive, Benutzer und Einstellungen bleiben unverändert.

## v1.0.56

### Manuelle GitHub-Veröffentlichung

- Dependabot-Konfiguration und gehosteten GitHub-Actions-Test-/Container-Build-Workflow entfernt.
- Zugehörige Hinweise und Prüfungen aus README, Beitragsrichtlinie, Release-Prüfung und Updater entfernt.
- Der Updater entfernt ein von v1.0.55 verbliebenes `.github`-Automatisierungsverzeichnis.
- Lokale automatisierte Tests, Syntaxprüfungen und `scripts/release-check.sh` bleiben für kontrollierte Releases erhalten.

### Update

- Keine Datenbankmigration erforderlich. Geräte, Repositorys, Jobs, Zeitpläne, Archive, Benutzer und Einstellungen bleiben unverändert.

## v1.0.55

### Vorbereitung für ein öffentliches Repository

- Apache License 2.0, Copyright-Hinweis, Sicherheitsrichtlinie, Beitragsrichtlinie und Third-Party-Hinweise ergänzt.
- Deutlicher Hinweis ergänzt, dass BorgBackup Manager ein unabhängiges Drittprojekt ist und weder mit dem BorgBackup-Projekt verbunden ist noch von diesem gepflegt wird.
- Transparenter Hinweis auf die Unterstützung durch OpenAI ChatGPT und die menschliche Prüfung und Verantwortung ergänzt.
- Dokumentiert, dass nur die aktuelle Version Sicherheitskorrekturen erhält und Versionen vor 1.0.38 nicht unterstützt werden.

### Lokale Release-Prüfung

- Wiederverwendbares lokales Release-Prüfskript und robuste Pytest-Pfadkonfiguration ergänzt.

### Repository-Hygiene

- `.gitignore` und `.dockerignore` um lokale Konfigurationen, Laufzeitdaten, Datenbanken, Logs, Backups, Updatearchive und Build-Ausgaben erweitert.
- Künstliche OpenSSH-Private-Key-Markierungen in HTML und Tests so aufgeteilt, dass generische Secret-Scanner sie seltener als echte private Schlüssel melden; Laufzeitvalidierung und sichtbarer Platzhalter bleiben unverändert.

### Update

- Keine Datenbankmigration erforderlich. Geräte, Repositorys, Jobs, Zeitpläne, Archive, Benutzer und Einstellungen bleiben unverändert.

## v1.0.54

### Warnungsmarkierung im Dashboard

- Der Inline-Status **Warnung** in der Backup-Job-Tabelle des Dashboards übernimmt nicht mehr die Innenabstände, den abgerundeten Hintergrund und die vergrößerte Schrift einer vollständigen Warnhinweis-Box.
- Warnhinweis-Boxen und Warnungs-Badges behalten ihre bisherige Darstellung. Die CSS-Selektoren unterscheiden jetzt ausdrücklich zwischen Inline-Statustext, Badge und Hinweiscontainer, einschließlich der kompakten Darstellung.

### Statische Demo abgeglichen

- Die separat bereitgestellte eigenständige Demo wurde erneut mit der Oberfläche von v1.0.54 abgeglichen. Unter Repository **Nutzung** stehen jetzt die Anzahl der zugeordneten Jobs und Geräte; die Repository-Größe bleibt in der getrennten Spalte **Größe**.
- Dashboard-Metadaten, Backup-Job-Liste, Zeitpläne, Benutzer und Repository-Zeilen entsprechen nun genauer der Struktur und den Bezeichnungen der echten Oberfläche.

### Prüfung

- Ein Regressionstest verhindert, dass der Inline-Warnungsstatus erneut Abstände einer Warnhinweis-Box übernimmt.
- Die statische Demo wurde mit Dummy-Repositorys, Geräten, Jobs, Zeitplänen, Benutzern und Ausführungen gerendert und geprüft.

## v1.0.53

### Diagnose bei deaktivierten Geräten

- Repository-Zugangsprüfungen vergleichen `authorized_keys` nur noch mit aktivierten Geräten. Gespeicherte Zugangszuordnungen deaktivierter Geräte bleiben für eine spätere Aktivierung erhalten, verursachen aber keine falschen Fehler bei **Forced Command** oder **Zugänge vollständig** mehr.
- Deaktivierte Zugangszuordnungen werden separat als Information angezeigt. Vorhandene aktive Schlüssel werden weiterhin auf den repositorybezogenen Forced Command geprüft.

### Umschaltbare Serverlogs und dauerhaftes Debug-Log

- Die Systemdiagnose zeigt `sshd`, `borg-serve` und das neue Debug-/Fehlerlog über drei Reiter, statt zwei lange Logdateien direkt untereinander auszugeben.
- `/data/logs/debug.log` erfasst unerwartete HTTP-Tracebacks, Scheduler-Fehler, unbehandelte Thread-Ausnahmen und Fehler aus asyncio beziehungsweise Hintergrundaufgaben. Für das Log gelten die vorhandenen Größen- und Rotationsgrenzen.
- Erwartete Borg-Ausgaben bleiben im jeweiligen Ausführungsprotokoll und werden nicht in das Debug-Log dupliziert.

### Dateibrowser für lokale Repositorys

- Die automatische Suche nach vorhandenen lokalen Repositorys bleibt erhalten.
- Ein zusätzlicher Dateibrowser listet den Inhalt unter `/repositories`, ermöglicht eine sichere Ordnernavigation und lässt erkannte Borg-Repositorys in direkten Unterordnern gezielt auswählen.
- Pfadausbruch aus `/repositories` und Navigation über symbolische Links werden blockiert; pro Ansicht werden höchstens 500 Einträge angezeigt.

### Prüfung

- Regressionstests decken die Diagnose deaktivierter Geräte, echte Fehler aktiver Zugänge, Forced-Command-Prüfung, Pfadbegrenzung des Repository-Browsers, Symlink-Schutz, Debug-Log und die Drei-Reiter-Ansicht ab.

## v1.0.52

### Kompaktes Dashboard und verbesserte Mobilansichten

- **Letzter Job** verwendet jetzt drei kompakte Zeilen: Ausführungs-ID mit Datum/Uhrzeit, Status mit Dauer sowie Zeitplan beziehungsweise manueller Start. Die Dashboard-Spalte wird nicht verbreitert.
- Auf Mobilgeräten übernimmt die Größenanzeige der letzten Sicherung nicht mehr die Desktop-Mindestbreite der Tabelle. Die Werte bleiben innerhalb der sichtbaren Karte, statt erst nach einem großen leeren horizontalen Bereich zu erscheinen.
- Archivkarten brechen Metadaten und Aktionen auf schmalen Ansichten direkt untereinander um. Der große Abstand zwischen Archiv-ID beziehungsweise Details und den Aktionsbuttons entfällt.
- Der Archivbrowser wechselt mobil zu lesbaren Metadatenkarten und zeigt weiterhin Name, Größe, Typ, Rechte, Besitzer und Änderungsdatum.
- Die Systemdiagnose stellt Serverprüfungen als kompakte Statuskarten dar. Dateisystemtabellen und Protokolle bleiben innerhalb der mobilen Ansicht; lange Protokollzeilen werden sicher umgebrochen.

### Prüfung

- Regressionstests decken die dreizeilige Darstellung des letzten Jobs, mobile Dashboard-Breiten, kompakte Archivkarten, den mobilen Archivbrowser und die responsive Systemdiagnose ab.

## v1.0.51

### Mehrfachlöschung von Archiven bei verschlüsselten Repositorys

- Die Löschung mehrfach ausgewählter Archive in passphrasengeschützten Repositorys wurde korrigiert.
- Der überwachte Wrapper stellte die Passphrase bisher über einen gemeinsam verwendeten `BORG_PASSPHRASE_FD` bereit. Der erste Borg-Prozess las diesen Deskriptor bis zum Dateiende; die zweite Archivlöschung oder das anschließende Compact erhielt deshalb keine Passphrase mehr und meldete eine falsche Passphrase.
- Der Wrapper verwendet jetzt eine geschützte temporäre Passphrase-Datei über `BORG_PASSCOMMAND`. Jeder Lösch- und Compact-Aufruf öffnet die Datei neu; die Passphrase selbst wird weder in die Befehlszeile noch in eine normale Umgebungsvariable geschrieben.
- Einzelne Archivlöschung, Mehrfachauswahl, optionales einmaliges Compact, kontrollierter Abbruch und die Bereinigung temporärer Dateien verwenden denselben korrigierten Pfad.

### Prüfung

- Ein Regressionstest führt zwei Borg-Löschungen und ein Compact nacheinander aus und bestätigt, dass alle drei Aufrufe die korrekte Passphrase erhalten.

## v1.0.50

### Kompakte Metadaten der Backup-Jobs im Dashboard

- **Größe letzte Sicherung** zeigt Dedupliziert, Original und Komprimiert jetzt als drei eng gesetzte Beschriftungs-/Wertzeilen, ohne die Dashboard-Tabelle zu verbreitern.
- **Letzter Job** zeigt Ausführungs-ID und Datum/Uhrzeit in der ersten Zeile; Dauer, Status und Auslöser stehen direkt darunter.
- **Quellenstatistik** verwendet zwei kompakte Zeilen: zuerst Größe und Dateianzahl, darunter Herkunft und Zeitpunkt des Wertes.

### Warnungsbenachrichtigungen mit betroffenen Dateien

- Benachrichtigungen zu Backup-Warnungen enthalten jetzt zu jeder strukturierten Borg-Warnungsursache die konkret gespeicherte Datei beziehungsweise den Pfad.
- Auf Meldungen wie `changed – file changed while we backed it up` folgt damit der betroffene Pfad statt nur der allgemeinen Ursache.
- Bis zu zehn strukturierte Einträge werden ausgegeben; weitere Einträge werden als Anzahl genannt.
- Die Benachrichtigung verwendet die bereits während des Borg-Laufs gespeicherte Warnungszusammenfassung und ist nicht von einem später gekürzten Logausschnitt abhängig.

### Dokumentation und Updatepaket

- Englisch bleibt die Standardsprache der Markdown-Dateien (`.md`); deutsche Fassungen verwenden ausschließlich `.de.md`.
- Der Updater prüft `RELEASE_NOTES.md` und `RELEASE_NOTES.de.md`; eine `.en.md`-Datei wird nicht benötigt.

### Prüfung

- Dashboard-Darstellung, deutsche und englische Benachrichtigungstexte, betroffene Warnungspfade, JavaScript-Syntax und Paketdokumentation sind durch Regressionstests abgedeckt.

## v1.0.49

### Aktive Markierung der System-Reiter zuverlässig sichtbar

- Die System-Reiter verwenden jetzt die eigene Klasse `system-tab` und werden von der allgemeinen Gestaltung normaler Aktionsbuttons ausgeschlossen, die zuvor alle Reiter gleich eingefärbt hat.
- Der ausgewählte Reiter erhält feste kontrastreiche Farben für Hell- und Dunkelmodus und ist nicht mehr von `color-mix()` abhängig.
- Der aktive Reiter wird gleichzeitig mit `active`, `aria-selected="true"` und `aria-current="page"` gekennzeichnet.
- Sitzungswiederherstellung, direkte Hash-Navigation und Seitenreload synchronisieren den ausgewählten Systembereich weiterhin.

### Englische Markdown-Dateien als Standard

- `README.md`, `INSTALLATION.md` und `RELEASE_NOTES.md` sind jetzt standardmäßig englisch.
- Die vollständigen deutschen Dokumente heißen `README.de.md`, `INSTALLATION.de.md` und `RELEASE_NOTES.de.md`.
- Der Release-Notes-Endpunkt der Anwendung lädt die englische Standarddatei und die deutsche `.de.md`-Datei ausdrücklich getrennt.
- Da Updater bis einschließlich v1.0.48 noch die frühere Datei `RELEASE_NOTES.en.md` verlangen, muss `update.sh` für den Übergang auf v1.0.49 einmalig vor dem normalen Update aus dem neuen ZIP übernommen werden.
- Build, Update, Tests und Dokumentationsverweise wurden an die neue Konvention angepasst.

### Prüfung

- CSS-Priorität der aktiven Reiter, feste Aktivfarben für Hell- und Dunkelmodus, Reload-Synchronisierung, zweisprachige Release Notes und die Vollständigkeit der Paketdokumentation werden durch Regressionstests geprüft.

## v1.0.48

### System-Reiter nach Reload zuverlässig wiederhergestellt

- Die Systemansicht wird nach Login, automatischer Sitzungswiederherstellung und Seitenreload erneut mit dem aktuellen URL-Hash und der Benutzerrolle synchronisiert.
- Die Reiterleiste bleibt dadurch bei direkten Links wie `#notifications`, `#users`, `#backups`, `#settings` und `#diagnostics` sichtbar.
- Der aktive Reiter wird sowohl über die CSS-Klasse als auch über `aria-selected="true"` eindeutig und dunkler hervorgehoben.
- Die strikte Administratorprüfung bleibt bestehen; normale Benutzer erhalten die System-Reiter weiterhin nicht.
- Ein neuer Regressionstest verhindert, dass die Reiterleiste bei einer späteren Änderung erneut nach dem Reload verschwindet.

### Prüfung

- 404 automatisierte Tests sind im Projektstand enthalten; die neuen Navigationstests und die statischen Prüfungen wurden erfolgreich ausgeführt.

## v1.0.47

### Sticky Systemnavigation

- Die fünf System-Reiter befinden sich direkt in der sticky Kopfzeile und bleiben beim Scrollen dauerhaft sichtbar.
- Der aktive Bereich wird als dunkel gefüllter Reiter hervorgehoben; die mobile Reiterleiste bleibt horizontal scrollbar.
- Bestehende Direktlinks, Administratorrechte und die Seitenleistenmarkierung **System** bleiben unverändert.

### Quellenstatistik für Backup-Jobs

- Die Backup-Job-Übersicht zeigt unter den Quellpfaden zusätzlich Originalgröße, Dateianzahl, Zeitpunkt und Herkunft der Werte.
- Nach einem erfolgreichen oder mit Warnung abgeschlossenen Backup werden Größe und Dateianzahl direkt aus Borgs Abschlussstatistik übernommen.
- **Aktualisieren** und **Mehr → Prüfen → Quellenstatistik** starten einen repositoryunabhängigen Live-Scan auf dem Quellgerät. Er schreibt kein Archiv und zählt die konfigurierten Quellen vor Borg-Ausschlüssen.
- Der Live-Scan läuft als derselbe SSH-Benutzer wie der Backup-Job, unterstützt `one_file_system`, kontrollierten Abbruch sowie einen `find`/`stat`-Fallback ohne Python 3.
- Änderungen an Quellpfaden, Ausschlüssen oder relevanten Dateisystemoptionen verwerfen automatisch veraltete Statistikwerte.
- Die Datenbank wird automatisch um die Quellen- und Dateizählerfelder erweitert.

### Archivbrowser als Dateibrowser

- Der Archivbrowser verwendet eine Breadcrumb-Navigation und eine Dateitabelle.
- Angezeigt werden Name, Größe, Typ, Rechte, Besitzer/Gruppe und Änderungsdatum.
- Verzeichnisse werden zuerst sortiert, symbolische Links mit Ziel dargestellt und die Anzahl der sichtbaren Einträge angezeigt.
- Die Metadaten stammen direkt aus `borg list --json-lines`; ein FUSE-Mount ist weiterhin nicht erforderlich.

### Prüfung

- 403 automatisierte Tests bestanden, darunter reale Live-Scan-, Persistenz-, Datenbankmigrations-, UI- und Archivmetadatentests.

## v1.0.46

### Systembereiche zentral zusammengeführt

- Unter **Infrastruktur** enthält die Seitenleiste nur noch **Geräte** und **System**.
- Die bisherigen Einträge **Benachrichtigungen**, **Benutzer**, **Manager-Backup** und **Einstellungen** wurden aus der Seitenleiste entfernt und gemeinsam unter **System** zusammengeführt.
- Der Systemarbeitsbereich besitzt am oberen Rand eine feste Reiterleiste in der Reihenfolge **Benachrichtigungen**, **Benutzer**, **Manager-Backup**, **Einstellungen** und **Systemdiagnose**.
- Beim Wechsel zwischen den fünf Bereichen bleibt **System** in der Seitenleiste aktiv und die Seitenüberschrift eindeutig auf **System** gesetzt.
- Die bisherigen direkten Hash-URLs bleiben gültig, sodass vorhandene Lesezeichen und interne Verlinkungen weiterhin funktionieren.

### Dashboard und responsive Darstellung

- Die Systemdiagnose wurde vollständig aus dem Dashboard entfernt und in den eigenen Reiter **Systemdiagnose** verschoben.
- Die Reiterleiste ist auf schmalen Bildschirmen horizontal scrollbar und unterstützt die kompakte Darstellungsdichte.
- Administratorrechte werden weiterhin für alle fünf Systembereiche erzwungen; normale Benutzer werden bei direkten URLs sicher zum Dashboard zurückgeführt.
- Controller-Schlüssel, Benachrichtigungen, Benutzerverwaltung, Manager-Backup und Systemeinstellungen behalten ihre bestehenden Funktionen und APIs unverändert.

### Anleitung und Tests

- README, Installationsanleitung sowie die integrierte deutsche und englische Hilfe wurden auf die neue Navigation und die verschobene Systemdiagnose aktualisiert.
- Neue Regressionstests prüfen Seitenleiste, Reiterreihenfolge, aktive Zustände, Rechteprüfung, mobile Darstellung und das Fehlen der Diagnose auf dem Dashboard.
- Die vollständige Testsuite umfasst 391 bestandene Tests.

## v1.0.45

### Zentrale Benachrichtigungen für Backup- und Systemereignisse

- Der neue Administrationsbereich **Benachrichtigungen** versendet auswählbare Ereignisse per SMTP-E-Mail, generischem JSON-Webhook, Discord-Webhook oder Telegram-Bot.
- Konfigurierbar sind Backup-Fehler, Backup-Warnungen, optionale Erfolgsmeldungen, Abbrüche, Repository-Aktionen, Zeitplanfehler und sonstige Manager-Ausführungen.
- Jeder Kanal besitzt eine Testfunktion. Die aktuellen Formularwerte werden vor dem Test sicher gespeichert, sodass keine separate Zwischenspeicherung erforderlich ist.
- Das Zustellungsprotokoll zeigt Kanal, Ereignis, Titel, Zeitpunkt und Erfolg beziehungsweise konkrete Fehlermeldung. Es kann unabhängig von den Laufprotokollen geleert werden.

### Sichere Geheimnis- und Ausführungsbehandlung

- SMTP-Passwort, Webhook-URL und Telegram-Bot-Token werden ausschließlich verschlüsselt in der Sicherheitsdatenbank gespeichert und niemals an die WebUI zurückgegeben.
- Gespeicherte Geheimnisse bleiben bei leeren Eingabefeldern erhalten und können nur über eine ausdrückliche Löschoption entfernt werden.
- Versandfehler ändern weder Borg-Rückgabecode noch Laufstatus. Repository-, Zeitplan- und globale Ausführungsplätze werden vor dem Kontakt mit externen Diensten freigegeben.
- Diagnoseausschnitte sind gefiltert und auf 4.000 Zeichen begrenzt; die Aufnahme kann vollständig deaktiviert werden. Geheimnisse aus Webhook- oder Telegram-Adressen werden auch aus Fehlermeldungen entfernt.
- Generische Webhooks erhalten ein strukturiertes JSON-Dokument mit Quelle, Ereignis, Schweregrad, Titel, Nachricht, Lauf-ID und UTC-Zeitstempel.

### Backup, Dokumentation und Tests

- Manager-Backups enthalten nun zusätzlich die nicht geheimen Benachrichtigungseinstellungen; die zugehörigen Geheimnisse waren bereits Bestandteil der gesicherten Sicherheitsdatenbank.
- Beim Einspielen eines älteren Backups ohne Benachrichtigungskonfiguration wird eine neuere lokale Konfiguration entfernt, damit keine veralteten Kanäle mit einer zurückgesetzten Sicherheitsdatenbank aktiv bleiben.
- README, Installationsanleitung sowie die integrierte deutsche und englische Hilfe beschreiben Einrichtung, Test, Ereignisauswahl, Sicherheit und Fehlerverhalten.
- Die vollständige Testsuite umfasst 388 bestandene Tests.

## v1.0.44

### Gerätestatus und Backup-Job-Status konsistent gekoppelt

- Beim Deaktivieren eines verbundenen Geräts werden jetzt alle zugehörigen aktiven Backup-Jobs innerhalb derselben Datenbanktransaktion automatisch deaktiviert.
- Die Kaskade gilt sowohl für den direkten **Deaktivieren**-Button in der Geräteliste als auch für das Speichern eines Geräts mit deaktiviertem Aktivstatus im Bearbeitungsformular.
- Laufende oder wartende Ausführungen blockieren die Deaktivierung weiterhin, sodass kein aktiver Borg- oder SSH-Prozess durch eine Statusänderung unterbrochen wird.
- Beim erneuten Aktivieren des Geräts bleiben seine Backup-Jobs bewusst deaktiviert. Dadurch starten Zeitpläne nach einer Wartung oder Störung nicht unbeabsichtigt wieder; die gewünschten Jobs müssen gezielt aktiviert werden.
- Bestätigungsdialog und Statusmeldung nennen die automatisch mitdeaktivierten Backup-Jobs.

### Dokumentation und Tests

- README, Installationsanleitung sowie die integrierte deutsche und englische Hilfe beschreiben die neue Kaskadenlogik und das bewusste Nicht-Wiederaktivieren der Jobs.
- Regressionstests prüfen den direkten Gerätebutton, das Geräte-Bearbeitungsformular, den Schutz bei aktiven Läufen und den Zustand nach erneuter Geräteaktivierung.

## v1.0.43

### Manager-Backups über die WebUI hochladen

- Im Bereich **Manager-Backup** steht ein eigener Upload für vorhandene verschlüsselte `.bbm`-Dateien und historische `.zip`-Manager-Backups bereit.
- Der Upload verwendet einen rohen, streamingbasierten Dateitransfer ohne zusätzliche Multipart-Abhängigkeit. Dateiname und Dateigröße werden vor beziehungsweise während der Übertragung begrenzt.
- Der Manager prüft das Backupformat vor der Übernahme. Historische ZIP-Dateien durchlaufen die vollständigen Pfad-, Eintrags-, Größen- und Kompressionskontrollen; verschlüsselte Backups werden auf gültigen BBM-Header, unterstützte AES-256-GCM-/scrypt-Parameter und vollständige Nutzdaten geprüft.
- Hochgeladene Backups werden atomar mit Modus `0600` gespeichert. Eine vorhandene Datei gleichen Namens wird niemals überschrieben.
- Die Passphrase eines verschlüsselten Backups ist beim Upload nicht erforderlich; die vollständige kryptografische Authentifizierung erfolgt weiterhin unmittelbar vor der Wiederherstellung.

### Geräte und Backup-Jobs direkt aktivieren oder deaktivieren

- Die Tabelle **Verbundene Geräte** besitzt unter Aktionen einen direkten Schalter **Aktivieren/Deaktivieren**.
- Backup-Jobs erhalten denselben Schalter unter **Mehr → Verwalten**.
- Laufende oder wartende Ausführungen blockieren das Deaktivieren, damit kein aktiver SSH- oder Borg-Prozess durch eine Konfigurationsänderung unterbrochen wird.
- Deaktivierte Geräte behalten ihre Konfiguration, werden aber aus aktiven Zeitplänen und verwalteten Repository-Zugängen entfernt. Ihre Jobs lassen sich auch manuell nicht starten.
- Deaktivierte Jobs behalten Quellen, Optionen, Aufbewahrung und Zeitplanzuordnungen, werden jedoch weder manuell noch geplant gestartet. Beim erneuten Aktivieren wird die Scheduler-Konfiguration automatisch synchronisiert.

### Anleitung und Tests

- README, Installationsanleitung sowie das integrierte deutsche und englische Betriebshandbuch wurden gegen den aktuellen Funktionsstand geprüft und um Upload, Aktivstatus, Scheduler-Verhalten, Sicherheitsgrenzen und Wiederherstellungsablauf ergänzt.
- Neue Regressionstests prüfen Uploadvalidierung, Schutz vor Überschreiben, direkte Aktivstatus-Endpunkte, Sperren bei aktiven Läufen und die CSP-konforme Einbindung der neuen Schaltflächen.
- Die vollständige Testsuite umfasst 379 bestandene Tests.

## v1.0.42

### Portablen Start von Remote-Backup-Jobs wiederhergestellt

- Der überwachte Remote-Wrapper verwendete zum Zurücksetzen geerbter Signalzustände die GNU-Coreutils-Erweiterung `env --default-signal`. Auf Geräten mit BusyBox, älteren Coreutils-Versionen oder einer abweichenden `env`-Implementierung brach der Backup-Job deshalb bereits vor dem Borg-Start mit `env: unrecognized option '--default-signal=HUP'` ab.
- Der Wrapper ist nicht mehr von dieser nicht portablen `env`-Option abhängig. Wenn Python 3 vorhanden ist, setzt ein kleiner Starthelfer `HUP`, `INT` und `TERM` auf Standardverhalten zurück, hebt mögliche Signalblockierungen auf und startet Borg anschließend per `exec`.
- Ist `setsid` vorhanden, läuft Borg weiterhin in einer eigenen Prozesssitzung, sodass der Manager beim Abbruch die vollständige Prozessgruppe kontrolliert beendet.
- Minimale Geräte mit einem eigenständigen Borg-Binary, aber ohne Python 3, bleiben ebenfalls nutzbar: Der Job startet direkt und verwendet bei einem Abbruch `SIGTERM` als portables erstes Beendigungssignal. Es gibt keinen Rückfall auf die fehlerhafte GNU-`env`-Option.

### Tests

- Ein Regressionstest stellt eine absichtlich inkompatible `env`-Implementierung bereit, die jede `--default-signal`-Option ablehnt. Der Remote-Backup-Befehl startet trotzdem erfolgreich.
- Der vorhandene kontrollierte Remote-Abbruchtest bestätigt weiterhin die Signalzustellung und das bestätigte Prozessende vor der Freigabe der Warteschlange.
- Die vollständige Testsuite umfasst 373 bestandene Tests.

## v1.0.41

### Managerseitige Repository-Aktionen unter dem unprivilegierten Webprozess korrigiert

- Die Web-API läuft seit der Sicherheitshärtung als Benutzer `borg`. Managerseitige Borg-Aufrufe verwendeten dennoch weiterhin `runuser -u borg`; `runuser` darf jedoch nur von Root gestartet werden und brach deshalb mit `runuser: may not be used by non-root users` ab.
- Repository-Verbindungsprüfung, Archivlisten, Archivinformationen, Compact, Check, Löschaktionen, Größenabfragen und weitere direkt im Manager ausgeführte Borg-Befehle starten jetzt direkt, wenn der Prozess bereits unprivilegiert läuft. Nur ein tatsächlicher Root-Aufrufer verwendet weiterhin `runuser`.
- Dadurch erreicht die Repository-Prüfung wieder Borg selbst. Die Archivaktualisierung erhält wieder die erwartete JSON-Ausgabe statt der vorangestellten `runuser`-Fehlermeldung.

### Systemdiagnose an den Root-/Borg-Betrieb angepasst

- Repository-R/W/X, Logverzeichnis, Borg-Serve-Wrapper und `authorized_keys` werden mit den tatsächlichen Rechten der Web-API geprüft, ohne einen unzulässigen zweiten Benutzerwechsel.
- `sshd -t` bleibt eine Root-Prüfung. Der Entrypoint führt sie vor dem Start aus und stellt das erfolgreiche Ergebnis anschließend über eine rootgeschützte, für die Web-API lesbare Laufzeitmarkierung bereit.
- Die Diagnose meldet dadurch keine falschen Fehler mehr allein aufgrund von `runuser` oder fehlendem Zugriff des Webprozesses auf den Root-eigenen SSH-Hostschlüssel.

### Tests

- Regressionstests prüfen Root- und Nicht-Root-Befehlsbildung, managerseitige Repository-Kommandos ohne `runuser` im Webprozess sowie die Übergabe der Root-sshd-Prüfung an die unprivilegierte Diagnose.
- Die vollständige Testsuite umfasst 370 bestandene Tests.

## v1.0.40

### CSP-konforme Bedienung der WebUI wiederhergestellt

- Die strenge Content-Security-Policy aus dem Sicherheitsupdate bleibt unverändert aktiv und erhält weiterhin kein `unsafe-inline` für JavaScript.
- Sämtliche dynamisch erzeugten HTML-Handler wie `onclick=...` wurden entfernt. Benutzerbearbeitung, Job-Schaltfläche **Mehr**, Dashboard-Kacheln, Ausführungsdetails, Repository-Aktionen, Geräte-, Zeitplan- und Archivnavigation verwenden jetzt eine zentrale Event-Delegation.
- Jede dynamische Aktion muss in einer festen Funktionsliste registriert sein. Parameter werden als HTML-escaptes JSON in `data-bbm-*`-Attributen transportiert und ohne `eval` oder dynamische Codeausführung verarbeitet.
- Fehler in einer einzelnen Oberflächenaktion werden protokolliert und als Meldung angezeigt, ohne die gesamte Ereignisbehandlung der Seite zu stoppen.

### Borg-JSON-Ausgaben robuster verarbeitet

- Borg-Informations- und Archivlisten werden weiterhin bevorzugt als exaktes JSON ausgewertet.
- Falls Borg, OpenSSH, `runuser` oder der überwachte Prozess-Wrapper harmlose Informationszeilen vor oder nach dem JSON ausgibt, wird nun gezielt ein vollständiges Borg-JSON-Dokument mit erwarteten Top-Level-Feldern extrahiert.
- Für Archivabfragen werden `stdout` und `stderr` gemeinsam berücksichtigt. Ausgaben ohne ein gültiges Borg-Dokument werden weiterhin mit einem Fehler abgewiesen.
- Dadurch wird die Meldung „Borg-Informationsausgabe ist kein gültiges JSON“ nicht mehr allein durch zusätzliche Wrapper- oder SSH-Ausgaben ausgelöst.

### Tests

- Regressionstests verbieten dynamische Inline-Eventhandler, gleichen alle verwendeten Oberflächenaktionen mit der festen Funktionsliste ab und prüfen die weiterhin strenge CSP.
- Zusätzliche Tests prüfen Borg-JSON mit vorangestellten und nachgestellten Informationszeilen sowie die unveränderte Ablehnung echter Nicht-JSON-Ausgaben.
- Die vollständige Testsuite umfasst 367 bestandene Tests.

## v1.0.39

### Containerstart nach der Sicherheitsumstellung korrigiert

- Der Root-Entrypoint materialisiert TLS- und Repository-SSH-Schlüssel weiterhin vor dem Privilegwechsel unter `/run/bbm-secrets`.
- Die anschließend als Benutzer `borg` gestartete Web-API führt diese Root-Operation nicht mehr ein zweites Mal aus. Damit entfällt der Startabbruch `PermissionError: Operation not permitted: /run/bbm-secrets`.
- Die Materialisierungsroutine ist zusätzlich idempotent: unveränderte Root-eigene private Laufzeitdateien werden von einem unprivilegierten Folgeprozess weder überschrieben noch umberechtigt.
- Direkte Entwicklungs- und Teststarts ohne Entrypoint führen die Sicherheitsinitialisierung weiterhin selbstständig aus.

### Tests

- Regressionstests prüfen den Root-/Nicht-Root-Übergang, die Startmarkierung des Entrypoints und den Erhalt des Root-eigenen SSH-Hostschlüssels. Die vollständige Testsuite umfasst 363 bestandene Tests.

## v1.0.38

### Sicherheitsupdate

- FastAPI wurde auf 0.139.2 aktualisiert; die vollständig gesperrte Laufzeitauflösung verwendet Starlette 1.3.1 und beseitigt die unauthentifizierte Range-Header-DoS-Schwachstelle der bisherigen Version.
- Der Login besitzt jetzt persistente Quell- und Quell/Benutzer-Limits vor der rechenintensiven Scrypt-Prüfung. Fehlversuche sperren kein Benutzerkonto mehr global; Sicherheitsereignisse werden zeitlich und mengenmäßig begrenzt.
- Browseränderungen benötigen einen anwendungsinternen Anti-CSRF-Header und bei vorhandenem `Origin` einen exakten Origin-Abgleich. Cookies sind standardmäßig `Secure`, `HttpOnly` und `SameSite=Strict`; Sitzungen erhalten zusätzlich einen Inaktivitätsablauf.
- `Forwarded`- und `X-Forwarded-*`-Header werden nur von Netzen aus `BBM_TRUSTED_PROXY_CIDRS` akzeptiert. Uvicorn startet mit `--no-proxy-headers`.
- Neue Manager-Backups müssen verschlüsselt sein und mindestens zwölf Zeichen lange Passphrasen verwenden. Vor einem WebUI-Restore wird ein gesondert verschlüsseltes Sicherheitsbackup erzeugt. Alte ZIP-Backups bleiben wiederherstellbar.
- Die Restore-Prüfung blockiert Pfadausbruch auch in `permissions.json`, symbolische Links, doppelte Pfade, übergroße Pakete, zu viele Einträge und unzulässige Kompressionsverhältnisse.
- Prozesssteuernde Umgebungsvariablen wie `PATH`, `HOME`, `LD_PRELOAD`, `PYTHONPATH`, `BASH_ENV` oder SSH-Agent-Variablen können nicht mehr als Repository-Zusatzumgebung gesetzt werden.
- Die Web-API läuft im Container als Benutzer `borg`; SSH-Hostschlüssel bleiben Root-eigen. OpenSSH verwendet `StrictModes yes`, Compose aktiviert `no-new-privileges`, und das offizielle Multi-Platform-Image Python 3.13.14-slim-trixie ist per Digest fixiert. Laufzeitpakete und ihre amd64-/arm64-Wheels sind per SHA-256 gesperrt und werden mit `--require-hashes` installiert.
- Die öffentliche Readiness-Antwort enthält nur noch `status`; detaillierte Informationen bleiben authentifizierten Diagnose-Endpunkten vorbehalten.
- Die normale Rolle `user` ist jetzt eine reine Beobachterrolle für Dashboard, Listen und zusammengefasste Laufstatus. Vollständige Logs, Archive, Restore/Export/Mount, manuelle Ausführungen und sämtliche Konfigurationsänderungen erfordern einen Administrator.
- Der Updater liest Release-Inhalte erst nach erfolgreichem SHA-256-Abgleich. Explizite Updates benötigen `--sha256`, `BBM_UPDATE_SHA256` oder eine gleichnamige `.sha256`-Datei; automatische Erkennung berücksichtigt nur ZIPs mit gültiger Sidecar-Prüfsumme.

### Kompatibilität und Tests

- Bestehende Repositorys, Jobs, Zeitpläne, Geräte, Benutzer und alte Manager-Backups werden übernommen. Fehlende neue `.env`-Werte ergänzt `update.sh` automatisch.
- Separate Sicherheitstests reproduzieren Anti-CSRF-/Origin-Schutz, Rate-Limit, Inaktivitätsablauf, Restore-Pfadausbruch, Archivgrenzen, Backup-Verschlüsselung, Umgebungsvariablen-Blockliste und Containerhärtung.

## v1.0.37

### Repository-ID direkt in der Übersicht

- Die Repository-Tabelle zeigt jetzt die numerische Manager-ID jedes Repository-Eintrags in einer eigenen Spalte direkt neben dem Status. Die Kennung entspricht der ID in BBM-Cachepfaden wie `/data/borg-cache/repository-<ID>` und `$HOME/.cache/borgbackup-manager/repository-<ID>`.
- Die Statusspalte wurde auf breiten Ansichten verkleinert. Die neue ID-Spalte ist bewusst kompakt und zeigt den Wert als `#<ID>`.
- Die Innenabstände zwischen Größen- und Aktionsspalte wurden reduziert, damit die zusätzliche Information ohne unnötige Tabellenbreite Platz findet.
- In der responsiven Kartenansicht bleibt die ID als eigene beschriftete Zeile sichtbar.

### Tests

- Regressionstests prüfen die neue Spaltenreihenfolge, die ID-Ausgabe, die Desktop-Spaltenbreiten, die engeren Abstände und die englische Bezeichnung.

## v1.0.36

### HTTP-504 bei der Prüfung externer Repositorys behoben

- **Verbindung prüfen** wird nicht mehr innerhalb eines lang laufenden HTTP-Aufrufs ausgeführt. Die Prüfung wird als reguläre Repository-Ausführung eingereiht, liefert sofort eine Lauf-ID zurück und kann im Live-Log verfolgt werden. Reverse-Proxys können den Borg-Aufruf dadurch nicht mehr mit HTTP 504 abschneiden.
- Im überwachten Remote-Wrapper aus Version 1.0.35 konnte der separate `cat`-Prozess des Steuerkanals nach einem erfolgreich beendeten Borg-Aufruf weiterlaufen. Er hielt die SSH- und HTTP-Pipes offen, obwohl Borg bereits beendet war. Der Watchdog verwendet jetzt ausschließlich eine Shell-`read`-Schleife, die zusammen mit dem Wrapper zuverlässig endet.
- Repository-Prüfungen verwenden dieselbe repositoryweite Warteschlange und dieselben globalen Parallelitätsgrenzen wie andere Manager-Aktionen.

### Borg-Caches je Repository isoliert

- Managerseitige Borg-Aufrufe verwenden jetzt einen eigenen Cache pro Repository-Eintrag unter `/data/borg-cache/repository-<ID>` statt eines gemeinsam genutzten Cache-Wurzelverzeichnisses.
- Borg-Aufrufe auf einem Quellgerät verwenden einen BBM-eigenen Cache unter `$HOME/.cache/borgbackup-manager/repository-<ID>`. Bei einem SSH-Benutzer `root` ist `$HOME` gleich `/root`; der bisher sichtbare Pfad `/root/.cache/borg/<Repository-ID>/lock.exclusive` war daher ein lokaler Client-Cache und kein Repository-Lock.
- Manuell ausgeführte Borg-Befehle und ältere BBM-Versionen im allgemeinen `$HOME/.cache/borg` können neue Manager-Läufe nicht mehr durch einen dort verbliebenen Cache-Lock blockieren.
- Nach dem bestätigten Ende des Borg-Prozesses entfernt der Remote-Wrapper ausschließlich verbliebene Lockdateien aus seinem privaten BBM-Cache. Repository-Locks und der allgemeine Borg-Cache des Benutzers werden nicht verändert.

### Cache-Löschung und Diagnose gehärtet

- **Cache löschen** entfernt den repositorybezogenen Manager-Cache direkt aus dem Dateisystem. Die Bereinigung muss Borg nicht mehr starten und kann deshalb auch einen Cache reparieren, dessen eigener `lock.exclusive` den Borg-Aufruf verhindern würde.
- Bei verwalteten Repositorys werden zusätzlich bekannte Alt-Caches aus früheren Versionen entfernt. Externe Alt-Caches bleiben unbenutzt und können keine neuen Prüfungen oder Jobs mehr blockieren.
- Die Laufdiagnose unterscheidet nun einen lokalen Cache-Lock auf dem Quellgerät von einer echten Repository-Sperre. Bei `/root/.cache/...` erklärt sie ausdrücklich, dass `/root` das Home-Verzeichnis des per SSH verwendeten Benutzers ist und dass dafür kein `borg break-lock` ausgeführt werden darf.

### Tests

- Regressionstests decken den zuvor verwaisten Watchdog-Prozess, asynchron eingereihte Verbindungstests, getrennte Manager- und Geräte-Caches, direkte Cache-Bereinigung sowie die eindeutige Cache-Lock-Diagnose ab.
- Die vollständige Testsuite umfasst 345 bestandene Tests.

## v1.0.35

### Externe Repository-Sperren beim Jobabbruch zuverlässig freigeben

- Backup-Aufrufe mit temporären Repository-Geheimnissen verwenden jetzt einen überwachten Abbruchkanal zwischen Manager und Gerät. Der Kanal bleibt nach der einmaligen Geheimnisübergabe geöffnet und dient ausschließlich der kontrollierten Prozessbeendigung.
- Beim Abbruch wird nicht mehr zuerst nur der lokale SSH-Client beendet. Stattdessen erkennt der Remote-Wrapper das Schließen des Steuerkanals, signalisiert die vollständige Borg-Prozessgruppe auf dem Gerät mit `SIGINT` und wartet auf deren tatsächliches Ende.
- Borg erhält dadurch auch bei externen SSH-Repositorys Gelegenheit, Checkpoint, Cache und Repository-Lock sauber zu schließen, bevor die Manager-Verbindung und der repositoryweite Queue-Platz freigegeben werden.
- Nicht interaktive Shells können `SIGINT` für Hintergrundprozesse als ignoriert vererben. Der Wrapper setzt deshalb `HUP`, `INT` und `TERM` vor dem Borg-Start explizit auf die Standardbehandlung zurück und führt Borg in einer eigenen Sitzung aus.
- Reagiert Borg nicht innerhalb des kontrollierten Zeitfensters, bleibt die vorhandene Eskalation über `SIGTERM` und `SIGKILL` als Rückfall erhalten. Das Laufprotokoll unterscheidet zwischen bestätigter Remote-Bereinigung und erzwungener Beendigung.
- Ein automatisches `borg break-lock` wird weiterhin bewusst nicht ausgeführt, da ein externes Repository außerhalb des Managers von einem weiteren legitimen Client verwendet werden könnte.

### Tests

- Ein neuer Regressionstest hält den Steuerkanal offen, bricht den Lauf anschließend ab und prüft, dass der überwachte Remote-Wrapper die gekapselte Prozessgruppe tatsächlich per `SIGINT` beendet.
- Die vollständige Testsuite umfasst 341 bestandene Tests.

## v1.0.34

### Globale und zeitplanbezogene Parallelitätsgrenzen

- Unter **Einstellungen → Parallelitätsgrenzen** kann eine globale Obergrenze von 1 bis 64 gleichzeitig laufenden Manager-Ausführungen festgelegt werden. Der Wert `0` lässt unterschiedliche Repositorys wie bisher unbegrenzt parallel arbeiten.
- Jeder zentrale Zeitplan besitzt zusätzlich eine optionale eigene Obergrenze. `0` übernimmt ausschließlich die globale Grenze; ein Zeitplanwert von `1` reiht beispielsweise Sicherungen mehrerer Geräte und unterschiedlicher Repositorys nacheinander ein.
- Repositorys bleiben unabhängig davon hart serialisiert: Für dasselbe tatsächliche Repository-Ziel läuft weiterhin niemals mehr als eine Borg-Aktion gleichzeitig.
- Globale, zeitplanbezogene und repositorybezogene Grenzen werden gemeinsam ausgewertet. Der jeweils engste zutreffende Grenzwert bestimmt den Start.
- Die Warteschlange belegt freie globale Plätze mit startfähigen Läufen und überspringt ältere Einträge, die selbst noch an einem belegten Repository oder Zeitplan warten. Dadurch bleiben unabhängige Kapazitäten nicht unnötig ungenutzt.
- Ausführungsprotokolle nennen eindeutig, ob auf das Repository, die Zeitplangrenze oder die globale Parallelitätsgrenze gewartet wird.

### Warteschlange gegen verwaiste Laufzustände abgesichert

- Nur tatsächlich lebende Manager-Tasks belegen Parallelitätsplätze. Verwaiste `queued`- oder `running`-Datensätze können die globale Warteschlange nach einem abgebrochenen Task nicht dauerhaft blockieren.
- Die Registrierung wird für jeden Ausführungspfad einschließlich früher Rückgabe und Abbruch zuverlässig bereinigt.
- Bereits beendete Tasks und ungültige Task-Platzhalter werden beim Erstellen des Ausführungsplans entfernt.

### Persistente Sortierung zentraler Listen

- Der Backup-Job-Block im Dashboard, die vollständige Backup-Job-Liste, Repositories und verbundene Geräte besitzen eigene Sortierauswahlen.
- Unterstützt werden je nach Liste unter anderem Name, Status, Gerät, Repository, letzter Lauf, Größe, Typ, Jobanzahl, Adresse und Borg-Version.
- Die Auswahl wird pro angemeldetem Benutzer und Browser gespeichert und beim nächsten Öffnen automatisch wiederhergestellt.

### Datenbank, Konfiguration und Tests

- Bestehende Installationen erhalten automatisch die neuen additiven Felder für Zeitplangrenze und Lauf-Snapshots.
- `BBM_MAX_PARALLEL_RUNS` kann den Standardwert der globalen Grenze vorgeben; die WebUI-Einstellung wird anschließend persistent gespeichert.
- Regressionstests decken globale Serialisierung über unterschiedliche Repositorys, Zeitplanlimits, freie Kapazitäten trotz blockierter älterer Läufe, verwaiste Zustände, Migration und Sortieroberfläche ab.

## v1.0.33

### Repository-Warteschlange gegen Borg-Lock-Konflikte gehärtet

- Repository-Aktionen erhalten vor dem Prozessstart zusätzlich zur lokalen `asyncio`-Sperre eine datenbankgestützte FIFO-Zulassung. Ein Lauf bleibt dadurch so lange **Wartend**, bis alle älteren Aktionen desselben Repository-Ziels abgeschlossen sind.
- Die Warteschlange verwendet nicht mehr nur die Repository-Datenbank-ID, sondern das tatsächliche verwaltete Verzeichnis beziehungsweise die externe Repository-URL. Auch alte doppelte Einträge, die dasselbe physische Ziel adressieren, werden dadurch gemeinsam serialisiert.
- Die FIFO-Prüfung wird nach Übernahme der lokalen Sperre erneut ausgeführt und schützt damit auch bei unterschiedlichen Event-Loops oder mehreren Anwendungskontexten vor einem gleichzeitigen Start.
- Das vollständige Laufprotokoll nennt die blockierende Ausführung, zum Beispiel `WARTESCHLANGE: Warte auf Repository-Ausführung #123`.

### Standortbestätigung sicher einreihen

- **Geänderten Repository-Standort bestätigen** verwendet jetzt wie reguläre Borg-Aktionen `--lock-wait 600` statt des abweichenden 30-Sekunden-Limits.
- Mehrere Bestätigungen für dasselbe Gerät und dasselbe Repository werden zusammengeführt. Wird die Aktion über einen weiteren Job desselben Geräts gestartet, verweist die WebUI auf den bereits wartenden oder laufenden Lauf, statt einen doppelten Borg-Prozess anzulegen.
- Bestätigungen für unterschiedliche Geräte bleiben eigenständige Läufe, werden am gemeinsamen Repository aber strikt nacheinander ausgeführt.
- Falls Borg selbst nach 600 Sekunden keine Sperre erhält, unterscheidet die Diagnose nun ausdrücklich zwischen einer funktionierenden Manager-Warteschlange und einem externen beziehungsweise verwaisten Borg-Lock. Ein automatisches `break-lock` wird weiterhin nicht ausgeführt.

### Regressionstests

- Die Tests decken FIFO-Serialisierung ohne gemeinsam genutzte In-Memory-Sperre, zwei Datenbankeinträge mit demselben physischen Repository-Ziel und die Zusammenführung mehrfach gestarteter Standortbestätigungen ab.

## v1.0.32

### Gelöschtes verwaltetes Repository sicher zurücksetzen

- Der Manager prüft bei verwalteten Repositorys jetzt zusätzlich den realen Borg-Zustand im Zielverzeichnis. Ein früher gespeichertes `initialized=true` kann eine fehlende Borg-`config` nicht mehr als betriebsbereites Repository darstellen.
- Betroffene Einträge werden als **Repository fehlt** gekennzeichnet und erhalten die neue Administratoraktion **Zurücksetzen**.
- Die Rücksetzung ist ausschließlich für verwaltete Repositorys zulässig, deren Ziel ein direktes Verzeichnis unter dem Repository-Basispfad ist, keine Borg-`config` enthält und vollständig leer ist.
- Die Funktion löscht keine Repository-Dateien. Vorhandene Dateien, Teilreste, symbolische Links, aktive Archiv-Mounts sowie laufende oder wartende Repository-Aktionen führen zu einem sicheren Abbruch.
- Zurückgesetzt werden Initialisierungs-, Prüf- und Größenmetadaten sowie der persistente Archivcache. Jobs, Zeitpläne, Gerätezuordnungen, Passphrase und Repository-Eintrag bleiben erhalten.
- Bei Keyfile-Verschlüsselung wird der zur gelöschten Repository-ID gehörende Keyfile entfernt; die anschließende Neuinitialisierung erzeugt und speichert einen neuen Schlüssel.
- Jede erfolgreiche Rücksetzung wird als eigene Ausführung `repository-reset` protokolliert und weist ausdrücklich aus, dass keine Dateien gelöscht wurden.

### Aktionen bei fehlender Repository-Struktur sperren

- Backup-, Prune-, Compact-, Archiv-, Größen- und Cache-Aktionen werden nicht mehr allein aufgrund des Datenbankstatus freigegeben.
- Repository-Liste und Backup-Jobs berücksichtigen die tatsächlich vorhandene Borg-Konfiguration und zeigen einen eindeutigen Hinweis, bis das Repository zurückgesetzt und neu initialisiert wurde.
- Der Initialisierungs-Endpunkt meldet bei einem veralteten Managerstatus gezielt die erforderliche Rücksetzung statt widersprüchlich „bereits initialisiert“.

## v1.0.31

### Warnungsursachen vor der Logkürzung dauerhaft speichern

- Borg-Warnungen werden jetzt bereits während des laufenden Prozesses zeilenweise aus `stdout` und `stderr` erfasst.
- Geteilte Prozess-Chunks werden korrekt zusammengesetzt; Warnzeilen bleiben erhalten, auch wenn danach sehr große Dateilisten oder Statistikausgaben folgen.
- Die strukturierte Warnungszusammenfassung wird als eigenes Feld am Lauf gespeichert und ist dadurch unabhängig von SQLite-Vorschauen, dem 256-KiB-Diagnosepuffer und der gekürzten Live-Log-Ansicht.
- Die WebUI kann erkannte Ursachen bereits während eines laufenden Backups anzeigen.
- Vorhandene Läufe ohne gespeicherte Zusammenfassung verwenden weiterhin die nachträgliche Loganalyse.

### Ehrlicher Fallback bei Borg RC 1 ohne Detailzeile

- Liefert Borg tatsächlich nur `terminating with warning status, rc 1`, zeigt die WebUI nicht länger eine scheinbar konkrete Diagnose.
- Der Lauf wird stattdessen ausdrücklich als „Ursache nicht ausgegeben“ gekennzeichnet und erhält eine passende Handlungsempfehlung.
- Zusätzliche Formate wie `Remote: C <Pfad>` sowie nie passende Include-/Exclude-Muster werden erkannt.

### Datenbank und Tests

- Bestehende Installationen erhalten beim Start automatisch die additive Spalte `runs.warning_summary_json`.
- Regressionstests simulieren eine früh auftretende, in zwei Chunks geteilte Warnung mit mehr als 300 KiB nachfolgender Ausgabe.
- API-, Migrations-, Parser- und UI-Fallbacktests wurden ergänzt.

## v1.0.30

### Repositoryweite Archivlöschung

- Archive werden vor einer Löschung zuerst über aktuelle oder historische Archivserien dem richtigen Job und Gerät zugeordnet.
- Für Legacy- und fremde Archive werden zusätzlich Borg-Hostname und der aus dem Archivnamen erkennbare Gerätename abgeglichen.
- Die Archivübersicht unterstützt Einzel- und Mehrfachauswahl einschließlich „Sichtbare Archive auswählen“ für den aktuellen Filter.
- Alle ausgewählten Archive werden mit einer gemeinsamen Sicherheitsbestätigung und einer repositoryweiten Ausführung verarbeitet.
- Enthält die Auswahl Archive verschiedener Geräte, zeigen Bestätigung, Rückmeldung und Ausführungsprotokoll eindeutig „Mehrere Geräte“.
- Der bisherige unsichere Fallback auf den ersten Job eines Repositorys wurde entfernt. Löschen benötigt keinen Backup-Job mehr; Restore und Umbenennen bleiben an eine eindeutige Job-/Gerätezuordnung gebunden.
- Vor dem Start werden alle exakten Archivnamen direkt im Repository geprüft. Gemountete ausgewählte Archive sowie laufende oder wartende Repository-Aktionen blockieren den Vorgang.
- Optional wird nach der gesamten Löschserie genau einmal Compact ausgeführt.

### Compact direkt am Repository

- Administratoren können Compact in der Repository-Liste starten, auch wenn kein Backup-Job vorhanden ist.
- Die Aktion verwendet den managerlokalen Repository-Zugang, die repositoryweite Sperre und ein reguläres Ausführungsprotokoll.
- Aktive Archiv-Mounts sowie laufende oder wartende Vorgänge desselben Repositorys verhindern einen parallelen Start.

### Cache, Protokollierung und Integration

- Nach einer begonnenen Archivlöschung wird der Archivcache auch bei Abbruch oder Fehler verworfen, da eine Mehrfachaktion bereits teilweise erfolgreich gewesen sein kann.
- Repositoryweite Aktionen speichern Repository beziehungsweise Gerät im Laufkopf; gemischte Löschungen werden als „Mehrere Geräte“ geführt.
- Deutsche und englische Oberfläche, Betriebshandbuch, README und Installationsanleitung wurden ergänzt.
- Regressionstests decken Eingabevalidierung, exakte Borg-Befehle, einmaliges Compact, Parallelitätssperren, Gerätezuordnung, Mehrfachauswahl und neue API-/UI-Pfade ab.

## v1.0.29

### Konkrete Ursachen bei Borg-Warnungen

- Backup-Läufe mit Borg-Rückgabecode `1` zeigen nicht mehr nur `terminating with warning status, rc 1`.
- Der Manager wertet Borg-Statuszeilen und Warnmeldungen strukturiert aus.
- Status `C` wird als „Datei während der Sicherung verändert“ mit dem betroffenen Pfad dargestellt.
- Status `E` sowie fehlende Dateien, Berechtigungs- und E/A-Fehler werden getrennt ausgewiesen.
- Der Laufdialog enthält einen kompakten, separat scrollbar begrenzten Bereich „Warnungsursachen“.
- Die Ausführungsliste zeigt eine verständliche Zusammenfassung, etwa „1 Datei wurde während der Sicherung verändert“.

### Warnungsrelevantes Protokoll ohne vollständige Dateiliste

- Ist „Verarbeitete Dateien im Live-Protokoll anzeigen“ deaktiviert, verwendet der Backup-Befehl intern `--list --filter CE`.
- Dadurch werden nur warnungsrelevante Datei-Status protokolliert, ohne das Log mit allen unveränderten Dateien zu füllen.
- Die gefilterte Fehler-/Warnungsvorschau in SQLite wurde von 8 KiB auf 32 KiB erweitert, damit auch mehrere betroffene Pfade erhalten bleiben.
- Vollständige Live-Logs bleiben unverändert unter `/data/run-logs` gespeichert.

### Tests und Dokumentation

- Regressionstests für veränderte, nicht lesbare, verschwundene und zugriffsverweigerte Dateien ergänzt.
- Deutsche und englische Anleitung sowie technische Dokumentation aktualisiert.

## v1.0.28

- Behebt ein Einfrieren der gesamten WebUI nach dem Update auf die erste zweisprachige Oberfläche.
- Die Übersetzungslogik schreibt Text- und Attributwerte nur noch, wenn sich der Zielwert tatsächlich unterscheidet.
- Verhindert eine selbst ausgelöste Endlosschleife des `MutationObserver`, durch die Anmeldung und Navigation nicht mehr reagierten.
- Ergänzt einen Regressionstest für mutationsstabile Übersetzungen.

## v1.0.27

### Update-Build von 1.0.25 auf 1.0.26 korrigiert

- Der Fehler beim Docker-Build mit `RELEASE_NOTES.en.md: not found` ist behoben.
- Ursache war die Übergangskombination aus dem noch laufenden Updater der Version 1.0.25 und dem Dockerfile der Version 1.0.26: Der alte Updater kopierte die neu eingeführte Top-Level-Datei nicht, während der neue Dockerfile sie bereits zwingend erwartete.
- Der Docker-Build verwendet die englischen Release Notes jetzt aus `app/RELEASE_NOTES.en.md`, weil das komplette `app`-Verzeichnis bereits von älteren Updatern zuverlässig übernommen wird.
- Die Top-Level-Datei `RELEASE_NOTES.en.md` bleibt im Release enthalten und wird von aktuellen Updatern für Dokumentations- und Paketvollständigkeit übernommen, ist aber keine harte Build-Voraussetzung mehr.
- Ein Regressionstest simuliert ausdrücklich die Datei-Whitelist des Updaters 1.0.25 und prüft, dass der daraus entstehende Docker-Build-Kontext vollständig ist.

### Update und Rollback

- Ein nach dem beschriebenen Fehler automatisch zurückgesetztes Projekt kann direkt mit Version 1.0.27 aktualisiert werden.
- Persistente Managerdaten, Repositories und die bestehende `.env` werden dabei nicht verändert.

### Sperrfreigabe nach dem Stoppen einer Aufgabe

- Der Abbruch beendet jetzt die vollständige Prozessgruppe und nicht mehr nur den direkten Elternprozess.
- Borg erhält zuerst `SIGINT`, damit laufende Operationen kontrolliert beendet und Repository-/Cache-Sperren freigegeben werden.
- Reagiert die Prozessgruppe nicht innerhalb des Sicherheitszeitfensters, eskaliert der Manager auf `SIGTERM` und anschließend `SIGKILL`.
- Die Abbruch-API wartet auf die Prozessbereinigung, bevor sie den Vorgang als abgeschlossen bestätigt.
- Ein automatisches `borg break-lock` wird nicht ausgeführt, weil gemeinsam genutzte Repositories parallel von externen Clients verwendet werden können.
- Neue Regressionstests prüfen Signalweitergabe, Prozessgruppenbeendigung und den bestehenden API-Abbruchpfad.

## v1.0.26

### Statusanzeige öffnet direkt das aktuelle Live-Log

- Die Statusanzeige vor dem Hell-/Dunkel-Schalter öffnet beim Anklicken ohne Zwischenliste unmittelbar das Live-Log des aktuell laufenden Vorgangs.
- Sind mehrere Läufe aktiv, wird ein tatsächlich laufender Vorgang bevorzugt; die Zahl weiterer aktiver Läufe bleibt als Zusatz sichtbar.
- Gibt es noch keinen laufenden, aber bereits wartende Vorgänge, wird der nächste wartende Lauf geöffnet.
- Aktive Läufe werden unabhängig vom Filter der Ausführungsseite geladen und bis zum Endstatus verfolgt.

### Sprache und Darstellung pro Benutzer

- Jeder Administrator und jeder normale Benutzer kann unter **Darstellung & Sprache** unabhängig Deutsch oder Englisch auswählen.
- Das Farbschema **Automatisch**, **Hell** oder **Dunkel** wird ebenfalls am jeweiligen Benutzerkonto gespeichert.
- Änderungen wirken nicht systemweit und beeinflussen keine anderen Benutzerkonten.
- Navigation, Formulare, Dialoge, dynamische Statusmeldungen, das integrierte Betriebshandbuch und die aktuellen Release Notes folgen der persönlichen Spracheinstellung.
- Die Sicherheitsdatenbank wird additiv um `language` und `appearance` je Benutzer erweitert; bestehende Konten erhalten sichere Standardwerte.

### Anleitung und Übersetzungen

- Das integrierte Betriebshandbuch wurde vollständig mit dem aktuellen Funktionsumfang abgeglichen und als getrennte deutsche und englische Fassung strukturiert.
- Beschrieben sind unter anderem Dashboard und direkter Live-Log-Sprung, Geräte, Repository-Zugänge, Cacheverwaltung, Speicherplatz-Sperren, Jobs, Zeitpläne, Archive, Restore, Manager-Backup, Benutzerrechte, persönliche Einstellungen und Systemdiagnose.
- Eine fehlerhafte HTML-Verschachtelung im bisherigen Archiv-Kapitel wurde entfernt.
- Release Notes werden passend zur gewählten Sprache geladen.

### Tests und Kompatibilität

- Regressionstests für direkte Statusnavigation, benutzerbezogene Einstellungen, Datenbankmigration sowie deutsche und englische UI-/Anleitungsressourcen ergänzt.
- Bestehende Repositories, Jobs, Benutzer und globale Systemeinstellungen bleiben unverändert.

## v1.0.25

### Kompaktere Backup-Job-Aktionen

- Die über **Mehr** eingeblendeten Jobaktionen sind als kompakte, gruppierte Aktionsleiste aufgebaut.
- Prüfungen, Repository-Zugang, Speicherpflege und Verwaltung verwenden kleine, umbrechende Schaltflächen statt hoher Vollbreitenbuttons.
- Der Prüfbereich nutzt auf breiten Ansichten zusätzlichen Platz; auf Tablets und Smartphones ordnen sich die Gruppen automatisch zweispaltig beziehungsweise einspaltig an.
- Repository-Zugangsstatus und Kurzbeschreibung bleiben sichtbar, benötigen aber deutlich weniger Höhe.

### Laufende Aufgaben direkt in der Kopfleiste

- Die bisherige Statusposition vor dem Hell-/Dunkel-Schalter zeigt bei aktiven Läufen deren Anzahl sowie die Aufteilung in laufend und wartend.
- Ein Klick öffnet eine kompakte Liste aller aktiven Aufgaben mit Laufnummer, Job beziehungsweise Repository-Verwaltung, Aktion, Startzeit und Status.
- Jeder Eintrag öffnet unmittelbar das zugehörige Live-Log.
- Aktive Läufe werden unabhängig vom gewählten Filter der Ausführungsansicht geladen; manuell gestartete Aktionen werden während ihrer vorhandenen Laufverfolgung sofort aktualisiert.
- Ohne aktive Aufgabe verwendet dieselbe Anzeige weiterhin die bisherigen Bestätigungen wie „Aktualisiert“, „erfolgreich“ oder „fehlgeschlagen“.

### Tests und Kompatibilität

- Regressionstests für aktiven Aufgabenabruf, direkte Live-Log-Verknüpfung und kompakte Jobaktionsgruppen ergänzt.
- Datenbankänderungen sind nicht erforderlich.

## v1.0.24

### Korrektur der Sitzungswiederherstellung beim Seitenreload

- JavaScript-Startabbruch seit Version 1.0.18 behoben.
- Der veraltete Export `bootstrapHost` wurde aus `Object.assign(window, …)` entfernt.
- Die Funktion war mit der Verlagerung der Repository-Zugangseinrichtung in den Backup-Job-Bereich entfernt worden, blieb aber als nicht definierter Bezeichner im globalen Export stehen.
- Dadurch brach `app.js` beim Laden mit `ReferenceError: bootstrapHost is not defined` ab, bevor `restoreBrowserSession()` ausgeführt werden konnte.
- Bestehende Cookie- und Reload-Sitzungen werden nach einem normalen Seitenreload nun wieder ausgewertet.
- Regressionstest ergänzt, der globale Frontend-Exporte gegen vorhandene Funktionsdefinitionen prüft.

## v1.0.23

### Seitenreload unabhängig vom Cookie-Transport abgesichert

- Der HttpOnly-Sitzungscookie bleibt der primäre Authentifizierungsweg.
- Zusätzlich erzeugt der Manager beim Login einen separaten, serverseitig nur als SHA-256-Hash gespeicherten Reload-Schlüssel. Die WebUI speichert ihn ausschließlich im `sessionStorage` des aktuellen Tabs.
- Fehlt der Cookie nach F5/Strg+R, authentifiziert sich derselbe Tab mit `Authorization: BBM-Reload …`. Der Schlüssel ist an die zugehörige Serversitzung und den Browser-User-Agent gebunden und verliert bei Abmeldung, Passwortwechsel, Benutzerdeaktivierung, Sitzungsablauf oder Tab-Schließen seine Wirkung.
- Der zusätzliche Schlüssel wird nicht in `localStorage`, nicht in einem Manager-Backup und nicht im Klartext in der Sicherheitsdatenbank gespeichert.
- Damit bleibt ein Reload auch in Browser-/Proxy-Konstellationen möglich, in denen der Cookie trotz korrekter Attribute nicht dauerhaft zurückgesendet wird.

### Tests und Migration

- Additive Sicherheitstabellen-Migration für tabgebundene Reload-Schlüssel.
- Regressionstests für Reload ohne Cookie, User-Agent-Bindung, Abmeldung und Frontend-Speicherung im `sessionStorage`.
- Bestehende Benutzer und Sitzungen bleiben erhalten; nach dem Update ist einmalig eine neue Anmeldung erforderlich, damit der Tab seinen Reload-Schlüssel erhält.

## v1.0.22

### Neustartschleife beim Update behoben

- Der Container versucht nicht mehr, die als einzelne Datei bind-gemountete Host-`.env` mit `sed -i` atomar zu ersetzen. Docker/Linux verweigerte den dafür erforderlichen `rename()` mit `Device or resource busy`, wodurch der Container unmittelbar nach jedem Start erneut beendet wurde.
- Der historische Standardwert `BBM_SESSION_COOKIE_NAME=bbm_session` wird weiterhin in `app/config.py` zur Laufzeit als `bbm_session_v2` interpretiert. `install.sh` und `update.sh` übernehmen die dauerhafte Änderung sicher auf dem Host.
- Die Host-`.env` wird für die Cookie-Migration innerhalb des Containers nur noch gelesen, nicht mehr ersetzt. Die bestehende Migration historischer Geheimnisse verwendet weiterhin einen direkten In-Place-Schreibzugriff und keine atomare Umbenennung des Mountpunkts.

### Transparenterer Update-Healthcheck

- Während eines längeren Containerstarts zeigt `update.sh` nach 10, 30 und 60 Sekunden den aktuellen Bereitschaftsfehler, den Compose-Status und die letzten Container-Logs.
- Ein fehlerhafter Containerstart wirkt dadurch nicht mehr wie ein stillstehendes Update; nach Ablauf der bestehenden 90-Sekunden-Frist erfolgt weiterhin der automatische Rollback.

### Tests und Kompatibilität

- Regressionstest stellt sicher, dass `docker/entrypoint.sh` kein `sed -i` mehr auf der bind-gemounteten `.env` ausführt.
- Datenbankänderungen sind nicht erforderlich. Das Update kann auch bei derzeit gestopptem beziehungsweise neu startendem Container ausgeführt werden.

## v1.0.21

### Seitenreload hinter Reverse Proxy korrigiert

- Reverse-Proxy-Angaben zum browserseitigen Protokoll haben jetzt Vorrang vor der internen HTTPS-Verbindung des Containers. Meldet der Proxy außen `http`, setzt der Manager keinen `Secure`-Cookie mehr, auch wenn der Proxy intern per HTTPS zum Container verbindet.
- Unterstützt werden `Forwarded: proto=…`, `X-Forwarded-Proto`, `X-Forwarded-Scheme` und `X-Forwarded-SSL`. Ohne Proxy-Angabe gilt weiterhin das direkte Verbindungsschema.
- Neue Einstellung `BBM_SESSION_COOKIE_SECURE=auto|always|never`; `auto` ist der Standard.
- Der Standard-Cookiename wechselt einmalig von `bbm_session` auf `bbm_session_v2`. Die Anwendung normalisiert den unveränderten alten Standard bereits beim ersten Start; der Container schreibt die Korrektur zusätzlich in die gemountete `.env`. Individuell gesetzte andere Namen bleiben erhalten. Dadurch kollidiert die neue Sitzung nicht mit einem alten, vom Browser geschützten `Secure`-Cookie.
- `SameSite` wird auf `Lax` gesetzt, damit normale Navigationen und Reverse-Proxy-Aufrufe stabil funktionieren, während Cookies bei fremden Unteranfragen weiterhin nicht mitgesendet werden.

### Anmeldung wird unmittelbar verifiziert

- Nach einem erfolgreichen Passwort-Login prüft die WebUI sofort in einer zweiten Anfrage, ob der HttpOnly-Cookie vom Browser gespeichert und zurückgesendet wurde.
- Schlägt diese Prüfung fehl, wird die Anmeldung nicht mehr scheinbar akzeptiert. Stattdessen erscheint direkt eine Erklärung mit Cookiename und Hinweis auf `BBM_SESSION_COOKIE_SECURE`.
- Beim Seitenstart unterscheidet `/api/auth/status` zwischen einem nicht gesendeten Cookie und einer ungültigen beziehungsweise abgelaufenen Sitzung.

### Tests und Kompatibilität

- Regressionstest für außen HTTP / intern HTTPS reproduziert den bisherigen Fehler.
- Gegenrichtung außen HTTPS / intern HTTP sowie direkte HTTP- und HTTPS-Verbindungen werden geprüft.
- `.env.example`, Compose, Installation, Manager-Backup und Restore enthalten die neue Cookie-Einstellung.
- Datenbankänderungen sind nicht erforderlich; nach dem Update ist wegen des neuen Standard-Cookienamens eine einmalige Anmeldung erforderlich.

## v1.0.20

### Weitere Korrektur der Sitzungsbehandlung

- Die WebUI meldet nicht mehr anhand von Textbestandteilen wie `session` oder `token` ab. Solche Wörter können auch in Borg-, SSH-, Proxy- oder Diagnosefehlern vorkommen und hatten trotz gültigem Cookie die lokale Anmeldung verworfen.
- Ein Wechsel zur Anmeldemaske erfolgt ausschließlich bei einem tatsächlichen HTTP-Status `401 Unauthorized`.
- `/api/auth/status` setzt den bereits gültigen Sitzungscookie mit den aktuell erkannten HTTPS-/Reverse-Proxy-Attributen erneut. Dabei wird keine zweite Sitzung erzeugt und der bestehende Token nicht ersetzt.
- Bestehende Behandlung mehrerer gleichnamiger Cookies, `HttpOnly`, `SameSite=Strict`, explizites Ablaufdatum und dynamisches `Secure` bleiben erhalten.

### Sicherere Controller-Schlüssel-Bedienung

- Im Geräteformular sitzt ein kompakter **Kopieren**-Button direkt in der Zeile des angezeigten öffentlichen Schlüssels.
- **Controller-Schlüssel erneuern** wurde vollständig aus dem Geräteformular entfernt.
- Die Erneuerung befindet sich jetzt ausschließlich unter **Einstellungen → Controller-Schlüssel** in einem eigenen Warnbereich.
- Ein direkter Link im Geräteformular führt zum Einstellungsbereich; die bestehende Sicherheitsbestätigung und Sperre bei laufenden beziehungsweise wartenden Jobs bleiben unverändert.

### Tests und Kompatibilität

- Regressionstests sichern ab, dass ausschließlich HTTP-401 eine Abmeldung auslöst und beliebige Fehlermeldungstexte die Sitzung nicht mehr verwerfen.
- Der erneute Cookie-Header beim Sitzungscheck sowie die getrennte Platzierung von Kopieren und Erneuern werden geprüft.
- Datenbankänderungen sind nicht erforderlich.

## v1.0.19

### Sitzungen bleiben nach einem Seitenreload erhalten

- Sitzungscookies erhalten neben `Max-Age` jetzt ein ausdrückliches Ablaufdatum.
- Das `Secure`-Attribut wird aus der tatsächlichen HTTPS-Verbindung beziehungsweise `X-Forwarded-Proto` abgeleitet. Direkter HTTPS-Zugriff bleibt vollständig geschützt; korrekt terminierende Reverse-Proxys werden ebenfalls unterstützt.
- Sind im Browser noch mehrere gleichnamige Cookies vorhanden, prüft der Manager alle Werte und verwendet die gültige serverseitige Sitzung. Ein alter Host-/Domain-Cookie kann die gerade angelegte Sitzung daher nicht mehr nach einem Reload überdecken.
- Abmelden widerruft alle mitgesendeten gleichnamigen Sitzungstoken.

### Controller-Schlüssel direkt kopieren

- Beim Hinzufügen oder Bearbeiten eines Geräts steht neben dem öffentlichen Controller-Schlüssel ein eigener Kopierbutton.
- Die Clipboard-API wird bevorzugt; bei nicht verfügbarer Browserfreigabe wird auf eine lokale Kopiermethode beziehungsweise eine lesbare Textanzeige zurückgegriffen.

### Fingerprint-Prüfung ohne Aktionsfenster

- **SSH-Fingerprint prüfen** lädt den Ed25519-Fingerprint direkt in den Geräteblock.
- Der Wert kann dort nach dem unabhängigen Vergleich mit **Fingerprint bestätigen** übernommen oder mit **Verwerfen** entfernt werden.
- Das bisherige Browser-Bestätigungsfenster entfällt. Adresse oder Port zu ändern verwirft weiterhin automatisch jede noch nicht gespeicherte Bestätigung.

### Tests und Kompatibilität

- Regressionstests prüfen HTTPS-, Proxy-/HTTP- und doppelte Cookie-Situationen sowie die Wiederverwendung der Sitzung nach einem erneuten Seitenaufruf.
- Statische UI-Tests sichern Kopierbutton, Inline-Fingerprint-Bestätigung und mobile Schaltflächenanordnung ab.
- Datenbankänderungen sind nicht erforderlich.

## v1.0.18

### Repository-Zugang direkt beim Backup-Job

- Einrichtung und Erneuerung repositorybezogener SSH-Schlüssel befinden sich jetzt direkt unter **Backup-Jobs → Mehr → Repository-Zugang**.
- Die Aktion arbeitet gezielt nur für die Kombination aus ausgewähltem Gerät und ausgewähltem verwaltetem Repository. Andere Zugänge desselben Geräts werden nicht erneut erzeugt.
- Die Geräteansicht zeigt weiterhin den Gesamtstatus, enthält aber keinen separaten Einrichtungsbutton mehr.
- Fehlende Zugänge werden in der Jobliste sichtbar markiert; repositoryabhängige Prüf-, Pflege- und Backup-Aktionen bleiben bis zur Einrichtung deaktiviert.
- Der bisherige Host-API-Endpunkt bleibt für Abwärtskompatibilität erhalten, während die WebUI den neuen jobbezogenen Endpunkt verwendet.

### Stabiler Ausführungsdialog bei Borg-Warnungen

- Der Ausführungsdialog verwendet eine feste, an die Browserhöhe angepasste Flex-Anordnung.
- Kritische Borg-Sicherheitswarnungen und weitere Diagnosen verkleinern nur den verbleibenden Logbereich, verschieben ihn aber nicht mehr aus dem sichtbaren Dialog.
- Lesbare Ausgabe und technische Details behalten eine eigene Scrollfläche bis zum tatsächlichen Ende der Ausgabe.
- Die Darstellung ist auch auf schmalen Mobilgeräten auf die verfügbare Viewporthöhe begrenzt.

### Backup direkt vom Dashboard starten

- Der Backup-Job-Block enthält eine zusätzliche Aktionsspalte mit **Starten**.
- Deaktivierte Jobs und verwaltete Jobs ohne eingerichteten Repository-Zugang können nicht versehentlich gestartet werden und zeigen einen erklärenden Hinweis.
- Der bestehende aktionsbezogene Laufstatus verfolgt auch Dashboard-Starts bis zum tatsächlichen Abschluss und aktualisiert anschließend gezielt Dashboard, Ausführungen, Jobs, Repositories und Archive.

### Tests und Kompatibilität

- Der jobbezogene Repository-Zugang wird mit zwei Repositories desselben Geräts getestet; nur der ausgewählte Zugang erhält einen Schlüssel.
- Regressionstests prüfen Dashboard-Start, Zugangsstatus, Warnungsdialog und responsive Logdarstellung.
- Datenbankänderungen sind nicht erforderlich; bestehende Geräte, Jobs, Zugänge und Läufe bleiben unverändert.

## v1.0.17

### Kurze und verwertbare Repository-Fehler

- Fehler beim Lesen lokaler Repository-Dateien geben in Archivansicht und Repository-Aktionen nicht mehr den vollständigen Borg-/Python-Traceback an den Browser weiter.
- Ein `PermissionError` wird auf den tatsächlich nicht lesbaren Pfad und die verwendete Manager-UID:GID reduziert. Dadurch ist die eigentliche Ursache sofort erkennbar.
- Bei als Ausführung gestarteten Aktionen bleibt die vollständige unveränderte Borg-Ausgabe weiterhin in der dateibasierten Laufprotokollierung erhalten. Direkte Archivlistenabfragen geben bewusst nur die kurze Ursache an den Browser zurück.
- Die Diagnose weist gezielt auf Eigentümer, Gruppenrechte, ACLs und NFS-UID/GID-Zuordnung hin, ohne Repository-Berechtigungen automatisch zu verändern.

### Aussagekräftige Compact-Ausgabe

- Manuelle Compact-Läufe und Compact nach einer Archivlöschung verwenden jetzt `borg compact --verbose --show-rc`.
- Das Laufprotokoll enthält dadurch die von Borg geschätzte freigegebene Größe, sofern tatsächlich unreferenzierte Segmente entfernt wurden.
- Erfolgreiche Compact-Läufe ohne freizugebende Daten bleiben weiterhin korrekt als erfolgreich gekennzeichnet.

### Backup-Jobs direkt im Dashboard

- Oberhalb der letzten Aktivitäten steht ein neuer vollständiger Backup-Job-Block.
- Angezeigt werden Status, Job, Gerät, Repository, Quellen, zugeordneter Zeitplan, letzter Backup-Lauf und Größe der letzten Sicherung.
- Der letzte Lauf enthält Laufnummer, Datum, Uhrzeit, Dauer, Status und die Ausführungsart `Manuell` oder `Zeitplan`.
- Bei zeitplangesteuerten Läufen wird der Name des tatsächlich auslösenden Zeitplans als Snapshot gespeichert.
- Original-, komprimierte und deduplizierte Borg-Größen werden nach einem Backup aus der Borg-Statistik übernommen und am Lauf gespeichert. Der Dashboard-Aufruf benötigt dadurch keinen zusätzlichen Repository-Scan.
- Ältere vorhandene Läufe werden soweit möglich aus ihrer gespeicherten Borg-Ausgabe rückwirkend ausgewertet.
- Schlägt der neueste Backup-Lauf fehl, bleibt er in „Letzter Job“ sichtbar; die Größenangabe greift getrennt auf die letzte erfolgreiche Sicherung zurück und nennt deren Laufnummer.
- Dieselben Angaben stehen auch im Detailkopf einer Ausführung zur Verfügung.

### Datenbank und Kompatibilität

- Additive Spalten ergänzen Ausführungsart, Zeitplanname, Archivname und Backup-Größen. Vorhandene Läufe und Datenbanken bleiben erhalten.
- Zentrale Zeitpläne übergeben ihren Namen bis in den erzeugten Lauf; manuelle Aktionen bleiben ausdrücklich als manuell markiert.
- Regressionstests decken Fehlermeldungsfilterung, Compact-Befehl, Statistikparser, Zeitplanausführung, Datenbankmigration und Dashboard-Daten ab.

## v1.0.16

### Korrigierter Installationspfad

- Neue Installationen verwenden für Managerdaten jetzt ausdrücklich `BBM_DATA_PATH=/docker_data/borgbackup-manager/data`.
- Das Repository-Verzeichnis bleibt getrennt unter `/docker_data/borgbackup-manager/repositories`.
- `install.sh`, `.env.example`, `restore-backup.sh`, README und Installationsanleitung verwenden dieselben Standardpfade. Bestehende `.env`-Werte werden bei Updates nicht verändert.
- Ein funktionaler Neuinstallationstest prüft den angezeigten und geschriebenen Datenpfad.

### Speicherplatz-Sperre pro Repository-Dateisystem

- Schreibende Backups prüfen jetzt den tatsächlichen `storage_path` des betroffenen verwalteten Repositorys statt pauschal den Basispfad `/repositories`.
- Mehrere NFS- oder Bind-Mounts unter `/repositories` werden getrennt behandelt. Ein voller Mount blockiert nur Backups in die darauf liegenden Repositories.
- Globale Aktivierung und Schwelle sind direkt in der WebUI unter Einstellungen konfigurierbar. Die Werte aus `.env` dienen als Anfangswerte.
- Jedes verwaltete Repository kann die globale Einstellung übernehmen, die Sperre aktivieren oder deaktivieren und optional eine eigene Schwelle verwenden.
- Die Repository-Liste zeigt die wirksame Schwelle; die Systemdiagnose zeigt zusätzlich Belegung und Blockierstatus. Externe Repositories bleiben von der lokalen Dateisystemprüfung ausgenommen.

### Erweiterte Systemdiagnose

- Die Diagnose liest alle im Container sichtbaren Mountpunkte unter `/repositories` ein.
- Pro Dateisystem werden Gesamtgröße, Belegung, freier Speicher, zugeordnete Repositories und die wirksamen Sperrwerte angezeigt.
- Additive Datenbankmigrationen ergänzen die beiden optionalen repositorybezogenen Sperrfelder ohne bestehende Repositorys zu verändern.

### Robuste Erstinstallation

- Das zufällig erzeugte erste Administratorpasswort enthält jetzt garantiert Kleinbuchstaben, Großbuchstaben, Zahl und Sonderzeichen.
- Damit kann die Erstinstallation nicht mehr selten an der eigenen Passwortkomplexitätsprüfung scheitern.

## v1.0.15

### Installationsabbruch und Pfadkonsistenz

- `install.sh` initialisiert die Zeitzone jetzt vor ihrer Prüfung. Der Abbruch `timezone: unbound variable` unter `set -u` ist damit behoben.
- Die Standardpfade wurden zentral im Installationsskript definiert. Der dabei noch verwendete Datenpfad ohne abschließendes `/data` wird mit Version 1.0.16 korrigiert.
- Ein Ausführungstest startet `install.sh --config-only` ohne vorhandene `.env` und prüft die erzeugte Zeitzone sowie die vollständige Konfiguration.

### Vollständige Skriptprüfung

- `install.sh`, `update.sh`, `recovery.sh`, `restore-backup.sh`, `docker/entrypoint.sh` und `docker/borg-serve.sh` werden gemeinsam auf Shell-Syntax geprüft.
- `recovery.sh` wechselt unabhängig vom Aufrufverzeichnis in den Projektordner und unterstützt Docker-Zugriff über `sudo` sowie den Compose-Fallback.
- `restore-backup.sh` prüft nun zusätzlich auf fehlende `migration.env`-/Datenbereiche, doppelte oder unsichere ZIP-Einträge, unsichere Berechtigungspfade, identische Daten-/Repository-Pfade und ungültige Zeitzonen. Fehlende Backup-Dateien erzeugen eine klare Fehlermeldung statt eines vorzeitigen `readlink`-Abbruchs.
- Der Containerstart weist `BBM_LOG_MAX_BYTES=0` eindeutig zurück, statt eine permanente Nullschwellen-Rotation zuzulassen. Der eingeschränkte Borg-Wrapper unterdrückt außerdem erwartbare Logdatei-Fehler sauber, falls er außerhalb der vorbereiteten Containerumgebung diagnostisch aufgerufen wird.

## v1.0.14

### Erweiterte Geräteerkennung und vollständige Konfigurationsprüfung

- Der Archivfilter erkennt jetzt auch minutengenaue Namen ohne Sekunden, beispielsweise `docker-2026-07-17_03-20`.
- Mehrteilige Präfixe und Checkpoint-Suffixe bleiben bei der Geräteableitung erhalten.
- `.env.example` wurde gegen Compose, Anwendungscode und Skripte abgeglichen, vollständig kommentiert und auf die produktiven Standardpfade vereinheitlicht.
- `BBM_COMMAND_TIMEOUT`, `BBM_SESSION_COOKIE_NAME`, `BBM_APPEARANCE`, `BBM_REPOSITORY_SIZE_AFTER_RUN`, Healthcheck- und Logwerte sind jetzt vollständig dokumentiert und werden von Compose beziehungsweise Installation übernommen.
- `install.sh` bewahrt erweiterte vorhandene `.env`-Werte, validiert alle unterstützten Optionen und verhindert identische Daten- und Repository-Pfade.
- `update.sh` prüft Release-ZIPs einschließlich Dokumentation und `.env.example`, schließt weitere Mounts mit `--one-file-system` aus und startet einen vor der Datensicherung gestoppten Container nach Abbruch automatisch wieder.
- Doppelte Release-ZIPs derselben Version werden deterministisch ausgewählt; die `docker-compose`-Kompatibilität berücksichtigt auch sudo.
- Host-Port sowie Daten- und Repository-Pfad werden jetzt zusätzlich als Metadaten in den Container übergeben, damit Manager-Backups keine leeren Wiederherstellungswerte erzeugen.
- Manager-Backups und `restore-backup.sh` übernehmen die erweiterten Umgebungswerte vollständig.
- Regressionstests für Archivnamen, `.env`, Installation, Update und Wiederherstellung wurden ergänzt.

## v1.0.13

### Archivsortierung und gerätebezogener Filter

- Repository- und Jobarchive werden serverseitig sowie unmittelbar vor der Darstellung deterministisch nach dem Archivzeitpunkt absteigend sortiert. Das neueste Archiv steht immer oben.
- Fehlt ein verwertbarer Startzeitpunkt, wird ein Zeitstempel aus üblichen Archivnamen als Sortierhilfe verwendet. Archive ohne erkennbaren Zeitpunkt stehen am Ende.
- Die Archivansicht erhält eine Auswahl **Alle Geräte / alle Archive** sowie automatisch erkannte Geräte.
- Die Geräteerkennung basiert ausschließlich auf dem Archivnamen und funktioniert deshalb auch für nicht angelegte Geräte, gelöschte Geräte, fremde Archive und Repositorys ohne Backup-Job.
- Aktuelle Präfixe wie `bbm-12-server01-…`, historische Präfixe wie `bbm-job-1-<kennung>-server01-…` und übliche `<gerät>-<zeitstempel>`-Namen werden unterstützt.
- Nicht eindeutig zuordenbare Namen können separat angezeigt werden.
- Der Filter arbeitet direkt auf der persistent zwischengespeicherten Archivliste und startet keinen zusätzlichen Borg-Scan. Die Auswahl wird je Repository im Browser gespeichert.
- Die gefilterte, weiterhin absteigend sortierte Liste wird auch für die Archivauswahl im Vergleich verwendet.

### Dashboard und Systemdiagnose

- Die bisher getrennten Kacheln **Repositories** und **Repository-Größe** sind zu einer gemeinsamen Repository-Kachel zusammengeführt.
- Die Kachel zeigt die Anzahl als Hauptwert und die summierte Repository-Größe als Zusatzwert; beide führten bereits zum gleichen Ziel.
- Eine geladene Systemdiagnose kann über **Diagnose schließen** sofort zurückgesetzt werden. Ein vollständiger Seitenreload ist nicht mehr erforderlich.
- **Diagnose neu laden** aktualisiert eine bereits geöffnete Diagnose gezielt. Laden, Schließen und Fehler werden in der zentralen Statusanzeige bestätigt.

### Tests und Dokumentation

- Tests für aktuelle, historische und generische Archivnamen ergänzt.
- Sortierung mit Startzeit sowie Fallback auf Zeitstempel im Archivnamen geprüft.
- UI-Prüfungen für Gerätefilter, zusammengeführte Repository-Kachel und schließbare Systemdiagnose ergänzt.
- README, Installationsanleitung und integriertes Betriebshandbuch aktualisiert.

## v1.0.12

### Persistenter Archivlisten-Cache für große Repositorys

- Die repositoryweite Archivliste einschließlich Dauer, Dateianzahl und Größenstatistiken wird nach dem ersten Borg-Aufruf atomar unter `/data/archive-cache` gespeichert.
- Weitere Aufrufe der Archivansicht verwenden den persistenten Cache und benötigen keinen erneuten `borg info`-Scan.
- Reguläre Listen und Listen mit eingeblendeten Checkpoint-Archiven werden getrennt gespeichert.
- Parallele Erstaufrufe werden repositorybezogen zusammengeführt, damit nicht mehrere identische Borg-Scans nacheinander ausgeführt werden.
- Die Zusammenfassung zeigt, ob die Daten aus dem Cache oder neu aus dem Repository stammen und wann die Liste erzeugt wurde.
- Archivdetails werden direkt aus der gespeicherten Detailstatistik angezeigt; bei unvollständigen Checkpoint-Daten bleibt der gezielte Detailabruf erhalten.
- Eine neue Aktion **Neu aus Repository einlesen** erfasst Änderungen, die außerhalb des BorgBackup Managers durchgeführt wurden.

### Präzise Cache-Invalidierung

- Erfolgreiche Backups, Prune-Läufe, Archivlöschungen und Archivumbenennungen invalidieren nur die beiden Cachevarianten des betroffenen Repositorys.
- Die Invalidierung erfolgt vor dem sichtbaren Endstatus des Laufs, damit die aktionsbezogene WebUI-Aktualisierung niemals noch die alte Liste übernimmt.
- Repository-Bearbeitung und -Löschung entfernen ebenfalls zugehörige Cachedateien.
- `/data/archive-cache` enthält nur regenerierbare JSON-Metadaten und wird aus dem Update-Datenbackup ausgeschlossen.

### Repository-Größe nach Zeitplanabschluss

- Die Einstellung zur automatischen Größenaktualisierung gilt jetzt ausdrücklich für manuelle schreibende Aktionen und zentrale Zeitpläne.
- Ein geplanter Ablauf führt die Größenabfrage nicht mehr nach Backup, Prune und Compact mehrfach aus.
- Nach Abschluss der gesamten Zeitplankette wird Original-, komprimierte und deduplizierte Größe sowie bei verwalteten Repositorys die Dateisystembelegung genau einmal aktualisiert.
- Manuelle Schreibvorgänge behalten die direkte Aktualisierung nach ihrem Abschluss.

### Prüfung

- Regressionstests für persistentes Speichern, getrennte Checkpoint-Varianten, Invalidierung und erzwungenes Neueinlesen ergänzt.
- API-Test stellt sicher, dass ein zweiter Archivaufruf keinen Borg-Befehl startet und `force_refresh` bewusst neu einliest.
- Zeitplantest sichert die einmalige Größenaktualisierung nach Backup, Prune und Compact.

## v1.0.11

### Aktionsbezogene Aktualisierung statt verfrühtem Einmal-Refresh

- Aktionen zeigen unmittelbar einen laufenden Zustand am betätigten Button und in einer persistenten Statusanzeige im Seitenkopf.
- Borg-Hintergrundläufe werden anhand ihrer konkreten Lauf-ID bis zu `success`, `warning`, `failed` oder `cancelled` verfolgt.
- Die bisherige einmalige Aktualisierung nach ungefähr 300 bis 600 Millisekunden wurde für Hintergrundaktionen entfernt; sie konnte vor dem tatsächlichen Laufende den unveränderten Zustand laden.
- Nach Abschluss werden gezielt nur betroffene Bereiche wie Dashboard, Läufe, Jobs und Repositories neu abgefragt.
- Backup, Prune, Compact, Archivumbenennung und Archivlöschung laden zusätzlich die geöffnete Archivliste des betroffenen Repositorys neu.
- Speichern, Löschen, Repository-Prüfung, Größenberechnung, Cache-Löschung, Geräteprüfung und Zugangseinrichtung bestätigen den Abschluss ebenfalls ohne Seitenreload.
- API-Lesezugriffe verwenden `cache: no-store`, damit nach einer Änderung keine veraltete Browserantwort verwendet wird.
- Das vorhandene Hintergrundintervall bleibt optional, ist aber nicht mehr für die Bestätigung einer Aktion verantwortlich.

### Bedienung und Prüfung

- Die Statusanzeige unterscheidet `Aktuell`, laufende Aktion, erfolgreiche Aktualisierung und Fehler.
- Während einer Anfrage werden betroffene Schaltflächen vorübergehend gesperrt und eindeutig beschriftet.
- Formulare werden erst nach erfolgreichem Speichern zurückgesetzt und die betroffenen Tabellen anschließend gezielt aktualisiert.
- Regressionstests sichern Laufverfolgung, gezielte Aktualisierung, Browser-Cache-Vermeidung und die Entfernung der verfrühten 500-/600-ms-Refreshs ab.

## v1.0.10

### Update-Stillstand nach dem Container-Stopp behoben

- Der Standardpfad `BBM_REPOSITORY_PATH=/docker_data/borgbackup-manager/repositories` liegt unterhalb von `BBM_DATA_PATH`. Das bisherige Update-Backup konnte deshalb nach dem Container-Stopp das vollständige Borg-Repository oder einen dort eingebundenen NFS-Mount mitkomprimieren.
- Zusätzlich wurde der regenerierbare Borg-Cache unter `/data/borg-cache` in das Datenbackup aufgenommen.
- Der Updater erkennt jetzt ein Repository-Unterverzeichnis innerhalb von `BBM_DATA_PATH` und schließt es ausdrücklich aus.
- `/data/borg-cache` wird ebenfalls ausgeschlossen; Borg baut diesen Cache bei Bedarf neu auf.
- Vor Beginn der Komprimierung erscheint eine eindeutige Statusmeldung, damit die Phase nicht mehr wie ein Docker-Stillstand wirkt.
- Persistente Backups werden zunächst als `.partial` geschrieben und erst nach erfolgreichem Abschluss atomar in `.tar.gz` umbenannt.
- Bei identischen Daten- und Repository-Pfaden bricht das Skript mit einer klaren Sicherheitsmeldung ab, statt ein unbrauchbares Backup zu erzeugen.
- Für den Übergang von 1.0.9 muss das neue `update.sh` einmalig vor dem Update gestartet werden, weil ein bereits laufendes Shell-Skript seine alten Funktionsdefinitionen behält.

### Geänderten Repository-Standort sicher bestätigen

- Der gemeldete Backup-Job-Fehler war keine SSH-Störung: Hostkey-Prüfung, Public-Key-Anmeldung und `borg serve` waren erfolgreich.
- Borg erkannte dieselbe Repository-ID unter der neuen URL `ssh://borg@...` statt des früheren Standorts und verlangte absichtlich eine Bestätigung.
- Administratoren erhalten beim Job unter **Mehr → Prüfen** die neue Aktion **Geänderten Repository-Standort bestätigen**.
- Die Aktion setzt `BORG_RELOCATED_REPO_ACCESS_IS_OK=yes` ausschließlich für einen einzelnen `borg info`-Prüflauf auf dem betroffenen Client.
- Normale Verbindungstests und Backups akzeptieren Standortänderungen weiterhin nicht automatisch.
- Die Aktion ist über einen eigenen Admin-Endpunkt geschützt und verlangt zusätzlich eine deutliche Sicherheitsbestätigung in der WebUI.
- Diagnoseausgaben erkennen `was previously located at` und verweisen direkt auf diese Aktion.

### Dokumentation und Tests

- README, Installationsanleitung, integrierte Hilfe und Update-Anweisungen wurden auf Version 1.0.10 aktualisiert.
- Regressionstests prüfen die einmalige Standortbestätigung, deren Nichtverwendung bei normalen Prüfläufen, die Admin-Trennung sowie die neue Diagnose.
- Eine Update-Simulation mit einem 250-MiB-Repository-Unterverzeichnis und einem 120-MiB-Borg-Cache bestätigt, dass beide nicht in das Manager-Datenbackup gelangen, während Sicherheitsdaten erhalten bleiben.

## v1.0.9

### Lokaler Borg-Cache aus dem Repository-Mount verlagert

- Managerseitige Borg-Befehle verwenden jetzt `/data/borg-cache` und `/data/borg-security`.
- Cache- und Sicherheitsdaten des Containerbenutzers werden dadurch nicht mehr unter `/repositories/.cache` beziehungsweise `/repositories/.config` angelegt.
- Dies verhindert insbesondere bei NFS- und Bind-Mount-Repositories, dass lokale Manager-Metadaten auf der Repository-Freigabe liegen oder durch frühere Berechtigungsfehler beschädigt werden.
- Der Containerstart erzeugt die neuen Verzeichnisse mit restriktiven Rechten und weist sie dem Borg-Benutzer zu.

### Repositorybezogene Cache-Löschung

- In der Repository-Zeile steht Administratoren die neue Aktion **Cache löschen** zur Verfügung.
- Die Aktion entfernt nur den Cache des ausgewählten Repositorys; Archive, Borg-Repository-Konfiguration, Passphrase, Keyfile und Sicherheitsstatus bleiben unverändert.
- Bei verwalteten Repositories wird zusätzlich ein noch vorhandener Alt-Cache unter `/repositories/.cache/borg/<Repository-ID>` entfernt.
- Andere Repository-Caches werden anhand der validierten 64-stelligen Borg-Repository-ID strikt ausgeschlossen.
- Während einer laufenden oder wartenden Repository-Ausführung ist das Löschen gesperrt.
- Der Vorgang wird als Repository-Verwaltungsaktivität protokolliert.
- Der erste Zugriff nach dem Löschen kann länger dauern, weil Borg den Cache neu aufbaut.

### Bestehende Repositories nicht mehr als neu initialisieren

- Ein fehlgeschlagener Verbindungstest setzt ein bereits vorhandenes verwaltetes Repository nicht mehr auf `initialized=false`.
- Die WebUI unterscheidet jetzt zwischen vorhandener Borg-Konfiguration, erfolgreicher letzter Prüfung und einem tatsächlich noch nicht initialisierten Zielverzeichnis.
- **Initialisieren** wird nur angeboten, wenn im verwalteten Verzeichnis keine Borg-`config` vorhanden ist.
- Bei Cache-Lockfehlern wie `lock.exclusive (timeout)` verweist die Diagnose direkt auf die neue Cache-Aktion.

### Dokumentation und Prüfung

- README, Installationsanleitung und integrierte Hilfe wurden um NFS-Cachepfade, Cache-Löschung und die sichere Einbindung vorhandener Repositories ergänzt.
- Regressionstests prüfen die gezielte Löschung von aktuellem und altem Cache, den Schutz fremder Cache-Verzeichnisse, ungültige Repository-IDs, die Sperre bestehender Repository-Zustände und die neue Diagnose.

## v1.0.8

### Archivzeit in der WebUI korrigiert

- Borg-1.x-Archivmetadaten enthalten Start- und Endzeit je nach Ausgabe ohne Zeitzonenkennung.
- Die WebUI behandelte diese lokalen Clientzeiten bisher wie UTC und rechnete für `Europe/Berlin` im Sommer nochmals zwei Stunden hinzu.
- Naive Borg-Zeitpunkte werden jetzt serverseitig mit der konfigurierten Anwendungszeitzone versehen; bereits mit `Z` oder Offset gelieferte Werte bleiben unverändert.
- Aktivitäts- und Ausführungszeiten bleiben echte UTC-Zeitpunkte und werden weiterhin unverändert korrekt nach `Europe/Berlin` umgerechnet.

### Kompakte, nicht wiederverwendbare Archivpräfixe

- Der bisherige 16-stellige Zufallsanteil wie `13984bc980b20426` wurde ursprünglich eingeführt, damit ein nach Löschung neu angelegter Job keine frühere Archivserie mit derselben SQLite-ID übernimmt.
- Neue und bestehende Jobs verwenden jetzt ein kurzes Präfix wie `bbm-12-`.
- Jede vergebene Job-ID wird in einer dauerhaften Reservierungstabelle gespeichert und nach dem Löschen nicht erneut vergeben. Die Schutzwirkung bleibt dadurch ohne langen Zufallsanteil erhalten.
- Beim Update wird das bisherige Präfix als historische Serie am Job gespeichert. Vorhandene Archive bleiben in Repository- und Jobansicht zugeordnet, können wiederhergestellt oder umbenannt werden und werden bei Prune weiterhin mit den bisherigen Aufbewahrungsregeln behandelt.

### Dokumentation und Prüfung

- README, Installationsanleitung und integrierte Hilfe wurden auf die Archivzeitbehandlung, das kompakte Präfix und die Migration bestehender Archivserien aktualisiert.
- Regressionstests prüfen Sommer-/Winterzeit, explizite UTC-Offsets, historische Präfixe, Prune über aktuelle und frühere Serien sowie die dauerhafte Reservierung gelöschter Job-IDs.

## v1.0.7

### SSH-Hostkey-Prüfung für Geräte korrigiert

- Beim Aufbau der Controller-SSH-Verbindung werden privater Controller-Schlüssel und bestätigter Geräte-Hostschlüssel weiterhin nur als temporäre Dateien unter `/tmp` bereitgestellt.
- Der Platzhalter des temporären `known_hosts`-Pfads wurde bisher nicht ersetzt, weil er innerhalb des zusammengesetzten OpenSSH-Arguments `UserKnownHostsFile=…` stand.
- OpenSSH erhielt dadurch einen nicht vorhandenen Platzhalternamen und meldete trotz korrekt geprüftem Fingerprint: `No ED25519 host key is known ... Host key verification failed.`
- Die Ersetzungslogik verarbeitet temporäre Dateiplatzhalter jetzt auch innerhalb zusammengesetzter Argumente. `StrictHostKeyChecking=yes` bleibt vollständig aktiv und verwendet den tatsächlich bestätigten Hostschlüssel.
- Ein Löschen und erneutes Hinzufügen des Geräts oder ein erneuter Controller-Schlüsselwechsel ist nach dem Update nicht erforderlich.

### Dokumentation und Prüfung

- README, Installationsanleitung und integrierte Hilfe erklären die getrennten Aufgaben von Controller-Schlüssel und Geräte-Hostschlüssel.
- Ein Regressionstest prüft ausdrücklich die Auflösung des `known_hosts`-Pfads innerhalb von `UserKnownHostsFile=…`.

## v1.0.6

### Repository-Tabelle neu ausgerichtet

- Die Statusspalte wurde verkleinert und der Abstand zum Repository-Namen reduziert.
- Die Größenspalte erhält mehr nutzbare Breite, ohne mit den Aktionsschaltflächen zu kollidieren.
- Original-, deduplizierte, komprimierte und lokale Dateisystemgröße stehen weiterhin untereinander; die Werte beginnen jetzt direkt neben der jeweiligen Bezeichnung statt am rechten Zellenrand.

### Geräteansicht als Vollbreiten-Arbeitsbereich

- „Gerät hinzufügen“ steht als oberer, vollständiger Block.
- „Verbundene Geräte“ folgt direkt darunter und nutzt die gesamte verfügbare Breite.
- Die bisherige seitliche Zweiteilung und das feststehende Formular wurden entfernt.

### Mobile WebUI vollständig nachgearbeitet

- Die Seitenleiste wird auf kleinen Displays über eine kompakte Menüschaltfläche geöffnet und nach einer Bereichsauswahl automatisch geschlossen.
- Dashboard, Geräte, Repositories, Backup-Jobs, Zeitpläne, Ausführungen, Archive, Restore, Manager-Backup, Benutzer, Einstellungen, Anleitung, Release Notes und Dialoge wurden auf horizontales Überlaufen geprüft.
- Tabellen wechseln mobil in beschriftete Karten; Formulare, Aktionsbereiche, Archivkennzahlen, Browserwerkzeuge und Dialoge passen sich einspaltig beziehungsweise mehrzeilig an.
- Lange Pfade, Repository-Namen, Archivnamen, Hinweise und Protokollinhalte bleiben innerhalb der verfügbaren Breite.

### Prüfung

- Responsive Layoutprüfung bei 360, 390, 768 und 1366 Pixel Breite für alle WebUI-Seiten.
- Zusätzliche Regressionstests prüfen Geräte-Stack, Mobile-Menü, Repository-Spalten und responsive Schutzregeln.

## v1.0.5

### Repository- und Archivgrößen übersichtlicher

- Repository-Größen werden in der Reihenfolge **Original**, **Dedupliziert**, **Komprimiert** untereinander dargestellt; die Werte stehen rechts daneben.
- Die lokale Dateisystembelegung verwalteter Repositories bleibt als zusätzliche vierte Zeile erhalten.
- Archivzeilen wurden in Höhe, Abständen und Aktionsschaltflächen kompakter gestaltet, ohne die bestehende Kennzahlenanordnung zu verändern.

### Archivkennzahlen direkt in der Übersicht

- Die repositoryweite Archivansicht ruft `borg info --json --glob-archives "*"` auf und erhält damit Dauer, Dateianzahl sowie Original-, komprimierte und deduplizierte Größe in einem einzigen Borg-Aufruf.
- Die Werte, die bisher nur im Details-Dialog vorhanden waren, werden dadurch auch direkt in jeder normalen Archivzeile angezeigt.
- Die Jobansicht mit repositoryweiter Archivauswahl verwendet dieselbe vollständige Statistikabfrage.
- Checkpoint-Archive bleiben über die vorhandene Listenzusammenführung unterstützt; nicht von Borg gelieferte Werte werden weiterhin als `–` angezeigt.

### Recovery-Skript im Update repariert

- `recovery.sh` wurde in Paketprüfung, Update-Whitelist, Projektsicherung, Rollback und Vergabe der Ausführungsrechte aufgenommen.
- Der Übergang von 1.0.4 oder älter benötigt einmalig die dokumentierte Vorabübernahme von `recovery.sh`, weil das bereits laufende alte `update.sh` seine Whitelist nicht selbst austauschen kann.
- Ab 1.0.5 übertragen, sichern und restaurieren spätere Updates das Recovery-Skript zuverlässig im vorhandenen Projektordner.
- README, Installationsanleitung, integrierte Hilfe, Versionsangaben und Prüfkommandos wurden auf Version 1.0.5 und den tatsächlichen Paketinhalt abgeglichen.

### Prüfung

- Regressionstests decken den repositoryweiten Archiv-Info-Aufruf, vollständig gefüllte Archivkennzahlen und die Übernahme von `recovery.sh` durch `update.sh` ab.

## v1.0.4

### Update von 1.0.2 repariert

- Die additive Migration von `manager.db` wird jetzt bereits im Security-Bootstrap ausgeführt, bevor Repository-Datensätze über das erweiterte SQLAlchemy-Modell gelesen werden.
- Bestehende Installationen erhalten die neuen Spalten `original_size_bytes`, `compressed_size_bytes` und `deduplicated_size_bytes` vor dem ersten Repository-Zugriff.
- Die Neustartschleife mit `sqlite3.OperationalError: no such column: repositories.original_size_bytes` ist damit behoben.
- Die Migration bleibt additiv und verändert weder vorhandene Repository-Einträge noch Borg-Repository-Daten.

### Prüfung

- Regressionstests prüfen die neuen Repository-Spalten sowie die erforderliche Migrationsreihenfolge beim Containerstart.

## v1.0.3

### Zentrales Recovery-Skript

- Neues ausführbares `recovery.sh` mit interaktivem Menü ergänzt.
- Kontostatus, einmalige Erstanmeldedaten, Kontosperre, Passwortreset und Wiederherstellung der Administratorrolle lassen sich ohne Kenntnis einzelner Python-Module auswählen.
- Dieselben Funktionen stehen für Wartung und Automatisierung über `status`, `status-json`, `initial-admin`, `unlock`, `reset` und `reset-admin` zur Verfügung.
- Das Skript prüft Compose-Konfiguration und laufenden Container, bevor eine Recovery-Aktion ausgeführt wird.

### Repository-Statistiken erweitert

- Originalgröße, komprimierte Größe und repositoryweit deduplizierte komprimierte Größe werden für verwaltete und externe Repositories angezeigt.
- Verwaltete Repositories zeigen zusätzlich die tatsächliche Dateisystembelegung des lokalen Repository-Verzeichnisses.
- Die bisherige Einzelanzeige „Borg-Nutzdaten · dedupliziert/komprimiert“ wurde durch eine klar beschriftete Statistikübersicht ersetzt.
- Die Größenberechnung nutzt `borg info --json`; die Dateisystembelegung wird nur bei lokal eingebundenen verwalteten Repositories zusätzlich ermittelt.

### Archivdetails erweitert

- Archivübersicht zeigt je Archiv Dauer, Dateianzahl, Originalgröße, komprimierte Größe und deduplizierte Größe.
- Die manuelle Archivaktualisierung lädt die detaillierten Statistiken mit `borg info --json` und benötigt dafür nicht pro Archiv einen separaten Aufruf.
- Der Details-Dialog stellt die Archivinformationen lesbar statt als ungefiltertes JSON dar.
- Checkpoint-Archive bleiben unterstützt; falls Borg dafür keine vollständigen Statistiken liefert, werden fehlende Werte eindeutig mit „–“ dargestellt.

## v1.0.2

### Anmeldung wieder funktionsfähig

- Einen Frontend-Laufzeitfehler durch den Verweis auf das entfernte Element `repo-env-field` behoben.
- Der Login-Handler wird jetzt früh registriert und kann nicht mehr durch Fehler in später initialisierten Verwaltungsansichten ausfallen.
- Das Anmeldeformular lädt die Seite auch bei einem Frontendfehler nicht mehr als normales HTML-Formular neu.
- Die parallele Prüfung einer bestehenden Sitzung kann einen gerade laufenden Login nicht mehr zurück auf die Anmeldemaske setzen.
- Ein statischer DOM-Konsistenztest verhindert künftig JavaScript-Verweise auf nicht vorhandene HTML-Elemente.

### Anmeldemaske vereinfacht

- Der Benutzername `admin` ist nicht mehr fest vorgegeben.
- Technische Hinweise zu HTTPS, Initialzugang und Kontowiederherstellung wurden aus der Anmeldemaske entfernt.
- Die aktuell laufende Programmversion wird auf der Anmeldemaske angezeigt und zusätzlich über `/api/ready` bereitgestellt.
- Benutzername bleibt bei einer abgelehnten Anmeldung erhalten; nur das Passwortfeld wird geleert.

## v1.0.1

### Update- und Kontodiagnose

- Update-Ausgabe bei HTML-Fallbacks gekürzt.
- Readiness-Prüfung um den Zustand der Benutzerverwaltung erweitert.
- Lokale Diagnose-, Entsperr- und Passwortreset-Befehle über `app.account_recovery` ergänzt.

## v1.0.0

### Zentrale, geräteübergreifende Zeitpläne

- Zeitpläne wurden aus Backup-Jobs entfernt und in einen eigenen Arbeitsbereich verschoben.
- Zuordnung zu einzelnen oder mehreren Geräten, allen Jobs eines Repositorys oder ausgewählten Backup-Jobs.
- Mehrere Uhrzeiten, Wochentage, Monatsmodus und freie Cron-Ausdrücke; verbindliche Zeitzone `Europe/Berlin`.
- Jobs ohne Zuordnung bleiben manuell und werden in der Jobliste entsprechend gekennzeichnet.
- Vorhandene Job-Cronwerte werden beim ersten Start verlustfrei in zentrale Einzelzeitpläne migriert.
- Überlappende aktive Zeitpläne für denselben Job werden abgewiesen.

### Repositoryweite Warteschlange

- Pro Repository läuft höchstens eine Borg-Aktion gleichzeitig.
- Weitere Backup-Anforderungen bleiben als `queued` sichtbar und starten automatisch nach Freigabe.
- Dashboard-Kachel **Wartend** und eigener Ausführungsfilter ergänzt.
- Unterschiedliche Repositories können weiterhin parallel arbeiten.

### Sicherheitsdaten vollständig getrennt

- Benutzerkonten, scrypt-Passworthashes, Sitzungshashes und Sicherheitsereignisse verbleiben in `/data/security/security.db`.
- Controller-, Repository-SSH- und TLS-Privatschlüssel, externe SSH-Schlüssel, Repository-Passphrasen, Borg-Keyfiles und sensitive Zusatzvariablen werden verschlüsselt in derselben Sicherheitsdatenbank gespeichert.
- Alte Geheimnisfelder in `manager.db` werden migriert und geleert.
- Persistente Klartext-Schlüsselverzeichnisse werden nach erfolgreicher Migration entfernt; Laufzeitdateien entstehen nur unter `/run/bbm-secrets` oder `/tmp/bbm-borg.*`.
- Das einmalige Admin-Passwort wird verschlüsselt gespeichert und ausschließlich über `python -m app.initial_admin` ausgegeben.
- `/data/security/master.key` bleibt als einziger externer Vertrauensanker mit Modus `0600`.

### Betriebsschutz

- Container-Hostname fest auf `bbm` gesetzt.
- Controller-Schlüsselerneuerung verlangt exakt `CONTROLLER-SCHLÜSSEL ERNEUERN`.
- Laufende oder wartende Ausführungen blockieren die Erneuerung.
- Integrierte Anleitung, README und Installationsanleitung auf Zeitpläne, Warteschlange und Sicherheitsablage aktualisiert.

### Prüfung

- Regressionstests für Zeitplanmigration, Mehrfachzuordnung, repositoryweite Queue, Wartestatus, verschlüsselte Bootstrap-Zugangsdaten und Schlüsselerneuerung ergänzt.

## v0.9.5

### Externe Repository-Prüfung verständlicher

- Normale Verbindungstests verwenden kein `ssh -vv` mehr.
- OpenSSH-Verhandlungsdetails wie KEX-, Cipher- und MAC-Listen werden nicht mehr direkt unter dem Repository angezeigt.
- Typische Fehler werden in kurze, handlungsorientierte Meldungen übersetzt, unter anderem fehlender Public Key, Timeout, falscher Hostkey, falsche Passphrase oder ungültiger Repository-Pfad.
- Technische Details bleiben dauerhaft gespeichert, gefiltert und über einen eigenen Button kopierbar.
- Bereits gespeicherte umfangreiche Diagnoseausgaben werden beim ersten Start automatisch verdichtet.

### Repository-Ansicht überarbeitet

- Der Bereich ist jetzt vertikal aufgebaut: Repository hinzufügen oben, Repository-Übersicht darunter, lokale Repository-Suche als eigener dritter Block.
- Die Repository-Tabelle verwendet feste, umbrechende Spalten und wechselt auf schmaleren Ansichten frühzeitig in eine Kartenansicht.
- Lange Repository-URLs und Aktionsbereiche erzwingen keinen horizontalen Seitenscroll mehr.
- Verbindungs- und Größenprüfungen erhalten einen dauerhaften Statusbereich statt nur kurz sichtbarer Toast-Meldungen.

### Externe Repository-Größe

- Die Größenberechnung ist jetzt auch für externe Repositories verfügbar.
- Verwaltete Repositories zeigen weiterhin die tatsächliche lokale Verzeichnisgröße.
- Externe Repositories zeigen die von Borg gemeldeten repositoryweiten deduplizierten komprimierten Nutzdaten.
- Die Oberfläche kennzeichnet beide Größenarten eindeutig, da die Borg-Nutzdaten bei externen Zielen keine vollständige serverseitige Dateisystembelegung darstellen.

### Klare Erstellen-/Hinzufügen-Logik

- Verwaltete Ziele verwenden die Aktion **Repository erstellen**.
- Vorhandene externe Ziele verwenden **Repository hinzufügen**.
- Die WebUI erklärt ausdrücklich, dass das Hinzufügen eines externen Repositorys dieses weder initialisiert noch überschreibt.
- Die Ablage generierter SSH-Schlüssel wird direkt im Formular und in der Anleitung dokumentiert: verschlüsselt in `/data/manager.db`, geschützt durch `/data/security/master.key`, temporäre Klartextdatei nur während des Borg-Aufrufs.

### Prüfung

- Regressionstests für Fehlerverdichtung, persistente Diagnosedetails, externe Borg-Größenstatistik, responsive Repository-Ansicht und die unterschiedliche Erstellen-/Hinzufügen-Beschriftung ergänzt.

## v0.9.4

### Externe Repositories direkt durch den Manager

- Die in 0.9.3 eingeführte Zugriffs-Client-Zwischenstation wurde vollständig aus Bedienung und Laufzeitlogik entfernt.
- Repository-Verwaltung, Verbindungstest, Archivliste, Archivinformationen, Check, Prune, Compact, Diff, Rename, Delete, Export und Archivbrowser laufen bei externen Repositories direkt im Manager-Container.
- Ein Backup-Job oder ein zusätzlicher Client ist für die Anzeige vorhandener Archive nicht erforderlich.
- Jeder externe SSH-Repository-Eintrag besitzt einen eigenen zentral verwalteten Ed25519-Schlüssel und einen repositorybezogenen `known_hosts`-Eintrag.
- Die WebUI kann den Schlüssel erzeugen oder einen vorhandenen unverschlüsselten OpenSSH-Privatschlüssel übernehmen.
- SSH-Hostkeys können direkt vom Manager gescannt oder manuell als geprüfter `known_hosts`-Eintrag hinterlegt werden.
- Private SSH-Schlüssel und `known_hosts` werden mit dem Sicherheits-Master-Key verschlüsselt gespeichert; in API-Ausgaben erscheint nur der öffentliche Schlüssel beziehungsweise der Hostkey-Fingerprint.

### Backup und Restore zu externen Zielen

- `borg create` und `borg extract` laufen weiterhin auf dem jeweiligen Quell- oder Ziel-Client, da dort die Nutzdaten liegen.
- Der Manager überträgt den zentral gespeicherten Repository-Schlüssel, `known_hosts`, Passphrase und gegebenenfalls das Borg-Keyfile ausschließlich temporär über die Controller-SSH-Verbindung.
- Temporäre Dateien werden mit restriktiven Rechten erstellt und nach dem Borg-Aufruf auch bei Abbruch entfernt.
- Eine dauerhafte externe Repository-Konfiguration auf jedem Client ist nicht mehr erforderlich.
- Befehlsvorschau und Laufprotokolle enthalten weder private SSH-Schlüssel noch Passphrasen oder Borg-Keyfiles.

### Migration von 0.9.3

- Alte Felder für Zugriffs-Client und SSH-Dateipfade bleiben nur zur additiven Datenbankmigration erhalten und werden beim Start geleert.
- Externe Einträge bleiben bestehen, werden ohne zentralen Manager-Schlüssel jedoch als ungeprüft markiert.
- Nach dem Upgrade muss ein solcher Eintrag einmal bearbeitet, der öffentliche Manager-Schlüssel am externen Ziel autorisiert und anschließend über **Verbindung prüfen** validiert werden.

### Prüfung

- Regressionstests für direkte Manager-Befehle, temporäre Secret-Übergabe, Archivliste und Archivbrowser ohne Backup-Job ergänzt.
- Datenbankmigration um verschlüsselte externe SSH-Daten, öffentlichen Schlüssel, Hostkey-Fingerprint und Validierungsstatus erweitert.

## v0.9.3

### Externe vorhandene Repositories

- Externe Borg-Repositories erhalten einen festen Zugriffs-Client für Verwaltungsbefehle.
- Repository-URL, optionaler SSH-Schlüsselpfad und optionale `known_hosts`-Datei werden repositorybezogen gespeichert.
- Beim Anlegen oder Ändern wird das vorhandene Repository mit `borg info` tatsächlich geöffnet.
- Hetzner Storage Box und andere SSH-basierte Borg-Ziele können damit ohne vorherigen Backup-Job eingebunden werden.
- Bestehende externe Einträge ohne Zugriffs-Client bleiben erhalten, werden aber als „Prüfung erforderlich“ gekennzeichnet.
- Wird ein Zugriffs-Client gelöscht, wird die Zuordnung entfernt und das externe Repository erneut als ungeprüft markiert.

### Repositoryzentrierte Archivübersicht

- Archivansicht wählt jetzt direkt ein Repository statt eines Backup-Jobs aus.
- `borg list`, Archivinformationen und der Archivbrowser funktionieren ohne vorhandenen Backup-Job.
- Verwaltete Repositories werden lokal im Manager geöffnet; externe Repositories über den gespeicherten Zugriffs-Client.
- Jobzuordnungen werden weiterhin anhand dauerhafter Archivpräfixe erkannt.
- Restore und schreibende Archivaktionen bleiben an einen passenden Backup-Job gebunden.
- Neue Repository-Aktion „Verbindung prüfen“ validiert den gespeicherten Zugriff erneut.

### Prüfung

- Datenbankmigration für Zugriffs-Client und externe SSH-Pfade ergänzt.
- Regressionstests für Storage-Box-URL, repositorybezogene SSH-Optionen und Archivlisten ohne Job ergänzt.

## v0.9.2

### Anleitung und Schnellzugriff

- Schnellzugriffe verwenden nun routerkompatible Ziele innerhalb der Anleitung.
- Ein Klick auf einen Eintrag bleibt in der Ansicht „Anleitung“ und scrollt zuverlässig zum gewählten Abschnitt.
- Direkte URLs wie `#help?section=help-archives` funktionieren auch nach Neuladen sowie mit Vor-/Zurück-Navigation.

### Checkpoint-Archive

- Archivübersicht um die manuelle Option „Unvollständige Checkpoint-Archive anzeigen“ erweitert.
- Der Manager verwendet dafür bei Borg 1.2 bis 1.4 `borg list --consider-checkpoints`.
- Checkpoint-Archive werden deutlich als unvollständig gekennzeichnet und sind standardmäßig ausgeblendet.
- Die Restore-Archivauswahl kann Checkpoints bei ausdrücklicher Aktivierung ebenfalls anzeigen.
- Archivvalidierung erkennt ausdrücklich ausgewählte Checkpoints auch dann, wenn die normale Übersicht sie ausblendet.

### Prüfung

- Regressionstests für Help-Routing, URL-Anker, Checkpoint-Befehle und API-Weitergabe ergänzt.

## v0.9.1

### Benutzerverwaltung

- Der letzte Administrator kann unabhängig von seinem Aktivstatus nicht gelöscht werden.
- Der Schutz wird zusätzlich direkt in der Benutzerliste sichtbar; die Löschaktion ist dort deaktiviert und erklärt.
- Das eigene Konto bleibt ebenfalls gegen Löschen geschützt.
- Die Sicherheitsübersicht zeigt Benutzer-, Administrator- und Sitzungsanzahl getrennt.

### Favicon und Darstellungsdichte

- Eigenes Borg-orientiertes SVG-Favicon für Browser, Anmeldung und Seitenleiste ergänzt.
- „Komfortabel“ und „Kompakt“ unterscheiden sich jetzt deutlich bei Navigation, Karten, Formularen, Tabellen, Schaltflächen und Abständen.
- Dichte und Listenhöhe werden bereits beim Ändern im Einstellungsformular als Vorschau angewendet.
- „Maximale Listenhöhe“ eindeutig als Höhe der Archivübersicht und weiterer scrollbarer Listen bezeichnet.

### Protokollanzeige

- Borg-Dateistatus und Abschlussstatistik werden nicht mehr fälschlich unter „Fehlerausgabe“ angezeigt.
- Die technische Fehleransicht enthält nur erkannte Fehler, Warnungen und relevante Traceback-Informationen.
- Das vollständige Ankunftsprotokoll einschließlich Dateiliste und Statistik bleibt unverändert in `/data/run-logs/run-ID.log` und in der normalen Live-Ansicht erhalten.
- Alte gespeicherte stderr-Vorschauen werden beim Start auf die gefilterte Darstellung reduziert.

### Anleitung

- Integrierte Anleitung vollständig neu gegliedert und auf den aktuellen Funktionsumfang abgestimmt.
- Schnellstart, Architektur, Sicherheit, Geräte, Repositories, Jobs, Zeitpläne, Archive, Restore, Backups, Benutzer, Einstellungen und Diagnose sind in lesbaren Abschnitten, Tabellen und Schrittfolgen beschrieben.
- README und Installationsanleitung an Administrator-Schutz, Fehlerfilter, Dichteoptionen und Listenhöhe angepasst.

### Prüfung

- Regressionstests für Administrator-Schutz, Borg-stderr-Filter, Favicon, Dichte und Anleitung ergänzt.

## v0.9.0

### Verständlicher Zeitplan-Editor

- Auswahl für manuell, täglich, Montag bis Freitag, Wochenende, ausgewählte Wochentage und monatlich.
- Pro Job können mehrere Uhrzeiten hinzugefügt und wieder entfernt werden.
- Vorschau zeigt Tage, Uhrzeiten, Anzahl der erzeugten Zeitpläne und `Europe/Berlin`.
- Sonderfälle bleiben über mehrere fünfteilige Cron-Ausdrücke möglich.
- Bestehende einzelne Cron-Ausdrücke bleiben kompatibel.
- Serverseitige Validierung, Deduplizierung und Begrenzung auf 24 Zeitpunkte je Job.
- APScheduler erhält je Uhrzeit einen eindeutig benannten Job.

### Anmeldung ohne Admin-Token in `.env`

- Neue Installationen erzeugen kein `BBM_ADMIN_TOKEN` und keinen `BBM_SECRET_KEY`.
- Einmalige initiale Zugangsdaten werden mit Modus `0600` unter `/data/security/initial-admin.txt` abgelegt.
- Benutzerpasswörter werden mit scrypt und individuellem Zufallssalt gehasht und sind nicht reversibel gespeichert.
- Persönliche, serverseitig widerrufbare Sitzungen ersetzen das globale Token.
- Sitzungstoken werden nur als SHA-256-Hash gespeichert.
- Browser-Cookie bleibt `HttpOnly`, `Secure` und `SameSite=Strict`.
- Fünf fehlgeschlagene Anmeldungen sperren das Konto für 15 Minuten.

### Separate Sicherheitsdatenbank und Master-Key

- Benutzer, Sitzungen und Sicherheitsereignisse liegen in `/data/security/security.db`.
- Repository-Passphrasen und Keyfiles werden mit einem zufälligen Master-Key unter `/data/security/master.key` verschlüsselt.
- Sicherheitsverzeichnis und Dateien werden auf restriktive Berechtigungen gesetzt.
- Manager-Backups enthalten Sicherheitsdatenbank und Master-Key als zusammengehörigen Zustand.
- Verschlüsselte `.bbm`-Backups bleiben für externe Ablage empfohlen.

### Automatische Migration von 0.8.x

- Bestehender Admin-Token wird einmalig als temporäres Passwort des Administrators übernommen.
- Bestehende Repository-Geheimnisse werden mit dem alten `BBM_SECRET_KEY` entschlüsselt und mit dem neuen Master-Key neu verschlüsselt.
- Danach werden `BBM_ADMIN_TOKEN`, `BBM_SECRET_KEY` und der Legacy-Schalter automatisch aus der Host-`.env` entfernt.
- Docker Compose übergibt alte Geheimwerte nicht mehr als dauerhafte Container-Umgebung.

### Benutzerverwaltung

- Benutzer mit Rollen Administrator und Benutzer anlegen, bearbeiten, aktivieren, deaktivieren und löschen.
- Temporäre Passwörter mit erzwungenem Wechsel vergeben.
- Passwörter administrativ zurücksetzen; vorhandene Sitzungen werden beendet.
- Eigenes Passwort jederzeit über die Seitenleiste ändern.
- Letzten aktiven Administrator sowie das eigene Konto gegen versehentliche Löschung schützen.
- Normale Benutzer auf operative Job-, Archiv- und Restore-Funktionen begrenzen.

### Backup und Wiederherstellung

- Sicherheitsdatenbank wird konsistent über SQLite-Backup gesichert.
- Master-Key und initiale Zugangsdaten werden mit korrekten Dateirechten übernommen.
- WebUI-Wiederherstellung übernimmt den vollständigen Benutzer-/Sitzungs-/Schlüsselzustand und verlangt danach eine neue Anmeldung.
- Migrationsumgebung enthält keine Admin-Token oder Verschlüsselungsschlüssel mehr.

### Tests

- Tests für Mehrfachzeitpläne, ungültige Cron-Ausdrücke und Zeitplanbegrenzung.
- Tests für scrypt-Passworthashes, Dateirechte, serverseitig gehashte Sitzungstoken und Rollenrechte.
- Regressionstests für Sicherheitsbackup und Entfernung alter Geheimwerte.

## v0.8.8

### Backup-Job-Seite neu angeordnet

- Jobeditor und Jobübersicht nicht mehr nebeneinander, sondern als zwei breite horizontale Arbeitsblöcke angeordnet.
- **Backup-Job erstellen** steht oben; die filterbare Tabelle **Backup-Jobs** folgt darunter.
- Grunddaten werden in einer kompakten Mehrspaltenansicht dargestellt.
- Quellpfade und Ausschlüsse stehen nebeneinander.
- Archivvorlage, Kompression und eigene Kompressionsspezifikation sind platzsparend gruppiert.
- Dateisystem-/Konsistenzoptionen und Aufbewahrung wurden in aufklappbare Bereiche verschoben.
- Aufbewahrungswerte werden in einer kompakten Sechsergruppe angezeigt; responsive Umbrüche bleiben für kleinere Bildschirme erhalten.

### Controller-Schlüssel erneuern

- Neue Aktion **Controller-Schlüssel erneuern** im Gerätebereich.
- Wechsel wird blockiert, solange Ausführungen laufen oder warten.
- Bisheriges privates und öffentliches Schlüsselpaar wird unter `/data/ssh/archive` gesichert.
- Ein neues Ed25519-Schlüsselpaar wird atomar erzeugt und sofort in der WebUI angezeigt.
- Repository-Zugangsschlüssel und Borg-Archive bleiben unverändert.
- Die Oberfläche weist dauerhaft darauf hin, dass der neue öffentliche Schlüssel auf allen Clients hinterlegt werden muss.

### Manager-Backup verschlüsseln

- Vorgegebene Bezeichnung `serverwechsel` entfernt; das Feld ist leer und optional.
- Unverschlüsselte Backups bleiben normale ZIP-Dateien.
- Optionales verschlüsseltes `.bbm`-Format mit AES-256-GCM.
- Schlüsselableitung aus der nicht gespeicherten Backup-Passphrase über scrypt.
- Manipulierte Dateien und falsche Passphrasen werden durch die authentifizierte Verschlüsselung erkannt.
- Backup-Liste kennzeichnet verschlüsselte und unverschlüsselte Dateien eindeutig.

### Manager-Backup wiederherstellen

- Neue vollständige Wiederherstellungsfunktion direkt im Bereich **Manager-Backup**.
- Vor der Wiederherstellung werden laufende und wartende Jobs geprüft.
- Verschlüsselte Backups verlangen ihre Backup-Passphrase.
- Backup-Pfade, Manifest und enthaltene Dateien werden vor dem Einspielen sicher validiert.
- Der im Backup enthaltene `BBM_SECRET_KEY` muss für eine direkte WebUI-Wiederherstellung zur laufenden Installation passen.
- Vor dem Ersetzen wird automatisch ein lokales Sicherheitsbackup erzeugt.
- Datenbank, Einstellungen, Controller-/Repository-SSH-Schlüssel, Borg-Keyfiles und TLS-Dateien werden wiederhergestellt.
- SQLite-WAL-/SHM-Dateien werden vor dem Datenbanktausch entfernt.
- Container startet nach erfolgreicher Wiederherstellung automatisch neu.
- `restore-backup.sh` unterstützt zusätzlich verschlüsselte `.bbm`-Backups und fragt die Passphrase verdeckt ab.

### Dokumentation und Tests

- README, Installationsanleitung und integrierte Anleitung um Joblayout, Schlüsselrotation, Backup-Verschlüsselung und Wiederherstellung ergänzt.
- Regressionstests für verschlüsselte Backups, falsche Passphrasen, Schlüsselarchivierung und neue UI-Struktur ergänzt.

## v0.8.7

### Zeitzone Europe/Berlin

- WebUI interpretiert offsetlose SQLite-Zeitwerte korrekt als UTC und stellt sie verbindlich in `Europe/Berlin` dar.
- Start-, End-, Prüf-, Archiv- und Backup-Zeitpunkte verwenden dieselbe Darstellungslogik.
- APScheduler und alle Cron-Ausdrücke laufen mit `Europe/Berlin`, einschließlich Sommer-/Winterzeit.
- Remote gestartete Borg-Befehle erhalten `TZ=Europe/Berlin`, damit Borg-Statistik und WebUI dieselben lokalen Zeiten zeigen.
- Container installiert `tzdata`; Compose verwendet weiterhin `TZ=${TZ:-Europe/Berlin}`.

### Gefilterte Ausführungsansicht

- Dashboard-Kacheln „Laufend“ und „Fehlgeschlagen“ öffnen direkt eine passende Statusansicht.
- Der Aufmerksamkeitshinweis für fehlgeschlagene Ausführungen öffnet ebenfalls ausschließlich fehlgeschlagene Läufe.
- Ausführungen können nach Alle, laufend/wartend, fehlgeschlagen, Warnung, erfolgreich oder abgebrochen gefiltert werden.
- Zusätzlich steht eine Suche nach Lauf-ID, Job, Aktion, Status oder Diagnose zur Verfügung.
- Der Filter wird im URL-Fragment gespeichert und bleibt bei Reload sowie Browsernavigation erhalten.

### Kompaktere Oberfläche für viele Clients

- Backup-Jobs, Geräte, Repositories, letzte Aktivitäten und Ausführungen werden auf Desktop als kompakte Tabellen dargestellt.
- Responsive Karten-/Tabellendarstellung bleibt auf kleinen Bildschirmen bedienbar.
- Backup-Jobs besitzen Suche nach Job, Gerät, Repository und Quellpfad sowie einen Aktivstatusfilter.
- Seltene Jobaktionen werden in einer stabilen, aufklappbaren Detailzeile angezeigt.
- Abstände, Dashboard-Kacheln, Panels und Aktionsbuttons wurden verdichtet, ohne Informationen zu entfernen.

### Passphrasendiagnose korrigiert

- Laufdiagnosen werden bei laufenden oder wartenden Jobs nicht mehr aus vorläufigen Logfragmenten erzeugt.
- „Passphrase abgelehnt“ erscheint nur noch bei einer eindeutigen finalen Borg-Fehlermeldung.
- Generische Wörter wie `passphrase` oder `incorrect` reichen nicht mehr zur Fehlerklassifikation aus.

### Laufprotokolle konsequent von SQLite getrennt

- Vollständige Ausgaben liegen ausschließlich unter `/data/run-logs/run-ID.log`.
- SQLite-Vorschauen sind fest begrenzt auf 4 KiB stdout, 8 KiB stderr und 16 KiB Bedienprotokoll.
- Der Borg-Prozess puffert bei `--list` nicht mehr die vollständige Dateiliste im Arbeitsspeicher.
- Vorhandene große DB-Protokolle werden beim ersten Start in Logdateien migriert, gekürzt und anschließend per `VACUUM` freigegeben.
- Aufbewahrungszeit, manuelle Bereinigung und Einzel-Löschung bleiben unverändert verfügbar.

## v0.8.6

### Borg-Version im Live-Protokoll

- Falsche Warnungen wie `Borg 1.02.1` behoben.
- Die Versionsauswertung durchsucht nicht mehr beliebige Dateinamen und Pfade im `--list`-Protokoll.
- Vorrangig ausgewertet wird ausschließlich die eindeutige Zeile `BORG AUF CLIENT: X.Y.Z`.
- Bekannte direkte Ausgaben wie `borg X.Y.Z` und `BorgBackup version X.Y.Z` bleiben für Versionsprüfungen kompatibel.
- Die erkannte Clientversion wird zusätzlich als Snapshot am Lauf gespeichert und bleibt dadurch auch bei sehr langen oder gekürzten Logs stabil.

### Ausführungsprotokolle und Speicherbereinigung

- Vollständige neue Live-Protokolle werden als Dateien unter `/data/run-logs/run-ID.log` gespeichert.
- SQLite speichert nur Metadaten sowie begrenzte stdout-, stderr- und Live-Vorschauen.
- Dashboard und Ausführungsliste laden keine vollständigen Logs mehr; das Log wird erst beim Öffnen eines einzelnen Laufs gelesen.
- Maximale Logdateigröße je Lauf ist konfigurierbar; bei Überschreitung bleiben Protokollanfang und aktuelles Ende einschließlich Abschlussstatistik erhalten.
- Maximale in der WebUI geladene Protokollgröße ist separat konfigurierbar.
- Einstellungen zeigen Anzahl der Läufe, Größe der Logdateien, DB-Protokollanteil und Größe der SQLite-Datei.
- Abgelaufene Protokolle können sofort manuell bereinigt werden.
- Optional können alle abgeschlossenen Protokolle gelöscht werden; laufende und wartende Läufe bleiben erhalten.
- Einzelne abgeschlossene Ausführungsprotokolle können direkt in der Laufübersicht gelöscht werden.
- Die automatische Bereinigung läuft weiterhin täglich um 03:30 Uhr; Standardaufbewahrung bleibt 90 Tage.
- Manuelle Bereinigung führt zusätzlich SQLite `VACUUM` aus, damit freier Datenbankplatz tatsächlich zurückgewonnen wird.
- Bestehende DB-Protokolle aus älteren Versionen bleiben lesbar und werden von der Aufbewahrungsregel erfasst.

## v0.8.5

### Live-Protokoll bei Backup-Jobs

- Backup-Jobs zeigen auf Wunsch jede von Borg verarbeitete Datei mit Borg-Status und Pfad an.
- Die neue Joboption **„Verarbeitete Dateien im Live-Protokoll anzeigen“** ist standardmäßig aktiviert und kann bei sehr großen Sicherungen deaktiviert werden.
- Der Backup-Befehl verwendet dafür das mit Borg 1.2 bis 1.4 kompatible `borg create --list`.
- Die Borg-Version wird eindeutig als **„Borg auf Client“** bezeichnet.
- Die interne Ausgabe `BBM_BORG_VERSION=...` wurde aus dem normalen Protokoll entfernt.
- Die Borg-Version des Managers wird nicht mehr mit der beim Backup tatsächlich verwendeten Client-Version vermischt.
- JavaScript- und CSS-Cacheversion auf 0.8.5 aktualisiert.

## v0.8.4

### Paket- und Docker-Namen

- Release-ZIP enthält unabhängig von der Version nur noch den Hauptordner `BorgBackup-Manager/`.
- Neuinstallationen erzeugen dadurch keinen Projektordner mit Versionssuffix.
- Docker-Image explizit auf `borgbackup-manager:latest` festgelegt.
- Compose-Projektname auf `borgbackup-manager` festgelegt; die doppelte Image-Bezeichnung `borgbackup-manager-borg-manager` entfällt.
- Containername bleibt `borgbackup-manager`.

### Zentrale Ausschlussvorlagen

- Neue zentrale Ausschlussvorlagen unter **Einstellungen → Ausschlussvorlagen**.
- Mitgelieferte Vorlage **Linux-Systempfade** enthält `/proc`, `/sys`, `/dev`, `/run`, `/tmp` und `/var/tmp`.
- Beliebig viele benannte Vorlagen können angelegt, erweitert, umbenannt oder entfernt werden.
- Im Backup-Job kann eine Vorlage ausgewählt und mit einem Klick zur Ausschlussliste hinzugefügt werden.
- Vorhandene Muster werden nicht doppelt eingetragen.
- Vorlagen dienen bewusst als Kopiervorlage; spätere Änderungen verändern bereits gespeicherte Jobs nicht automatisch.
- Einstellungen bleiben in der bestehenden persistenten `settings.json` gespeichert; keine Datenbankmigration erforderlich.

### Anleitung und Anzeige

- Integrierte Anleitung vollständig auf alle Bereiche und Arbeitsabläufe erweitert.
- README und Installationsanleitung vollständig überarbeitet.
- Installation, Geräte, Repositories, Jobs, Borg-Optionen, Archivverwaltung, Export, Restore, Manager-Backup, Sicherheit und Diagnose detailliert beschrieben.
- Release-Notes-Anzeige erhält automatischen Zeilenumbruch, Wortumbruch und keine horizontale Überbreite mehr.
- Lange Befehle, Pfade und Textzeilen bleiben innerhalb der verfügbaren Anzeigefläche.

### Weitere Korrekturen

- Installer prüft nach dem Start `/api/ready` statt des umfassenden Komponentenendpunkts.
- JavaScript- und CSS-Cacheversion auf 0.8.4 aktualisiert.

## v0.8.3

### Update- und Healthcheck-Korrektur

- Update-Rollback bei tatsächlich erreichbarer und funktionsfähiger WebUI behoben.
- Neue öffentliche Bereitschaftsprüfung `/api/ready` prüft ausschließlich, ob WebAPI und Scheduler vollständig gestartet sind.
- Docker-Healthcheck verwendet `/api/ready` statt der strengen Komponentenprüfung `/api/health`.
- Repository-SSH-Banner und weitere Komponenten bleiben über `/api/health` diagnostizierbar; der Endpunkt liefert aus Kompatibilitätsgründen immer HTTP 200 und kennzeichnet Einschränkungen im JSON-Status.
- Neuer strenger Diagnoseendpunkt `/api/health/strict` liefert bei einem eingeschränkten Komponentenstatus HTTP 503.
- Dadurch akzeptiert auch das während des Updates noch laufende 0.8.2-Skript den ersten Start von 0.8.3 und führt keinen erneuten Fehlrollback aus.
- Ein vorübergehend fehlgeschlagener SSH-Banner-Test erzeugt nach erfolgreichem Webstart nur noch eine Warnung und keinen automatischen Rollback.
- Update-Skript prüft zuerst den veröffentlichten HTTPS-Port und verwendet `docker compose exec` nur als Fallback.
- Prüfzeit von 45 auf 90 Sekunden erhöht.
- Letzte HTTP-Antwort beziehungsweise konkrete Fehlermeldung wird bei einem echten Startfehler ausgegeben.
- Kompatibilitätsprüfung über die Startseite ergänzt, damit auch ein Rollback auf Version 0.8.2 oder älter zuverlässig als gestartet erkannt wird.

## v0.8.2

### HTTPS und Chrome-Anmeldung

- Unverschlüsselten WebUI-Listener auf Port 8080 entfernt; die WebUI wird ausschließlich über HTTPS auf dem konfigurierbaren Standardport 8443 ausgeliefert.
- Persistentes, beim ersten Start automatisch erzeugtes TLS-Zertifikat unter `/data/tls` ergänzt. Eigene Zertifikatsdateien können dort verwendet werden.
- Admin-Token-Anmeldung auf ein signiertes `HttpOnly`-/`Secure`-/`SameSite=Strict`-Session-Cookie umgestellt. Der Admin-Token verbleibt nicht mehr dauerhaft im Browser-`localStorage`.
- Falls bereits auf derselben HTTPS-Origin eine alte Tokenablage vorhanden ist, wird sie einmalig in eine Sitzung migriert und danach entfernt. Beim Wechsel von HTTP auf HTTPS ist wegen der neuen Browser-Origin eine einmalige Neuanmeldung erforderlich.
- WebUI-, API- und JavaScript-Antworten erhalten `no-store`, damit Chrome nach Updates keine inkompatible alte Oberfläche aus dem Cache weiterverwendet.
- Kurzes HSTS-Fenster ohne Subdomain-Zwang ergänzt.

### Backup-Job-Ansicht

- Kleine, außerhalb des sichtbaren Bereichs öffnende Aktions-Popups durch einen vollständigen Inline-Bereich in jeder Jobkarte ersetzt.
- Aktionen logisch in **Prüfen**, **Speicherpflege** und **Verwalten** gruppiert.
- Geöffnete Bereiche **Weitere Aktionen** werden gespeichert und bleiben bei Statusaktualisierungen geöffnet.
- Automatische Hintergrundaktualisierung rendert die aktive Jobansicht nicht mehr unkontrolliert neu.
- Jobliste nicht mehr in einen kleinen internen Scrollblock gezwungen; die normale Seitennavigation übernimmt das Scrollen.

### Archivexport

- Dateien und Ordner können im Archivbrowser markiert und direkt als TAR.GZ heruntergeladen werden.
- Export läuft bei verwalteten Repositories lokal im Manager gegen den eingebundenen Repository-Pfad.
- Temporäre Extraktions- und Archivdateien werden nach dem Download automatisch entfernt.
- Exportstatus und Fehler bleiben dauerhaft sichtbar und kopierbar.

### Wiederherstellung

- Generischen Formularhandler entfernt, der zuvor nur **Gespeichert** meldete und keinen sichtbaren Restore-Ablauf startete.
- Restore besitzt jetzt einen eigenen Handler, zeigt die gestartete Lauf-ID und öffnet sofort das Live-Protokoll.
- Neuer Zielmodus **Am ursprünglichen Speicherort**: ausgewählte Archivpfade werden relativ zu `/` wiederhergestellt. Produktive Läufe benötigen eine ausdrückliche Überschreibbestätigung.
- Alternativer Zielmodus unterstützt zwei Layouts: Auswahl direkt im Ziel oder vollständige Archivpfade.
- Für die direkte Ablage im Ziel berechnet der Manager `--strip-components` aus dem gemeinsamen übergeordneten Pfad der Auswahl.
- Dry-Run schreibt keine Dateien und benötigt kein Zielverzeichnis.

### Update und Migration

- Installer, Update-Healthcheck, Vollbackup-Migrationsdaten und Wiederherstellungsskript auf HTTPS-Port 8443 umgestellt.
- Alte `BBM_HTTP_PORT`-Werte werden beim Installations-/Restore-Ablauf als Migrationsvorgabe übernommen.
- Bestehende Geräte, Jobs, Repositories, Archive, Schlüssel und Laufprotokolle bleiben unverändert erhalten.

## v0.8.1

### Archivverwaltung ohne unnötigen SSH-Umweg

- Verwaltete Repositories werden für Archivliste, Archivinformationen, Check, Datenprüfung, Prune, Compact, Diff, Rename und Einzellöschung direkt über ihren eingebundenen Pfad im Manager-Container geöffnet.
- Diese Verwaltungsaktionen verbinden sich nicht mehr über einen Backup-Client zurück zum integrierten Repository-SSH-Port 2222.
- Backup und Restore bleiben bewusst Client-Aktionen, weil die Quell- beziehungsweise Zieldateien auf dem jeweiligen Gerät liegen.
- Externe Repositories werden weiterhin über den ausgewählten Zugriffsclient verwaltet, da dafür kein lokaler Repository-Pfad im Manager vorhanden ist.
- Lokale Verwaltungsbefehle laufen weiterhin als eingeschränkter Benutzer `borg`, übernehmen die Repository-Passphrase sicher über Dateideskriptor 0 und stellen gespeicherte Keyfiles nur temporär bereit.

### Manuell stabile Archivübersicht

- Archivlisten werden ausschließlich mit **Archive laden** aktualisiert.
- Der globale Auto-Refresh für Dashboard, Jobs und Ausführungen verändert die geöffnete Archivliste nicht mehr.
- Beim Wechsel von Job oder Repository-Ansicht wird die alte Liste bewusst verworfen und eine manuelle Aktualisierung angefordert.
- Während einer Aktualisierung bleibt eine bereits sichtbare Liste erhalten.
- Schlägt die Aktualisierung fehl, bleibt die vorherige Liste sichtbar und die Fehlermeldung dauerhaft oberhalb der Liste stehen.
- Parallele beziehungsweise verspätete Archivabfragen werden über eine Request-ID verworfen und können keine neuere Ansicht mehr überschreiben.

### Archivbrowser ohne FUSE

- **Einhängen & durchsuchen** wurde durch **Inhalt durchsuchen** ersetzt.
- Der Browser liest Archivverzeichnisse mit `borg list --json-lines` und lädt jeweils nur die direkte Verzeichnisebene.
- `borg mount`, `fuse3`, `fusermount`, `mountpoint`, `findutils` und `/dev/fuse` werden für den normalen Archivbrowser nicht mehr benötigt.
- Verwaltete Repositories werden lokal im Manager durchsucht; externe Repositories weiterhin über den Zugriffsclient.
- Dateien, Verzeichnisse und symbolische Links werden robust aus verschiedenen Borg-1.x-Typdarstellungen erkannt.
- Ausgewählte Pfade können wie bisher direkt in den Restore-Dialog übernommen werden.
- Browserfehler bleiben dauerhaft im geöffneten Bereich sichtbar und können kopiert werden.

### Übergang von alten Mount-Sitzungen

- Bestehende FUSE-Mount-Sitzungen aus 0.7.x oder 0.8.0 werden nicht stillschweigend vergessen.
- Sind noch alte Sitzungen registriert, erscheint ein eigener Bereich **Alte FUSE-Mounts**.
- Dort können diese Sitzungen kontrolliert ausgehängt und aus der Datenbank entfernt werden.
- Neue Browser-Sitzungen erzeugen keine Mount-Einträge mehr.

### Dokumentation und Prüfung

- README, Installationsanleitung und integrierte Hilfe auf direkten lokalen Repository-Zugriff, manuelle Archivaktualisierung und FUSE-freies Browsen umgestellt.
- Parser- und Oberflächentests für vollständige Borg-Typnamen, numerische Größen als Zeichenfolge, symbolische Links, lokale Repository-Aktionen, manuelle Aktualisierung und alte Mount-Sitzungen ergänzt.

## v0.8.0

### Debian Trixie und Borg 1.4

- Containerbasis von Debian Bookworm auf **Debian 13 Trixie** umgestellt.
- Python-Basis auf `python:3.13-slim-trixie` aktualisiert.
- Borg wird direkt aus dem regulären Trixie-Paketbestand installiert; Bookworm Backports wurden vollständig entfernt.
- Image-Build verlangt Borg 1.4.x und verhindert versehentliches Borg 2.x.
- Integrierter Repository-SSH-Dienst arbeitet damit mit Borg 1.4, bleibt aber für Borg-1.2-bis-1.4-Clients nutzbar.

### Borg 1.2.0 bis 1.4.x

- Mindestversion für Quellclients auf Borg 1.2.0 abgesenkt.
- Borg 1.2.0 bis 1.2.4 wird nicht mehr blockiert, sondern mit einer auffälligen kritischen Sicherheitswarnung weitergeführt.
- Borg 1.2.5 bis 1.2.7 erhält eine normale Aktualisierungswarnung.
- Borg 1.2.8 bis 1.4.x wird ohne Warnung freigegeben.
- Versionen unter 1.2.0 und Borg 2.x bleiben technisch ausgeschlossen.
- Robuste Versionsabfrage mit Fallback über `borg --version`, `borg -V` und `borg --show-version help`.
- Borg-Version, Warnstatus und letzter Prüfzeitpunkt werden je Gerät gespeichert.
- Neue direkte Geräteaktion **Borg prüfen** funktioniert bereits vor dem ersten Backup-Job.
- Dashboard zeigt Clients mit kritischer, veralteter oder unbekannter Borg-Version im Bereich **Aufmerksamkeit**.

### Lesbare Live-Ausgabe

- `borg create --json` aus Backup-Jobs entfernt.
- Backup-Läufe verwenden wieder Borgs normale `--stats`-Darstellung mit Start, Ende, Dauer, Dateianzahl, Originalgröße, komprimierter Größe und deduplizierter Größe.
- Jeder Lauf erhält einen klaren Kopf mit Job, Gerät, Quellen, Repository und Borg-Version.
- Abschließender Ergebnisblock unterscheidet Erfolg, Warnung und Fehlercode.
- stdout und stderr werden zusätzlich in tatsächlicher Ankunftsreihenfolge in einem gemeinsamen Bedienprotokoll gespeichert.
- Neue Protokollansicht mit Status, Startzeit, Dauer und Laufnummer.
- Standardregister **Lesbare Ausgabe** blendet den langen SSH-Befehl aus.
- Register **Technische Details** enthält weiterhin vollständigen Befehl, stdout und stderr für die Fehleranalyse.
- Alte Läufe bleiben lesbar; fehlt das neue gemeinsame Protokoll, wird es aus den bisherigen Feldern aufgebaut.

### Überarbeitete Oberfläche

- Navigation nach Betrieb, Daten, Infrastruktur und Information gruppiert.
- Systemschrift statt dekorativer Dokumentenschrift; höhere Informationsdichte und klarere Hierarchie.
- Dashboard-Kennzahlen reduziert und priorisiert.
- Neuer Bereich **Aufmerksamkeit** für fehlgeschlagene Läufe und Borg-Versionswarnungen.
- Jobansicht auf drei Primäraktionen reduziert: Backup starten, Archive und Verbindung prüfen.
- Wartung, Prüfungen, Prune, Compact, Bearbeiten und Löschen kompakt unter **Weitere Aktionen**.
- Geräte zeigen Borg-Version und Warnstatus direkt als Badge.
- Responsive Darstellung für Desktop, Tablet und Smartphone vollständig neu aufgebaut.

### Gemeinsamer Borg-1.2-bis-1.4-Funktionsumfang

- Alle zentral erzeugten Backup-, Listen-, Info-, Check-, Verify-, Prune-, Compact-, Diff-, Mount-, Delete-, Rename- und Restore-Befehle gegen den Borg-1.2-Funktionsumfang abgeglichen.
- Maschinenlesbares JSON bleibt nur bei internen Archiv- und Metadatenabfragen erhalten.
- Backup-Protokolle verwenden bewusst keine JSON-Ausgabe.
- Kompressionsauswahl gegen Borg 1.2.0 abgeglichen: `none`, `lz4`, `zstd`, `zlib`, `lzma`, `auto` und `obfuscate`.
- Obfuscate bleibt verfügbar, wird aber in der Oberfläche ausdrücklich nur für verschlüsselte Repositories empfohlen.

### Migration und Dokumentation

- Additive Datenbankmigration für Borg-Version, Versionsstatus, Prüfzeitpunkt und gemeinsames Laufprotokoll.
- README, Installationsanleitung und integrierte Hilfe auf Trixie, Borg 1.2.0–1.4.x, Warnstufen und neue Protokollansicht aktualisiert.
- Regressionstests für Versionsparser, CLI-Fallbacks, Warnstufen, Trixie-Image und lesbare Backup-Befehle ergänzt.

## v0.7.0

### Archivverwaltung im Vorta-orientierten Arbeitsablauf

- Neuer eigener Bereich **Archive** mit Auswahl eines Zugriffs-/Ziel-Jobs. Dieser Client führt Repository-Aktionen, Mount und Restore aus.
- Wahlweise nur Archive des ausgewählten Jobs oder alle Archive des zugehörigen Repositorys anzeigen.
- Archivnamen werden anhand der dauerhaften Jobpräfixe einem Job zugeordnet; Altbestände und nicht mehr zuordenbare Archive erscheinen als Legacy-/fremde Archive.
- Archivinformationen für einen exakten Archivnamen abrufen.
- Zwei Archive über `borg diff --json-lines` vergleichen; optionale relative Pfade und `--content-only` werden unterstützt.
- Archive umbenennen. Bei bekannten Jobarchiven muss das Jobpräfix erhalten bleiben, damit Besitzerzuordnung und Prune weiterhin korrekt funktionieren.
- Einzelne Archive exakt löschen; der Benutzer entscheidet separat, ob anschließend sofort ein repositoryweites Compact ausgeführt wird.
- Löschablauf behandelt Borg-Warnungen korrekt: Bei Rückgabecode 1 wird ein ausgewähltes Compact trotzdem ausgeführt, echte Fehler ab Rückgabecode 2 brechen ab.

### Archiv einhängen, durchsuchen und auswählen

- Archive werden auf dem ausgewählten Client mit `borg mount` unter `~/.local/share/bbm/mounts/` eingehängt.
- Vor dem Mount werden `mountpoint`, `fusermount3` beziehungsweise `fusermount` und `/dev/fuse` geprüft; Fehlermeldungen nennen die fehlende Voraussetzung.
- Neue persistente Mount-Sitzungen erlauben **Weiter durchsuchen** nach einem Seitenwechsel oder Reload.
- Browser lädt nur eine Verzeichnisebene und eignet sich dadurch auch für große Archive.
- Dateien und Ordner können im Browser markiert und direkt in das Restore-Formular übernommen werden.
- Aktive Mounts blockieren Delete, Rename und Job-Löschung, bis sie kontrolliert ausgehängt wurden.

### Restore mit echter Archivauswahl

- Nach Auswahl eines Backup-Jobs werden die tatsächlich verfügbaren Archivnamen aus Borg geladen und als Auswahlfeld angeboten.
- Repositoryweite beziehungsweise Legacy-Archive können über eine ausdrückliche Freigabe ausgewählt werden.
- Auswahl aus dem Archivbrowser wird als sichere relative Pfadliste übernommen.
- Borg-Archivnamen mit ISO-Zeitstempeln, Doppelpunkten und internen Leerzeichen werden korrekt akzeptiert. Pfadtrenner, NUL, Zeilenumbrüche, `::` und Optionspräfixe bleiben gesperrt.
- Produktive Restores werden nur in leere, nicht symbolisch verlinkte Zielverzeichnisse zugelassen. Ein Dry-Run legt kein Zielverzeichnis mehr an.

### Mehrere Clients in einem Repository

- Die künstliche Ein-Gerät-Sperre für verwaltete Repositories wurde entfernt.
- Jeder Client behält einen eigenen Ed25519-Schlüssel pro Repository und einen eigenen Forced-Command-Eintrag.
- Bei verwalteten Keyfile-Repositories wird der entschlüsselte Borg-Key nur temporär für den jeweiligen Borg-Aufruf auf dem Client erzeugt und anschließend auch bei Signalabbruch entfernt.
- Jobs verschiedener Clients bleiben durch ihre Jobpräfixe für Liste, Archivprüfung, Datenprüfung und Prune getrennt. Die vorgelagerte Repository-Segmentprüfung von Borg Check bleibt repositoryweit.
- Aktionen werden weiterhin innerhalb einer Manager-Instanz repositoryweit serialisiert.
- Systemdiagnose zählt gemeinsam genutzte Repositories nur noch als Information; dies ist kein Fehlerzustand mehr.
- Dokumentation weist ausdrücklich darauf hin, dass ein gemeinsam genutztes Repository keine Sicherheitsisolation zwischen den Clients bietet.

### Jobs zuverlässig löschen

- Vorhandene Borg-Archive blockieren das Löschen eines Jobs nicht und werden dabei nicht verändert.
- Abgeschlossene Ausführungsprotokolle werden vor der Job-Löschung entkoppelt und behalten den bisherigen Jobnamen als Snapshot.
- Nur laufende beziehungsweise wartende Ausführungen und aktive Archiv-Mounts blockieren die Löschung.
- Archive eines gelöschten Jobs bleiben in der repositoryweiten Archivansicht als Legacy-/fremde Archive sichtbar.

### Vorhandene Repositories wieder einbinden

- Repository-Verzeichnis kann nach noch nicht registrierten Borg-Repositories durchsucht werden.
- Erkannt werden direkte Unterverzeichnisse mit einer Borg-Datei `config`.
- Import unterstützt alle angebotenen Borg-1.2-Verschlüsselungsmodi, Passphrase und vorhandenen Keyfile-Inhalt.
- Vor der Registrierung führt der Manager ein echtes `borg info` als eingeschränkter Borg-Benutzer aus.
- Bei einer fehlgeschlagenen Prüfung wird der unvollständige Datenbankeintrag zurückgerollt; Repository-Nutzdaten werden nicht verändert.

### Navigation und Oberfläche

- Aktive Hauptseite wird im URL-Fragment gespeichert, beispielsweise `#archives` oder `#restore`.
- Browser-Reload bleibt auf der aktuell geöffneten Seite und springt nicht mehr zum Dashboard.
- Archivansicht, Restore-Auswahl, Repository-Erkennung und Mount-Browser wurden responsiv in die vorhandene WebUI integriert.
- Dynamische Archiv-, Repository- und Backup-Namen werden nicht mehr als unsichere Inline-JavaScript-Argumente ausgegeben, sondern über sichere Datenattribute gebunden.

### Plausibilitäts- und Sicherheitskorrekturen

- Mindestversion für Quellclients auf Borg 1.2.8 bis kleiner 2.0 festgelegt. Der Verbindungstest stoppt ältere beziehungsweise noch nicht unterstützte Hauptversionen mit eigener Diagnose.
- Manager-Image bezieht Borg aus Debian Bookworm Backports und validiert beim Build ebenfalls den unterstützten Versionsbereich.
- Archivnamen erlauben gültige Doppelpunkte und interne Leerzeichen, lehnen aber Pfadtrenner, NUL, Zeilenumbrüche, `::` und Optionspräfixe ab.
- Import-Passphrasen müssen nichtleer und einzeilig sein; Borg-Keyfiles dürfen weiterhin mehrzeilig sein.
- Delete, Rename und Diff prüfen vor dem Start, ob die genannten Archive im Repository vorhanden sind.
- Rename verhindert Kollisionen mit vorhandenen Archivnamen und schützt das Jobpräfix.
- Diff akzeptiert ausschließlich sichere relative Archivpfade.
- Job-Löschung verändert niemals implizit Borg-Daten.
- Neue Jobs erhalten ein nicht wiederverwendbares Präfix wie `bbm-job-12-a1b2c3d4e5f60718-`. Dadurch können gelöschte Job-IDs später nicht versehentlich alte Archivserien übernehmen oder prunen. Bestehende Präfixe bleiben unverändert.

### Dokumentation und Prüfung

- README und Installationsanleitung vollständig auf 0.7.0, Mehrgeräte-Repositories, Repository-Import, Archivverwaltung, Mount/Browse, Restore und Job-Löschung aktualisiert.
- Automatisierte Tests für Mehrgeräte-Zuordnung, Job-Löschung mit Historie, Repository-Erkennung, gültige ISO-Archivnamen, Delete, Rename, Diff, Mount, Browser, sichere Restore-Ziele und nicht wiederverwendbare Jobpräfixe ergänzt.

## v0.6.0

### Repository-SSH-Verbindung und Überwachung

- Fehlerbild „Connection closed by remote host“ korrekt auf die SSH-Phase eingegrenzt. Ein Abbruch direkt nach `Connecting ... port 2222` und vor `Remote protocol version` liegt vor Hostkey-Prüfung, Anmeldung, `authorized_keys`, Forced Command und Borg.
- Repository-sshd läuft nicht mehr unbeaufsichtigt als daemonisierter Nebenprozess. EntryPoint startet ihn mit `sshd -D`, überwacht PID und WebAPI gemeinsam und beendet den Container, sobald einer der beiden Dienste ausfällt.
- Start- und Docker-Healthcheck prüfen nicht mehr nur eine geöffnete TCP-Verbindung, sondern lesen einen gültigen `SSH-`-Banner. Damit wird auch ein Dienst erkannt, der TCP annimmt und sofort wieder schließt.
- Basisimage auf Debian Bookworm mit Borg 1.2.x vereinheitlicht.
- SSH-Konfiguration gehärtet: ausschließlich Public-Key-Authentifizierung, kein TTY, kein Port-/Agent-/X11-Forwarding, keine User-RC-Skripte, Keepalive und begrenzte Authentifizierungsversuche.
- Verbindungstest erweitert: Client-Borg-Version, Schlüsseldateien, `ssh-keyscan`-Banner/Hostkey, `ssh -vv` und `borg info` werden in einer nachvollziehbaren Kette geprüft.
- Diagnose unterscheidet jetzt eindeutig zwischen Abbruch vor SSH-Banner, Abbruch während Aushandlung/Anmeldung und Abbruch nach erfolgreicher SSH-Anmeldung.

### Repositoryspezifische Gerätezugänge

- Globalen Repository-Schlüssel pro Gerät durch einen eigenen Ed25519-Schlüssel pro Gerät und verwaltetem Repository ersetzt.
- Jeder Schlüssel wird mit `restrict` und einem Forced Command exakt auf ein Repository beschränkt:
  `borg serve --restrict-to-repository /repositories/...`.
- Alte globale BBM-Schlüssel werden beim Neuaufbau von `authorized_keys` entfernt.
- Repository-Zugang kann nach neuen Jobzuordnungen, Clientänderungen oder Serverwechseln jederzeit erneuert werden.
- Systemdiagnose vergleicht Datenbank-Zugänge, vollständig provisionierte Zugänge und tatsächliche `authorized_keys`-Einträge.
- Verwaltete Repositories dürfen bei neuen oder geänderten Jobs nur einem Gerät zugeordnet werden. Mehrere Jobs desselben Geräts bleiben möglich. Bestehende problematische Mehrgeräte-Zuordnungen werden in der Systemdiagnose sichtbar.

### Jobbezogene Archivbereiche

- Jeder Job erhält dauerhaft ein Präfix `bbm-job-ID-`.
- Backup-Archivnamen werden automatisch mit diesem Präfix erzeugt.
- Archive, Info, Archivprüfung, Datenprüfung und Prune verwenden `--glob-archives bbm-job-ID-*`; die Repository-Segmentprüfung von Borg Check bleibt repositoryweit.
- **Alle Archive** bleibt als ausdrücklich repositoryweite Diagnose- und Migrationsfunktion verfügbar.
- Restore akzeptiert standardmäßig nur Archive des ausgewählten Jobs. Archive vor 0.6.0 können nur mit aktivierter Legacy-Freigabe wiederhergestellt werden.
- Alte Archive ohne Jobpräfix werden vom neuen Prune nicht gelöscht.

### Nebenläufigkeit und Aufbewahrung

- Aktionen werden nicht mehr nur pro Job, sondern repositoryweit serialisiert. Zwei Jobs gegen dasselbe Repository laufen somit niemals gleichzeitig innerhalb einer Manager-Instanz.
- Borg-Befehle verwenden einheitlich `--lock-wait 600`.
- Prune unterstützt zusätzlich `--keep-last`.
- Nullwerte werden weiterhin vollständig aus dem Prune-Befehl entfernt; Prune startet nur mit mindestens einer positiven Regel.
- Geplanter Ablauf ist jetzt konsistent: Backup, danach optional Prune und nach erfolgreichem Prune optional Compact.
- Compact bleibt bewusst repositoryweit, da erst diese Aktion nicht mehr referenzierten Speicher physisch freigibt.

### Borg-1.2-Optionen und Plausibilitätsprüfung

- Create-Optionen ergänzt und validiert:
  - `--one-file-system`
  - `--exclude-caches`
  - `--exclude-nodump`
  - `--numeric-ids`
  - `--files-cache`
  - `--checkpoint-interval`
- Datei-Cache-Auswahl auf die dokumentierten Borg-1.2-Werte begrenzt: `ctime,size,inode`, `mtime,size,inode`, `ctime,size`, `mtime,size`, `rechunk,ctime`, `rechunk,mtime`, `disabled`.
- Ungültigen Modus `rechunk,ctime,size,inode` entfernt.
- Kompressionsvalidierung auf Borg-1.2-Syntax korrigiert. Zstd-Level 1–22, zlib/lzma 0–9 sowie gültige `auto`- und `obfuscate`-Ketten werden unterstützt; ungültiger Modus 250 wurde entfernt.
- Direkte Passphrasen müssen nichtleer und einzeilig sein.
- Bewusst konfigurierte unverschlüsselte beziehungsweise authentifizierte Repositorys werden nichtinteraktiv bestätigt, damit der erste Lauf nicht an Borgs Sicherheitsabfrage hängen bleibt.
- `borg check --repair` und automatisches `break-lock` bleiben aus Sicherheitsgründen ausgeschlossen.

### Oberfläche, Dokumentation und Migration

- Einrichtungsreihenfolge korrigiert: Repository und Job zuerst zuordnen, anschließend repositoryspezifischen Gerätezugang einrichten.
- Repository-Zugangsbutton bleibt ohne verwaltete Zuordnung deaktiviert und erklärt den notwendigen nächsten Schritt.
- Systemdiagnose zeigt SSH-Bannerstatus, Forced-Command-Integrität, Zugangsvollständigkeit und unerwünschte Mehrgeräte-Repositories.
- Integrierte Hilfe, README und Installationsanleitung vollständig an Architektur, Borg-Semantik, Update, Fehlerdiagnose und Sicherheitsgrenzen angepasst.
- Nach einem Update von 0.5.x müssen alle Geräte mit verwalteten Jobs einmal über **Repository-Zugang erneuern** reprovisioniert werden.
- Archive aus 0.5.x sind Legacy-Archive und werden über **Alle Archive** beziehungsweise die explizite Legacy-Restore-Freigabe behandelt.
- Unbegrenztes Wachstum reduziert: sshd-/borg-serve-Logs werden größenbasiert rotiert; abgeschlossene Ausführungsprotokolle besitzen eine konfigurierbare Aufbewahrung von standardmäßig 90 Tagen.
- Testabdeckung auf 87 automatisierte Tests erweitert.

## v0.5.1

- Echten Repository-Verbindungstest pro Job ergänzt. Er prüft auf dem Client Borg und die provisionierten SSH-Dateien und führt anschließend mit ausführlichem SSH-Debugging ein `borg info` gegen das konfigurierte Repository aus.
- Repository-SSH-Logging ergänzt: `sshd` schreibt Authentifizierungs- und Sitzungsfehler dauerhaft nach `/data/logs/sshd.log`; die Systemdiagnose zeigt dieses Protokoll getrennt vom `borg-serve`-Log an.
- Forced-Command-Wrapper erweitert: Benutzer, UID/GID, Gegenstelle, Arbeitsverzeichnis, Originalbefehl, Borg-Version und konkrete R/W/X-Berechtigungsfehler werden protokolliert.
- Startprüfung für den Repository-Mount von nur „schreibbar“ auf lesbar, schreibbar und durchsuchbar erweitert.
- Eigentümer und Modi persistenter Controller- und Repository-SSH-Schlüssel werden beim Containerstart ausdrücklich normalisiert.
- Irreführende Diagnose korrigiert: „Connection closed“ beweist keinen erfolgreichen Repository-SSH-Login.
- Verwaltete Repository-URLs werden beim Managerstart aus dem aktuellen öffentlichen Repository-Endpunkt aktualisiert.
- Repository-Zugang eines Geräts kann erneut provisioniert werden.
- Kritischen Prune-Fehler behoben: Aufbewahrungswerte `0` werden nicht mehr als `--keep-… 0` ausgeführt.

## v0.5.0

- Borg-1.2-Kompatibilität korrigiert: Client-Test verwendet `borg --version`.
- Berechtigungen des integrierten Repository-SSH-Diensts korrigiert.
- WebUI-Vollbackups und geführte Wiederherstellung für Serverwechsel ergänzt.
- Repository-Größencache und Einstellungsbereich ergänzt.
- Laufnummern, integrierte Anleitung, Release Notes und begrenzte Listenbereiche ergänzt.

## v0.4.0

- Backup-Jobs vollständig bearbeitbar gemacht.
- Live-Log, Abbruch, Wiederholung, Laufzeit und Fehlerdiagnosen ergänzt.
- Warteschlange und Repository-Serverdiagnose ergänzt.
- Frühe Forced-Command-Absicherung des Repository-Diensts eingeführt.
- Speicherplatz-Sperre und Wiederanlaufbehandlung ergänzt.

## v0.3.0

- Alle Borg-1.x-Verschlüsselungsmodi und geschützte Keyfile-Verwaltung ergänzt.
- Borg-Kompressionsauswahl und persistenter Hell-/Darkmode ergänzt.
- Gerätebearbeitung, Dashboard-Verknüpfungen und additive Migrationen ergänzt.

## v0.2.0

- Geführten Linux-Installer, getrennte Persistenzpfade und integrierten Borg-SSH-Repository-Dienst ergänzt.
- Verwaltete Repositories, verschlüsselte Passphrasen, SSH-Fingerprint-Prüfung und Update-System ergänzt.

## v0.1.0

- Erste MVP-Version mit Geräten, externen Repositories, Backup-Jobs, Scheduler, Protokollen und Restore-Testlauf.
