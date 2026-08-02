# Installation und Betrieb – BorgBackup Manager 1.3.4

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
BorgBackup-Manager-1.3.4.zip
└── BorgBackup-Manager/
```

Installation unter `/opt`:

```bash
cd /opt
unzip /pfad/BorgBackup-Manager-1.3.4.zip
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

Das Skript erzeugt `.env` und die persistenten Verzeichnisse. Beim ersten Containerstart entstehen:

```text
/docker_data/borgbackup-manager/data/security/security.db
/docker_data/borgbackup-manager/data/security/master.key
```

Passwörter werden als scrypt-Prüfwerte gespeichert. Controller-, Repository-SSH- und TLS-Privatschlüssel, Repository-Passphrasen sowie Borg-Keyfiles werden verschlüsselt in `security.db` abgelegt. `master.key` ist der einzige externe Vertrauensanker und besitzt Modus `0600`. Laufzeitdateien werden ausschließlich unter `/run/bbm-secrets` materialisiert.

Beim geführten Quellcode-Build lautet der lokale Image-Name `borgbackup-manager:latest`. Das veröffentlichte Image steht als `ghcr.io/the-ab/borgbackup-manager:latest` und versionsfest als `ghcr.io/the-ab/borgbackup-manager:v1.3.4` bereit. Containername ist `borgbackup-manager`, interner Hostname `bbm`.

### Installation ausschließlich mit dem GHCR-Image

Für einen Docker-Host, auf dem weder Projektquellcode noch `install.sh` liegen sollen, enthält das Release den separaten Ordner `docker-compose/`:

```text
docker-compose/
├── compose.yaml
├── .env.example
├── README.de.md
└── README.md
```

Die Compose-Datei und `.env`-Vorlage in ein eigenes Betriebsverzeichnis kopieren:

```bash
sudo mkdir -p /opt/borgbackup-manager
sudo cp docker-compose/compose.yaml /opt/borgbackup-manager/compose.yaml
sudo cp docker-compose/.env.example /opt/borgbackup-manager/.env
cd /opt/borgbackup-manager
sudo chmod 600 .env
sudo editor .env
```

Mindestens `BBM_REPOSITORY_PUBLIC_HOST`, `BBM_TLS_HOSTS`, `BBM_DATA_PATH` und `BBM_REPOSITORY_PATH` prüfen. Anschließend:

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail=200 borg-manager
```

`BBM_IMAGE_TAG=latest` verwendet `ghcr.io/the-ab/borgbackup-manager:latest`. Für einen kontrollierten Versionsstand kann beispielsweise `BBM_IMAGE_TAG=v1.3.4` gesetzt werden. Ein Update des Image-Stacks erfolgt durch Anpassen des Tags beziehungsweise erneutes `docker compose pull` und danach `docker compose up -d`. Die persistenten Hostpfade bleiben dabei erhalten.

Beim ersten Start prüft der Entrypoint den Mount `/repositories` mit der konfigurierten `BBM_BORG_UID` und `BBM_BORG_GID`. Ist der Mount leer und nur wegen der automatischen Docker-Anlage `root` zugeordnet, wird ausschließlich das Stammverzeichnis auf die konfigurierte UID/GID gesetzt und für den Eigentümer lesbar, beschreibbar und betretbar gemacht. Es erfolgt ausdrücklich kein `chown -R`. Enthält das Verzeichnis bereits Daten, werden keine Eigentümer automatisch geändert. In diesem Fall müssen die Rechte oder ACLs auf dem Host passend korrigiert werden. Bei NFS mit `root_squash` ist die Berechtigung serverseitig beziehungsweise über passende numerische UID/GID zu setzen.

#### Standardmäßig aktivierte schreibgeschützte Archiv-Mounts

Die normale `compose.yaml` aktiviert die Borg-FUSE-Funktion ohne zusätzliche Compose-Datei. Der Docker-Host muss `/dev/fuse` bereitstellen. Vor dem ersten Start den Hostpfad aus `BBM_ARCHIVE_MOUNT_PATH` für die konfigurierte Borg-UID/GID vorbereiten:

```bash
sudo modprobe fuse
sudo mkdir -p /docker_data/borgbackup-manager/archive-mounts
sudo chown 1000:1000 /docker_data/borgbackup-manager/archive-mounts
sudo chmod 700 /docker_data/borgbackup-manager/archive-mounts

docker compose config
docker compose pull
docker compose up -d
```

Die Standardkonfiguration reicht `/dev/fuse` durch, ergänzt `CAP_SYS_ADMIN`, erlaubt FUSE über AppArmor und verwendet `rshared`-Mount-Propagation. Diese Rechte erweitern die Containerberechtigungen und setzen einen vertrauenswürdigen Docker-Host voraus. Die Mount-Funktion unterstützt ausschließlich lokal verwaltete Repositories; externe SSH-Repositories werden abgewiesen. Die Mounts verwenden FUSE `allow_other`; das Image aktiviert dafür `user_allow_other` in `/etc/fuse.conf`. Dadurch kann der propagierte Mount auch auf dem Docker-Host betreten werden. Die archivierten Dateirechte bleiben weiterhin sichtbar, Root auf dem Host kann den Mount jedoch öffnen.

Bei einer echten Neuinstallation schreibt der Container die einmaligen Admin-Zugangsdaten genau einmal in sein lokales Startprotokoll. Das imagebasierte Beispiel aktiviert dies mit `BBM_SHOW_INITIAL_ADMIN_ON_START=1`:

```bash
cd /opt/borgbackup-manager
docker compose logs --tail=200 borg-manager
```

Bis zum verpflichtenden Passwortwechsel können dieselben verschlüsselt gespeicherten Daten jederzeit gezielt erneut ausgegeben werden:

```bash
docker compose exec -T borg-manager python -m app.initial_admin
```

Mit `BBM_SHOW_INITIAL_ADMIN_ON_START=0` wird die automatische Protokollausgabe deaktiviert. Bei aktivierter Ausgabe enthält das lokale Docker-Protokoll das temporäre Passwort. Es ist deshalb unmittelbar zu ändern; Docker-Zugriff und Protokolle dürfen ausschließlich Administratoren zugänglich sein.

### Vollständige `.env`-Konfiguration

Eine nach Pflichtwerten, Netzwerk, Pfaden, Sitzungen, Sicherheitsgrenzen, Backup-Limits und Leistungswerten gegliederte Referenz liegt direkt beim Image-Stack unter [`docker-compose/README.de.md`](docker-compose/README.de.md). Die englische Fassung befindet sich in [`docker-compose/README.md`](docker-compose/README.md).

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
```

`BBM_SESSION_COOKIE_SECURE=always` ist der empfohlene und voreingestellte Wert. Der Manager wird selbst per HTTPS ausgeliefert. `auto` und insbesondere `never` sind nur für ausdrücklich geprüfte Sonderfälle vorgesehen. Proxy-Header beeinflussen Scheme, Client-IP oder Origin ausschließlich, wenn die unmittelbare Proxy-Adresse in `BBM_TRUSTED_PROXY_CIDRS` liegt. Bei einem separaten Docker-Reverse-Proxy muss dessen festes Container-Netz dort ausdrücklich ergänzt werden; eingehende Forwarded-Header sind am Proxy zu überschreiben.

Bei einem Update ab v1.1.0 baut `update.sh` die vorhandene `.env` anhand der aktuellen Vorlage neu auf. Unterstützte eigene Werte bleiben erhalten, fehlende aktuelle Werte werden ergänzt und obsolete Einträge wie `COMPOSE_FILE`, alte Token-/Secret-Variablen, interne Archiv-Mount-Schalter, `BBM_DEBUG_LOG_LEVEL`, `BBM_HTTP_PORT` und alte TLS-Dateipfade werden entfernt. Die Datei bleibt mit Modus `0600` geschützt.

`BBM_APPEARANCE` ist der Startwert für Konten ohne persönliche Darstellung. Danach gilt das benutzerbezogene Farbschema aus **Profil → Darstellung & Sprache**. `BBM_REPOSITORY_SIZE_AFTER_RUN` bestimmt den Anfangswert der systemweiten Größenaktualisierung, solange noch keine `settings.json` vorhanden ist.

Daten- und Repository-Pfad dürfen nicht identisch sein. Die neuen Standardpfade liegen als getrennte Geschwisterverzeichnisse unter `/docker_data/borgbackup-manager`: Managerdaten unter `data`, Repositories unter `repositories`. Abweichende Bestandsinstallationen bleiben unterstützt; liegt das Repository-Verzeichnis innerhalb des Datenpfads, schließt der Updater es bei der Managersicherung gezielt aus. Host-Port und Hostpfade werden zusätzlich als reine Metadaten in den Container übergeben, damit ein Manager-Backup sie vollständig in `migration.env` aufnehmen kann; die tatsächlichen Mounts bleiben unverändert durch Compose definiert.

## 4. Bestehende Installation ab v1.1.0 übernehmen

Direkte Updates werden ausschließlich von BorgBackup Manager v1.1.0 oder neuer unterstützt. Bei älteren Installationen ist eine Neuinstallation erforderlich; vor-v1.1.0-Datenbank-, Token-, Secret- und Mount-Kompatibilität wurde entfernt.

Für eine unterstützte Bestandsinstallation müssen `.env`, das persistente Datenverzeichnis und der Repository-Pfad unverändert weiterverwendet werden. Niemals `docker compose down -v` oder das Löschen von `/docker_data/borgbackup-manager` verwenden. Der normale Weg ist das geprüfte `update.sh`; es sichert den Zustand, bereinigt `.env`, baut das Image neu und führt bei einem fehlgeschlagenen Start soweit möglich ein Rollback aus.

Die Sicherheitsdatenbank und der Master-Key liegen unter `BBM_DATA_PATH/security`. Beide gehören zusammen und müssen gemeinsam gesichert werden.

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

Mit Benutzer `admin` und dem temporären Passwort anmelden. Die WebUI erzwingt unmittelbar ein neues persönliches Passwort. Es muss mindestens zwölf Zeichen enthalten und mindestens drei der Gruppen Kleinbuchstaben, Großbuchstaben, Ziffern und Sonderzeichen verwenden. Nach dem Wechsel wird das verschlüsselte Bootstrap-Geheimnis gelöscht. Sitzungen werden serverseitig gespeichert und über ein `HttpOnly`-/`SameSite=Strict`-/`Secure`-Cookie zugeordnet. Sie enden standardmäßig nach 24 Stunden absolut oder nach 60 Minuten Inaktivität. Das Inaktivitäts-Timeout kann später unter **System → Einstellungen → Sitzung** geändert werden; `BBM_SESSION_IDLE_TIMEOUT_SECONDS` liefert den anfänglichen Standardwert, während `BBM_SESSION_TTL_SECONDS` die absolute Obergrenze vorgibt. Ein separater, nur im aktuellen Tab gespeicherter Reload-Schlüssel ist serverseitig gehasht, an Sitzung und User-Agent gebunden und verliert beim Schließen des Tabs, Abmelden, Passwortwechsel oder Sitzungsablauf seine Wirkung. Teure Passwortprüfungen werden persistent pro Quelle und pro Quelle/Benutzer-Kombination begrenzt; Benutzerkonten werden durch fremde Fehlversuche nicht mehr systemweit gesperrt.

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

### Gespeicherte SSH-Aktionen

Unter **Geräte → Gespeicherte SSH-Aktionen** können Administratoren pro Gerät wiederkehrende Wartungsbefehle hinterlegen. Beispielsweise kann ein Host-Mount über einen bereits eingerichteten fstab-Eintrag ein- oder ausgehängt werden:

```bash
sudo -n mount /mnt/offline-backup
sudo -n umount /mnt/offline-backup
```

Die WebUI besitzt keine freie SSH-Konsole. Nur gespeicherte Aktionen können gestartet werden und jeder Start wird vorher bestätigt. Name, Befehl, Zielgerät, Aktivstatus und Zeitlimit werden mit dem vorhandenen Master-Key geschützt; der Befehlsinhalt liegt authentifiziert verschlüsselt in `/data/security/security.db`. Beim ersten Start von v1.3.4 werden vorhandene Klartexteinträge aus `manager.db` zunächst vollständig importiert und durch erneutes Entschlüsseln verifiziert. Erst danach wird die alte Tabelle entfernt. Auch eine leere oder nach einem früheren Abbruch verbliebene Alttabelle wird erkannt. Die Datenbank einschließlich WAL wird vor Freigabe der WebUI per Checkpoint und `VACUUM` bereinigt; danach kontrolliert BBM zusätzlich, dass kein migrierter Befehl mehr in `manager.db`, `manager.db-wal` oder `manager.db-shm` enthalten ist. Schlägt ein Schritt fehl, bleibt der Vorgang wiederholbar und der Manager startet nicht mit einer nur teilweise migrierten Aktion. Laufvorschau und normale Protokolle nennen nur Aktion und Zielgerät. Interaktive Passwortabfragen funktionieren weiterhin nicht; benötigte Root-Rechte sind über eine eng begrenzte sudoers-Regel und `sudo -n` bereitzustellen. Ausgabe und Fehler erscheinen als reguläres Ausführungsprotokoll und der Lauf kann über das Live-Log gestoppt werden.

Warnstufen:

```text
1.2.0–1.2.4  kritisch, aber nutzbar
1.2.6–1.2.8  veraltet, aber nutzbar
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

Bei unterstützten Updates ab v1.1.0 bleiben externe Repository-Einträge und ihre zentral verwalteten SSH-Daten erhalten.

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

Für **externe SSH-Repositories** kann die Speicherplatz-Sperre ebenfalls pro Repository aktiviert werden. Die Repository-Liste zeigt die über eine separate SSH-`df -m`-Abfrage ermittelte Belegung. Vor dem Backup wird zwingend frisch geprüft; während `borg create` erfolgt die Prüfung alle 15 Sekunden und nach Jobende ein letztes Mal. Wird die Grenze während des Backups erreicht, stoppt der Manager Borg kontrolliert. Zwei aufeinanderfolgende fehlgeschlagene Prüfungen beenden einen laufenden Job ebenfalls, sofern die Sperre aktiviert ist. Externe Repositorys erben die globale Aktivierung nicht automatisch; ohne ausdrückliche Aktivierung bleibt die externe Sperre aus. Der Prozentwert kann bei Aktivierung weiterhin global übernommen oder repositorybezogen überschrieben werden. Ein ausschließlich auf `borg serve` beschränkter SSH-Zugang kann die Dateisystemabfrage verhindern; in diesem Fall kann eine aktivierte externe Sperre keinen Backupstart zulassen.

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

- vorhandene Vorlage über eine Auswahlbox laden
- Vorlagenname ändern
- Muster ergänzen oder entfernen
- neue Vorlage anlegen
- ausgewählte Vorlage löschen

Es wird immer nur die ausgewählte Vorlage im Editor angezeigt. Dadurch bleibt der Bereich auch mit vielen Vorlagen kompakt.

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

Der Zeitplan läuft in drei Phasen: zuerst alle Backups, danach alle Archivbereinigungen und anschließend – wenn die Systemeinstellung aktiviert ist – maximal ein Compact je betroffenem Repository. Mehrere Jobs auf demselben Repository lösen daher nicht mehr mehrere Compact-Aufträge aus. Diese Systemeinstellung gilt nur für Zeitpläne; eine manuell gestartete Archivbereinigung löst darüber kein Compact aus.

Für manuelle Starts stehen im Backup-Job unter **Aufbewahrung** zwei optionale Nachbereitungen bereit: **Nach manuellem Backup Archivbereinigung ausführen** und **Nach erfolgreicher manueller Archivbereinigung Compact ausführen**. Bei aktivierter Nachbereitung bleibt das Repository für die gesamte Kette reserviert; weitere Jobs desselben Repositorys warten bis zum Abschluss.

## 10b. Warteschlange und Parallelitätsgrenzen

Pro Repository wird immer nur eine Borg-Aktion gleichzeitig ausgeführt. Starten mehrere Geräte zur selben Zeit, bleibt der erste Lauf **Laufend**, alle weiteren stehen **Wartend**. Das Dashboard zeigt beide Zustände getrennt. Sobald das Repository frei wird, startet der nächste wartende Lauf automatisch. Direkt am Repository gestartetes Compact und repositoryweite Archivlöschungen werden ebenfalls über diese Sperre und ein reguläres Ausführungsprotokoll gesteuert; ein Backup-Job ist dafür nicht erforderlich.

Die Parallelität wird in vier Ebenen begrenzt: durch einen festen Einzelplatz pro physischem Borg-Repository, **global**, **pro erkanntem Repository-Dateisystem** und optional **pro Zeitplan**. Die Repository-Grenze ist nicht konfigurierbar, weil Borg schreibende Vorgänge im selben Repository ohnehin exklusiv sperrt. Unter **System → Einstellungen → Parallelitätsgrenzen** kann die globale Obergrenze von `0` bis `64` gesetzt werden (`0` = unbegrenzt), für jeden erkannten lokalen Mount oder externen SSH-Dateisystemverbund eine gemeinsame Grenze hinterlegt werden (`0` = unbegrenzt) und die Zahl gleichzeitig laufender manueller Quellenstatistiken separat begrenzt werden (Standard `1`). Externe Gruppen entstehen automatisch aus SSH-Identität und dem durch die Remote-Dateisystemprüfung gemeldeten Mountpunkt. Eine Grenze von `2` erlaubt zwei unterschiedliche Repositorys auf demselben lokalen oder externen Dateisystem; weitere Repositorys dieses Dateisystems warten. Mehrere Jobs desselben Repositorys bleiben immer serialisiert. Quellenstatistiken zählen gleichzeitig gegen die globale Grenze, reservieren aber kein Repository und kein Repository-Dateisystem, weil sie nur das Quellgerät lesen. Zeitpläne können zusätzlich eine engere Grenze besitzen. Ein Job startet nur, wenn alle für ihn geltenden Grenzen gleichzeitig freie Kapazität besitzen.
Eine geänderte Dateisystemgrenze wird von bereits wartenden Läufen fortlaufend neu eingelesen und gilt daher ohne vorheriges Leeren der Warteschlange. Persistierte Läufe werden ausschließlich durch den datenbankgestützten FIFO-Ausführungsplan zugelassen; eine zweite prozesslokale Reservierung findet nicht statt. Externe Gruppen erscheinen nach erfolgreicher Speicherprüfung beziehungsweise nach dem Laden der Systemdiagnose. Solange kein Remote-Mount erkannt wurde, bleibt die repositoryweise Serialisierung aktiv. Unter **System → Systemdiagnose → Repository-Dateisysteme** erscheinen die tatsächlich wirksame Grenze jedes lokalen und erkannten externen Dateisystems, die aktuelle Belegung als **aktiv / wartend** sowie die globale und die separate Quellenstatistik-Grenze.

Die Reihenfolge wird als atomarer datenbankgestützter FIFO-Ausführungsplan geführt. Globale, Zeitplan-, Mount- und Repository-Grenzen werden dabei in genau einer Zulassungsentscheidung vergeben. Eine zusätzliche Laufzeitsperre schützt nur direkte interaktive Borg-Aufrufe desselben Repository-Datensatzes; sie reserviert keine Mount-Kapazität für persistierte Jobs. Das tatsächliche Repository-Verzeichnis beziehungsweise die externe URL bildet im Queue-Plan weiterhin die physische Sperridentität, sodass auch versehentlich doppelt erfasste Ziele nicht parallel bearbeitet werden. Freie globale Plätze werden nicht durch einen älteren Lauf verschwendet, der noch auf sein Repository oder seine Zeitplangrenze wartet. Wartende Laufprotokolle nennen die konkrete Ursache und gegebenenfalls die davorliegende Ausführungs-ID. Nur tatsächlich lebende Manager-Tasks belegen Plätze; verwaiste Laufzustände werden nicht als dauerhafte Blocker behandelt. Extern gestartete Borg-Prozesse sind für die Manager-Warteschlange nicht sichtbar und werden weiterhin durch Borgs eigene Repository-Sperre abgefangen.

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

Die vollständige Dateiliste ist bei neu angelegten Jobs standardmäßig deaktiviert, um die Manager-CPU bei sehr großen Sicherungen niedrig zu halten. Borg-Fortschritt, A/M/C/E-Livezähler und C/E-Warnungspfade bleiben trotzdem verfügbar. Bei bestehenden Jobs wird die gespeicherte Einstellung unverändert übernommen. Die angezeigte Version ist die auf dem Backup-Client tatsächlich verwendete Borg-Version.

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
2. Checkpoint-Archive werden in der normalen Archivübersicht automatisch angezeigt und eindeutig als unvollständig gekennzeichnet.
3. **Archive anzeigen** wählen. Diese Aktion liest ausschließlich den vorhandenen persistenten Archivcache und startet keinen Borg-Befehl.
4. Ist noch kein Cache vorhanden oder wurde das Repository außerhalb des Managers verändert, **Neu aus Repository einlesen** wählen. BBM legt dafür eine normale Hintergrund-Ausführung mit eigener Run-ID an; `borg info`/`borg list` sind damit unabhängig vom HTTP- beziehungsweise Reverse-Proxy-Timeout.
5. Während des Scans bleibt eine vorhandene Archivliste sichtbar. Erst nach erfolgreichem Abschluss wird der Cache atomar ersetzt.
6. Optional ein erkanntes Gerät auswählen. Die Zuordnung verwendet zuerst die Archivserie, danach Borg-Hostname beziehungsweise Archivname.
7. Für eine Mehrfachlöschung einzelne Archive markieren oder **Sichtbare Archive auswählen** verwenden.

Nach Backup, Archivbereinigung, Umbenennen oder Löschen wird nur der Cache des betroffenen Repositorys automatisch ungültig. Andere Repository-Caches bleiben erhalten. Ein Backup-Job ist für Archivliste, Archivinformationen und den Browser nicht erforderlich. Verwaltete Repositories werden über ihren lokalen Pfad gelesen; externe Repositories öffnet der Manager selbst per Borg/SSH mit den zentral gespeicherten Repository-Zugangsdaten.

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

Eine Archivlöschung wird anhand der streng validierten ausgewählten Namen sofort als normale Ausführung eingereiht und liefert unmittelbar eine Run-ID. Das vollständige Repository wird vor der Run-Erstellung nicht erneut innerhalb der HTTP-Anfrage eingelesen. Das Laufprotokoll öffnet sich sofort; ein veralteter Cache beziehungsweise ein außerhalb des Managers bereits entferntes Archiv erscheint dort als Borg-Fehler. Dadurch bleiben Löschungen auch bei sehr großen Repositorys unabhängig vom HTTP-/Reverse-Proxy-Timeout sichtbar.

Bei lokal verwalteten Repositories benötigt der Containerbenutzer `BBM_BORG_UID:BBM_BORG_GID` Leserechte auf allen Segmentdateien. Schreiben weitere Clients mit abweichenden Eigentümern, müssen gemeinsame Gruppen, ACLs oder die NFS-UID/GID-Zuordnung entsprechend eingerichtet werden. Bei fehlenden Rechten zeigt die WebUI nur den betroffenen Pfad und die verwendete UID:GID. Bei als Ausführung gestarteten Aktionen bleibt die vollständige Borg-Ausgabe im Laufprotokoll; direkte Archivlistenabfragen liefern bewusst nur die kurze Ursache.

Compact wird mit `--verbose` ausgeführt. Dadurch enthält das Ausführungsprotokoll die von Borg geschätzte freigegebene Größe, sofern unreferenzierte Segmente entfernt wurden. Die direkte Repository-Aktion ist während eines aktiven Archiv-Mounts oder eines laufenden beziehungsweise wartenden Repository-Laufs gesperrt. Bei der Mehrfachlöschung werden alle Archivnamen vor dem Start erneut geprüft; gemountete ausgewählte Archive blockieren die Aktion.

## 14. Archivbrowser und Export

Der Browser arbeitet ohne FUSE. Dateien und Ordner können markiert werden.

Aktionen:

- Auswahl in Wiederherstellung übernehmen
- Auswahl als TAR.GZ exportieren

Exportdateien liegen temporär unter `/data/exports` und werden nach der Übertragung entfernt.

### Archiv schreibgeschützt auf dem Docker-Host einhängen

In der Standardkonfiguration steht in der Archivübersicht **Archiv einhängen** zur Verfügung. Der Manager erzeugt den Zielpfad ausschließlich unter `/archive-mounts`; auf dem Host entspricht dies `BBM_ARCHIVE_MOUNT_PATH`. Pro Repository ist nur ein aktiver Mount erlaubt.

Während des Mounts:

- warten Backup-Läufe, Archivbereinigung und Compact desselben Repositorys,
- sind Archivlöschung und Umbenennung gesperrt,
- bleibt der Mount schreibgeschützt,
- kann er im Bereich **Aktive Archiv-Mounts** kontrolliert ausgehängt werden.

Beim Aushängen verwendet der Manager zuerst `fusermount3`, danach Borg und als letzte Rückfallstufe ein Lazy-Unmount. Jeder Versuch ist zeitlich begrenzt. Überschreitet die Operation das interne Zeitlimit, antwortet die API vor einem typischen Proxy-Timeout mit einer Fehler-ID und schreibt die technische Diagnose in `debug.log`. Beim Containerstopp werden aktive Mounts vor dem Beenden ebenfalls mit begrenzten Rückfallstufen ausgehängt. Nach einem harten Abbruch erkennt der nächste Start verwaiste Datenbankeinträge. `/data/exports` wird nicht als Mount-Ziel verwendet.

## 15. Wiederherstellung

### Dry-Run

Prüft den Vorgang, schreibt aber keine Dateien.

### Live-Fortschritt

BBM zählt vor dem Restore die ausgewählten Archivobjekte und summiert deren Originalgröße in einem gestreamten Borg-Listenlauf. Der anschließende Live-Dialog zeigt Gesamt-/Restdateien beziehungsweise Objekte, Gesamt-/Restgröße, Prozent, aktuelle Rate, Restzeit und aktuellen Pfad. Bei einem Dry-Run wird derselbe Fortschritt für die Prüfung angezeigt. Die Vorbereitung benötigt bei großen Auswahlen einen zusätzlichen Metadatenlauf, überträgt aber keine vollständige Dateiliste an den Manager.

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

Ein Borg-Rückgabecode `1` bedeutet, dass der Vorgang sein normales Ende erreicht und das Archiv gespeichert wurde, aber Warnungen vorlagen. Der Manager zeigt die konkreten Ursachen im Laufdialog an. Wenn die vollständige Dateiliste im Job deaktiviert ist, ergänzt der Backup-Befehl intern `--list --filter AMCE`: `A` und `M` werden nur als leichtgewichtige Live-Zähler ausgewertet und nicht dauerhaft in das Laufprotokoll geschrieben; `C` und `E` bleiben zusätzlich für die Warnungsdiagnose erhalten. Unveränderte `U`-Einträge werden nicht angefordert. Ist die vollständige Liste aktiviert, verarbeitet der Manager die große Statusausgabe gepuffert und mit einer Schnellprüfung für normale Dateistatus, sodass die vollständige Anzeige deutlich weniger Manager-CPU benötigt.

Bei nutzbarer Quellenbasis friert der Backup-Lauf beim Einreihen die zuletzt bekannte Quellengröße und Dateianzahl ein. Borg O/N werden direkt davon abgezogen. Die Restzeit wird rein rechnerisch aus den verbleibenden Bytes mit einer festen 1-Gbit/s-Annahme und 80 % nutzbarem Durchsatz (effektiv 100 MB/s) bestimmt; die verbleibende Dateianzahl ergänzt lediglich den festen Korrekturfaktor für viele kleine Dateien. Gemessener Netzwerkdurchsatz, kurzfristige Borg-Raten, Files-Cache-Phasen und frühere Gesamtlaufzeiten fließen nicht ein. Wird die eingefrorene Byte-Basis überschritten, bleibt die Restzeit leer statt einen falschen Null- oder Negativwert anzuzeigen.

Ab Version 0.8.7 liegen vollständige neue Laufprotokolle unter:

```text
/data/run-logs/run-ID.log
```

SQLite speichert nur Metadaten sowie feste, von Borg-Dateistatus bereinigte Vorschauen von maximal 4 KiB stdout, 32 KiB gefilterte Fehler-/Warnungsausgabe und 16 KiB Bedienprotokoll. Normale Dateipfade liegen ausschließlich in `/data/run-logs`; nur konkret betroffene Warnungspfade werden begrenzt in der strukturierten Warnungszusammenfassung gespeichert. Beim Start werden größere oder ältere Rohinhalte bei Bedarf zuerst nach `/data/run-logs` migriert und anschließend aus der Datenbank entfernt. Unter **System → Einstellungen → Ausführungs- und Benachrichtigungsprotokolle** werden Anzahl, Dateigröße, Datenbankanteil und Benachrichtigungszustellungen angezeigt. Die Fristbereinigung entfernt abgelaufene Ausführungsprotokolle und Zustellungsprotokolle, bewahrt aber für jeden noch vorhandenen Backup-Job ausschließlich den neuesten erfolgreichen beziehungsweise mit Warnung abgeschlossenen Backup-Lauf als belastbaren letzten Sicherungsstand. Fehlgeschlagene oder abgebrochene Backup-Läufe sind nicht geschützt und unterliegen der normalen Aufbewahrung beziehungsweise können einzeln gelöscht werden. Die gespeicherte Quellenstatistik vorhandener Jobs bleibt ebenfalls erhalten. **Alle Protokolle löschen** ist die einzige Gesamtbereinigung, die auch diese geschützten letzten Stände, alle Benachrichtigungszustellungen und die gespeicherten Quellenstatistiken entfernt. Die automatische Bereinigung läuft täglich um 03:30 Uhr Europe/Berlin nach der konfigurierten Aufbewahrungsdauer. Aktive und wartende Läufe bleiben immer erhalten.

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

## 18. Manager-Backup, Cache-Backup und Sicherheitsdaten

Seit v1.0.77 sind Managerdaten und Borg-Caches zwei getrennte Sicherungstypen. Neue Manager-Backups enthalten keinen Borg-Cache mehr. Dadurch wächst die für eine eigentliche BBM-Wiederherstellung benötigte Datei nicht mit den Cache-Daten mehrerer TiB-Repositories oder vieler Clients.

### Manager-Backup erstellen

Das Manager-Backup enthält Manager-Datenbank, Sicherheitsdatenbank, Master-Key, Einstellungen, Benachrichtigungskonfiguration und `migration.env`. Controller-Schlüssel, Repository-SSH-Hostschlüssel, Borg-Keyfiles/Passphrasen, TLS-Material und Benachrichtigungsgeheimnisse sind verschlüsselt in der Sicherheitsdatenbank gespeichert; der Master-Key ist der zwingende Entschlüsselungsanker. `authorized_keys` und die Klartextdateien unter `/run/bbm-secrets` werden nach dem Restore aus den Datenbanken neu erzeugt. Vor dem Speichern prüft BBM beide SQLite-Datenbanken, die Vollständigkeit der Security-Tabellen, den Master-Key und die Entschlüsselbarkeit sämtlicher gespeicherter Geheimnisse. Fehlt ein Bestandteil oder passt der Master-Key nicht zur Sicherheitsdatenbank, wird kein erfolgreiches Backup erzeugt. Repository-Nutzdaten, vorhandene Backup-Artefakte, Exporte, vollständige Lauf-/Debug-Protokolle, `/data/borg-cache`, `/data/borg-security` und Client-Borg-Caches sind nicht enthalten.

Neue Manager-Backups werden ausschließlich als AES-256-GCM-verschlüsselte `.bbm`-Dateien erzeugt. Die eigene Passphrase muss mindestens zwölf Zeichen lang sein und wird nicht gespeichert. Die Kompression ist wählbar zwischen keine, Deflate 1, Deflate 6 (Standard) und Deflate 9. Import und Wiederherstellung setzen eine Metadatenversion v1.1.0 oder neuer voraus.

Während der Erstellung zeigt die WebUI Phase, Fortschrittsbalken und ein Live-Protokoll. Ein Seiten-Reload nimmt den aktiven Backup-Task wieder auf.

### Getrennte Cache-Artefakte erstellen

Ab v1.3.0 erzeugt ein Cache-Backup-Lauf keine große Sammeldatei mehr. Stattdessen entstehen unabhängig voneinander:

- `borgbackup-manager-cache-manager-v...` für `/data/borg-cache` und `/data/borg-security`
- `borgbackup-manager-cache-client-<Gerätename>-h<ID>-v...` für jedes ausgewählte Gerät

Im Formular kann der Manager-Cache separat aktiviert werden. Für Client-Caches gibt es **Alle Geräte** oder **Ausgewählte Geräte** mit Mehrfachauswahl. Nicht ausgewählte Geräte werden nicht per SSH kontaktiert. Jedes Gerätearchiv enthält alle aktuell über Backup-Jobs zugeordneten Repository-Caches dieses Geräts einschließlich des jeweils zuordenbaren Borg-Sicherheitsstatus. Gerätename und stabile ID stehen im Dateinamen und in den internen Archivpfaden.

Ein Ausfall eines Geräts bricht die übrigen Archive nicht ab. Das betroffene Gerät wird als Warnung dokumentiert; Geräte ohne sicherbare Cache-/Security-Daten erzeugen keine leere Datei. `lock.exclusive`, `lock.roster` und symbolische Links werden ausgeschlossen. Während der Erstellung dürfen keine Ausführungen laufen oder warten.

Die Verschlüsselung ist standardmäßig aktiv und empfohlen. Jedes Einzelartefakt wird separat mit AES-256-GCM/scrypt verschlüsselt und erhält `.bbm`; bewusst unverschlüsselte Artefakte verwenden `.zip`. Alle Dateien eines Laufs verwenden dieselbe eingegebene Passphrase und Kompressionsstufe. Die Live-Anzeige zeigt `Archiv x/y`, Gerätename, Repository und übertragene Bytes.

Unter **Cache-Backup wiederherstellen** wird ein Manager-Cache-Artefakt als eigene Aktion eingespielt. Bei einem Gerätearchiv werden die enthaltenen Repository-Caches einzeln angezeigt. Für jeden Eintrag kann als Ziel das ursprüngliche Gerät oder ein anderes aktives Gerät gewählt werden, das demselben Repository zugeordnet ist. Vorhandene Ziel-Caches werden als `pre-bbm-restore`-Sicherheitskopie erhalten; bestehender Borg-Sicherheitsstatus wird nicht durch einen älteren Stand überschrieben.

Unter **Borg-Cache verwalten** können Manager- und Client-Zustände weiterhin unabhängig vom Backup auf Knopfdruck geprüft, zurückgesetzt und bereinigt werden. Der Client-Scan unterstützt ebenfalls alle Geräte oder eine Mehrfachauswahl.

### Backup hochladen

1. **System → Manager-Backup** öffnen.
2. Direkt unter **Manager-Backup erstellen** im kompakten Bereich **Backup hochladen** ein BBM-Manager- oder Cache-Backup auswählen.
3. **Backup hochladen** wählen.
4. Nach erfolgreicher Prüfung erscheint die Datei in der passenden Liste **Manager-Backups** oder **Cache-Backups**.

Dateityp, Dateiname, Größe und Struktur werden geprüft, vorhandene Dateien werden nicht überschrieben und die gespeicherte Datei erhält Modus `0600`. Manager-Backups verwenden `BBM_BACKUP_MAX_FILE_BYTES` (standardmäßig 256 MiB). Für Cache-Backups gelten die separaten Grenzen `BBM_BACKUP_CACHE_MAX_FILE_BYTES` (32 GiB), `BBM_BACKUP_CACHE_MAX_UNCOMPRESSED_BYTES` (128 GiB), `BBM_BACKUP_CACHE_MAX_ENTRIES` (250000) und `BBM_BACKUP_CACHE_MAX_COMPRESSION_RATIO` (5000). Bei verschlüsselten Dateien wird die vollständige kryptografische Authentifizierung vor der Wiederherstellung mit der Passphrase durchgeführt.

### Manager-Backup in der WebUI wiederherstellen

1. Alle laufenden und wartenden Jobs beenden.
2. Ein **Manager-Backup** auswählen.
3. bei `.bbm` die Backup-Passphrase eingeben.
4. eine separate, mindestens zwölf Zeichen lange Passphrase für das verschlüsselte Sicherheitsbackup eingeben und bestätigen.
5. Ersetzungsbestätigung aktivieren.
6. Wiederherstellung starten.

Der Manager prüft Sicherungstyp und Mindestversion v1.1.0, erstellt ein verschlüsseltes lokales Sicherheitsbackup und ersetzt anschließend Manager- und Sicherheitsdatenbank, Master-Key, Einstellungen sowie SSH-/TLS-/Repository-Schlüssel. Ein separates Cache-Backup kann nicht als Managerzustand wiederhergestellt werden. Der Container startet neu; bestehende Browser-Sitzungen müssen sich danach neu anmelden.

### Cache-Backup gezielt wiederherstellen

1. **System → Manager-Backup → Cache-Backup wiederherstellen** öffnen.
2. Ein Cache-Backup auswählen; bei verschlüsselten Dateien die Passphrase eingeben.
3. Falls enthalten, **Manager-Cache wiederherstellen** wählen oder **Client-Caches anzeigen**.
4. Beim gewünschten Client-Gerät/Repository **Wiederherstellen** wählen und die Sicherheitsabfrage bestätigen.

Die Wiederherstellung ist nur ohne laufende oder wartende Ausführungen möglich. Beim Manager-Cache werden vorhandene `/data/borg-cache`-/`/data/borg-security`-Stände vor dem Austausch als zeitgestempelte `pre-bbm-restore`-Sicherheitskopien erhalten. Bei Client-Caches müssen Gerät und Repository weiterhin gemeinsam einem aktuellen Backup-Job zugeordnet sein und das Gerät muss aktiviert sein. Ein vorhandener Zielcache wird als `repository-<ID>.pre-bbm-restore-<Zeit>` erhalten. Unerwartete TAR-Pfade, symbolische Links und alte Lockartefakte werden nicht aktiviert.

Cache-Backups werden nur akzeptiert, wenn ihre Metadatenversion v1.1.0 oder neuer ist.

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

Für einen Serverwechsel werden ausschließlich Manager- und Cache-Backups mit Metadatenversion v1.1.0 oder neuer unterstützt. Repository-Verzeichnisse müssen separat übertragen oder wieder eingebunden werden.

## 19. Zeitzone, Dashboard und Systembereich

Der Compose-Stack setzt standardmäßig `TZ=Europe/Berlin`. Das Dashboard zeigt Repository-Anzahl und summierte Repository-Größe gemeinsam in einer Kachel. Darüber hinaus steht oberhalb der letzten Aktivitäten eine sortierbare Backup-Job-Tabelle mit Status, Gerät, Repository, Quellen, Zeitplan, letztem Lauf und den gespeicherten Größen der letzten Sicherung. Quellenstatistik und letzter Lauf werden jeweils in zwei kompakten Zeilen dargestellt; Dedupliziert, Original und Komprimiert stehen als drei eng gesetzte Beschriftungs-/Wertzeilen untereinander. Ein fehlgeschlagener letzter Lauf ersetzt dabei nicht die Größenwerte der vorherigen erfolgreichen Sicherung. Die Systemdiagnose befindet sich unter **System → Systemdiagnose** und lässt sich nach dem Laden ohne Seitenreload wieder schließen. Das Dashboard zeigt neben laufenden auch wartende Ausführungen; beide Kacheln öffnen die entsprechend gefilterte Protokollansicht. Die WebUI stellt serverseitige UTC-Zeitwerte in dieser Zeitzone dar. Borg-Archivzeitpunkte ohne Offset werden als lokale Zeit dieser Zeitzone interpretiert und nicht ein zweites Mal um zwei Stunden verschoben. Cron-Zeitpläne werden in dieser Zeitzone ausgewertet und remote gestartete Borg-Befehle erhalten dieselbe TZ-Variable.


- Darstellung hell, dunkel oder automatisch
- globale Parallelitätsgrenze für alle Manager-Ausführungen (`0` = unbegrenzt) sowie gemeinsame Parallelitätsgrenzen pro erkanntem lokalen oder externen Repository-Dateisystem
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
- Compact nach geplanter Archivbereinigung
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

Jeder Administrator und jeder normale Benutzer öffnet in der Seitenleiste direkt unter dem Benutzernamen **Profil**. Der Eintrag führt auf eine eigene Profilseite mit Kontoübersicht, direkt bearbeitbaren Einstellungen für **Darstellung & Sprache**, einem Passwortformular und der Verwaltung der **Zwei-Faktor-Authentifizierung**. Unter **Darstellung & Sprache** können eigene Werte gespeichert werden:

- Sprache: Deutsch oder Englisch
- Farbschema: Automatisch, Hell oder Dunkel

Die Werte liegen am jeweiligen Benutzerkonto in der Sicherheitsdatenbank. Sie verändern keine globale Einstellung und haben keinen Einfluss auf andere Konten. Navigation, Formulare, Dialoge, dynamische Statusmeldungen, das integrierte Betriebshandbuch und die aktuellen Release Notes folgen der gewählten Sprache.

## 21. Aktionsbestätigung und Aktualisierung

Die WebUI bestätigt Änderungen unmittelbar über den betätigten Button, eine Toast-Meldung und die Statusanzeige im Seitenkopf. Bei laufenden oder wartenden Aufgaben zeigt die Statusposition vor dem Farbschema-Schalter die aktuell laufende Aufgabe und gegebenenfalls die Zahl weiterer aktiver Läufe. Ein Klick öffnet ohne Zwischenliste direkt das Live-Log des aktuell laufenden Vorgangs; falls ausschließlich wartende Läufe vorhanden sind, wird der nächste wartende Lauf geöffnet. Borg-Hintergrundläufe werden nach ihrer Lauf-ID bis zum tatsächlichen Abschluss verfolgt. Anschließend werden ausschließlich die betroffenen API-Bereiche neu geladen. Archivlisten verwenden einen persistenten repositorybezogenen Cache. Nach Backup, Archivbereinigung, Umbenennen oder Löschen wird dieser vor dem sichtbaren Laufabschluss invalidiert; eine geöffnete Ansicht baut ihn anschließend gezielt neu auf. Compact allein verändert die Archivliste nicht.

Das unter **Einstellungen** konfigurierbare Aktualisierungsintervall ist nur eine zusätzliche Hintergrundaktualisierung. Die Bestätigung und Übernahme einer Aktion ist nicht von diesem Zeitwert abhängig. Ein manuelles Neuladen der gesamten Browserseite ist im Normalfall nicht erforderlich.

## 22. Update

### Unterstützte Updates ab Version 1.1.0

Direkte Updates von Versionen vor v1.1.0 werden ausdrücklich abgelehnt. Solche Installationen müssen neu eingerichtet werden. Dadurch entfallen frühere Sonderpfade für alte Updater, Token, Secrets, Client-Mounts und Datenbankschemata.

### Einmaliger Übergang von v1.2.4 auf v1.2.5

Der Updater aus v1.2.4 verlangt noch die inzwischen entfernte Datei `compose.archive-mounts.yaml` im Release-ZIP. Deshalb muss für genau diesen Übergang zuerst der neue Updater sicher aus dem bereits verifizierten v1.2.5-ZIP übernommen werden:

```bash
cd /opt/BorgBackup-Manager
unzip -p updates/BorgBackup-Manager-1.2.5.zip BorgBackup-Manager/update.sh > update.sh.new
bash -n update.sh.new
chmod 755 update.sh.new
mv update.sh.new update.sh
```

Danach den normalen v1.2.5-Updatebefehl ausführen. Der neue Updater entfernt die alte Override-Datei und bereinigt `COMPOSE_FILE` sowie weitere obsolete Werte aus `.env`.

### Normale Updates ab Version 1.1.0

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

Das Störungsprotokoll `/data/logs/debug.log` speichert unerwartete Tracebacks, unbehandelte Anwendungs-/Hintergrundfehler, kritische Framework- oder Systemfehler und managerseitige HTTP-5xx-Antworten. Normale Backup-Läufe, Quellenstatistik-Ausgaben, erwartbare Borg-Warnungen sowie lange, aber nicht technische Meldungen werden dort nicht abgelegt. Geschützte Fehler erscheinen mit einer kurzen `BBM-...`-Fehler-ID. Der Hinweis nach einem fehlgeschlagenen oder abgebrochenen Lauf verschwindet nach sechs Sekunden; andere handlungsrelevante rote Fehler bleiben bis zum Schließen sichtbar.

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
- Vor Archivbereinigung, Compact, Archivlöschung und Restore Datenlage prüfen.
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


### Checkpoint-Archive

Die Archivübersicht zeigt erkannte Checkpoint-Archive automatisch und kennzeichnet sie eindeutig als unvollständig. Checkpoints entstehen bei unterbrochenen Sicherungen und können nur einen Teil der vorgesehenen Dateien enthalten; Restore oder Löschen sollte daher bewusst erfolgen. Im Restore-Dialog bleibt die separate Auswahlfreigabe erhalten.

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

Die Quellenstatistik eines Backup-Jobs wird nach abgeschlossenen Backups aus Borgs Abschlusswerten aktualisiert. Eine manuelle Aktualisierung führt einen repositoryunabhängigen Live-Scan auf dem Quellgerät aus. Der bevorzugte Scanner berücksichtigt die Job-Ausschlussmuster sowie Cache-Tags, `nodump` und die konfigurierte Dateisystemgrenze; er erzeugt kein Archiv. Pfadbasierte Ausschlüsse werden vor `stat()` geprüft, sodass ausgeschlossene Dateien und Verzeichnisbäume möglichst ohne unnötige Metadatenabfragen übersprungen werden. Normale erfolgreiche Scans zeigen nur Herkunft und Zeitpunkt. Nicht sicher nachbildbare Sondermuster oder Lesefehler werden ausschließlich mit einer konkreten Einschränkungsursache angezeigt. Bei deaktivierter Option **Nur jeweiliges Quelldateisystem** werden auch eingehängte Unterverzeichnisse durchlaufen. Ist die Option aktiviert, werden erkannte Unter-Mounts wie bei Borg übersprungen und im Ausführungsprotokoll ausdrücklich aufgeführt. Nach einem abgeschlossenen Backup ersetzen Borgs exakte Abschlusswerte nach Anwendung der Ausschlüsse die Scanwerte. Der Archivbrowser liest Metadaten direkt über `borg list --json-lines`, zeigt Größe, Typ, Rechte, Besitzer/Gruppe und Änderungszeit und benötigt kein FUSE.

## Zwei-Faktor-Authentifizierung, Zugriffslog und externe Sperrwerkzeuge

Jeder Benutzer kann in der Seitenleiste unter **Profil → Zwei-Faktor-Authentifizierung** eine TOTP-Einrichtung starten. Das aktuelle Passwort wird erneut geprüft. BBM erzeugt lokal aus derselben `otpauth://`-URI einen QR-Code, der direkt mit einer Authenticator-App gescannt werden kann; alternativ bleiben Base32-Schlüssel und URI für die manuelle Einrichtung verfügbar. Es wird kein externer QR-Dienst kontaktiert. Anschließend bestätigt ein aktueller sechsstelliger Code die Aktivierung. Die zehn Codes erscheinen in einem ausdrücklich als **Wiederherstellungscodes** beschrifteten Bereich mit Hinweis, dass sie nur bei dieser Einrichtung vollständig sichtbar und jeweils einmal gültig sind. Sie müssen außerhalb des Managers sicher gespeichert werden.

Das persistente Zugriffslog liegt auf dem Host unter:

```text
${BBM_DATA_PATH}/logs/access.log
```

Bei Standardwerten:

```text
/docker_data/borgbackup-manager/data/logs/access.log
```

Ein Fail2ban-Filter unter `/etc/fail2ban/filter.d/borgbackup-manager.conf` kann so aussehen:

```ini
[Definition]
failregex = ^\{.*"event":"login_(?:failed|blocked)".*"remote_address":"<HOST>".*\}$
ignoreregex =
```

Beispiel für `/etc/fail2ban/jail.d/borgbackup-manager.local`:

```ini
[borgbackup-manager]
enabled = true
filter = borgbackup-manager
logpath = /docker_data/borgbackup-manager/data/logs/access.log
backend = auto
port = 8443
findtime = 5m
maxretry = 5
bantime = 15m
```

`port` und `logpath` müssen zur eigenen Installation passen. Vor dem Aktivieren testen:

```bash
sudo fail2ban-regex \
  /docker_data/borgbackup-manager/data/logs/access.log \
  /etc/fail2ban/filter.d/borgbackup-manager.conf
```

Für CrowdSec wird dieselbe Datei als benutzerdefinierte File-Acquisition eingebunden. Der benutzerdefinierte Parser muss die JSON-Felder auslesen, `remote_address` als `evt.Meta.source_ip` setzen und für `login_failed`/`login_blocked` einen eigenen `evt.Meta.log_type` vergeben. Das zugehörige Szenario kann diesen Logtyp mit einem `leaky`-Bucket auswerten. Die exakten Pfade und YAML-Schemata hängen von der installierten CrowdSec-Version ab; Parser und Szenario deshalb mit `cscli explain` und der CrowdSec-Konfigurationsprüfung testen, bevor ein Bouncer Firewall-Entscheidungen umsetzt.

Das Access-Log enthält keine Passwörter, TOTP-/Wiederherstellungscodes oder Sitzungstoken. Bei Reverse-Proxy-Betrieb muss `BBM_TRUSTED_PROXY_CIDRS` korrekt gesetzt sein, damit ausschließlich vertrauenswürdige Proxy-Adressen die tatsächliche Client-IP übermitteln dürfen.

## Manager-Datenbank warten

Unter **System → Systemdiagnose → Manager-Datenbank bereinigen** zuerst **Datenbank prüfen** ausführen. Die Vorschau nennt ausschließlich technisch veraltete oder verwaiste Einträge. **Sicher bereinigen** erstellt vor Änderungen eine geprüfte Kopie unter `/data/maintenance-backups`, korrigiert die angezeigten Zeilen und führt die SQLite-Optimierung durch. Während aktiver/wartender Läufe oder Manager-/Cache-Backups bleibt die Funktion gesperrt.
