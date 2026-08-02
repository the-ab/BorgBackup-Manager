# BorgBackup Manager – `.env` für die GHCR-Installation

Diese Anleitung beschreibt die Konfiguration der Datei `.env`, die zusammen mit `compose.yaml` aus diesem Ordner für eine eigenständige Installation über das veröffentlichte Container-Image verwendet wird.

```text
ghcr.io/the-ab/borgbackup-manager:latest
```

Für diesen Installationsweg werden weder der Projektquellcode noch `install.sh` benötigt.

## Dateien vorbereiten

Kopiere die beiden benötigten Dateien in ein eigenes Installationsverzeichnis:

```bash
sudo mkdir -p /opt/borgbackup-manager
cd /opt/borgbackup-manager

sudo cp /pfad/BorgBackup-Manager/docker-compose/compose.yaml .
sudo cp /pfad/BorgBackup-Manager/docker-compose/.env.example .env
sudo chmod 600 .env
sudo nano .env
```

Die Datei `.env` muss im selben Verzeichnis wie `compose.yaml` liegen. Sie wird außerdem schreibgeschützt in den Container eingebunden, damit vorhandene Altinstallationen sicher migriert werden können. Deshalb darf sie keine unnötigen Geheimnisse enthalten und sollte nur für Administratoren lesbar sein.

## Was muss eingestellt werden?

### Zwingend erforderlich

| Variable | Beispiel | Bedeutung |
|---|---|---|
| `BBM_REPOSITORY_PUBLIC_HOST` | `backup-manager.example.org` | DNS-Name oder IP-Adresse, unter der Backup-Geräte den Manager erreichen. Ohne diesen Wert startet Compose nicht. Kein `https://`, kein Port und kein Pfad eintragen. |

### Vor dem ersten Start prüfen

| Variable | Standard | Bedeutung |
|---|---:|---|
| `BBM_IMAGE_TAG` | `latest` | Zu verwendender GHCR-Tag. Für reproduzierbare Installationen wird ein fester Tag wie `v1.3.8` empfohlen. |
| `TZ` | `Europe/Berlin` | Zeitzone für WebUI, Zeitpläne und Borg-Läufe. Einen gültigen IANA-Zeitzonennamen verwenden. |
| `BBM_HTTPS_PORT` | `8443` | Auf dem Docker-Host veröffentlichter HTTPS-Port der WebUI. |
| `BBM_REPOSITORY_SSH_PORT` | `2222` | Auf dem Docker-Host veröffentlichter SSH-Port für Borg-Repository-Zugriffe. |
| `BBM_TLS_HOSTS` | Beispielhost, `localhost`, `127.0.0.1` | Kommagetrennte DNS-Namen und IP-Adressen für das beim ersten Start erzeugte TLS-Zertifikat. Keine Leerzeichen verwenden. |
| `BBM_DATA_PATH` | `/docker_data/borgbackup-manager/data` | Absoluter Hostpfad für Datenbank, Einstellungen, Protokolle, Schlüsselmaterial und Manager-Backups. |
| `BBM_REPOSITORY_PATH` | `/docker_data/borgbackup-manager/repositories` | Absoluter Hostpfad für lokal verwaltete Borg-Repositorys und dort eingehängte Unterverzeichnisse. |
| `BBM_ARCHIVE_MOUNT_PATH` | `/docker_data/borgbackup-manager/archive-mounts` | Hostpfad für die standardmäßig aktivierten schreibgeschützten Archiv-Mounts. |
| `BBM_BORG_UID` | `1000` | Numerische UID des eingeschränkten Benutzers `borg` im Container. Sie muss zu den Host-/NFS-Rechten des Repository-Pfads passen. |
| `BBM_BORG_GID` | `1000` | Numerische GID des eingeschränkten Benutzers `borg` im Container. Sie muss zu den Host-/NFS-Rechten des Repository-Pfads passen. |
| `BBM_SHOW_INITIAL_ADMIN_ON_START` | `1` | Gibt bei einer echten Neuinstallation Benutzername und temporäres Passwort genau einmal im Container-Startprotokoll aus. `0` deaktiviert die automatische Ausgabe. |

`BBM_DATA_PATH` und `BBM_REPOSITORY_PATH` müssen verschieden sein. Der Datenpfad darf nicht innerhalb des Repository-Pfads liegen. Bei NFS mit `root_squash` müssen UID, GID, ACLs und Exportrechte bereits auf dem Storage passend gesetzt sein.

## Image-Version

```dotenv
BBM_IMAGE_TAG=latest
```

`latest` folgt dem jeweils zuletzt veröffentlichten Image. Für kontrollierte Updates besser eine feste Version verwenden:

```dotenv
BBM_IMAGE_TAG=v1.3.8
```

Das daraus verwendete Image lautet:

```text
ghcr.io/the-ab/borgbackup-manager:v1.3.8
```

## Netzwerk und TLS

### `TZ`

Legt die Zeitzone des Containers fest. Beispiele:

```dotenv
TZ=Europe/Berlin
```

### `BBM_HTTPS_PORT`

Hostport der WebUI. Der interne Container-Port bleibt immer `8443`.

```dotenv
BBM_HTTPS_PORT=8443
```

Die WebUI ist danach erreichbar unter:

```text
https://SERVER:8443
```

### `BBM_REPOSITORY_SSH_PORT`

Hostport des integrierten Repository-SSH-Dienstes. Der interne Container-Port bleibt immer `2222`.

```dotenv
BBM_REPOSITORY_SSH_PORT=2222
```

Der Port muss von den Backup-Geräten erreichbar sein und darf auf dem Host nicht bereits belegt sein.

### `BBM_REPOSITORY_PUBLIC_HOST`

Adresse, die der Manager in Repository-Zugangsdaten und Client-Konfigurationen verwendet.

```dotenv
BBM_REPOSITORY_PUBLIC_HOST=backup-manager.example.org
```

Gültig sind beispielsweise:

```dotenv
BBM_REPOSITORY_PUBLIC_HOST=192.0.2.10
BBM_REPOSITORY_PUBLIC_HOST=backup-manager.example.org
```

Nicht eintragen:

```dotenv
BBM_REPOSITORY_PUBLIC_HOST=https://backup-manager.example.org:8443/
```

### `BBM_TLS_HOSTS`

Kommagetrennte Subject-Alternative-Names für das beim ersten Start automatisch erzeugte Zertifikat:

```dotenv
BBM_TLS_HOSTS=backup-manager.example.org,localhost,127.0.0.1
```

Ein bereits verschlüsselt gespeichertes Zertifikat wird durch eine spätere Änderung dieser Variable nicht automatisch ersetzt.

## Persistente Hostpfade und Rechte

### `BBM_DATA_PATH`

Enthält den persistenten Manager-Zustand, unter anderem:

```text
├── Datenbank
├── Einstellungen
├── Sicherheitsdatenbank und Master-Key
├── Ausführungs- und Systemprotokolle
├── Manager-Backups
├── Borg-Cache
└── Archiv-Metadaten-Cache
```

Beispiel:

```dotenv
BBM_DATA_PATH=/docker_data/borgbackup-manager/data
```

### `BBM_REPOSITORY_PATH`

Wird im Container als `/repositories` eingebunden:

```dotenv
BBM_REPOSITORY_PATH=/docker_data/borgbackup-manager/repositories
```

Ein frisches, leeres und von Docker als `root` angelegtes Verzeichnis wird beim ersten Start nur am Mount-Stamm für `BBM_BORG_UID:BBM_BORG_GID` initialisiert. Vorhandene Inhalte werden niemals automatisch rekursiv per `chown` verändert.

### `BBM_ARCHIVE_MOUNT_PATH` und standardmäßige FUSE-Funktion

Archiv-Mounts sind in der normalen `compose.yaml` aktiviert. Der Host muss `/dev/fuse` bereitstellen; eine zusätzliche Compose-Datei ist nicht erforderlich.

```dotenv
BBM_ARCHIVE_MOUNT_PATH=/docker_data/borgbackup-manager/archive-mounts
```

Hostpfad für die konfigurierte Borg-UID/GID vorbereiten:

```bash
sudo modprobe fuse
sudo mkdir -p /docker_data/borgbackup-manager/archive-mounts
sudo chown 1000:1000 /docker_data/borgbackup-manager/archive-mounts
sudo chmod 700 /docker_data/borgbackup-manager/archive-mounts

docker compose config
docker compose pull
docker compose up -d
```

Die Standardkonfiguration verwendet `/dev/fuse`, `CAP_SYS_ADMIN`, eine AppArmor-Freigabe und `rshared`-Mount-Propagation. Diese Rechte setzen einen vertrauenswürdigen Docker-Host voraus. Eingehängte Archive erscheinen unter:

```text
BBM_ARCHIVE_MOUNT_PATH/
└── REPOSITORY-rID/
    └── ARCHIV-HASH/
```

Mounts sind schreibgeschützt. Die Funktion unterstützt in dieser Version ausschließlich **lokal verwaltete Repositories** des Managers; externe SSH-Repositories werden nicht eingehängt. Pro Repository ist höchstens ein aktiver Archiv-Mount zulässig. Solange er aktiv ist, warten Backup-Läufe, Archivbereinigung und Compact dieses Repositorys; Archivlöschung und Umbenennung werden blockiert. Beim kontrollierten Containerstopp werden alle aktiven Mounts ausgehängt. Nach einem harten Abbruch bereinigt der Manager beim nächsten Start verwaiste Datenbankeinträge.

Auf dem Docker-Host ist der FUSE-Inhalt für die numerische Identität `BBM_BORG_UID:BBM_BORG_GID` bestimmt. Der zugreifende Hostbenutzer sollte deshalb dieselbe UID besitzen; Zugriffe anderer Benutzer können durch FUSE verweigert werden.

`/data/exports` bleibt davon getrennt und dient weiterhin ausschließlich temporären TAR.GZ-Downloads aus dem Archivbrowser.

### `BBM_BORG_UID` und `BBM_BORG_GID`

Beide Werte müssen positive numerische IDs ungleich `0` sein:

```dotenv
BBM_BORG_UID=1000
BBM_BORG_GID=1000
```

Prüfung auf dem Host:

```bash
id BENUTZERNAME
stat -c '%u:%g %A %n' /docker_data/borgbackup-manager/repositories
```

Bei einem nicht leeren Repository-Pfad muss der konfigurierte Benutzer dort lesen, schreiben und Verzeichnisse betreten können. Eigentümer, Gruppenrechte oder ACLs sind dann auf dem Host zu korrigieren.

## Erstanmeldung

### `BBM_SHOW_INITIAL_ADMIN_ON_START`

```dotenv
BBM_SHOW_INITIAL_ADMIN_ON_START=1
```

Bei einer echten Neuinstallation erscheinen Benutzername und temporäres Passwort genau einmal in:

```bash
docker compose logs --tail=200 borg-manager
```

Das Passwort unmittelbar nach der ersten Anmeldung ändern. Docker-Zugriff und Docker-Protokolle dürfen nur Administratoren zugänglich sein.

Automatische Ausgabe deaktivieren:

```dotenv
BBM_SHOW_INITIAL_ADMIN_ON_START=0
```

Die Zugangsdaten können bis zum ersten Passwortwechsel gezielt abgerufen werden:

```bash
docker compose exec -T borg-manager python -m app.initial_admin
```

## Sitzungen, Cookies und Reverse Proxy

### `BBM_SESSION_TTL_SECONDS`

Absolute maximale Sitzungsdauer in Sekunden. Mindestwert: `300`.

```dotenv
BBM_SESSION_TTL_SECONDS=86400
```

### `BBM_SESSION_IDLE_TIMEOUT_SECONDS`

Abmeldung nach Inaktivität. Gültig sind mindestens `60` Sekunden und höchstens der Wert von `BBM_SESSION_TTL_SECONDS`.

```dotenv
BBM_SESSION_IDLE_TIMEOUT_SECONDS=3600
```

Der Wert dient als Standard für eine neue Installation und kann später in der WebUI geändert werden.

### `BBM_SESSION_COOKIE_NAME`

Name des Browser-Sitzungscookies:

```dotenv
BBM_SESSION_COOKIE_NAME=bbm_session_v2
```

Nur ändern, wenn auf derselben Domain mehrere getrennte Manager-Installationen betrieben werden und Cookie-Namenskonflikte vermieden werden müssen.

### `BBM_SESSION_COOKIE_SECURE`

Gültige Werte:

```text
always   Cookie ausschließlich über HTTPS senden; empfohlener Standard
auto     Verhalten anhand der erkannten Verbindung bestimmen
never    Secure-Attribut abschalten; nur für ausdrücklich geprüfte Sonderfälle
```

Empfohlen:

```dotenv
BBM_SESSION_COOKIE_SECURE=always
```

### `BBM_TRUSTED_PROXY_CIDRS`

Nur von diesen Netzen werden `Forwarded`- und `X-Forwarded-*`-Header akzeptiert:

```dotenv
BBM_TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128
```

Bei einem Reverse Proxy dessen tatsächliches Docker-/Hostnetz explizit ergänzen. Keine pauschalen Netze eintragen, wenn sie nicht benötigt werden.

## Anmeldebegrenzung und Sicherheitsereignisse

Alle folgenden Werte müssen positive Ganzzahlen sein.

| Variable | Standard | Bedeutung |
|---|---:|---|
| `BBM_LOGIN_RATE_WINDOW_SECONDS` | `300` | Zeitfenster für die Bewertung fehlgeschlagener Anmeldungen. |
| `BBM_LOGIN_RATE_BLOCK_SECONDS` | `900` | Dauer einer temporären Anmeldesperre. |
| `BBM_LOGIN_RATE_MAX_PER_IP` | `20` | Maximale Fehlversuche pro Quell-IP im Zeitfenster. |
| `BBM_LOGIN_RATE_MAX_PER_IP_USER` | `5` | Maximale Fehlversuche pro Kombination aus Quell-IP und Benutzer. |
| `BBM_SECURITY_EVENT_RETENTION_DAYS` | `90` | Aufbewahrungsdauer der Sicherheitsereignisse. |
| `BBM_SECURITY_EVENT_MAX_ROWS` | `10000` | Maximale Anzahl gespeicherter Sicherheitsereignisse. |

Die Standardwerte sind für normale Installationen vorgesehen und sollten nur bei einem konkreten betrieblichen Grund verändert werden.

## Grenzen für Manager-Backups und Restore

Die Werte begrenzen hochgeladene Backup-Dateien sowie entpackte Inhalte und schützen vor übergroßen oder stark komprimierten Archiven. Größenangaben erfolgen in Bytes, alle Werte müssen größer als `0` sein.

### Manager-Konfigurationsbackup

| Variable | Standard | Bedeutung |
|---|---:|---|
| `BBM_BACKUP_MAX_FILE_BYTES` | `268435456` | Maximale Größe der hochgeladenen Backup-Datei: 256 MiB. |
| `BBM_BACKUP_MAX_UNCOMPRESSED_BYTES` | `1073741824` | Maximale entpackte Gesamtgröße: 1 GiB. |
| `BBM_BACKUP_MAX_ENTRIES` | `5000` | Maximale Zahl der Archiveinträge. |
| `BBM_BACKUP_MAX_COMPRESSION_RATIO` | `250` | Maximales Verhältnis zwischen entpackter und komprimierter Größe. |

### Borg-Cache-Backup

| Variable | Standard | Bedeutung |
|---|---:|---|
| `BBM_BACKUP_CACHE_MAX_FILE_BYTES` | `34359738368` | Maximale Größe der Cache-Backup-Datei: 32 GiB. |
| `BBM_BACKUP_CACHE_MAX_UNCOMPRESSED_BYTES` | `137438953472` | Maximale entpackte Gesamtgröße: 128 GiB. |
| `BBM_BACKUP_CACHE_MAX_ENTRIES` | `250000` | Maximale Zahl der Archiveinträge. |
| `BBM_BACKUP_CACHE_MAX_COMPRESSION_RATIO` | `5000` | Maximales Kompressionsverhältnis. |

### `BBM_COMMAND_TIMEOUT`

Maximale Laufzeit eines einzelnen Borg-/Systembefehls in Sekunden:

```dotenv
BBM_COMMAND_TIMEOUT=86400
```

Der Wert muss positiv sein. Lange Backups benötigen gegebenenfalls einen entsprechend hohen Wert.

## Standardwerte für neue WebUI-Einstellungen

Diese Variablen erzeugen die Anfangswerte einer neuen `settings.json`. Danach in der WebUI gespeicherte Werte haben Vorrang.

| Variable | Standard | Gültige Werte / Bedeutung |
|---|---:|---|
| `BBM_APPEARANCE` | `auto` | `auto`, `light` oder `dark`. |
| `BBM_REPOSITORY_SIZE_AFTER_RUN` | `1` | `1` aktiviert die automatische Repository-Größenberechnung nach Läufen, `0` deaktiviert sie. |
| `BBM_MAX_PARALLEL_RUNS` | `0` | Globale parallele Läufe; `0` bedeutet unbegrenzt, gültig `0` bis `64`. |
| `BBM_SOURCE_STATS_PARALLEL_LIMIT` | `1` | Parallele Quellenstatistik-Scans, gültig `1` bis `64`. |
| `BBM_STORAGE_GUARD_ENABLED` | `1` | Speicherplatz-Sperre standardmäßig aktivieren (`1`) oder deaktivieren (`0`). |
| `BBM_STORAGE_GUARD_THRESHOLD_PERCENT` | `95` | Sperrgrenze der Speichernutzung, gültig `1` bis `100`. |

## Zugriffs- und Authentifizierungslog

### `BBM_ACCESS_LOG_PATH`

Interner Containerpfad des maschinenlesbaren JSON-Lines-Zugriffslogs:

```dotenv
BBM_ACCESS_LOG_PATH=/data/logs/access.log
```

Der Standard liegt im persistenten `BBM_DATA_PATH` und ist auf dem Host normalerweise unter `${BBM_DATA_PATH}/logs/access.log` erreichbar. Das Log enthält HTTP-Zugriffe sowie erfolgreiche, fehlgeschlagene und blockierte Anmeldungen. Passwörter, 2FA-Codes, Wiederherstellungscodes und Sitzungstoken werden nicht gespeichert. Fail2ban oder CrowdSec können insbesondere die Ereignisse `login_failed` und `login_blocked` auswerten. Der Pfad sollte nur geändert werden, wenn er weiterhin innerhalb eines persistent eingebundenen und nur für Administratoren lesbaren Verzeichnisses liegt.

## Bereitschaftsprüfung und Protokollrotation

### `BBM_HEALTH_REQUIRE_SSHD`

```dotenv
BBM_HEALTH_REQUIRE_SSHD=1
```

Bei `1` gilt der Container nur dann als bereit, wenn neben der Webanwendung auch der interne Repository-SSH-Dienst läuft. `0` lockert diese Prüfung.

### `BBM_LOG_MAX_BYTES`

Maximale Größe eines Zugriffs-, Repository-SSH- oder Fehlerprotokolls vor der Rotation:

```dotenv
BBM_LOG_MAX_BYTES=10485760
```

Der Standard entspricht 10 MiB.

### `BBM_LOG_ROTATIONS`

Anzahl aufzubewahrender rotierter Protokolle:

```dotenv
BBM_LOG_ROTATIONS=5
```

Der Wert muss mindestens `1` sein.

## Alte TLS-Dateien migrieren

Die auskommentierten Variablen werden nur benötigt, wenn eine alte Installation noch Zertifikatsdateien im Container-Datenpfad besitzt:

```dotenv
# BBM_TLS_CERT_FILE=/data/tls/fullchain.pem
# BBM_TLS_KEY_FILE=/data/tls/privkey.pem
```

Bei aktuellen Neuinstallationen nicht aktivieren. Zertifikat und privater Schlüssel werden verschlüsselt in der Sicherheitsdatenbank verwaltet.

## Start und Kontrolle

```bash
cd /opt/borgbackup-manager
docker compose config
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail=200 borg-manager
```

WebUI:

```text
https://SERVER:BBM_HTTPS_PORT
```

## Änderungen an `.env` übernehmen

Nach einer Änderung:

```bash
cd /opt/borgbackup-manager
docker compose up -d
```

Bei einem geänderten Image-Tag zusätzlich:

```bash
docker compose pull
docker compose up -d
```

Persistente Daten, Repositorys und Archiv-Mount-Pfade bleiben in den über `BBM_DATA_PATH`, `BBM_REPOSITORY_PATH` und `BBM_ARCHIVE_MOUNT_PATH` eingebundenen Hostverzeichnissen erhalten. Alle späteren `pull`, `up`, `stop` und `down`-Befehle verwenden nur die normale `compose.yaml`.
