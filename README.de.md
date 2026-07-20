# BorgBackup Manager 1.0.54

BorgBackup Manager ist eine zentrale Webverwaltung für BorgBackup-1.x-Clients. Der Manager erstellt und plant Backup-Jobs, verwaltet Repositories und Archive, führt Prüfungen aus und steuert Wiederherstellungen. Auf den Quellgeräten ist kein eigenes Backup-Skript und kein lokaler Cronjob erforderlich.

Die englische Standarddokumentation befindet sich in `README.md`. Die deutschen Markdown-Dateien verwenden durchgehend die Endung `.de.md`: `README.de.md`, `INSTALLATION.de.md` und `RELEASE_NOTES.de.md`.

## Systembasis

- Containerbasis: Debian 13 Trixie
- Borg im Manager: Borg 1.4.x
- Unterstützte Clientversionen: Borg 1.2.0 bis 1.4.x
- WebUI: ausschließlich HTTPS
- Repository-Dienst: integrierter OpenSSH-Dienst mit eingeschränktem `borg serve`
- Persistente Daten: standardmäßig `/docker_data/borgbackup-manager/data`
- Persistente Repositories: standardmäßig `/docker_data/borgbackup-manager/repositories`
- Docker-Image: `borgbackup-manager:latest`
- Zeitzone für WebUI, Cron-Zeitpläne und Borg-Läufe: `Europe/Berlin`
- Containername: `borgbackup-manager`
- Container-Hostname: `bbm`
- Installationsskripte: strikter Shell-Modus mit geprüften Standardpfaden und früh initialisierter Zeitzone

## Paketstruktur

Das Release-ZIP besitzt unabhängig von der Versionsnummer immer denselben Hauptordner:

```text
BorgBackup-Manager/
```

Dadurch muss nach einem Update oder einer Neuinstallation kein versionsabhängiger Projektordner umbenannt werden. Der ZIP-Dateiname enthält weiterhin die Version, beispielsweise:

```text
BorgBackup-Manager-1.0.54.zip
```

## Sicherheit und Härtung

- FastAPI und die vollständig aufgelösten Laufzeitabhängigkeiten sind auf feste Versionen gesperrt; die eingesetzte Starlette-Version enthält die Korrektur für die Range-Header-DoS-Schwachstelle.
- Browseränderungen benötigen den anwendungsinternen Header `X-BBM-Request: 1`; vorhandene `Origin`-Header müssen zur tatsächlichen Manager-URL passen.
- Anmeldungen werden persistent pro Quelladresse und pro Kombination aus Quelle und Benutzer begrenzt. Ein Angreifer kann dadurch kein Konto systemweit sperren.
- Sitzungen laufen standardmäßig nach 24 Stunden absolut oder nach 60 Minuten Inaktivität ab.
- `Forwarded`- und `X-Forwarded-*`-Header werden ausschließlich von explizit vertrauenswürdigen Proxy-Netzen ausgewertet.
- Neue Manager-Backups sind immer AES-256-GCM-verschlüsselt und benötigen mindestens zwölf Zeichen. Vor jedem WebUI-Restore wird ein eigenes verschlüsseltes Sicherheitsbackup erzeugt. Alte ZIP-Backups bleiben lesbar.
- Restore-Pakete werden auf Pfadausbruch, symbolische Links, doppelte Einträge, Dateianzahl, Gesamtgröße und Kompressionsverhältnis geprüft.
- Die Web-API läuft als Benutzer `borg`, während nur der überwachte Startprozess und `sshd` Root-Rechte behalten. Der Container nutzt `no-new-privileges`, und OpenSSH prüft Dateieigentümer mit `StrictModes yes`.
- Sicherheitsereignisse besitzen eine zeit- und mengenbezogene Aufbewahrungsgrenze.

## Architektur

```text
Backup
WebUI / Scheduler
        │
        └─ SSH zum Quellclient
                 │
                 ├─ Borg liest lokale Quelldateien
                 └─ Borg verbindet sich mit dem Repository

Restore
WebUI
  │
  └─ SSH zum Zielclient
           └─ Borg extrahiert Dateien auf dem Zielclient

Verwaltung eines lokalen, verwalteten Repositorys
WebUI → Borg 1.4 im Manager → /repositories/REPOSITORY

Verwaltung eines externen Repositorys
WebUI → Borg 1.4 im Manager → SSH → externes Repository
```

Backup und Restore laufen auf dem Client, weil sich dort Quell- und Zieldateien befinden. Archivliste, Archivinfo, Check, Prune, Compact, Diff, Rename, Delete, Browser und Export werden bei einem verwalteten Repository direkt im Manager-Container ausgeführt. Dafür ist kein SSH-Umweg über den Repository-Port notwendig.

## Borg-Kompatibilität

| Clientversion | Verhalten |
|---|---|
| 1.2.0–1.2.4 | nutzbar, kritische Sicherheitswarnung |
| 1.2.5–1.2.7 | nutzbar, Aktualisierungswarnung |
| 1.2.8–1.4.x | freigegeben |
| älter als 1.2.0 | nicht unterstützt |
| 2.x | nicht kompatibel |

Die Versionsprüfung verwendet mehrere Varianten:

```bash
borg --version
borg -V
borg --show-version help
```

Damit können auch Clients abgefragt werden, deren CLI-Ausgabe von neueren Borg-Versionen abweicht.

## Anmeldung, Benutzer und Sicherheitsdaten

Neue Installationen verwenden kein Admin-Token und keinen statischen Verschlüsselungsschlüssel in `.env`. Beim ersten Start erzeugt der Manager ein temporäres Administratorkonto. Das einmalige Passwort liegt verschlüsselt in `/data/security/security.db` und wird nur über einen administrativen Containeraufruf angezeigt:

```bash
cd /opt/BorgBackup-Manager
docker compose exec -T borg-manager python -m app.initial_admin
```

Nach der ersten Anmeldung muss das Passwort geändert werden. Danach wird das verschlüsselte Bootstrap-Geheimnis gelöscht. Die Anmeldung verwendet:

- scrypt-Passworthashes mit individuellem Zufallssalt
- serverseitig gespeicherte, widerrufbare Sitzungen
- nur als SHA-256-Hash gespeicherte Sitzungstoken
- `HttpOnly`-, `SameSite=Strict`- und grundsätzlich `Secure`-Cookie
- quellenbezogene Login-Rate-Limits pro IP-Adresse und IP-/Benutzer-Kombination; fremde Fehlversuche sperren kein Konto global
- Sitzungs-Cookies erhalten ein explizites Ablaufdatum; bei mehreren gleichnamigen alten und neuen Cookies akzeptiert der Manager den gültigen Sitzungseintrag statt einen veralteten Wert vorzuziehen
- der Sitzungsstatus setzt einen gültigen Cookie mit den sicheren HTTPS-Attributen erneut; Proxy-Header werden ausschließlich von ausdrücklich vertrauten Proxy-Netzen berücksichtigt
- `BBM_SESSION_COOKIE_SECURE=always` ist der sichere Standard; Proxy-Header werden nur von Netzen in `BBM_TRUSTED_PROXY_CIDRS` akzeptiert und Uvicorn vertraut ihnen nicht eigenständig
- Python-Abhängigkeiten sind vollständig aufgelöst und für Linux amd64/arm64 per SHA-256 gesperrt; das Docker-Basisimage ist zusätzlich über seinen Multi-Platform-Digest fixiert
- der historische Standardname `bbm_session` wird zur Laufzeit als `bbm_session_v2` interpretiert; `install.sh` und `update.sh` übernehmen die dauerhafte Änderung sicher auf dem Host, individuell konfigurierte andere Cookie-Namen bleiben unverändert
- nach der Anmeldung prüft die WebUI sofort mit einer zweiten Anfrage, ob der Browser den Cookie wirklich zurücksendet; ein Cookie-Problem wird daher direkt angezeigt und nicht erst nach einem Reload
- zusätzlich erhält nur der aktuelle Browser-Tab einen serverseitig gehashten, an Sitzung und User-Agent gebundenen Reload-Schlüssel im `sessionStorage`; er wird nur verwendet, wenn der HttpOnly-Cookie beim Reload fehlt, und verschwindet beim Schließen des Tabs
- die WebUI meldet nur bei einem echten HTTP-401 ab, nicht anhand zufälliger Wörter in einer Fehlermeldung
- erzwungenen Passwortwechsel für neue oder zurückgesetzte Konten

Administratoren können Benutzer anlegen, bearbeiten, deaktivieren, löschen und Passwörter zurücksetzen. Das eigene Konto und der letzte Administrator können nicht gelöscht werden; der letzte aktive Administrator kann außerdem weder deaktiviert noch herabgestuft werden. Normale Benutzer besitzen eine reine Beobachterrolle: Sie dürfen Dashboard, Listen und zusammengefasste Laufstatus lesen sowie ihre persönliche Sprache und Darstellung ändern. Manuelle Ausführungen, vollständige Logs, Archive, Restore/Export/Mount, Geräte-, Repository-, Job-, Zeitplan-, Manager-Backup-, Einstellungs- und Benutzeränderungen bleiben Administratoren vorbehalten.

Beim Update von 0.8.x werden ein vorhandener `BBM_ADMIN_TOKEN` einmalig als temporäres Passwort des Benutzers `admin` und ein vorhandener `BBM_SECRET_KEY` ausschließlich zur Entschlüsselung und Neuverschlüsselung bestehender Repository-Geheimnisse verwendet. Nach erfolgreicher Migration entfernt der Container diese Altwerte aus der Host-`.env`.

## Navigation und Funktionsbereiche

Unter **Infrastruktur** stehen in der Seitenleiste nur noch **Geräte** und **System**. **System** bündelt die administrativen Bereiche in einer gemeinsamen Reiterleiste direkt in der sticky Kopfzeile. Sie bleibt beim Scrollen sichtbar; der aktuell geöffnete Bereich wird durch einen dunkel gefüllten Reiter eindeutig hervorgehoben. Sichtbarkeit und aktive Markierung werden auch nach einem Seitenreload oder beim Öffnen eines direkten System-Links aus der URL wiederhergestellt:

1. **Benachrichtigungen**
2. **Benutzer**
3. **Manager-Backup**
4. **Einstellungen**
5. **Systemdiagnose**

Beim Wechsel zwischen diesen Reitern bleibt **System** in der Seitenleiste markiert. Die bisherigen direkten URLs wie `#notifications`, `#users`, `#backups`, `#settings` und `#diagnostics` bleiben gültig, damit vorhandene Lesezeichen weiterhin funktionieren. Die Systemdiagnose befindet sich nicht mehr auf dem Dashboard.

### Übersicht

Das Dashboard zeigt:

- Anzahl der Backup-Jobs
- laufende Ausführungen
- wartende Ausführungen in repositoryweiten Warteschlangen
- fehlgeschlagene Ausführungen
- eine gemeinsame Repository-Kachel mit Anzahl und summierter Repository-Größe
- eine vollständige Backup-Job-Tabelle mit Status, Gerät, Repository, Quellen und Zeitplan
- den letzten Backup-Lauf je Job mit Laufnummer und Datum/Uhrzeit in der ersten sowie Dauer, Status und Ausführungsart in der zweiten Zeile
- die Quellenstatistik mit Größe/Dateianzahl und Herkunft/Zeitpunkt in zwei kompakten Zeilen
- die Original-, komprimierte und deduplizierte Größe der letzten Sicherung als drei eng gesetzte Beschriftungs-/Wertzeilen
- einen direkten **Starten**-Button für jeden nutzbaren Backup-Job
- eine persistente Sortierung des Dashboard-Jobblocks nach Name, Status, Gerät, Repository, letztem Lauf oder Sicherungsgröße
- letzte Ausführungen
- Hinweise auf ungeprüfte oder veraltete Borg-Versionen

Der Backup-Job-Block steht direkt oberhalb der letzten Aktivitäten. Aktive Jobs können dort unmittelbar manuell gestartet werden. Bei verwalteten Repositories bleibt der Startknopf deaktiviert, solange der repositorybezogene SSH-Zugang noch nicht direkt beim Backup-Job eingerichtet wurde. Der Block verwendet ausschließlich bereits gespeicherte Laufmetadaten und löst beim Öffnen des Dashboards keinen zusätzlichen Borg-Zugriff aus. Bei älteren Backup-Läufen versucht der Manager vorhandene Borg-Statistiken aus der gespeicherten Protokollvorschau zu übernehmen; fehlen diese Angaben, wird ein neutraler Platzhalter angezeigt. Ist der neueste Backup-Lauf fehlgeschlagen, bleibt er als letzter Lauf sichtbar; die Größenangabe stammt dann aus der letzten erfolgreichen Sicherung und nennt deren Laufnummer.

Die Repository-Anzahl und die summierte Repository-Größe stehen gemeinsam in einer Kachel und führen beide in denselben Arbeitsbereich. Die übrigen Kennzahlen verlinken ebenfalls direkt auf den jeweiligen Arbeitsbereich. „Laufend“, „Wartend“ und „Fehlgeschlagen“ öffnen die Ausführungsansicht bereits mit dem passenden Statusfilter. Der Aufmerksamkeitshinweis für fehlgeschlagene Läufe verwendet denselben Filter und zeigt nicht mehr ungezielt alle Protokolle.

Die Betriebslisten für Jobs, Geräte, Repositories und Ausführungen verwenden kompakte Tabellen. Backup-Jobs können nach Name, Gerät, Repository oder Quellpfad durchsucht, nach Aktivstatus gefiltert und zusätzlich sortiert werden. Eigene Sortierauswahlen stehen auch für den Dashboard-Jobblock, Repositories und verbundene Geräte bereit. Die Auswahl wird pro angemeldetem Benutzer und Browser gespeichert. Dadurch bleibt die Übersicht auch bei 20 oder mehr Clients nutzbar. Die über **Mehr** eingeblendeten Jobaktionen erscheinen als kompakte, gruppierte Aktionsleiste: Prüfungen, Repository-Zugang, Speicherpflege und Verwaltung brechen innerhalb ihrer Gruppe um, statt pro Aktion eine hohe Vollbreitenzeile zu belegen.

Die WebUI verwendet ein eigenes Borg-orientiertes Favicon und dieselbe Bildmarke auf Anmeldung und Seitenleiste.

Ausführungsdialoge verwenden die verfügbare Fensterhöhe dynamisch. Auch bei zusätzlichen Borg-Sicherheitswarnungen oder Diagnosen bleibt der Logbereich sichtbar und besitzt eine eigene vollständige Scrollleiste; Warnungen verschieben das Ende der Ausgabe nicht mehr außerhalb des Dialogs.

Auf Smartphones und schmalen Tablets wird die Seitenleiste über **Menü** ein- und ausgeblendet. Formulare, Aktionsbereiche, Repository-, Geräte-, Job-, Zeitplan-, Lauf- und Benutzertabellen, Archivansicht, Restore, der Systembereich mit seinen Reitern, Anleitung, Release Notes und Dialoge passen sich ohne horizontales Seiten-Scrolling an. Breite Tabellen werden in beschriftete Karten umgewandelt; lange Pfade, Archivnamen und Protokollzeilen brechen innerhalb der verfügbaren Breite um.

### Geräte

Die Liste der verbundenen Geräte lässt sich nach Name, Aktivstatus, Adresse oder Borg-Version sortieren. Die Auswahl bleibt für den angemeldeten Benutzer in diesem Browser erhalten.

Die Geräteansicht verwendet zwei vollständige Arbeitsblöcke untereinander: **Gerät hinzufügen** oben und **Verbundene Geräte** darunter. Dadurch bleibt die Eingabe auch auf breiten Bildschirmen übersichtlich und die Geräteliste erhält die gesamte verfügbare Breite. Der Controller-Schlüssel besitzt direkt in seiner Anzeigezeile einen kompakten Kopierbutton. Die sicherheitskritische Erneuerung befindet sich ausschließlich unter **System → Einstellungen → Controller-Schlüssel**. Die SSH-Fingerprint-Prüfung zeigt den gefundenen Ed25519-Fingerprint im Formular an; Bestätigen oder Verwerfen erfolgt ohne separates Aktionsfenster. Der Zugangsstatus bleibt hier sichtbar; Einrichtung und Erneuerung repositorybezogener Schlüssel erfolgen jedoch direkt beim jeweiligen Backup-Job.

Ein Gerät besteht aus:

- Name
- IP-Adresse oder DNS-Name
- SSH-Port
- SSH-Benutzer
- bestätigtem Ed25519-Hostschlüssel
- Aktivstatus
- erkannter Borg-Version
- Prüfzeitpunkt und Warnstatus

Verfügbare Aktionen:

- SSH-Fingerprint prüfen
- Gerät speichern oder bearbeiten
- Gerät direkt in der Tabelle aktivieren oder deaktivieren
- Borg-Version prüfen
- Repository-Zugänge einrichten oder erneuern
- Gerät löschen, sofern es von keinem Job verwendet wird
- Controller-Schlüssel unter **System → Einstellungen → Controller-Schlüssel** kontrolliert erneuern

Ein deaktiviertes Gerät behält seine vollständige Konfiguration, wird aber aus aktiven Zeitplänen und den erzeugten Repository-SSH-Zugängen entfernt. Beim Deaktivieren setzt der Manager außerdem sämtliche zugehörigen aktiven Backup-Jobs automatisch auf **inaktiv**, damit Geräte- und Jobstatus nicht auseinanderlaufen. Laufende oder wartende Ausführungen müssen vorher beendet sein. Beim erneuten Aktivieren synchronisiert der Manager Zeitpläne und Repository-Zugänge; die Backup-Jobs bleiben aus Sicherheitsgründen deaktiviert und müssen anschließend gezielt wieder aktiviert werden.

Beim Erneuern des Controller-Schlüssels wird das bisherige Schlüsselpaar verschlüsselt als historischer Systemschlüssel in `/data/security/security.db` archiviert. Laufende oder wartende Ausführungen blockieren den Wechsel. Anschließend muss der neue öffentliche Schlüssel auf jedem Client in `authorized_keys` eingetragen werden; Repository-Schlüssel und Borg-Archive werden dabei nicht verändert.

Der öffentliche Controller-Schlüssel muss einmalig auf jedem Client in `authorized_keys` eingetragen werden. Für verwaltete Repositories erzeugt der Manager zusätzlich je Gerät und Repository einen eigenen eingeschränkten Schlüssel.

Controller-Schlüssel und Geräte-Hostschlüssel erfüllen unterschiedliche Aufgaben: Der Controller-Schlüssel authentifiziert den Manager am Client; der beim Fingerprint-Scan bestätigte Ed25519-Hostschlüssel authentifiziert den Client gegenüber dem Manager. Bei jeder Verbindung werden beide Prüfungen verwendet. Nach dem Scan bleibt der Fingerprint direkt im Geräteformular sichtbar und muss dort ausdrücklich bestätigt werden. Der Geräte-Hostschlüssel wird als temporäre `known_hosts`-Datei eingebunden, während `StrictHostKeyChecking=yes` aktiv bleibt.

### Repositories

Die Repository-Liste lässt sich nach Name, Bereitschaftsstatus, Typ, Anzahl zugeordneter Jobs oder gespeicherter Größe sortieren. Die Auswahl wird benutzer- und browserbezogen gespeichert. Direkt neben dem Status wird die numerische Manager-ID des Repository-Eintrags angezeigt; sie entspricht der Kennung in BBM-Cachepfaden wie `repository-<ID>`.

#### Verwaltetes Repository

Ein verwaltetes Repository liegt unter dem eingebundenen Verzeichnis `/repositories`. Der Manager erzeugt:

- sicheren Verzeichnisnamen
- Borg-Repository
- Repository-URL für die Clients
- eingeschränkte `authorized_keys`-Zuordnungen
- verschlüsselte Ablage von Passphrase oder Keyfile

#### Externes Repository

Ein externes Repository wird als **vorhandenes Borg-Repository** eingebunden und nicht neu initialisiert. Repository-Verwaltung und Archivanzeige erfolgen immer direkt im Manager-Container. Ein Backup-Client wird dafür nicht als Zwischenstation verwendet.

Für SSH-Repositories verwaltet der Manager repositorybezogen:

- einen eigenen Ed25519-Schlüssel,
- den geprüften `known_hosts`-Eintrag,
- optional die Borg-Passphrase,
- optional das Borg-Keyfile.

Der private SSH-Schlüssel und `known_hosts` werden mit dem Master-Key verschlüsselt gespeichert. Konkret liegen die verschlüsselten Werte in `/data/security/security.db`; der dafür verwendete Schutzschlüssel liegt unter `/data/security/master.key`. Es existiert keine dauerhafte Klartext-Schlüsseldatei. Nur während eines Borg-Aufrufs wird unter `/tmp/bbm-borg.XXXXXX/` ein temporärer Schlüssel mit Modus `0600` erzeugt und anschließend entfernt. Die WebUI kann den Ed25519-Schlüssel erzeugen oder einen vorhandenen unverschlüsselten OpenSSH-Privatschlüssel übernehmen. Der Hostkey kann direkt vom Manager gescannt oder manuell eingefügt werden.

Beispiel Hetzner Storage Box:

```text
Repository-URL:
ssh://u123456@u123456.your-storagebox.de:23/./borg-repository

Manager-Schlüssel:
im Repository-Formular erzeugen

known_hosts:
direkt vom Manager abrufen oder geprüften Eintrag einfügen
```

Nach dem Speichern wird der öffentliche Schlüssel angezeigt. Dieser muss bei der Storage Box beziehungsweise auf dem Zielserver autorisiert werden. Anschließend reiht **Verbindung prüfen** einen repositoryweiten `borg info`-Lauf ein und öffnet dessen Live-Log. Die HTTP-Anfrage kehrt sofort mit einer Lauf-ID zurück; auch ein längerer Cache-Neuaufbau kann daher nicht mehr durch den Timeout eines Reverse-Proxys als HTTP 504 abgebrochen werden. Erst nach erfolgreicher Prüfung wird das Repository als **bereit** markiert.

Fehlgeschlagene Prüfungen werden in der Repository-Zeile nur als kurze, handlungsorientierte Meldung dargestellt. OpenSSH-Debugausgaben werden dort nicht mehr ausgegeben. Bei einem lokalen `PermissionError` zeigt die WebUI nur den nicht lesbaren Repository-Pfad sowie die tatsächlich verwendete Manager-UID:GID an, statt den vollständigen Python-Traceback von Borg einzublenden. Die gefilterten technischen Details bleiben über **Details** beziehungsweise den dauerhaften Statusbereich kopierbar. Bei Aktionen, die als Ausführung gestartet werden, bleibt das unveränderte vollständige Laufprotokoll zusätzlich in der zugehörigen Logdatei erhalten; eine direkte Archivlistenabfrage gibt bewusst nur die kurze Ursache an den Browser zurück.

Alle Prozesse, die direkt auf ein verwaltetes Repository zugreifen, müssen dessen Dateien lesen beziehungsweise bei Schreibaktionen verändern können. Schreiben weitere Clients mit `root` in denselben NFS- oder Bind-Mount, müssen Eigentümer, gemeinsame Gruppe, ACLs oder NFS-Zuordnung so gewählt werden, dass auch `BBM_BORG_UID:BBM_BORG_GID` Zugriff besitzt. Der Manager verändert Repository-Berechtigungen nicht automatisch.

Managerseitige Borg-Zugriffe verwenden einen eigenen lokalen Borg-Cache je Repository-Eintrag unter `/data/borg-cache/repository-<ID>`, den Archivlisten-Cache unter `/data/archive-cache` und Sicherheitsstatus unter `/data/borg-security`. Diese Daten liegen damit nicht mehr unter `/repositories/.cache` oder `/repositories/.config`. Das ist insbesondere bei per NFS eingebundenen Repository-Verzeichnissen wichtig: Der Repository-Mount enthält nur die Borg-Repositories, während der lokale Manager-Zustand im persistenten Datenverzeichnis bleibt.

Backup-, Restore- und Prüfbefehle, die auf einem Quellgerät ausgeführt werden, erhalten ebenfalls einen getrennten BBM-Cache je Repository unter `$HOME/.cache/borgbackup-manager/repository-<ID>`. Verbindet sich der Manager als Benutzer `root`, ist `$HOME` gleich `/root`. Eine Meldung zu `/root/.cache/borg/.../lock.exclusive` bezeichnet deshalb den allgemeinen **lokalen Borg-Cache auf dem Quellgerät** und nicht den Repository-Ordner. Dieser frühere Standardpfad wird von neuen BBM-Läufen nicht mehr verwendet. Nach dem bestätigten Ende eines Borg-Prozesses werden nur eventuell verbliebene Locks im privaten BBM-Cache bereinigt; Repository-Locks und manuell genutzte Borg-Caches bleiben unangetastet.

Die Repository-Aktion **Cache löschen** entfernt ausschließlich den managerseitigen Cache des ausgewählten Repositorys direkt aus dem Dateisystem. Sie muss dafür Borg nicht starten und funktioniert dadurch auch dann, wenn gerade der Cache-eigene `lock.exclusive` einen Borg-Aufruf verhindern würde. Archive, Repository-Konfiguration, Passphrase, Keyfile und Borg-Sicherheitsstatus werden nicht gelöscht. Bei verwalteten Repositories entfernt die Aktion zusätzlich bekannte Alt-Caches unter `/data/borg-cache/<Repository-ID>` und `/repositories/.cache/borg/<Repository-ID>`. Der erste anschließende Zugriff kann länger dauern, weil Borg den Cache neu aufbaut. Während einer laufenden oder wartenden Repository-Ausführung ist die Aktion gesperrt.

#### Repositorybezogene Speicherplatz-Sperre

Schreibende Backup-Läufe werden nicht mehr pauschal anhand des Dateisystems von `/repositories` beurteilt. Der Manager prüft den tatsächlichen `storage_path` des betroffenen verwalteten Repositorys. Liegen beispielsweise mehrere NFS-Mounts als `/repositories/nas-a`, `/repositories/nas-b` und `/repositories/offline` vor, wird für jeden Backup-Job genau der Mount des zugehörigen Repositorys ausgewertet. Ein voller Mount blockiert damit nur die darauf schreibenden Backups; andere Repository-Dateisysteme bleiben nutzbar.

Unter **System → Einstellungen → Speicherplatz-Sperre** werden die globale Aktivierung und die globale Schwelle von 1 bis 100 Prozent festgelegt. Jedes verwaltete Repository kann unter **Repositories → Bearbeiten**:

- die globale Einstellung vollständig übernehmen,
- die Sperre ausdrücklich aktivieren oder deaktivieren,
- eine eigene Schwelle verwenden und die globale Schwelle damit überschreiben.

Die Repository-Liste zeigt die wirksame Schwelle. Aktuelle Belegung und Blockierstatus werden gesammelt in der Systemdiagnose angezeigt. Externe Repositories werden nicht mit dieser lokalen Dateisystemprüfung bewertet, weil deren tatsächlicher freier Speicher über Borg nicht zuverlässig abgefragt werden kann.

Die Systemdiagnose listet den Repository-Basismount und alle im Container sichtbaren Unter-Mounts unter `/repositories` getrennt auf. Angezeigt werden Gesamtgröße, Belegung, freier Speicher, zugeordnete Repositories, wirksame Sperrwerte und Blockierstatus.

Die Aktion **Größe berechnen** arbeitet abhängig vom Repository-Typ:

- verwaltetes Repository: tatsächliche Verzeichnisgröße auf dem Manager-Dateisystem,
- externes Repository: von Borg gemeldete repositoryweite deduplizierte komprimierte Nutzdaten.

Bei externen Zielen ist dieser Borg-Wert nicht identisch mit einer serverseitigen `du`-Ausgabe, da Dateisystem- und Repository-Metadaten des entfernten Servers nicht über einen normalen Borg-Zugang abgefragt werden.

Bei Backup und Restore läuft Borg weiterhin auf dem jeweiligen Quell- beziehungsweise Ziel-Client, weil dort die Nutzdaten liegen. Dafür überträgt der Manager den repositorybezogenen SSH-Schlüssel, `known_hosts`, Passphrase und gegebenenfalls das Borg-Keyfile nur temporär über die bereits bestehende Controller-SSH-Verbindung. Die Dateien werden auf dem Client in einem geschützten temporären Verzeichnis angelegt und nach dem Borg-Aufruf entfernt. Eine dauerhafte Storage-Box-Konfiguration auf jedem Client ist nicht erforderlich.

Externe Repositories aus Version 0.9.3 verlieren beim Upgrade ihre frühere Client-Zwischenstation. Sie bleiben erhalten, werden aber als ungeprüft markiert und müssen einmal mit einem zentralen Manager-Schlüssel sowie `known_hosts` ergänzt und erneut geprüft werden.

#### Vorhandenes Repository einbinden

Die Suchfunktion prüft direkte Unterverzeichnisse des eingebundenen Repository-Pfads auf eine Borg-Konfiguration. Beim Import werden Name, Verschlüsselungsmodus, Passphrase und bei Keyfile-Repositories der vorhandene Keyfile-Inhalt abgefragt. Der Manager öffnet das Repository testweise, bevor der Eintrag gespeichert wird.

Ein vorhandenes Repository wird durch **Repository prüfen und einbinden** nicht initialisiert, geleert oder zurückgesetzt. Die Aktion **Initialisieren** wird nur angeboten, wenn im verwalteten Zielverzeichnis noch keine Borg-Konfiguration vorhanden ist. Schlägt eine spätere Verbindungsprüfung fehl, bleibt ein bereits vorhandenes Repository als vorhanden erkannt und wird nicht wieder als neu zu initialisieren dargestellt.

Wurde ein bereits registriertes verwaltetes Repository außerhalb des Managers vollständig gelöscht, erkennt die Repository-Liste die fehlende Borg-`config` unabhängig vom früher gespeicherten Initialisierungsstatus. Der Status wechselt auf **Repository fehlt** und bietet **Zurücksetzen** an. Die Rücksetzung ist nur zulässig, wenn der verwaltete Zielordner vorhanden, vollständig leer und frei von einer Borg-Konfiguration ist. Sie löscht keine Dateien, sondern setzt ausschließlich Initialisierungs-, Prüf- und Größenmetadaten sowie den Archivcache zurück. Laufende oder wartende Repository-Aktionen und aktive Archiv-Mounts blockieren die Rücksetzung. Danach steht **Initialisieren** wieder zur Verfügung.

Bei `keyfile`-Verschlüsselung wird der Schlüssel des gelöschten Repositorys entfernt, da er für die neue Repository-ID nicht mehr verwendbar ist; die Neuinitialisierung erzeugt und speichert automatisch einen neuen Keyfile. Eine vorhandene Passphrase bleibt erhalten. Jobs, Zeitpläne und Gerätezuordnungen bleiben bestehen, ihre Repository-Aktionen sind jedoch bis zur erfolgreichen Neuinitialisierung gesperrt.

#### Verschlüsselungsmodi

- `repokey`
- `repokey-blake2`
- `keyfile`
- `keyfile-blake2`
- `authenticated`
- `authenticated-blake2`
- `none`

Repository-Passphrasen und Keyfiles werden mit einem zufälligen Fernet-Master-Key verschlüsselt. Der Master-Key liegt als einziger externer Vertrauensanker mit Modus `0600` unter `/data/security/master.key`; Benutzerpasswörter werden niemals entschlüsselbar gespeichert, sondern mit scrypt und einem individuellen Salt gehasht. Benutzer, Passworthashes, Sitzungshashes, Sicherheitsereignisse sowie verschlüsselte Controller-, SSH-, TLS-, Repository- und Borg-Geheimnisse befinden sich in `/data/security/security.db`. Der externe Vertrauensanker `/data/security/master.key` besitzt Modus `0600` und darf nicht getrennt von der Sicherheitsdatenbank wiederhergestellt werden.

### Backup-Jobs

Die Jobübersicht zeigt zusätzlich eine Quellenstatistik mit Originalgröße und Dateianzahl. Nach einem erfolgreichen oder mit Warnung abgeschlossenen Backup werden die Werte direkt aus Borgs Abschlussstatistik übernommen. Über **Aktualisieren** beziehungsweise **Quellenstatistik** kann ein repositoryunabhängiger Live-Scan auf dem Quellgerät gestartet werden. Dieser zählt die konfigurierten Quellen vor Borg-Ausschlüssen und schreibt kein Archiv. Nach dem nächsten abgeschlossenen Backup werden die Werte wieder durch Borgs exakte Statistik nach Anwendung der Ausschlüsse ersetzt.



Der Jobbereich besteht aus zwei breiten Blöcken: oben der kompakte Editor, darunter die filter- und sortierbare Jobtabelle. Sortiert werden kann nach Name, Status, Gerät oder Repository; die Auswahl bleibt pro Benutzer und Browser erhalten. Grunddaten, Quellpfade und Ausschlüsse werden nebeneinander angeordnet; Dateisystemoptionen und Aufbewahrung lassen sich bei Bedarf aufklappen. Dadurch bleibt der Editor auch bei vielen Optionen deutlich kürzer.

Nach dem Speichern eines Jobs steht unter **Mehr → Repository-Zugang** die passende Einrichtung direkt im Jobbereich bereit. Für verwaltete Repositories erzeugt der Manager dabei ausschließlich den Schlüssel für die konkrete Kombination aus Gerät und Repository. Andere Repository-Zugänge desselben Geräts werden nicht unnötig erneuert. Der Status und fehlende Zugänge sind in der Jobliste unmittelbar sichtbar. Unter **Mehr → Verwalten** kann der Job außerdem direkt aktiviert oder deaktiviert werden. Deaktivierte Jobs behalten sämtliche Optionen und Zeitplanzuordnungen, werden aber nicht gestartet; laufende oder wartende Ausführungen müssen vor dem Deaktivieren abgeschlossen oder beendet sein.

Ein Backup-Job verbindet:

- ein Gerät
- ein Repository
- einen oder mehrere Quellpfade
- Ausschlüsse
- Archivnamensvorlage
- Kompression
- Borg-Create-Optionen
- Aufbewahrungsregeln

#### Quellpfade

Quellpfade werden zeilenweise als absolute POSIX-Pfade angegeben:

```text
/home
/etc
/srv/data
```

Bei Quelle `/` sollte `Nur jeweiliges Quelldateisystem sichern` aktiviert bleiben. Separate Dateisysteme müssen dann als zusätzliche Quelle angegeben werden.

#### Zentrale Ausschlussvorlagen

Unter **System → Einstellungen → Ausschlussvorlagen** können beliebig viele benannte Vorlagen gepflegt werden. Die mitgelieferte Standardvorlage lautet:

```text
Linux-Systempfade
/proc
/sys
/dev
/run
/tmp
/var/tmp
```

Im Jobformular wird eine Vorlage ausgewählt und mit **Vorlage zur Liste hinzufügen** in die Ausschlussliste kopiert. Bereits vorhandene Muster werden nicht doppelt eingetragen.

Wichtig:

- Vorlagen sind zentrale Eingabehilfen.
- Ein Job speichert weiterhin seine eigene feste Ausschlussliste.
- Eine spätere Änderung der Vorlage verändert bestehende Jobs nicht automatisch.
- Dadurch bleiben vorhandene Jobs nachvollziehbar und werden nicht unerwartet verändert.

Eigene Vorlagen können beispielsweise für Docker, Nextcloud, Home-Verzeichnisse oder temporäre Anwendungsdaten angelegt werden.

#### Ausschlussmuster

Jede Zeile wird als eigener Borg-Parameter übergeben:

```bash
--exclude MUSTER
```

Beispiele:

```text
/proc
/sys
*/.cache
*.tmp
/home/*/Downloads
```

#### Archivnamen

Jeder Job erhält ein kompaktes, dauerhaft reserviertes Präfix:

```text
bbm-12-
```

Die konfigurierbare Vorlage wird dahinter angefügt:

```text
{hostname}-{now:%Y-%m-%dT%H:%M:%S}
```

Damit entsteht beispielsweise `bbm-12-server01-2026-07-17T22:00:00`. Verwendete Job-IDs werden auch nach dem Löschen dauerhaft reserviert und nicht erneut vergeben. Beim Update werden bisherige lange Präfixe als historische Archivserien am Job gespeichert; vorhandene Archive bleiben zugeordnet, wiederherstellbar und werden bei der Aufbewahrung weiterhin berücksichtigt. Die Vorlage muss `{now...}` oder `{utcnow...}` enthalten.

#### Zeitsteuerung

Backup-Jobs enthalten keinen eigenen Cron-Zeitplan mehr. Ohne zentrale Zuordnung werden sie ausschließlich manuell ausgeführt. Die Jobliste zeigt je Job eindeutig **Manuell** oder **Nach Zeitplan** sowie die Namen der zugeordneten Zeitpläne.

#### Kompression

Unterstützt werden die gemeinsamen Borg-1.2-bis-1.4-Spezifikationen:

- `none`
- `lz4`
- `zstd`
- `zlib`
- `lzma`
- `auto,...`
- `obfuscate,...` für verschlüsselte Repositories

#### Create-Optionen

- `--one-file-system`
- `--exclude-caches`
- `--exclude-nodump`
- `--numeric-ids`
- `--list` – verarbeitete Dateien mit Borg-Status und Pfad im Live-Protokoll anzeigen
- `--files-cache`
- `--checkpoint-interval`
- `--lock-wait 600`

#### Aufbewahrung

- Letzte Archive: `--keep-last`
- Stündlich: `--keep-hourly`
- Täglich: `--keep-daily`
- Wöchentlich: `--keep-weekly`
- Monatlich: `--keep-monthly`
- Jährlich: `--keep-yearly`

Der Wert 0 deaktiviert die jeweilige Regel. Prune wird auf das feste Jobpräfix begrenzt. Compact kann nach einem geplanten Prune automatisch ausgeführt werden. Compact wird mit ausführlicher Borg-Ausgabe gestartet, sodass im Laufprotokoll auch die von Borg geschätzte freigegebene Größe erscheint, sofern tatsächlich unreferenzierte Segmente vorhanden sind.

#### Jobaktionen

Direkt verfügbar:

- Backup starten
- Archive öffnen
- Verbindung prüfen

Unter **Weitere Aktionen**:

- Job-Info
- Borg-Version
- Repository prüfen
- Daten vollständig prüfen
- geänderten Repository-Standort einmalig bestätigen
- Aufbewahrung anwenden
- Speicher freigeben
- alle Repository-Archive anzeigen
- Job bearbeiten
- Job löschen

Geöffnete Aktionsbereiche bleiben bei automatischen Hintergrundaktualisierungen geöffnet.

Wenn Borg meldet, dass dasselbe Repository früher unter einer anderen URL lag, war die SSH-Verbindung bereits erfolgreich. Borg blockiert dann absichtlich, bis der neue Standort bestätigt wurde. Administratoren verwenden beim betroffenen Job unter **Mehr → Prüfen → Geänderten Repository-Standort bestätigen** die einmalige Sicherheitsfreigabe. Die Aktion setzt `BORG_RELOCATED_REPO_ACCESS_IS_OK=yes` nur für diesen einen Prüflauf; normale Backups bestätigen Standortänderungen niemals automatisch. Vor der Bestätigung müssen SSH-Fingerprint, Repository-Ziel und beabsichtigter Umzug geprüft sein.

Die Bestätigung ist technisch eine Aktion des jeweiligen Geräts für das Repository, nicht des einzelnen Jobs. Mehrere Klicks über verschiedene Jobs desselben Geräts werden deshalb zu einem Lauf zusammengeführt. Bestätigungen unterschiedlicher Geräte werden über die repositoryweite FIFO-Warteschlange nacheinander ausgeführt. Borg wartet dabei bis zu 600 Sekunden auf eine noch aktive Repository-Sperre. Schlägt die Aktion danach weiterhin mit `lock.exclusive (timeout)` fehl, greift außerhalb der Manager-Warteschlange noch ein Borg-Prozess zu oder es liegt eine sicher zu prüfende verwaiste Sperre vor.

### Zentrale Zeitpläne

Zeitpläne werden im eigenen Bereich **Zeitpläne** verwaltet. Ein Zeitplan kann auf drei Arten zugeordnet werden:

- einzelne oder mehrere Geräte: erfasst alle aktiven Jobs dieser Geräte
- ein Repository: erfasst alle aktiven Jobs des Repositorys, einschließlich später neu angelegter Jobs
- einzelne oder mehrere Backup-Jobs

Unterstützt werden täglich, Montag bis Freitag, Wochenende, ausgewählte Wochentage, monatlich und frei definierte fünfteilige Cron-Ausdrücke. Pro Zeitplan sind bis zu 24 Uhrzeiten beziehungsweise Cron-Ausdrücke möglich. Alle Ausführungen verwenden `Europe/Berlin`.

Jeder Zeitplan kann eine eigene Obergrenze für gleichzeitig laufende Ausführungen erhalten. `0` bedeutet, dass nur die globale Grenze gilt; mit `1` werden auch Jobs verschiedener Geräte und verschiedener Repositorys aus diesem Zeitplan nacheinander gestartet. Die Zeitplangrenze gilt nur für Läufe, die von genau diesem Zeitplan ausgelöst wurden.

Ein aktiver Backup-Job darf nur einem aktiven zentralen Zeitplan zugeordnet sein. Überlappende Zuordnungen werden beim Speichern abgewiesen, damit ein Job nicht doppelt gestartet wird. Beim Upgrade werden vorhandene Job-Cronwerte automatisch als eigene zentrale Zeitpläne übernommen; anschließend wird das alte Jobfeld geleert.

### Warteschlange und Parallelitätsgrenzen

Alle Borg-Aktionen werden pro Repository serialisiert. Beginnen mehrere Geräte gleichzeitig ein Backup in dasselbe Repository, wechselt nur der erste Lauf auf **Laufend**. Weitere Anforderungen bleiben als **Wartend** sichtbar und starten automatisch, sobald das Repository frei ist. Dies verhindert parallele Schreibzugriffe und Borg-Lock-Konflikte. Repositoryweite Administratoraktionen wie **Compact** und eine gemeinsame Mehrfachlöschung von Archiven verwenden dieselbe Sperr- und Laufprotokollierung und benötigen keinen Backup-Job.

Zusätzlich kann unter **System → Einstellungen → Parallelitätsgrenzen** die maximale Anzahl aller gleichzeitig laufenden Manager-Ausführungen festgelegt werden. `0` bedeutet unbegrenzt; `1` serialisiert auch Aktionen auf unterschiedlichen Repositorys. Eine am Zeitplan gesetzte Grenze kann die Ausführungen dieses Zeitplans weiter einschränken. Repository-Grenze, Zeitplangrenze und globale Grenze werden gemeinsam angewendet; die jeweils engste zutreffende Grenze entscheidet.

Die Reihenfolge wird dauerhaft über die Datenbank als FIFO bestimmt. Maßgeblich ist das tatsächliche Repository-Ziel – bei verwalteten Repositorys das Verzeichnis, bei externen Repositorys die URL – und nicht nur die interne Datenbank-ID. Dadurch werden auch ältere doppelte Einträge mit demselben Ziel gemeinsam gesperrt. Freie globale Plätze werden mit startfähigen Läufen belegt; ein älterer Lauf, der selbst noch an einem belegten Repository oder Zeitplan wartet, blockiert unabhängige Repositorys nicht unnötig. Im vollständigen Laufprotokoll wird unterschieden, ob auf eine Repository-Ausführung, die Zeitplangrenze oder die globale Grenze gewartet wird. Nur tatsächlich lebende Manager-Tasks belegen Parallelitätsplätze, damit verwaiste Laufzustände die Warteschlange nicht dauerhaft sperren. Die Manager-Warteschlange kann keine Borg-Prozesse erfassen, die außerhalb des Managers gestartet wurden; für diese Fälle verwendet Borg zusätzlich seine eigene Sperre und `--lock-wait`.

### Ausführungen und Protokolle

Jede Aktion erzeugt einen Lauf mit:

- Lauf-ID
- Jobbezeichnung
- Aktion
- Status
- Startzeit
- Endzeit
- Dauer
- Ausführungsart `Manuell` oder `Zeitplan`
- Name des auslösenden Zeitplans
- Archivname und Borg-Größenstatistik bei Backup-Läufen
- Diagnose
- lesbarer Ausgabe
- technischen Details

Die Standardansicht zeigt eine aufbereitete Borg-Ausgabe mit Job, Gerät, Quellen, eindeutig als **Borg auf Client** bezeichneter Version, Statistik und Ergebnis. Der Detailkopf zeigt zusätzlich die Ausführungsart und – bei Backup-Läufen – die gespeicherten Original-, komprimierten und deduplizierten Größen. Bei `rc 1` sammelt der Manager Warnungsursachen bereits während des Borg-Prozesses zeilenweise aus stdout und stderr und speichert sie strukturiert direkt am Lauf. Dadurch bleiben frühe Warnungen auch dann erhalten, wenn danach sehr große Dateilisten folgen oder die sichtbare Protokollansicht gekürzt wird. Borg-Status `C` bedeutet „Datei während der Sicherung verändert“, `E` kennzeichnet einen Datei-Zugriffs- oder Lesefehler; zusätzlich werden verschwundene Dateien, Berechtigungsfehler, E/A-Fehler und nie passende Include-/Exclude-Muster unterschieden. Ist die Joboption **Verarbeitete Dateien im Live-Protokoll anzeigen** aktiv, werden alle Borg-Status und Pfade fortlaufend ausgegeben. Bei deaktivierter Dateiliste protokolliert der Manager weiterhin ausschließlich die warnungsrelevanten Status `C` und `E`. Gibt Borg trotz `rc 1` tatsächlich keine Detailzeile aus, wird dies ausdrücklich als **Ursache nicht ausgegeben** angezeigt. Der vollständige SSH-/Borg-Befehl, stdout und eine gefilterte Fehler-/Warnungsausgabe stehen getrennt unter **Technische Details**. Borg schreibt Dateilisten und Statistik regulär nach stderr; normale Statuszeilen werden nicht als Fehler angezeigt.

Laufende Aktionen können gestoppt werden. Der Manager beendet dabei nicht mehr nur den direkten Wrapper-Prozess, sondern die vollständige Prozessgruppe aus SSH, Shell, runuser und Borg. Bei über SSH auf einem Gerät ausgeführten Backups bleibt nach der einmaligen Geheimnisübergabe zusätzlich ein überwachter Steuerkanal offen. Ein Abbruch schließt zuerst diesen Kanal; der Remote-Wrapper signalisiert Borg auf dem Gerät mit SIGINT und wartet auf das tatsächliche Prozessende, bevor SSH und der repositoryweite Queue-Platz freigegeben werden. Das verhindert insbesondere zurückbleibende Locks externer Repositorys. Erst bei ausbleibender Reaktion folgen SIGTERM und als letzte Stufe SIGKILL. Die Abbruchanforderung wartet auf diesen Abschluss, bevor ein neuer Lauf angeboten wird. Ein automatisches `borg break-lock` wird bewusst nicht ausgeführt, da bei gemeinsam genutzten Repositories sonst eine aktive Sperre eines anderen Clients entfernt werden könnte. Abgeschlossene Jobläufe können wiederholt oder einzeln gelöscht werden. Die Ausführungsliste bietet die Filter Alle, laufend/wartend, fehlgeschlagen, Warnung, erfolgreich und abgebrochen sowie eine Textsuche.

Neue vollständige Live-Protokolle werden ausschließlich als Dateien unter `/data/run-logs/run-ID.log` gespeichert. SQLite enthält nur Laufmetadaten sowie feste kleine Vorschauen: maximal 4 KiB stdout, 32 KiB gefilterte Fehler-/Warnungsausgabe und 16 KiB zusammengeführtes Bedienprotokoll. Auch der laufende Prozess hält die Dateiliste nicht mehr vollständig im Arbeitsspeicher. Beim ersten Start von 0.8.7 werden große Altprotokolle aus SQLite in Logdateien überführt, auf Vorschaugröße reduziert und die Datenbank anschließend mit `VACUUM` komprimiert.

Unter **System → Einstellungen → Ausführungsprotokolle** sind konfigurierbar:

- Aufbewahrungsdauer in Tagen; `0` bedeutet unbegrenzt
- maximale Größe je Logdatei
- maximale in der WebUI geladene Protokollmenge
- sofortige Bereinigung abgelaufener Protokolle
- Löschen aller abgeschlossenen Protokolle

Die automatische Bereinigung läuft täglich um 03:30 Uhr Europe/Berlin. Aktive und wartende Läufe werden niemals entfernt. Bei manueller Bereinigung wird SQLite zusätzlich mit `VACUUM` komprimiert. Alte Läufe aus Versionen vor 0.8.7 bleiben weiterhin lesbar: vollständige Altinhalte werden beim ersten Start in Logdateien migriert, SQLite behält nur die begrenzten Vorschauen. Anschließend gilt dieselbe Aufbewahrungsregel.

Passphrasenfehler werden erst nach Abschluss eines fehlgeschlagenen Borg-Laufs diagnostiziert. Vorläufige Live-Fragmente können daher keine kurzzeitig eingeblendete falsche Meldung „Passphrase abgelehnt“ mehr erzeugen.

### Archive

Der Archivbrowser arbeitet ohne FUSE wie ein Dateibrowser. Er zeigt Breadcrumb-Navigation sowie Name, Größe, Typ, POSIX-Rechte, Besitzer/Gruppe und Änderungszeit der Archivobjekte.



Die Archivübersicht ist repositoryzentriert. Beim ersten Aufruf liest der Manager die vollständige Liste samt Archivstatistiken aus Borg und speichert sie persistent unter `/data/archive-cache`. Weitere Aufrufe verwenden diesen Zwischenspeicher und öffnen dadurch auch sehr große Repositorys deutlich schneller. Ein Backup-Job ist für das Auflisten, Anzeigen von Archivinformationen und Durchsuchen des Inhalts nicht erforderlich. Ein zeitgesteuerter Seitenrefresh wird dafür nicht verwendet.

Verfügbare Funktionen:

- Repository direkt auswählen und die gespeicherte Liste sofort anzeigen
- Archivcache-Zeitpunkt und Datenquelle in der Zusammenfassung erkennen
- bei extern vorgenommenen Änderungen bewusst **Neu aus Repository einlesen** ausführen
- alle Archive des Repositorys immer absteigend mit dem neuesten Archiv zuerst anzeigen
- Archive anhand reservierter Archivserien, Borg-Hostname oder Archivname dem richtigen Gerät zuordnen und danach filtern
- nicht eindeutig erkennbare Archivnamen bei Bedarf separat anzeigen
- Jobzuordnung anhand der Archivpräfixe erkennen
- Legacy- und fremde Archive erkennen
- Checkpoint-Archive optional einblenden
- Archivdetails anzeigen
- Archivinhalt ohne FUSE durchsuchen
- bei eindeutiger Jobzuordnung Archive vergleichen, umbenennen oder wiederherstellen
- einzelne oder mehrere Archive repositoryweit auswählen und mit einer gemeinsamen Sicherheitsbestätigung löschen
- gemischte Auswahlen in Bestätigung und Laufprotokoll als **Mehrere Geräte** kennzeichnen
- nach der gesamten Mehrfachlöschung optional genau einmal Compact ausführen
- Compact unabhängig von einem Backup-Job direkt in der Repository-Liste starten

Die Gerätezuordnung verwendet zuerst aktuelle und historische Jobpräfixe. Für Legacy- oder fremde Archive werden anschließend der von Borg gespeicherte Hostname und ein aus dem Archivnamen erkennbares Gerät mit den konfigurierten Geräten abgeglichen. Aktuelle Namen wie `bbm-12-server01-2026-07-17T22:00:00`, historische Manager-Präfixe und übliche Muster wie `server01-2026-07-17_22-00-00` oder `docker-2026-07-17_03-20` werden erkannt. Sekunden im Zeitstempel sind optional. Der Filter arbeitet ausschließlich im Browser auf dem persistenten Cache und löst keinen zusätzlichen Borg-Aufruf aus. Eine Löschanforderung prüft die exakten Archivnamen vor dem Start erneut direkt im Repository.

Nach erfolgreichen Backups, Prune-Läufen oder Archivumbenennungen wird ausschließlich der Cache des betroffenen Repositorys invalidiert. Nach einer begonnenen Archivlöschung wird der Cache auch bei Abbruch oder Fehler verworfen, weil eine Mehrfachaktion bereits teilweise wirksam gewesen sein kann. Die nächste Anzeige baut ihn einmalig neu auf. Repositorys, die sich nicht geändert haben, werden weiterhin direkt aus dem Cache angezeigt. Bei verwalteten Repositories verwendet der Manager den direkten lokalen Pfad. Externe Repositories öffnet er selbst per Borg und SSH mit den zentral verschlüsselt gespeicherten Repository-Zugangsdaten. Ein Backup-Job ist für Lesen, Archivinformationen und Browsen nicht erforderlich. Restore und andere datenpfadabhängige Aktionen benötigen weiterhin einen passenden Ziel- beziehungsweise Quell-Client.

### Archivbrowser

Der Archivbrowser benötigt kein FUSE. Er verwendet Borg List und lädt jeweils die aktuelle Verzeichnisebene.

Funktionen:

- in Ordner navigieren
- Dateityp, Größe und Änderungszeit anzeigen
- Dateien markieren
- Ordner markieren
- Auswahl in den Restore übernehmen
- Auswahl als TAR.GZ exportieren
- dauerhaft sichtbare Fehlermeldungen

### Archivexport

Markierte Dateien und Ordner werden im Manager aus dem Repository extrahiert und als TAR.GZ bereitgestellt. Temporäre Exportdaten werden nach dem Download entfernt.

### Wiederherstellung

#### Archivauswahl

Nach Auswahl des Jobs werden die tatsächlich verfügbaren Archivnamen geladen. Optional können alle Repository-Archive und Legacy-Archive freigegeben werden.

#### Pfadauswahl

Pfade können manuell eingetragen oder aus dem Archivbrowser übernommen werden.

#### Dry-Run

Ein Testlauf prüft die Auswahl und den Borg-Befehl, schreibt aber keine Dateien. Der Lauf wird tatsächlich gestartet und direkt im Live-Protokoll geöffnet.

#### Originalpfad

Ausgewählte Dateien und Ordner werden auf dem Client an ihren ursprünglichen absoluten Pfad zurückgeschrieben. Ein produktiver Lauf erfordert eine ausdrückliche Bestätigung, weil bestehende Dateien überschrieben werden können.

#### Alternatives Ziel

Zwei Layouts stehen zur Verfügung:

- Auswahlwurzel entfernen: nur die ausgewählte Datei oder der ausgewählte Ordner landet direkt im Ziel.
- vollständige Archivpfade beibehalten: der gesamte Pfad aus dem Archiv wird unterhalb des Zielverzeichnisses angelegt.

### Manager-Backup

Ein Manager-Backup enthält:

- Manager-Datenbank und Einstellungen
- separate Sicherheitsdatenbank mit Benutzern und Sitzungshashes
- Master-Key für Repository-Passphrasen und Keyfiles
- Controller- und Repository-SSH-Schlüssel
- Borg-Keyfiles
- TLS-Zertifikate
- relevante nicht geheime Migrationswerte

Nicht enthalten sind Repository-Nutzdaten und vollständige Laufprotokolle unter `/data/run-logs`.

Beim Erstellen ist die Bezeichnung optional. Neue Manager-Backups werden ausschließlich als mit eigener Passphrase verschlüsselte und authentifizierte `.bbm`-Datei erzeugt; die Passphrase muss mindestens zwölf Zeichen lang sein. Historische unverschlüsselte `.zip`-Backups bleiben für bestehende Sicherungen wiederherstellbar, können aber nicht mehr neu erstellt werden.

Die `.bbm`-Verschlüsselung verwendet AES-256-GCM und scrypt. Die Backup-Passphrase wird weder gespeichert noch in einer Datenbank abgelegt.

Unter **System → Manager-Backup → Hochladen** kann eine vorhandene `.bbm`-Datei oder ein historisches Manager-Backup im `.zip`-Format in die lokale Backupliste übernommen werden. Der Manager prüft Dateinamen, Größenlimit und Struktur, speichert die Datei mit Modus `0600` und überschreibt niemals ein bereits vorhandenes Backup. Bei verschlüsselten `.bbm`-Dateien wird beim Upload der authentifizierte Containeraufbau geprüft; die vollständige AES-GCM-Authentifizierung erfolgt bei der Wiederherstellung nach Eingabe der Passphrase.

Unter **System → Manager-Backup → Wiederherstellen** kann ein vorhandenes oder hochgeladenes Backup direkt eingespielt werden. Vorher wird mit einer separat einzugebenden Passphrase automatisch ein verschlüsseltes Sicherheitsbackup erstellt. Laufende und wartende Ausführungen blockieren den Vorgang. Nach erfolgreicher Prüfung werden Manager- und Sicherheitsdatenbank, Einstellungen sowie SSH-, TLS- und Repository-Schlüssel ersetzt; der Container startet automatisch neu. Alle Browser-Sitzungen aus dem vorherigen Stand verlieren dadurch ihre Gültigkeit.

Für einen Serverwechsel kann `restore-backup.sh` verwendet werden. Neue Backups bringen Sicherheitsdatenbank und Master-Key vollständig mit. Alte 0.8.x-Backups werden beim ersten Start über ihre vorhandenen Altwerte migriert. Verschlüsselte `.bbm`-Dateien werden nach Installation von `python3-cryptography` unterstützt.

### Benachrichtigungszentrale

Unter **System → Benachrichtigungen** konfigurieren Administratoren eine zentrale Ereigniszustellung. Unterstützt werden:

- E-Mail über SMTP mit STARTTLS, direktem TLS/SSL oder bewusst unverschlüsseltem Transport für isolierte interne Netze
- generischer JSON-Webhook
- Discord-Webhook
- Telegram-Bot mit Chat-ID oder Kanalname

Die Ereignisauswahl umfasst fehlgeschlagene, mit Warnungen beendete und optional erfolgreiche Backups, abgebrochene Läufe, Repository-Aktionen, Zeitplanfehler sowie sonstige Manager-Ausführungen. Bei strukturierten Borg-Warnungen enthält die Nachricht zusätzlich die konkret betroffene Datei beziehungsweise den Pfad; bis zu zehn Einträge werden ausgegeben, weitere als Anzahl zusammengefasst. Erfolgsereignisse sind standardmäßig deaktiviert, damit Installationen mit vielen täglichen Backups nicht unnötig viele Meldungen erzeugen.

SMTP-Passwort, Webhook-URL und Telegram-Bot-Token liegen ausschließlich verschlüsselt in der Sicherheitsdatenbank. Die nicht geheimen Einstellungen werden unter `/data/notifications.json` gespeichert und sind Bestandteil eines Manager-Backups. Leere Geheimnisfelder behalten den bereits gespeicherten Wert; separate Löschoptionen entfernen ihn ausdrücklich.

Jeder Kanal besitzt eine Testfunktion. Das Zustellungsprotokoll zeigt Versandzeit, Kanal, Ereignis, Titel sowie Erfolg oder konkrete Fehlermeldung. Ein fehlgeschlagener Benachrichtigungsversand verändert niemals den Status des Borg-Laufs und blockiert keine Repository- oder globale Warteschlange. Der Versand startet erst, nachdem der Laufstatus gespeichert und der Ausführungsplatz freigegeben wurde.

Der generische Webhook erhält ein JSON-Dokument mit `source`, `event`, `severity`, `title`, `message`, `run_id` und `timestamp`. Diagnoseausschnitte sind gefiltert, auf 4.000 Zeichen begrenzt und können vollständig deaktiviert werden.

### Zeitzone

Anwendungs- und Aktivitätszeitpunkte werden als UTC gespeichert und verbindlich in `Europe/Berlin` dargestellt. Borg 1.x liefert Archivzeitpunkte teilweise ohne Zeitzonenkennung; solche Werte interpretiert der Manager als lokale Zeit der konfigurierten Zeitzone, statt sie fälschlich als UTC nochmals umzurechnen. Cron-Ausdrücke werden ebenfalls in `Europe/Berlin` ausgeführt. Der Manager setzt `TZ=Europe/Berlin` auch für remote gestartete Borg-Befehle, damit Start- und Endzeiten im Borg-Protokoll mit der WebUI übereinstimmen.

### Aktionsbezogene Aktualisierung

Nach Speichern, Löschen, Prüfen oder Starten einer Borg-Aktion bestätigt die WebUI den Vorgang sofort am betätigten Button und in der Statusanzeige des Seitenkopfs. Sind Aufgaben aktiv, zeigt dieselbe Position vor dem Hell-/Dunkel-Schalter die aktuell laufende Aufgabe und gegebenenfalls die Zahl weiterer aktiver Läufe. Ein Klick öffnet ohne Zwischenmenü unmittelbar das Live-Log des aktuell laufenden Vorgangs. Gibt es noch keinen laufenden, aber bereits einen wartenden Lauf, öffnet der Klick den nächsten wartenden Vorgang. Hintergrundläufe werden anhand ihrer konkreten Lauf-ID bis zu einem Endstatus verfolgt. Erst danach lädt der Browser gezielt die betroffenen Daten neu, beispielsweise Jobs, Repositories, Laufprotokolle oder die aktuell geöffnete Archivliste. Diese Aktualisierung hängt nicht vom konfigurierten Hintergrundintervall ab und benötigt kein vollständiges Neuladen der Seite. GET-Abfragen verwenden zusätzlich `no-store`, damit nach einer Aktion keine veraltete Browserantwort angezeigt wird.

### Persönliche Darstellung und Sprache

Jeder Benutzer kann über **Darstellung & Sprache** seine Oberfläche unabhängig einstellen:

- Sprache: Deutsch oder Englisch
- Farbschema: Automatisch, Hell oder Dunkel

Beide Werte werden benutzerbezogen in der Sicherheitsdatenbank gespeichert. Eine Änderung wirkt ausschließlich auf das angemeldete Konto und verändert weder die Darstellung anderer Benutzer noch eine systemweite Vorgabe. Das integrierte Betriebshandbuch und die aktuellen Release Notes werden passend zur gewählten Sprache geladen.

### Systemeinstellungen

Administratoren können systemweit konfigurieren:

- Darstellungsdichte mit deutlich unterscheidbaren Modi „Komfortabel“ und „Kompakt“
- Anzahl letzter Läufe im Dashboard
- Anzahl Läufe in der Protokollliste
- zusätzliche Hintergrundaktualisierung; gestartete Aktionen werden unabhängig davon bis zum Abschluss verfolgt
- sichtbarer Aktionsstatus mit laufender, erfolgreicher oder fehlgeschlagener Bestätigung
- maximale Höhe der Archivübersicht und weiterer scrollbarer Listen
- Aufbewahrungsdauer der Laufprotokolle
- maximale Logdateigröße pro Lauf
- maximale Protokollmenge in der WebUI
- manuelle Bereinigung und Speicherübersicht
- automatische Größenberechnung nach manuellen Schreibvorgängen und genau einmal nach Abschluss eines vollständigen Zeitplans
- Compact nach geplantem Prune
- zentrale Ausschlussvorlagen

### Release Notes

Release Notes werden passend zur persönlichen Spracheinstellung auf Deutsch oder Englisch geladen und innerhalb der WebUI mit automatischem Zeilenumbruch angezeigt. Lange Befehle, Pfade und Textzeilen bleiben innerhalb der verfügbaren Anzeigefläche.

## Installation

```bash
cd /opt
unzip /pfad/BorgBackup-Manager-1.0.54.zip
cd BorgBackup-Manager
chmod +x install.sh update.sh recovery.sh restore-backup.sh
bash install.sh
```

Das ZIP erzeugt direkt `/opt/BorgBackup-Manager` und keinen Ordner mit Versionssuffix.

### `.env` und Skriptverhalten

`.env.example` enthält alle regulär unterstützten Hostvariablen mit produktionsnahen Standardwerten. `install.sh` erzeugt eine vollständige `.env`, erhält bei erneuter Ausführung zusätzliche bestehende Schlüssel und validiert Ports, Pfade, Boolean-Werte, Zeitlimits, Cookie-Namen, Darstellung und Logrotation. Daten- und Repository-Pfad dürfen nicht identisch sein.

Der Updater verifiziert ab Version 1.0.38 vor jedem Einlesen des Release-ZIPs die veröffentlichte SHA-256-Prüfsumme und validiert anschließend neben den Laufzeitdateien auch `.env.example`, README, Installationsanleitung und Release Notes. Fehlende neue `.env`-Werte werden mit ihren Erläuterungen ergänzt. Wird der Vorgang nach dem kontrollierten Container-Stopp abgebrochen oder scheitert die Managersicherung, startet `update.sh` den zuvor gestoppten Container automatisch wieder und entfernt eine unvollständige `.partial`-Datei. `--one-file-system` verhindert zusätzlich, dass unerwartete Unter-Mounts in die Managersicherung gelangen.

Standardwerte:

```text
WebUI:          https://SERVER:8443
Repository-SSH: SERVER:2222
Daten:          /docker_data/borgbackup-manager/data
Repositories:   /docker_data/borgbackup-manager/repositories
Image:          borgbackup-manager:latest
Container:      borgbackup-manager
```

## Update

### WebUI friert nach Version 1.0.26/1.0.27 ein

Die erste zweisprachige Oberfläche konnte durch identische Schreibzugriffe des Übersetzungs-Observers eine Endlosschleife auslösen. In diesem Zustand reagieren Anmeldemaske und Navigation nicht, obwohl Container und Auth-API gesund sind. Version 1.0.28 behebt die Ursache. Das Update kann vollständig über die Shell ausgeführt werden; anschließend die Seite einmal mit `Strg+F5` neu laden.

### Fehlgeschlagener Übergang von 1.0.25 auf 1.0.26

Wenn der Build mit `RELEASE_NOTES.en.md: not found` abgebrochen und der Projektstand automatisch zurückgesetzt wurde, kann direkt Version 1.0.28 installiert werden. Der Fehler betraf ausschließlich den Projekt-Build-Kontext: Der Updater 1.0.25 übernahm die neu hinzugekommene Top-Level-Datei noch nicht. Version 1.0.28 macht den Docker-Build wieder mit dieser alten Datei-Whitelist kompatibel; ein manuelles Kopieren der Datei ist nicht erforderlich.


### Einmaliger Übergang von 1.0.4 oder älter auf 1.0.5

Beim Update auf 1.0.5 muss `recovery.sh` einmalig vor dem normalen Update aus dem ZIP übernommen werden, weil der alte Updater diese Datei noch nicht kennt:

```bash
cd /opt/BorgBackup-Manager
cp /pfad/BorgBackup-Manager-1.0.5.zip updates/
unzip -p updates/BorgBackup-Manager-1.0.5.zip BorgBackup-Manager/recovery.sh > recovery.sh
chmod 755 recovery.sh
bash update.sh --file updates/BorgBackup-Manager-1.0.5.zip
```

### Einmaliger Übergang von 1.0.9 auf 1.0.10

Version 1.0.9 konnte beim Datenbackup ein unterhalb von `BBM_DATA_PATH` liegendes Repository-Verzeichnis und den Borg-Cache mitkomprimieren. Das sah nach `Container borgbackup-manager Stopped` wie ein Stillstand aus. Wenn dieser Zustand bereits eingetreten ist, den laufenden Updater mit `Strg+C` abbrechen und den aktuellen Container wieder starten:

```bash
cd /opt/BorgBackup-Manager
docker compose up -d
```

Da das bereits gestartete 1.0.9-Skript seine alten Funktionen im Speicher behält, muss für diesen Übergang das neue `update.sh` vor dem Start übernommen werden:

```bash
cd /opt/BorgBackup-Manager
cp /pfad/BorgBackup-Manager-1.0.10.zip updates/
unzip -p updates/BorgBackup-Manager-1.0.10.zip BorgBackup-Manager/update.sh > update.sh.new
chmod 755 update.sh.new
mv update.sh.new update.sh
bash update.sh --file updates/BorgBackup-Manager-1.0.10.zip
```

Ein beim abgebrochenen Vorgang neu angelegtes `*-persistent-v<Ausgangsversion>.tar.gz` kann unvollständig sein und darf nicht als gültige Sicherung verwendet werden. Ab Version 1.0.10 schließt das Update-Backup ein innerhalb des Manager-Datenpfads liegendes `BBM_REPOSITORY_PATH` sowie `/data/borg-cache` und `/data/archive-cache` ausdrücklich aus. Repository-Inhalte werden nicht gelesen oder komprimiert. Das Archiv wird zunächst als unvollständige Datei geschrieben und erst nach erfolgreichem Abschluss in `.tar.gz` umbenannt.

### Normale Updates ab Version 1.0.10

```bash
cd /opt/BorgBackup-Manager
cp /pfad/BorgBackup-Manager-NEUE-VERSION.zip updates/
bash update.sh --file updates/BorgBackup-Manager-NEUE-VERSION.zip --sha256 VERÖFFENTLICHTE_SHA256
```

Die persistente `.env`, Manager- und Sicherheitsdatenbank, Schlüssel und TLS-Dateien bleiben erhalten. Repositories und regenerierbare Borg-Caches sind bewusst nicht Bestandteil des Update-Backups. Beim ersten Update von 0.8.x werden alte Token-/Schlüsselwerte automatisch migriert und anschließend aus `.env` entfernt.

## Sicherheitshinweise

- `/data/security/security.db` und `/data/security/master.key` nur gemeinsam sichern und wiederherstellen.
- Private SSH-Schlüssel, TLS-Privatschlüssel, Repository-Passphrasen und Borg-Keyfiles liegen verschlüsselt in `security.db`; Klartextdateien entstehen nur temporär unter `/run/bbm-secrets` oder `/tmp/bbm-borg.*`.
- Port 2222 per Firewall auf bekannte Clients begrenzen.
- Mehrere Clients in einem Repository müssen gegenseitig vertrauenswürdig sein.
- Borg Repair und automatisches Break-lock werden absichtlich nicht angeboten.
- Datenbanken und aktive Anwendungen benötigen anwendungskonsistente Dumps oder Snapshots.
- Vor Restore, Prune, Compact und Archivlöschung aktuelle Sicherungen prüfen.

## Vorhandenes verwaltetes Repository gezielt auswählen

Neben **Automatisch suchen** steht auf der Repository-Seite **Ordner auswählen** zur Verfügung. Der Browser ist strikt auf `/repositories` begrenzt, folgt keinen symbolischen Links und kennzeichnet direkte Unterordner mit Borg-`config` als auswählbar. Die Auswahl füllt das vorhandene Importformular; vor der Registrierung wird das Repository geprüft und niemals initialisiert oder überschrieben.

## Diagnose

```bash
cd /opt/BorgBackup-Manager
docker compose ps
docker compose logs --tail=200 borg-manager
curl -k https://127.0.0.1:8443/api/ready
```

Die Web-API läuft als Benutzer `borg`. Managerseitige Borg-Aktionen werden deshalb direkt unter diesem Benutzer ausgeführt; `runuser` wird nur in Root-Kontexten verwendet. Die Root-exklusive Prüfung `sshd -t` wird beim Containerstart ausgeführt und in der WebUI-Diagnose über eine geschützte Laufzeitmarkierung angezeigt.

Repository-Dienst:

```bash
docker compose exec -T borg-manager pgrep -a sshd
docker compose exec -T borg-manager tail -n 200 /data/logs/sshd.log
docker compose exec -T borg-manager tail -n 200 /data/logs/borg-serve.log
docker compose exec -T borg-manager tail -n 200 /data/logs/debug.log
```

## Entwicklung und Prüfung

```bash
python -m compileall app
node --check app/static/app.js
bash -n install.sh update.sh recovery.sh restore-backup.sh
sh -n docker/entrypoint.sh docker/borg-serve.sh
PYTHONPATH=. pytest -q
```


### Checkpoint-Archive anzeigen

Die Archivübersicht blendet Checkpoint-Archive standardmäßig aus. Bei Bedarf kann „Unvollständige Checkpoint-Archive anzeigen“ aktiviert werden. Der Manager ergänzt dann `borg list --consider-checkpoints`. Checkpoints entstehen bei unterbrochenen Sicherungen und können nur einen Teil der vorgesehenen Dateien enthalten; Restore oder Löschen sollte daher bewusst erfolgen.

## Lokales Recovery-Skript

Alle bisherigen Befehle zur Kontowiederherstellung sind über ein gemeinsames Skript erreichbar:

```bash
cd /opt/BorgBackup-Manager
./recovery.sh
```

Das interaktive Menü bietet:

1. Kontozustand anzeigen
2. einmalige Erstanmeldedaten anzeigen
3. Benutzerkonto entsperren
4. Benutzerpasswort zurücksetzen
5. Benutzerpasswort zurücksetzen und Administratorrolle setzen
6. JSON-Status für Diagnose ausgeben

Direkte Aufrufe sind ebenfalls möglich:

```bash
./recovery.sh status
./recovery.sh status-json
./recovery.sh initial-admin
./recovery.sh unlock BENUTZER
./recovery.sh reset BENUTZER
./recovery.sh reset-admin BENUTZER
```

Passwortresets widerrufen bestehende Sitzungen und erzeugen ein temporäres Passwort. Das Skript arbeitet ausschließlich lokal über `docker compose exec` und stellt keinen zusätzlichen Recovery-Endpunkt über das Netzwerk bereit.

## Repository- und Archivstatistiken

Die Repository-Übersicht zeigt nach **Größe berechnen**:

| Wert | Bedeutung |
|---|---|
| Original | Summe der ursprünglichen Daten aller Archive gemäß Borg-Statistik |
| Dedupliziert | repositoryweit vorhandene eindeutige, komprimierte Chunks |
| Komprimiert | Summe der komprimierten Daten vor repositoryweiter Deduplizierung |
| Dateisystem | nur bei verwalteten Repositories: tatsächliche Größe der Repository-Dateien im eingebundenen Verzeichnis |

Bei externen Repositories kann der Manager keine serverseitige Dateisystembelegung wie mit `du` ermitteln. Dort werden deshalb die drei von Borg gelieferten Werte angezeigt. Die Werte stehen zeilenweise mit Bezeichnung links und Größe rechts. Bei verwalteten Repositories wird darunter zusätzlich die lokale Dateisystembelegung angezeigt.

Die Archivübersicht speichert die einmal aus Borg geladenen Detailangaben persistent und zeigt sie anschließend ohne erneuten repositoryweiten Scan:

- Start- und Endzeit
- Dauer
- Anzahl der Dateien
- Originalgröße
- komprimierte Größe
- deduplizierte Größe dieses Archivs
- Hostname, Benutzer, Kommentar und Archiv-ID

Die deduplizierte Größe eines einzelnen Archivs bezeichnet nur die Chunks, die ausschließlich dieses Archiv benötigt. Sie darf deshalb nicht zur repositoryweiten deduplizierten Größe aufsummiert werden.

Der Cache enthält keine Repository-Nutzdaten, sondern ausschließlich die JSON-Metadaten der Archivübersicht. Er ist regenerierbar, wird nicht in Update-Backups aufgenommen und kann bei externen Borg-Änderungen über **Neu aus Repository einlesen** ersetzt werden. Archivdetails werden direkt aus der gespeicherten Liste angezeigt, sofern Borg dort bereits vollständige Statistiken geliefert hat.
