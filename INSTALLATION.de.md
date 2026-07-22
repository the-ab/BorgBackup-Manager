# Installation und Betrieb – BorgBackup Manager 1.0.63

Die englische Standardanleitung befindet sich in `INSTALLATION.md`. Diese Datei ist die deutsche Ausgabe gemäß der einheitlichen `.de.md`-Namenskonvention.

## 1. Voraussetzungen des Manager-Hosts

Empfohlen:

- Debian oder Ubuntu als Docker-Host
- Docker Engine
- Docker Compose v2
- erreichbare TCP-Ports 8443 und 2222
- persistenter lokaler Datenträger oder geeigneter NFS-Mount für Repositories
- funktionierende Uhrzeit und Zeitzone

Der Container selbst basiert auf Debian 13 Trixie und installiert Borg 1.4.x.

## 2. Release entpacken

Der ZIP-Dateiname enthält die Version, der enthaltene Hauptordner jedoch nicht:

```text
BorgBackup-Manager-1.0.63.zip
└── BorgBackup-Manager/
```

Installation unter `/opt`:

```bash
cd /opt
unzip /pfad/BorgBackup-Manager-1.0.63.zip
cd BorgBackup-Manager
chmod +x install.sh update.sh restore-backup.sh recovery.sh
```

Nach dem Entpacken lautet der Projektpfad immer:

```text
/opt/BorgBackup-Manager
```

## 3. Geführte Installation

```bash
cd /opt/BorgBackup-Manager
bash install.sh
```

Das Skript fragt ab:

- Datenverzeichnis
- Repository-Verzeichnis
- öffentliche IP oder DNS-Adresse des Managers
- HTTPS-Port
- Repository-SSH-Port
- Speicherplatz-Sperre
- Speichergrenze
- UID und GID des eingeschränkten Borg-Benutzers

Standardpfade:

```text
BBM_DATA_PATH=/docker_data/borgbackup-manager/data
BBM_REPOSITORY_PATH=/docker_data/borgbackup-manager/repositories
```

Diese Werte sind im Installationsskript zentral definiert. Bei einer Neuinstallation ohne vorhandene `.env` müssen genau diese vollständigen Pfade im Dialog erscheinen. Die Zeitzone wird vor allen Validierungen aus `TZ`, einer vorhandenen `.env` oder dem Standard `Europe/Berlin` bestimmt.

Das Skript erzeugt `.env` und die persistenten Verzeichnisse. Admin-Token und `BBM_SECRET_KEY` werden bei einer Neuinstallation nicht erzeugt. Beim ersten Containerstart entstehen:

```text
/docker_data/borgbackup-manager/data/security/security.db
/docker_data/borgbackup-manager/data/security/master.key
```

Passwörter werden als scrypt-Prüfwerte gespeichert. Controller-, Repository-SSH- und TLS-Privatschlüssel, Repository-Passphrasen sowie Borg-Keyfiles werden verschlüsselt in `security.db` abgelegt. `master.key` ist der einzige externe Vertrauensanker und besitzt Modus `0600`. Laufzeitdateien werden ausschließlich unter `/run/bbm-secrets` materialisiert.

Der Image-Name ist `borgbackup-manager:latest`, der Containername `borgbackup-manager`, der interne Hostname `bbm`.

### Vollständige `.env`-Konfiguration

Die Datei `.env.example` ist die Referenz für alle vom Compose-Stack unterstützten Hostwerte. `install.sh` erzeugt daraus eine vollständige `.env` und bewahrt bei einer erneuten Konfiguration zusätzliche vorhandene Schlüssel. Besonders relevant sind:

```text
TZ=Europe/Berlin
BBM_HTTPS_PORT=8443
BBM_REPOSITORY_SSH_PORT=2222
BBM_REPOSITORY_PUBLIC_HOST=backup-manager.example.org
BBM_TLS_HOSTS=backup-manager.example.org,localhost,127.0.0.1
BBM_DATA_PATH=/docker_data/borgbackup-manager/data
BBM_REPOSITORY_PATH=/docker_data/borgbackup-manager/repositories
BBM_BORG_UID=1000
BBM_BORG_GID=1000
BBM_SESSION_TTL_SECONDS=86400
BBM_SESSION_IDLE_TIMEOUT_SECONDS=3600
BBM_SESSION_COOKIE_NAME=bbm_session_v2
BBM_SESSION_COOKIE_SECURE=always
BBM_TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128
BBM_LOGIN_RATE_WINDOW_SECONDS=300
BBM_LOGIN_RATE_BLOCK_SECONDS=900
BBM_LOGIN_RATE_MAX_PER_IP=20
BBM_LOGIN_RATE_MAX_PER_IP_USER=5
BBM_SECURITY_EVENT_RETENTION_DAYS=90
BBM_SECURITY_EVENT_MAX_ROWS=10000
BBM_BACKUP_MAX_FILE_BYTES=268435456
BBM_BACKUP_MAX_UNCOMPRESSED_BYTES=1073741824
BBM_BACKUP_MAX_ENTRIES=5000
BBM_BACKUP_MAX_COMPRESSION_RATIO=250
BBM_COMMAND_TIMEOUT=86400
BBM_APPEARANCE=auto
BBM_REPOSITORY_SIZE_AFTER_RUN=1
BBM_STORAGE_GUARD_ENABLED=1
BBM_STORAGE_GUARD_THRESHOLD_PERCENT=95
BBM_HEALTH_REQUIRE_SSHD=1
BBM_LOG_MAX_BYTES=10485760
BBM_LOG_ROTATIONS=5
BBM_DEBUG_LOG_LEVEL=WARNING
```

`BBM_SESSION_COOKIE_SECURE=always` ist der empfohlene und voreingestellte Wert. Der Manager wird selbst per HTTPS ausgeliefert. `auto` und insbesondere `never` sind nur für ausdrücklich geprüfte Sonderfälle vorgesehen. Proxy-Header beeinflussen Scheme, Client-IP oder Origin ausschließlich, wenn die unmittelbare Proxy-Adresse in `BBM_TRUSTED_PROXY_CIDRS` liegt. Bei einem separaten Docker-Reverse-Proxy muss dessen festes Container-Netz dort ausdrücklich ergänzt werden; eingehende Forwarded-Header sind am Proxy zu überschreiben.

Beim Update wird der frühere unveränderte Standard `BBM_SESSION_COOKIE_NAME=bbm_session` durch `update.sh` auf dem Host automatisch auf `bbm_session_v2` umgestellt. Bis dahin interpretiert die Anwendung den alten Standardwert bereits zur Laufzeit als neuen Namen. Der Container ersetzt die als einzelne Datei bind-gemountete `.env` bewusst nicht selbst; andere individuell gesetzte Cookie-Namen werden nicht verändert.

`BBM_APPEARANCE` ist nur ein rückwärtskompatibler Startwert für Konten, die noch keine persönliche Darstellung gespeichert haben. Danach gilt das benutzerbezogene Farbschema aus **Darstellung & Sprache**. `BBM_REPOSITORY_SIZE_AFTER_RUN` bestimmt den Anfangswert der systemweiten Größenaktualisierung, solange noch keine `settings.json` vorhanden ist. Die Zertifikatpfade `BBM_TLS_CERT_FILE` und `BBM_TLS_KEY_FILE` sind nur für die einmalige Übernahme alter Klartext-Zertifikate vorgesehen und gehören bei aktuellen Installationen normalerweise nicht in `.env`.

Daten- und Repository-Pfad dürfen nicht identisch sein. Die neuen Standardpfade liegen als getrennte Geschwisterverzeichnisse unter `/docker_data/borgbackup-manager`: Managerdaten unter `data`, Repositories unter `repositories`. Abweichende Bestandsinstallationen bleiben unterstützt; liegt das Repository-Verzeichnis innerhalb des Datenpfads, schließt der Updater es bei der Managersicherung gezielt aus. Host-Port und Hostpfade werden zusätzlich als reine Metadaten in den Container übergeben, damit ein Manager-Backup sie vollständig in `migration.env` aufnehmen kann; die tatsächlichen Mounts bleiben unverändert durch Compose definiert.

## 4. Bestehende Daten übernehmen und 0.8.x migrieren

Für eine Neuinstallation mit vorhandenem Zustand müssen `.env`, das persistente Datenverzeichnis und das Repository-Verzeichnis weiterverwendet werden. Niemals `docker compose down -v` oder das Löschen von `/docker_data/borgbackup-manager` verwenden.

```bash
cd /opt/BorgBackup-Manager-alt
docker compose down

cd /opt
unzip /pfad/BorgBackup-Manager-1.0.63.zip
cp /opt/BorgBackup-Manager-alt/.env /opt/BorgBackup-Manager/.env
cd /opt/BorgBackup-Manager
docker compose up -d --build
```

Beim ersten Start einer aktuellen 1.x-Version gilt für Installationen aus 0.8.x weiterhin:

1. `BBM_ADMIN_TOKEN` wird einmalig als temporäres Passwort des Benutzers `admin` übernommen.
2. Das Konto muss das Passwort nach der Anmeldung ändern.
3. `BBM_SECRET_KEY` entschlüsselt bestehende Repository-Passphrasen und Keyfiles.
4. Diese Geheimnisse werden sofort mit dem neuen zufälligen Master-Key neu verschlüsselt.
5. Nach erfolgreicher Migration werden `BBM_ADMIN_TOKEN`, `BBM_SECRET_KEY` und `BBM_ALLOW_LEGACY_TOKEN_AUTH` aus der Host-`.env` entfernt.
6. Docker Compose übergibt diese Werte nicht als dauerhafte Container-Umgebung.

Die neue Sicherheitsdatenbank und der Master-Key liegen anschließend unter `BBM_DATA_PATH/security`. Beide gehören zusammen und müssen gemeinsam gesichert werden.

## 5. WebUI öffnen und Erstanmeldung

```text
https://SERVER:8443
```

Das automatisch erzeugte Zertifikat ist selbstsigniert. Fingerprint prüfen und im Browser akzeptieren. TLS-Zertifikat und privater Schlüssel werden verschlüsselt in `security.db` gespeichert und beim Containerstart nur unter `/run/bbm-secrets/tls` bereitgestellt. Vorhandene Zertifikatsdateien aus älteren Installationen werden einmalig importiert und danach entfernt.

Neue Installation – einmalige Zugangsdaten anzeigen:

```bash
cd /opt/BorgBackup-Manager
docker compose exec -T borg-manager python -m app.initial_admin
```

Mit Benutzer `admin` und dem temporären Passwort anmelden. Die WebUI erzwingt unmittelbar ein neues persönliches Passwort. Es muss mindestens zwölf Zeichen enthalten und mindestens drei der Gruppen Kleinbuchstaben, Großbuchstaben, Ziffern und Sonderzeichen verwenden. Nach dem Wechsel wird das verschlüsselte Bootstrap-Geheimnis gelöscht. Sitzungen werden serverseitig gespeichert und über ein `HttpOnly`-/`SameSite=Strict`-/`Secure`-Cookie zugeordnet. Sie enden standardmäßig nach 24 Stunden absolut oder nach 60 Minuten Inaktivität. Ein separater, nur im aktuellen Tab gespeicherter Reload-Schlüssel ist serverseitig gehasht, an Sitzung und User-Agent gebunden und verliert beim Schließen des Tabs, Abmelden, Passwortwechsel oder Sitzungsablauf seine Wirkung. Teure Passwortprüfungen werden persistent pro Quelle und pro Quelle/Benutzer-Kombination begrenzt; Benutzerkonten werden durch fremde Fehlversuche nicht mehr systemweit gesperrt.

### Mobile Bedienung

Auf Smartphones und schmalen Tablets zeigt die Kopfzeile der Seitenleiste die Schaltfläche **Menü**. Sie öffnet Navigation und Kontofunktionen; nach Auswahl eines Bereichs wird das Menü automatisch geschlossen. Die Betriebsseiten wurden bei 360, 390 und 768 Pixel Breite geprüft. Tabellen wechseln auf beschriftete Karten, Formulare werden einspaltig, Aktionsschaltflächen umbrechen vollständig und Dialoge bleiben innerhalb der sichtbaren Bildschirmhöhe. Es ist kein horizontales Scrollen der gesamten WebUI erforderlich.

Unter **Infrastruktur** enthält die Seitenleiste ausschließlich **Geräte** und **System**. Der Systembereich besitzt direkt in der sticky Kopfzeile eine horizontale Reiterleiste für **Benachrichtigungen**, **Benutzer**, **Manager-Backup**, **Einstellungen** und **Systemdiagnose**. Sie bleibt beim Scrollen sichtbar, hebt den aktiven Bereich dunkel hervor und bleibt auf Mobilgeräten horizontal scrollbar. Nach einem Seitenreload oder dem Aufruf eines direkten System-Links werden Reiterleiste und aktiver Reiter automatisch aus der URL wiederhergestellt. Die Systemdiagnose wurde vom Dashboard in diesen eigenen Reiter verschoben. Beim Wechsel der Reiter bleibt **System** in der Seitenleiste aktiv; vorhandene direkte URLs und Lesezeichen bleiben gültig.

## 6. Client vorbereiten

Auf Debian oder Ubuntu:

```bash
apt update
apt install borgbackup openssh-server
systemctl enable --now ssh
```

Den in der WebUI angezeigten Controller-Schlüssel mit dem direkt daneben angeordneten Button **Kopieren** übernehmen und beim gewünschten SSH-Benutzer autorisieren:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo 'CONTROLLER_PUBLIC_KEY' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Der SSH-Benutzer benötigt Leserechte auf alle Quellen und Schreibrechte auf Restore-Ziele. Für vollständige Systemsicherungen ist häufig root erforderlich.

## 7. Gerät anlegen

Die Seite zeigt **Gerät hinzufügen** als oberen Vollbreitenblock und **Verbundene Geräte** direkt darunter.

1. **Geräte** öffnen.
2. Name, Adresse, SSH-Benutzer und Port eintragen.
3. **SSH-Fingerprint prüfen** auswählen. Der gefundene Wert erscheint direkt im Formular; es öffnet sich kein Aktionsfenster.
4. Angezeigten Ed25519-Fingerprint mit dem Client vergleichen und anschließend im Formular **Fingerprint bestätigen** auswählen.
5. Gerät speichern.
6. **Borg prüfen** ausführen.

In der Liste **Verbundene Geräte** kann ein Gerät direkt über **Deaktivieren** aus dem Betrieb genommen und später über **Aktivieren** wieder freigegeben werden. Die Konfiguration bleibt erhalten. Beim Deaktivieren setzt der Manager alle zugehörigen aktiven Backup-Jobs automatisch auf **inaktiv**, entfernt das Gerät aus aktiven Zeitplänen und entzieht seine aktiven Repository-SSH-Zugänge. Laufende oder wartende Ausführungen blockieren das Deaktivieren. Beim erneuten Aktivieren werden Zeitpläne und Repository-Zugänge synchronisiert; die Backup-Jobs bleiben bewusst deaktiviert und müssen einzeln wieder aktiviert werden.

Die Erneuerung des zentralen Controller-Schlüssels befindet sich aus Sicherheitsgründen ausschließlich unter **System → Einstellungen → Controller-Schlüssel**. Im Geräteformular steht nur die ungefährliche Kopierfunktion zur Verfügung.

Der Controller-Schlüssel in `authorized_keys` erlaubt die Anmeldung des Managers. Der separat bestätigte Ed25519-Hostschlüssel weist die Identität des Clients nach. Beide Prüfungen sind erforderlich; der Hostschlüssel wird bei der Verbindung über eine temporäre `known_hosts`-Datei mit aktivem `StrictHostKeyChecking=yes` verwendet.

Warnstufen:

```text
1.2.0–1.2.4  kritisch, aber nutzbar
1.2.5–1.2.7  veraltet, aber nutzbar
1.2.8–1.4.x  freigegeben
```

## 8. Repository anlegen

### Verwaltetes Repository

1. **Repositories** öffnen.
2. Name vergeben.
3. Typ `verwaltet` wählen.
4. Verschlüsselungsmodus wählen.
5. Passphrase angeben, sofern erforderlich.
6. Repository erstellen und initialisieren.
7. Beim Gerät **Repository-Zugänge einrichten** ausführen.

Das Repository liegt unter:

```text
/repositories/GENERIERTER_NAME
```

### Externes Repository

1. Typ **Extern – vorhandenes Borg-Repository hinzufügen** wählen.
2. vollständige Borg-Location eintragen.
3. für SSH-Ziele einen Ed25519-Schlüssel im Manager erzeugen oder einen vorhandenen unverschlüsselten OpenSSH-Privatschlüssel einfügen.
4. den SSH-Hostkey direkt vom Manager abrufen oder einen geprüften `known_hosts`-Eintrag einfügen.
5. Verschlüsselungsmodus, Passphrase und bei Keyfile-Repositories den Keyfile-Inhalt hinterlegen.
6. **Repository hinzufügen** auswählen. Dieser Vorgang initialisiert oder überschreibt das externe Repository nicht.
7. den angezeigten öffentlichen Schlüssel beim Repository-Anbieter beziehungsweise auf dem SSH-Ziel autorisieren.
8. **Verbindung prüfen** ausführen. Der Manager reiht `borg info` als Repository-Ausführung ein, liefert sofort eine Lauf-ID zurück und öffnet das Live-Log. Dadurch bleibt die HTTP-Anfrage kurz und ein Reverse-Proxy kann die Prüfung nicht mehr mit HTTP 504 abbrechen.

Beispiel Hetzner Storage Box:

```text
ssh://u123456@u123456.your-storagebox.de:23/./borg-repository
```

Der öffentliche Manager-Schlüssel muss in der Storage Box autorisiert werden. Beim automatischen Hostkey-Scan verbindet sich der Manager selbst mit Port 23. Falls der Container dieses Ziel wegen Firewall, DNS oder Routing nicht erreicht, den geprüften `known_hosts`-Eintrag manuell einfügen.

Der generierte private Schlüssel wird verschlüsselt in `/data/security/security.db` abgelegt. Die Entschlüsselung ist nur mit `/data/security/master.key` möglich. Eine Klartextdatei existiert dauerhaft nicht; temporäre Dateien unter `/tmp/bbm-borg.XXXXXX/` werden nach jedem Borg-Aufruf entfernt.

Wenn der öffentliche Schlüssel noch nicht auf der Storage Box autorisiert ist, zeigt die Prüfung nur noch eine kurze Meldung wie **SSH-Anmeldung abgelehnt**. Die technischen Details bleiben dauerhaft in der Repository-Ansicht abruf- und kopierbar; umfangreiche OpenSSH-Verhandlungszeilen werden aus der normalen Ansicht gefiltert.

Nach erfolgreicher Prüfung kann **Größe berechnen** verwendet werden. Für externe Repositories wird die von Borg gemeldete deduplizierte komprimierte Repository-Nutzdatenmenge gespeichert. Diese ist technisch nicht exakt mit der belegten Dateisystemgröße auf der Storage Box gleichzusetzen.

Für Backup und Restore werden SSH-Schlüssel, `known_hosts`, Passphrase und Keyfile nur für die Dauer des Borg-Aufrufs an den jeweiligen Client übertragen. Sie werden dort mit Modus `0600` in einem temporären Verzeichnis abgelegt und anschließend entfernt. Eine dauerhafte Storage-Box-Schlüsseldatei auf jedem Client ist nicht erforderlich.

Beim Upgrade von 0.9.3 bleiben externe Repository-Einträge erhalten, werden aber als ungeprüft markiert. Die frühere Zugriffs-Client-Zuordnung wird entfernt; das Repository muss einmal bearbeitet, mit zentralen SSH-Daten versehen und erneut geprüft werden.

### Vorhandenes Repository importieren

1. vorhandenes Repository als direktes Unterverzeichnis in `BBM_REPOSITORY_PATH` bereitstellen.
2. **Vorhandene Repositories einbinden** öffnen.
3. Verzeichnis durchsuchen.
4. gefundenen Eintrag auswählen.
5. Verschlüsselungsmodus, Passphrase und gegebenenfalls Keyfile angeben.
6. Importprüfung starten.

Der Manager speichert keinen unvollständigen Eintrag, wenn Borg das Repository nicht öffnen kann.

Das Einbinden führt kein `borg init` aus und verändert vorhandene Archive nicht. Die Schaltfläche **Initialisieren** erscheint nur für verwaltete Zielverzeichnisse ohne vorhandene Borg-Konfiguration.

Falls ein bereits registriertes verwaltetes Repository außerhalb des Managers auf Dateiebene gelöscht wurde, erscheint in der Repository-Liste **Repository fehlt**. **Zurücksetzen** entfernt ausschließlich den veralteten Managerstatus und ist nur bei einem vollständig leeren Zielordner ohne Borg-`config` möglich. Die Funktion löscht selbst keine Dateien. Nach der Rücksetzung kann das Repository erneut initialisiert werden. Jobs und Zuordnungen bleiben erhalten, werden bis dahin aber für Repository-Aktionen gesperrt. Bei Keyfile-Verschlüsselung wird der alte, zur gelöschten Repository-ID gehörende Keyfile verworfen und bei der Neuinitialisierung neu erzeugt.

### Borg-Caches auf Manager und Quellgeräten

Die Repository-Übersicht zeigt die zugehörige numerische Manager-ID direkt neben dem Status.

Managerseitige Borg-Befehle speichern ihren Borg-Cache repositorybezogen unter `/data/borg-cache/repository-<ID>`, die persistenten Archivlisten-Metadaten unter `/data/archive-cache` und den Borg-Sicherheitsstatus unter `/data/borg-security`. Diese Verzeichnisse gehören zum persistenten Manager-Datenpfad. Dadurch werden keine lokalen Cache- oder Konfigurationsdaten mehr im häufig per NFS eingebundenen `/repositories`-Mount abgelegt.

Auf dem Quellgerät ausgeführte Borg-Befehle verwenden einen davon getrennten Cache unter `$HOME/.cache/borgbackup-manager/repository-<ID>`. Bei einem Gerät, das der Manager per SSH als `root` anspricht, steht `$HOME` für `/root`. Der Pfad

```text
/root/.cache/borg/<Repository-ID>/lock.exclusive
```

gehört daher zum allgemeinen lokalen Borg-Cache des Quellgeräts und nicht zum Repository. Neue BBM-Läufe verwenden diesen allgemeinen Altpfad nicht mehr. Nach dem bestätigten Prozessende bereinigt der Remote-Wrapper ausschließlich verbliebene Locks im privaten BBM-Cache. Eine solche Cache-Sperre darf nicht mit `borg break-lock` behandelt werden, weil `break-lock` Repository- und Cache-Sperren des Borg-Aufrufs beeinflussen kann und für den alten lokalen Cache nicht erforderlich ist.

Bei einer Meldung wie:

```text
Failed to create/acquire the lock .../lock.exclusive (timeout).
```

unter **Repositories → Aktionen → Cache löschen** den managerseitigen Cache des betroffenen Repositorys entfernen und anschließend **Verbindung prüfen** ausführen. Die Cache-Aktion löscht den repositorybezogenen Ordner direkt und muss dafür Borg nicht starten; sie funktioniert deshalb auch bei einem Cache, dessen eigener Lock den Borg-Aufruf blockiert. Archive, Repository-Konfiguration und Zugangsdaten bleiben erhalten. Bei verwalteten Repositorys werden bekannte Alt-Caches unter `/data/borg-cache/<Repository-ID>` und `/repositories/.cache/borg/<Repository-ID>` ebenfalls entfernt. Während laufender oder wartender Ausführungen ist die Aktion gesperrt.

### Speicherplatz-Sperre bei mehreren Repository-Mounts

Unterhalb von `BBM_REPOSITORY_PATH` können mehrere eigenständige Dateisysteme eingehängt werden, beispielsweise:

```text
/docker_data/borgbackup-manager/repositories/nas-a
/docker_data/borgbackup-manager/repositories/nas-b
/docker_data/borgbackup-manager/repositories/offline
```

Im Container erscheinen diese als `/repositories/nas-a`, `/repositories/nas-b` und `/repositories/offline`. Die Speicherplatz-Sperre prüft beim Start eines Backups den tatsächlichen Pfad des gewählten Repositorys. Die Belegung des Docker-Hostsystems oder eines anderen Repository-Mounts wird dafür nicht verwendet.

Globale Einstellung:

1. **System → Einstellungen** öffnen.
2. **Speicherplatz-Sperre global aktivieren** ein- oder ausschalten.
3. Globale Sperrgrenze zwischen 1 und 100 Prozent setzen.
4. Einstellungen speichern.

Repositorybezogene Abweichung:

1. **Repositories** öffnen.
2. Repository über **Bearbeiten** öffnen.
3. Unter **Speicherplatz-Sperre** „Globale Einstellung übernehmen“, „aktivieren“ oder „deaktivieren“ auswählen.
4. Optional eine eigene Sperrgrenze setzen. Eine leere Angabe übernimmt den globalen Wert.

Die **Systemdiagnose** zeigt alle im Container sichtbaren Mountpunkte unter `/repositories` getrennt mit Belegung, freiem Speicher, zugeordneten Repositories und Blockierstatus. Ein Mount ab seiner wirksamen Schwelle blockiert nur Backups in die darauf liegenden Repositories.

## 9. Ausschlussvorlagen konfigurieren

Unter **System → Einstellungen → Ausschlussvorlagen** befindet sich standardmäßig:

```text
Linux-Systempfade
/proc
/sys
/dev
/run
/tmp
/var/tmp
```

Funktionen:

- Vorlagenname ändern
- Muster ergänzen
- Muster entfernen
- mehrere Vorlagen anlegen
- Vorlage löschen

Jedes Muster steht in einer eigenen Zeile. Vorlagen müssen einen eindeutigen Namen und mindestens ein Muster enthalten.

Vorlagen werden nicht dynamisch mit Jobs verknüpft. Beim Anwenden werden die Muster in den Job kopiert. Dadurch verändern spätere Vorlagenänderungen keine laufenden Jobs unbeabsichtigt.

## 10. Backup-Job erstellen

1. Namen vergeben.
2. Gerät auswählen.
3. Repository auswählen.
4. Quellpfade zeilenweise eintragen.
5. optional Ausschlussvorlage anwenden und ergänzen.
6. Archivnamensvorlage prüfen. Der Manager ergänzt automatisch ein kompaktes Präfix wie `bbm-12-`; verwendete Job-IDs werden dauerhaft reserviert.
7. Kompression und Dateisystemoptionen festlegen.
8. Aufbewahrungswerte setzen.
9. Job speichern.
10. **Mehr** öffnen. Die kompakte Aktionsleiste bündelt Prüfen, Repository-Zugang, Speicherpflege und Verwaltung.
11. Unter **Repository-Zugang** den Zugang für genau dieses Gerät und Repository einrichten.
12. Verbindung prüfen und ein kleines Testbackup ausführen.

Unter **Mehr → Verwalten** kann ein Backup-Job direkt deaktiviert und später wieder aktiviert werden. Alle Quellen, Borg-Optionen, Aufbewahrungswerte und Zeitplanzuordnungen bleiben gespeichert. Deaktivierte Jobs werden weder manuell noch geplant gestartet. Eine laufende oder wartende Ausführung muss vorher beendet sein.

Backup-Jobs besitzen keinen eigenen Zeitplan. Ohne zentrale Zuordnung werden sie ausschließlich manuell ausgeführt und in der Jobliste als **Manuell** gekennzeichnet. Aktive und vollständig eingerichtete Jobs können zusätzlich direkt aus dem Dashboard gestartet werden. Bei verwalteten Repositories wird der Start bis zur Einrichtung des repositorybezogenen Zugangs gesperrt.

Beispiel für Quelle `/`:

```text
Quellpfad:
/

Ausschlüsse:
/proc
/sys
/dev
/run
/tmp
/var/tmp
```

`--one-file-system` verhindert das automatische Betreten anderer Mounts. Zusätzliche gewünschte Dateisysteme müssen als eigene Quellpfade eingetragen werden.

## 10a. Zentralen Zeitplan anlegen

Unter **Zeitpläne** einen Namen vergeben und die Zielgruppe wählen:

- **Ausgewählte Geräte:** Einzel- oder Mehrfachauswahl; alle aktiven Jobs der Geräte werden erfasst.
- **Repository:** alle aktiven Jobs des Repositorys, einschließlich später neu angelegter Jobs.
- **Ausgewählte Backup-Jobs:** direkte Einzel- oder Mehrfachauswahl.

Danach Rhythmus, eine oder mehrere Uhrzeiten und bei Bedarf **Maximal parallele Ausführungen** festlegen. `0` übernimmt nur die globale Grenze; `1` startet die von diesem Zeitplan ausgelösten Jobs auch bei unterschiedlichen Repositorys nacheinander. Unterstützt werden täglich, Montag bis Freitag, Wochenende, ausgewählte Wochentage, monatlich und erweiterte Cron-Ausdrücke. Maximal 24 Zeitpunkte sind zulässig. Der Scheduler arbeitet verbindlich in `Europe/Berlin`.

Ein Job darf nur einem aktiven Zeitplan zugeordnet sein. Überlappungen werden beim Speichern abgewiesen. Bestehende Job-Cronwerte älterer Versionen werden beim ersten Start automatisch in eigene zentrale Zeitpläne migriert.

## 10b. Warteschlange und Parallelitätsgrenzen

Pro Repository wird immer nur eine Borg-Aktion gleichzeitig ausgeführt. Starten mehrere Geräte zur selben Zeit, bleibt der erste Lauf **Laufend**, alle weiteren stehen **Wartend**. Das Dashboard zeigt beide Zustände getrennt. Sobald das Repository frei wird, startet der nächste wartende Lauf automatisch. Direkt am Repository gestartetes Compact und repositoryweite Archivlöschungen werden ebenfalls über diese Sperre und ein reguläres Ausführungsprotokoll gesteuert; ein Backup-Job ist dafür nicht erforderlich.

Unter **System → Einstellungen → Parallelitätsgrenzen** kann zusätzlich eine globale Obergrenze von `0` bis `64` gesetzt werden. `0` lässt unterschiedliche Repositorys unbegrenzt parallel arbeiten; `1` erlaubt insgesamt nur eine laufende Manager-Ausführung. Zeitpläne können eine eigene, engere Grenze besitzen. Damit lassen sich beispielsweise zwei Geräte mit zwei verschiedenen Repositorys gemeinsam um 22:00 Uhr einreihen, ohne gleichzeitig Netzwerk und CPU zu belasten.

Die Reihenfolge wird als datenbankgestützte FIFO-Warteschlange geführt und zusätzlich durch eine lokale Prozesssperre abgesichert. Das tatsächliche Repository-Verzeichnis beziehungsweise die externe URL bildet die Sperridentität, sodass auch versehentlich doppelt erfasste Ziele nicht parallel bearbeitet werden. Freie globale Plätze werden nicht durch einen älteren Lauf verschwendet, der noch auf sein Repository oder seine Zeitplangrenze wartet. Wartende Laufprotokolle nennen die konkrete Ursache und gegebenenfalls die davorliegende Ausführungs-ID. Nur tatsächlich lebende Manager-Tasks belegen Plätze; verwaiste Laufzustände werden nicht als dauerhafte Blocker behandelt. Extern gestartete Borg-Prozesse sind für die Manager-Warteschlange nicht sichtbar und werden weiterhin durch Borgs eigene Repository-Sperre abgefangen.

## 11. Borg-Optionen im Job

### Kompression

```text
none
lz4
zstd,LEVEL
zlib,LEVEL
lzma,LEVEL
auto,...
obfuscate,...
```

### Dateisystemoptionen

```text
--one-file-system
--exclude-caches
--exclude-nodump
--numeric-ids
--list  # verarbeitete Dateien im Live-Protokoll
--files-cache MODUS
--checkpoint-interval SEKUNDEN
```

### Aufbewahrung

```text
--keep-last
--keep-hourly
--keep-daily
--keep-weekly
--keep-monthly
--keep-yearly
```

Die Dateiliste ist standardmäßig aktiv und kann bei sehr großen Sicherungen im Job deaktiviert werden. Die angezeigte Version ist die auf dem Backup-Client tatsächlich verwendete Borg-Version.

Der Wert 0 wird nicht an Borg übergeben.

## 12. Jobaktionen

Direkt:

- Backup starten
- Archive öffnen
- Verbindung prüfen

Weitere Aktionen:

- Job-Info
- Borg-Version
- Repository prüfen
- Daten vollständig prüfen
- geänderten Repository-Standort einmalig bestätigen
- Aufbewahrung anwenden
- Speicher freigeben
- alle Repository-Archive
- bearbeiten
- löschen

Ein Job kann gelöscht werden, obwohl Archive vorhanden sind. Archive werden dabei nicht automatisch gelöscht. Laufende oder wartende Aktionen und alte aktive Mount-Sitzungen müssen vorher beendet werden.

### Repository unter neuer URL

Die Meldung `The repository at location ... was previously located at ...` bedeutet nicht, dass SSH oder das Repository defekt sind. Borg hat dieselbe Repository-ID bereits unter einem anderen Standort im Sicherheitsstatus des Backup-Clients gespeichert. Nach einem beabsichtigten Umzug oder einer neuen Einbindung:

1. SSH-Fingerprint, Repository-Ziel und neuen Pfad prüfen.
2. beim betroffenen Job **Mehr → Prüfen → Geänderten Repository-Standort bestätigen** auswählen. Mehrere Jobs desselben Geräts und Repositorys verwenden automatisch denselben Bestätigungslauf; unterschiedliche Geräte werden nacheinander eingereiht. Borg wartet dabei bis zu 600 Sekunden auf eine aktive Repository-Sperre.
3. die Sicherheitsabfrage bestätigen.
4. anschließend **Verbindung prüfen** erneut ausführen.

Die Freigabe gilt nur für den einmaligen Prüflauf und setzt `BORG_RELOCATED_REPO_ACCESS_IS_OK=yes` nicht dauerhaft. Sie ist ausschließlich Administratoren zugänglich. Ein normaler Backup-Lauf akzeptiert einen Standortwechsel nie automatisch.

## 13. Archivübersicht

Die Liste wird repositorybezogen persistent unter `/data/archive-cache` gespeichert. Ein zeitgesteuerter Auto-Refresh wird nicht verwendet.

1. Repository auswählen.
2. optional unvollständige Checkpoint-Archive einblenden.
3. **Archive anzeigen** wählen. Beim ersten Zugriff oder nach einer erfolgreichen Archivänderung liest der Manager Borg neu ein; danach kommt die Liste direkt aus dem Cache.
4. Optional unter **Archive anzeigen** ein erkanntes Gerät auswählen. Die Zuordnung verwendet zuerst die Archivserie, danach Borg-Hostname beziehungsweise Archivname.
5. Für eine Mehrfachlöschung einzelne Archive markieren oder **Sichtbare Archive auswählen** verwenden.
6. Nur bei Änderungen außerhalb des Managers **Neu aus Repository einlesen** wählen.

Nach Backup, Prune, Umbenennen oder Löschen wird der Cache des betroffenen Repositorys automatisch ungültig. Andere Repository-Caches bleiben erhalten. Ein Backup-Job ist für Archivliste, Archivinformationen und den Browser nicht erforderlich. Verwaltete Repositories werden über ihren lokalen Pfad gelesen; externe Repositories öffnet der Manager selbst per Borg/SSH mit den zentral gespeicherten Repository-Zugangsdaten.

Die Liste wird unabhängig von der Borg-Ausgabereihenfolge immer absteigend sortiert; das neueste Archiv steht oben. Der Gerätefilter verwendet die Namen der bereits zwischengespeicherten Archive und startet keinen erneuten Repository-Scan. Unterstützt werden auch generische Namen mit minutengenauem Zeitstempel wie `docker-2026-07-17_03-20`; Sekunden sind optional. Nicht eindeutig erkennbare Namen können separat ausgewählt werden.

Funktionen:

- Archivdetails
- gerätebezogene Zuordnung über Archivserie, Borg-Hostname oder Archivname
- Jobzuordnung und Legacy-Erkennung
- Inhalt ohne FUSE durchsuchen
- Checkpoints optional anzeigen
- einzelne und mehrere Archive repositoryweit löschen; gemischte Auswahl wird als **Mehrere Geräte** bestätigt
- optional einmaliges Compact nach der vollständigen Löschserie
- Compact direkt in der Repository-Liste, unabhängig von einem Job
- mit eindeutig passendem Backup-Job zusätzlich Diff, Rename und Restore

Bei lokal verwalteten Repositories benötigt der Containerbenutzer `BBM_BORG_UID:BBM_BORG_GID` Leserechte auf allen Segmentdateien. Schreiben weitere Clients mit abweichenden Eigentümern, müssen gemeinsame Gruppen, ACLs oder die NFS-UID/GID-Zuordnung entsprechend eingerichtet werden. Bei fehlenden Rechten zeigt die WebUI nur den betroffenen Pfad und die verwendete UID:GID. Bei als Ausführung gestarteten Aktionen bleibt die vollständige Borg-Ausgabe im Laufprotokoll; direkte Archivlistenabfragen liefern bewusst nur die kurze Ursache.

Compact wird mit `--verbose` ausgeführt. Dadurch enthält das Ausführungsprotokoll die von Borg geschätzte freigegebene Größe, sofern unreferenzierte Segmente entfernt wurden. Die direkte Repository-Aktion ist während eines aktiven Archiv-Mounts oder eines laufenden beziehungsweise wartenden Repository-Laufs gesperrt. Bei der Mehrfachlöschung werden alle Archivnamen vor dem Start erneut geprüft; gemountete ausgewählte Archive blockieren die Aktion.

## 14. Archivbrowser und Export

Der Browser arbeitet ohne FUSE. Dateien und Ordner können markiert werden.

Aktionen:

- Auswahl in Wiederherstellung übernehmen
- Auswahl als TAR.GZ exportieren

Exportdateien liegen temporär unter `/data/exports` und werden nach der Übertragung entfernt.

## 15. Wiederherstellung

### Dry-Run

Prüft den Vorgang, schreibt aber keine Dateien.

### Originalpfad

Stellt markierte Pfade direkt an ihrem ursprünglichen Ort wieder her. Ein produktiver Lauf benötigt eine Überschreibbestätigung.

### Alternatives Ziel

Beispiel:

```text
Archivpfad: home/user/Dokumente/datei.pdf
Ziel:       /srv/restore
```

Auswahlwurzel entfernen:

```text
/srv/restore/datei.pdf
```

Archivpfade erhalten:

```text
/srv/restore/home/user/Dokumente/datei.pdf
```

## 16. Ausführungsprotokolle

Standardansicht:

- Job
- Gerät
- Quellen
- Borg-Version
- Start und Ende
- Dauer
- Dateianzahl
- Größenstatistik
- Ergebnis

Technische Details:

- vollständiger Befehl
- stdout
- während des Prozesses dauerhaft gespeicherte Warnungsursachen bei `rc 1`, einschließlich veränderter Dateien (`C`), Datei-Zugriffsfehler (`E`), fehlender Pfade, Berechtigungs-, E/A- und Musterwarnungen; bleibt Borg ohne Detailzeile, wird dies ausdrücklich gekennzeichnet
- gefilterte Fehler- und Warnungsausgabe; normale Borg-Dateilisten und Statistiken werden nicht als Fehler geführt

Fehlermeldungen können markiert und kopiert werden.

Ein Borg-Rückgabecode `1` bedeutet, dass der Vorgang sein normales Ende erreicht und das Archiv gespeichert wurde, aber Warnungen vorlagen. Der Manager zeigt die konkreten Ursachen im Laufdialog an. Wenn die vollständige Dateiliste im Job deaktiviert ist, ergänzt der Backup-Befehl intern `--list --filter CE`; dadurch werden nur geänderte Dateien (`C`) und Datei-Zugriffsfehler (`E`) protokolliert, ohne das Live-Log mit allen unveränderten Dateien zu füllen. Ist die vollständige Liste aktiviert, verarbeitet der Manager die große Statusausgabe gepuffert und mit einer Schnellprüfung für normale Dateistatus, sodass die vollständige Anzeige deutlich weniger Manager-CPU benötigt.

Ab Version 0.8.7 liegen vollständige neue Laufprotokolle unter:

```text
/data/run-logs/run-ID.log
```

SQLite speichert nur Metadaten sowie feste, von Borg-Dateistatus bereinigte Vorschauen von maximal 4 KiB stdout, 32 KiB gefilterte Fehler-/Warnungsausgabe und 16 KiB Bedienprotokoll. Normale Dateipfade liegen ausschließlich in `/data/run-logs`; nur konkret betroffene Warnungspfade werden begrenzt in der strukturierten Warnungszusammenfassung gespeichert. Beim Start werden größere oder ältere Rohinhalte bei Bedarf zuerst nach `/data/run-logs` migriert und anschließend aus der Datenbank entfernt. Unter **System → Einstellungen → Ausführungsprotokolle** werden Anzahl, Dateigröße und Datenbankanteil angezeigt. Dort können abgelaufene oder alle abgeschlossenen Protokolle sofort gelöscht werden. Die automatische Bereinigung läuft täglich um 03:30 Uhr Europe/Berlin nach der konfigurierten Aufbewahrungsdauer. Aktive Läufe bleiben immer erhalten.

## 17. Benachrichtigungszentrale einrichten

1. Als Administrator **System → Benachrichtigungen** öffnen.
2. Installationsnamen, Sprache und gewünschte Ereignisse wählen.
3. Mindestens einen Kanal einrichten:
   - SMTP-Server, Port, Transportverschlüsselung, Absender und Empfänger
   - generischer oder Discord-Webhook
   - Telegram-Bot-Token und Chat-ID beziehungsweise Kanal
4. Konfiguration speichern.
5. Den jeweiligen **Testen**-Button verwenden und das Zustellungsprotokoll kontrollieren.
6. Erst danach **Benachrichtigungen global aktivieren**.

Geheimnisse werden nicht in `notifications.json` abgelegt, sondern mit dem Manager-Master-Key verschlüsselt in der Sicherheitsdatenbank gespeichert. Beim Bearbeiten bleiben leere Passwort-, URL- und Tokenfelder unverändert; zum Entfernen muss die jeweilige Löschoption aktiviert werden.

Für SMTP sollte STARTTLS oder direktes TLS verwendet werden. Die Einstellung **Keine** ist ausschließlich für bewusst isolierte interne Mail-Relays vorgesehen. Ausgehende Verbindungen zu SMTP, Webhook und Telegram müssen durch Firewall, DNS und gegebenenfalls den Reverse-Proxy-Host erlaubt sein.

Warnungsbenachrichtigungen übernehmen aus der strukturierten Borg-Warnungszusammenfassung zusätzlich die konkret betroffenen Dateien beziehungsweise Pfade. Bis zu zehn Einträge werden vollständig ausgegeben; weitere Einträge werden gezählt. Fehlgeschlagene Zustellungen werden im Benachrichtigungsprotokoll gespeichert, verändern aber weder den Borg-Rückgabecode noch den Status der Sicherung. Der Manager gibt den Repository- und Parallelitätsplatz frei, bevor er externe Dienste kontaktiert.

## 18. Manager-Backup und Sicherheitsdaten

Das Manager-Backup enthält Manager-Datenbank, Sicherheitsdatenbank, Master-Key, Einstellungen, Controller-/Repository-SSH-Schlüssel, Borg-Keyfiles und TLS-Dateien. Repository-Nutzdaten und vollständige Dateien aus `/data/run-logs` sind nicht enthalten.

### Backup erstellen

Die Bezeichnung ist optional. Neue Manager-Backups werden ausschließlich als verschlüsselte `.bbm`-Dateien erzeugt. Die eigene Passphrase muss mindestens zwölf Zeichen lang sein und wird nicht gespeichert. Historische unverschlüsselte `.zip`-Backups bleiben für die Wiederherstellung lesbar, können aber nicht mehr neu erstellt werden.

Die `.bbm`-Datei verwendet AES-256-GCM und scrypt.

### Backup hochladen

1. **System → Manager-Backup** öffnen.
2. Unter **Manager-Backup hochladen** eine vorhandene `.bbm`-Datei oder ein historisches `.zip`-Manager-Backup auswählen.
3. **Backup hochladen** wählen.
4. Nach erfolgreicher serverseitiger Prüfung erscheint die Datei unter **Vorhandene Backups** und in der Wiederherstellungsauswahl.

Der Upload akzeptiert ausschließlich Manager-Backup-Dateinamen im vom BorgBackup Manager erzeugten Format. Dateigröße und Struktur werden geprüft, vorhandene Dateien werden nicht überschrieben und die gespeicherte Datei erhält Modus `0600`. Das konfigurierte Eingabelimit ist `BBM_BACKUP_MAX_FILE_BYTES` und beträgt standardmäßig 256 MiB. Für verschlüsselte Backups ist beim Upload keine Passphrase erforderlich; die kryptografische Authentifizierung erfolgt vor der Wiederherstellung.

### Wiederherstellung in der WebUI

1. Alle laufenden und wartenden Jobs beenden.
2. Backup auswählen.
3. bei `.bbm` die Backup-Passphrase eingeben.
4. eine separate, mindestens zwölf Zeichen lange Passphrase für das verschlüsselte Sicherheitsbackup eingeben und bestätigen.
5. Ersetzungsbestätigung aktivieren.
6. Wiederherstellung starten.

Der Manager prüft das Backup, erstellt ein verschlüsseltes lokales Sicherheitsbackup und ersetzt anschließend Manager- und Sicherheitsdatenbank, Master-Key, Einstellungen sowie SSH-/TLS-/Repository-Schlüssel. Der Container startet neu; bestehende Browser-Sitzungen müssen sich danach neu anmelden.

### Serverwechsel

```bash
cd /opt/BorgBackup-Manager
bash restore-backup.sh /pfad/manager-backup.zip
```

Für ein verschlüsseltes Backup:

```bash
apt install python3-cryptography
bash restore-backup.sh /pfad/manager-backup.bbm
```

Neue 0.9.x-Backups enthalten Sicherheitsdatenbank und Master-Key vollständig. Alte 0.8.x-Backups übernehmen beim ersten Start ihre bisherigen Token-/Schlüsselwerte einmalig in das neue Sicherheitsmodell. Repository-Verzeichnisse müssen separat übertragen oder wieder eingebunden werden.

## 19. Zeitzone, Dashboard und Systembereich

Der Compose-Stack setzt standardmäßig `TZ=Europe/Berlin`. Das Dashboard zeigt Repository-Anzahl und summierte Repository-Größe gemeinsam in einer Kachel. Darüber hinaus steht oberhalb der letzten Aktivitäten eine sortierbare Backup-Job-Tabelle mit Status, Gerät, Repository, Quellen, Zeitplan, letztem Lauf und den gespeicherten Größen der letzten Sicherung. Quellenstatistik und letzter Lauf werden jeweils in zwei kompakten Zeilen dargestellt; Dedupliziert, Original und Komprimiert stehen als drei eng gesetzte Beschriftungs-/Wertzeilen untereinander. Ein fehlgeschlagener letzter Lauf ersetzt dabei nicht die Größenwerte der vorherigen erfolgreichen Sicherung. Die Systemdiagnose befindet sich unter **System → Systemdiagnose** und lässt sich nach dem Laden ohne Seitenreload wieder schließen. Das Dashboard zeigt neben laufenden auch wartende Ausführungen; beide Kacheln öffnen die entsprechend gefilterte Protokollansicht. Die WebUI stellt serverseitige UTC-Zeitwerte in dieser Zeitzone dar. Borg-Archivzeitpunkte ohne Offset werden als lokale Zeit dieser Zeitzone interpretiert und nicht ein zweites Mal um zwei Stunden verschoben. Cron-Zeitpläne werden in dieser Zeitzone ausgewertet und remote gestartete Borg-Befehle erhalten dieselbe TZ-Variable.


- Darstellung hell, dunkel oder automatisch
- globale Parallelitätsgrenze für alle Manager-Ausführungen (`0` = unbegrenzt)
- komfortable oder deutlich verdichtete Darstellung; die Umschaltung verändert Tabellen, Formulare, Karten und Navigation
- Dashboard-Limit
- Protokolllimit
- Aktualisierungsintervall
- maximale Höhe der Archivübersicht und weiterer scrollbarer Listen
- Protokollaufbewahrung
- maximale Größe je Lauf-Logdatei
- maximale Anzeigegröße in der WebUI
- Speicherübersicht und manuelle Protokollbereinigung
- Repository-Größe nach manuellen Schreibvorgängen und nach Abschluss eines Zeitplans
- Compact nach geplantem Prune
- Ausschlussvorlagen

Dashboard-Backup-Jobs, Backup-Jobs, Repositories und verbundene Geräte besitzen jeweils eigene Sortierfelder. Die Auswahl wird je angemeldetem Benutzer im verwendeten Browser gespeichert.

## 20. Benutzerverwaltung

Administratoren öffnen **System → Benutzer** und können dort:

- Konten mit Benutzername, Rolle und temporärem Passwort anlegen
- Passwortwechsel bei der nächsten Anmeldung erzwingen
- Rollen zwischen Administrator und Benutzer ändern
- Konten aktivieren oder deaktivieren
- Passwörter zurücksetzen; alle Sitzungen des Kontos werden dabei beendet
- Konten löschen

Schutzregeln:

- Das eigene Konto kann nicht gelöscht werden.
- Der letzte Administrator kann nicht gelöscht werden.
- Der letzte aktive Administrator kann weder deaktiviert noch zum normalen Benutzer herabgestuft werden.
- Passwörter werden ausschließlich als scrypt-Prüfwerte mit individuellem Salt gespeichert.
- Sitzungstoken stehen nie im Klartext in der Datenbank; gespeichert wird nur ihr SHA-256-Hash.
- Quellenbezogene Rate-Limits begrenzen Login-Versuche pro IP-Adresse und IP-/Benutzer-Kombination, ohne ein Konto durch fremde Fehlversuche global zu sperren.
- Ein eigener Passwortwechsel beendet alle bisherigen Sitzungen und verlangt eine neue Anmeldung.

Rollen:

- **Administrator:** vollständige Konfiguration einschließlich Geräte, Repositories, Jobs, Einstellungen, Manager-Backup und Benutzer.
- **Benutzer:** reine Beobachterrolle für Dashboard, Listen und zusammengefasste Laufstatus sowie persönliche Sprache und Darstellung; keine manuellen Ausführungen, vollständigen Logs, Archive, Restore-/Export-/Mount-Aktionen oder Konfigurationsänderungen.

### Persönliche Sprache und Darstellung

Jeder Administrator und jeder normale Benutzer kann über **Darstellung & Sprache** eigene Werte speichern:

- Sprache: Deutsch oder Englisch
- Farbschema: Automatisch, Hell oder Dunkel

Die Werte liegen am jeweiligen Benutzerkonto in der Sicherheitsdatenbank. Sie verändern keine globale Einstellung und haben keinen Einfluss auf andere Konten. Navigation, Formulare, Dialoge, dynamische Statusmeldungen, das integrierte Betriebshandbuch und die aktuellen Release Notes folgen der gewählten Sprache.

## 21. Aktionsbestätigung und Aktualisierung

Die WebUI bestätigt Änderungen unmittelbar über den betätigten Button, eine Toast-Meldung und die Statusanzeige im Seitenkopf. Bei laufenden oder wartenden Aufgaben zeigt die Statusposition vor dem Farbschema-Schalter die aktuell laufende Aufgabe und gegebenenfalls die Zahl weiterer aktiver Läufe. Ein Klick öffnet ohne Zwischenliste direkt das Live-Log des aktuell laufenden Vorgangs; falls ausschließlich wartende Läufe vorhanden sind, wird der nächste wartende Lauf geöffnet. Borg-Hintergrundläufe werden nach ihrer Lauf-ID bis zum tatsächlichen Abschluss verfolgt. Anschließend werden ausschließlich die betroffenen API-Bereiche neu geladen. Archivlisten verwenden einen persistenten repositorybezogenen Cache. Nach Backup, Prune, Umbenennen oder Löschen wird dieser vor dem sichtbaren Laufabschluss invalidiert; eine geöffnete Ansicht baut ihn anschließend gezielt neu auf. Compact allein verändert die Archivliste nicht.

Das unter **Einstellungen** konfigurierbare Aktualisierungsintervall ist nur eine zusätzliche Hintergrundaktualisierung. Die Bestätigung und Übernahme einer Aktion ist nicht von diesem Zeitwert abhängig. Ein manuelles Neuladen der gesamten Browserseite ist im Normalfall nicht erforderlich.

## 22. Update

### Eingefrorene WebUI nach Version 1.0.26/1.0.27

Die erste zweisprachige Oberfläche konnte den eigenen `MutationObserver` durch identische Text- und Attributschreibvorgänge fortlaufend erneut auslösen. Container und `/api/ready` bleiben dabei erreichbar, die Browseroberfläche reagiert jedoch nicht mehr auf die Anmeldung. Version 1.0.28 schreibt nur noch tatsächlich geänderte Werte. Das Update wird per Shell installiert; danach die WebUI einmal mit `Strg+F5` neu laden.

### Fehlgeschlagener Build beim Übergang von 1.0.25 auf 1.0.26

Die Meldung `RELEASE_NOTES.en.md: not found` entsteht, wenn noch das Update-Skript aus Version 1.0.25 läuft: Diese Version kopiert die neue Top-Level-Datei nicht in den Projektordner, während der Dockerfile aus 1.0.26 sie bereits erwartet. Nach dem automatischen Rollback kann direkt das ZIP von Version 1.0.28 mit dem vorhandenen Updater installiert werden. Es ist kein Vorab-Austausch von `update.sh` und kein manuelles Extrahieren der englischen Release Notes erforderlich.

### Abbruch einer laufenden Borg-Aufgabe

Der Manager beendet beim Stoppen die vollständige Prozesskette aus SSH, Shell, `runuser` und Borg. Seit Version 1.0.35 bleibt bei über ein Gerät ausgeführten Backup-Aufrufen nach der einmaligen Übergabe temporärer Repository-Geheimnisse ein eigener Steuerkanal offen. Beim Abbruch wird dieser Kanal zuerst geschlossen. Der Wrapper auf dem Gerät sendet daraufhin `SIGINT` an die vollständige Borg-Prozessgruppe und wartet auf deren Ende, damit insbesondere Locks externer Repositorys vor dem Schließen der SSH-Verbindung freigegeben werden. Erst wenn dieser Weg nicht reagiert, folgen `SIGTERM` und `SIGKILL`. Version 1.0.38 ersetzt den früheren separaten `cat`-Watchdog durch eine Shell-interne `read`-Schleife, damit nach einem regulär beendeten Borg-Aufruf kein Hilfsprozess mehr die SSH- und HTTP-Verbindung offenhalten kann. Die API bestätigt den Abschluss erst nach der Prozessbereinigung oder nach Ablauf des Sicherheitszeitfensters. Ein automatisches `borg break-lock` erfolgt nicht, weil ein Repository gleichzeitig von weiteren unabhängigen Clients verwendet werden kann.



### Einmaliger Übergang von 1.0.4 oder älter auf 1.0.5

Der bisherige Updater enthält `recovery.sh` noch nicht in seiner Whitelist. Deshalb muss die Datei vor diesem einen Übergang aus dem ZIP übernommen werden:

```bash
cd /opt/BorgBackup-Manager
cp /pfad/BorgBackup-Manager-1.0.5.zip updates/
unzip -p updates/BorgBackup-Manager-1.0.5.zip BorgBackup-Manager/recovery.sh > recovery.sh
chmod 755 recovery.sh
bash update.sh --file updates/BorgBackup-Manager-1.0.5.zip
```

### Einmaliger Übergang von 1.0.9 auf 1.0.10

Der Updater 1.0.9 konnte nach dem Stoppen des Containers versehentlich ein unter `BBM_DATA_PATH` liegendes Repository-Verzeichnis und `/data/borg-cache` in das komprimierte Manager-Datenbackup aufnehmen. Bei großen oder per NFS eingebundenen Repositories wirkte das Skript deshalb nach der Meldung `Container borgbackup-manager Stopped` blockiert.

Einen bereits laufenden Vorgang mit `Strg+C` abbrechen und den Container wieder starten:

```bash
cd /opt/BorgBackup-Manager
docker compose up -d
```

Danach das korrigierte Update-Skript vorab übernehmen und neu starten:

```bash
cd /opt/BorgBackup-Manager
cp /pfad/BorgBackup-Manager-1.0.10.zip updates/
unzip -p updates/BorgBackup-Manager-1.0.10.zip BorgBackup-Manager/update.sh > update.sh.new
chmod 755 update.sh.new
mv update.sh.new update.sh
bash update.sh --file updates/BorgBackup-Manager-1.0.10.zip
```

Ein während des abgebrochenen Vorgangs neu angelegtes `*-persistent-v<Ausgangsversion>.tar.gz` kann abgeschnitten sein und darf nicht als gültige Sicherung verwendet werden. Es kann anhand seines Zeitstempels dem fehlgeschlagenen Versuch zugeordnet und nach Prüfung entfernt werden. Der neue Updater schreibt zunächst `.partial` und benennt die Datei erst nach erfolgreichem Abschluss um.

### Normale Updates ab Version 1.0.10

```bash
cd /opt/BorgBackup-Manager
cp /pfad/BorgBackup-Manager-NEUE-VERSION.zip updates/
bash update.sh --file updates/BorgBackup-Manager-NEUE-VERSION.zip --sha256 VERÖFFENTLICHTE_SHA256
```

Das Update-Skript:

1. verifiziert das ZIP vor dem Einlesen gegen `--sha256`, `BBM_UPDATE_SHA256` oder eine gleichnamige `.sha256`-Datei und prüft anschließend die Paketstruktur einschließlich `recovery.sh`.
2. sichert Projektdateien einschließlich `recovery.sh`.
3. sichert persistente Manager-Daten, schließt aber `BBM_REPOSITORY_PATH`, `/data/borg-cache` und den regenerierbaren Archivlisten-Cache `/data/archive-cache` aus.
4. schreibt das Manager-Datenbackup zunächst als `.partial` und veröffentlicht es erst nach erfolgreichem Abschluss.
5. übernimmt neue Projektdateien einschließlich `recovery.sh` und setzt die Ausführungsrechte.
6. ergänzt fehlende `.env`-Werte einschließlich der zugehörigen Kommentare.
7. validiert das vollständige Release-Paket einschließlich `.env.example`, Dokumentation und Recovery-Skripten.
8. baut `borgbackup-manager:latest`.
9. stoppt den Container erst unmittelbar vor der konsistenten Managersicherung.
10. startet den vorherigen Container bei Abbruch oder Sicherungsfehler automatisch wieder.
11. startet den neuen Container und prüft `/api/ready`.
12. zeigt einen eingeschränkten Komponentenstatus nur als Warnung.
13. führt nur bei nicht erreichbarer WebUI einen Rollback aus.

Repository-Nutzdaten werden beim Update weder kopiert noch verändert. Das Datenbackup verwendet zusätzlich `--one-file-system`, sodass unerwartete weitere Unter-Mounts im Manager-Datenpfad nicht traversiert werden. Der Borg-Cache ist regenerierbar und wird ebenfalls nicht in das Update-Backup aufgenommen. Sicherheitsdatenbank, Master-Key, Einstellungen, SSH-/TLS-Schlüssel und Borg-Sicherheitsstatus bleiben Bestandteil der persistenten Managersicherung.

## 23. Healthchecks

Web-Bereitschaft:

```bash
curl -k https://127.0.0.1:8443/api/ready
```

Öffentlicher, inhaltsarmer Komponentenstatus:

```bash
curl -k https://127.0.0.1:8443/api/health
```

Strenger öffentlicher Statuscode für Updates und externe Überwachung (`200` bereit, `503` eingeschränkt):

```bash
curl -k -i https://127.0.0.1:8443/api/health/strict
```

Detaillierte Komponenteninformationen stehen nur angemeldeten Administratoren über die WebUI-Systemdiagnose beziehungsweise authentifiziert unter `/api/system/health` zur Verfügung. Dort werden zusätzlich alle sichtbaren Repository-Mounts unter `/repositories`, die Belegung und die wirksame globale oder repositorybezogene Speicherplatz-Sperre angezeigt.

### Reproduzierbarer Sicherheitsbuild

Der Docker-Build verwendet den festgeschriebenen Multi-Platform-Digest des offiziellen Python-Basisimages. `requirements.txt` enthält für alle direkten und transitiven Laufzeitpakete geprüfte SHA-256-Hashes der Linux-amd64- und Linux-arm64-Wheels; Pip installiert ausschließlich mit `--require-hashes`. Änderungen an Abhängigkeiten erfordern deshalb eine bewusste Aktualisierung von Versionen und Hashes.

## 24. Docker-Diagnose

```bash
cd /opt/BorgBackup-Manager
docker compose ps
docker image ls borgbackup-manager
docker compose logs --tail=200 borg-manager
```

Erwartete Namen:

```text
IMAGE       borgbackup-manager:latest
CONTAINER   borgbackup-manager
```

## 25. Repository-SSH-Diagnose

Die WebUI-Diagnose prüft Repository-Zugriff, Logs, Wrapper und `authorized_keys` direkt als Benutzer `borg`. Die nur als Root mögliche Konfigurationsprüfung `sshd -t` wird beim Containerstart ausgeführt und der Web-API als geschützter Laufzeitstatus bereitgestellt.

```bash
docker compose exec -T borg-manager pgrep -a sshd
docker compose exec -T borg-manager /usr/sbin/sshd -t
docker compose exec -T borg-manager tail -n 200 /data/logs/sshd.log
docker compose exec -T borg-manager tail -n 200 /data/logs/borg-serve.log
docker compose exec -T borg-manager tail -n 200 /data/logs/debug.log
```

## 26. Sicherheitsregeln

- Port 2222 nur für bekannte Clients freigeben.
- `/data/security/security.db` und `/data/security/master.key` nur gemeinsam sichern.
- Manager-Backup verschlüsselt und geschützt speichern.
- Nicht vertrauenswürdige Clients in getrennten Repositories sichern.
- Vor Prune, Compact, Archivlöschung und Restore Datenlage prüfen.
- Anwendungsdatenbanken vor dem Dateibackup konsistent dumpen oder snapshotten.
- Keine zweite Manager-Instanz gleichzeitig auf dasselbe Repository schreiben lassen.

## 27. Deinstallation ohne Datenverlust

Container entfernen:

```bash
cd /opt/BorgBackup-Manager
docker compose down
```

Projektdateien können danach entfernt werden. Die persistenten Pfade bleiben bestehen, solange sie nicht ausdrücklich gelöscht werden.

Nicht verwenden, wenn Daten erhalten bleiben sollen:

```bash
docker compose down -v
rm -rf /docker_data/borgbackup-manager
```


### Checkpoint-Archive anzeigen

Die Archivübersicht blendet Checkpoint-Archive standardmäßig aus. Bei Bedarf kann „Unvollständige Checkpoint-Archive anzeigen“ aktiviert werden. Der Manager ergänzt dann `borg list --consider-checkpoints`. Checkpoints entstehen bei unterbrochenen Sicherungen und können nur einen Teil der vorgesehenen Dateien enthalten; Restore oder Löschen sollte daher bewusst erfolgen.

## Lokale Kontowiederherstellung

Seit Version 1.0.3 bündelt `recovery.sh` alle bisherigen Recovery-Befehle. Version 1.0.5 stellt sicher, dass das Skript auch bei Updates in den Projektordner übernommen wird:

```bash
cd /opt/BorgBackup-Manager
chmod +x recovery.sh
./recovery.sh
```

Direkte Beispiele:

```bash
./recovery.sh status
./recovery.sh unlock admin
./recovery.sh reset admin
./recovery.sh reset-admin admin
```

Das Skript prüft zuerst, ob die Compose-Konfiguration gültig ist und der Dienst `borg-manager` läuft. Die Recovery-Funktionen werden ausschließlich lokal im Container ausgeführt. Es wird kein ungeschützter Web-Endpunkt angelegt.

## Größenangaben kontrollieren

Nach dem Update unter **Repositories → Größe berechnen** ausführen. Erwartet werden:

```text
Original
Dedupliziert
Komprimiert
Dateisystem   # nur bei verwalteten Repositories
```

Anschließend unter **Archive → Archive anzeigen** prüfen, ob je Archiv Dauer, Dateianzahl und die drei Größen erscheinen. Bei sehr alten oder unvollständigen Checkpoint-Archiven können einzelne Werte fehlen; die WebUI zeigt dann `–`.


## Quellenstatistik und Archivbrowser

Die Quellenstatistik eines Backup-Jobs wird nach abgeschlossenen Backups aus Borgs Abschlusswerten aktualisiert. Eine manuelle Aktualisierung führt einen repositoryunabhängigen Live-Scan auf dem Quellgerät aus. Dieser zählt die konfigurierten Quellen vor Borg-Ausschlüssen und erzeugt kein Archiv. Nach einem abgeschlossenen Backup ersetzen Borgs exakte Abschlusswerte nach Anwendung der Ausschlüsse die Scanwerte. Der Archivbrowser liest Metadaten direkt über `borg list --json-lines`, zeigt Größe, Typ, Rechte, Besitzer/Gruppe und Änderungszeit und benötigt kein FUSE.
