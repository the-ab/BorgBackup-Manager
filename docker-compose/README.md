# BorgBackup Manager — `.env` for the GHCR deployment

This guide documents the `.env` configuration used together with the `compose.yaml` in this directory for a standalone deployment from the published container image.

```text
ghcr.io/the-ab/borgbackup-manager:latest
```

This installation mode does not require the project source tree or `install.sh`.

## Prepare the files

Copy the two required files into a dedicated deployment directory:

```bash
sudo mkdir -p /opt/borgbackup-manager
cd /opt/borgbackup-manager

sudo cp /path/BorgBackup-Manager/docker-compose/compose.yaml .
sudo cp /path/BorgBackup-Manager/docker-compose/.env.example .env
sudo chmod 600 .env
sudo editor .env
```

The `.env` file must remain next to `compose.yaml`. It is also mounted read-only into the container so that legacy installations can be migrated safely. Do not store unrelated secrets in it, and restrict read access to administrators.

## What must be configured?

### Required

| Variable | Example | Purpose |
|---|---|---|
| `BBM_REPOSITORY_PUBLIC_HOST` | `backup-manager.example.org` | DNS name or IP address through which backup devices reach the manager. Compose refuses to start without it. Do not include `https://`, a port, or a path. |

### Review before first start

| Variable | Default | Purpose |
|---|---:|---|
| `BBM_IMAGE_TAG` | `latest` | GHCR tag to deploy. Pin a release such as `v1.3.5` for reproducible installations. |
| `TZ` | `Europe/Berlin` | Time zone used by the Web UI, schedules, and Borg processes. Use a valid IANA time-zone name. |
| `BBM_HTTPS_PORT` | `8443` | HTTPS Web UI port published on the Docker host. |
| `BBM_REPOSITORY_SSH_PORT` | `2222` | SSH port published on the Docker host for Borg repository access. |
| `BBM_TLS_HOSTS` | Example host, `localhost`, `127.0.0.1` | Comma-separated DNS names and IP addresses for the TLS certificate generated on first start. Do not use spaces. |
| `BBM_DATA_PATH` | `/docker_data/borgbackup-manager/data` | Absolute host path for the database, settings, logs, security material, and manager backups. |
| `BBM_REPOSITORY_PATH` | `/docker_data/borgbackup-manager/repositories` | Absolute host path for managed Borg repositories and submounts. |
| `BBM_ARCHIVE_MOUNT_PATH` | `/docker_data/borgbackup-manager/archive-mounts` | Host path for read-only archive mounts enabled by default. |
| `BBM_BORG_UID` | `1000` | Numeric UID of the restricted `borg` user inside the container. It must match host or NFS permissions on the repository path. |
| `BBM_BORG_GID` | `1000` | Numeric GID of the restricted `borg` user inside the container. It must match host or NFS permissions on the repository path. |
| `BBM_SHOW_INITIAL_ADMIN_ON_START` | `1` | Writes the administrator name and temporary password exactly once to the container startup log on a genuine new installation. Set to `0` to disable automatic output. |

`BBM_DATA_PATH` and `BBM_REPOSITORY_PATH` must be different. The data path must not be inside the repository path. For NFS with `root_squash`, configure matching UID, GID, ACLs, and export permissions on the storage before starting the container.

## Image version

```dotenv
BBM_IMAGE_TAG=latest
```

`latest` follows the most recently published image. Prefer a fixed release for controlled deployments:

```dotenv
BBM_IMAGE_TAG=v1.3.5
```

This selects:

```text
ghcr.io/the-ab/borgbackup-manager:v1.3.5
```

## Network and TLS

### `TZ`

Sets the container time zone. Example:

```dotenv
TZ=Europe/Berlin
```

### `BBM_HTTPS_PORT`

Host port for the Web UI. The internal container port always remains `8443`.

```dotenv
BBM_HTTPS_PORT=8443
```

The Web UI is then available at:

```text
https://SERVER:8443
```

### `BBM_REPOSITORY_SSH_PORT`

Host port for the integrated repository SSH service. The internal container port always remains `2222`.

```dotenv
BBM_REPOSITORY_SSH_PORT=2222
```

The port must be reachable by backup devices and must not already be in use on the host.

### `BBM_REPOSITORY_PUBLIC_HOST`

Address embedded by the manager in repository access details and client configuration:

```dotenv
BBM_REPOSITORY_PUBLIC_HOST=backup-manager.example.org
```

Valid examples:

```dotenv
BBM_REPOSITORY_PUBLIC_HOST=192.0.2.10
BBM_REPOSITORY_PUBLIC_HOST=backup-manager.example.org
```

Do not use:

```dotenv
BBM_REPOSITORY_PUBLIC_HOST=https://backup-manager.example.org:8443/
```

### `BBM_TLS_HOSTS`

Comma-separated Subject Alternative Names for the certificate generated on first start:

```dotenv
BBM_TLS_HOSTS=backup-manager.example.org,localhost,127.0.0.1
```

Changing this variable later does not automatically replace a certificate already stored in encrypted form.

## Persistent host paths and permissions

### `BBM_DATA_PATH`

Stores persistent manager state, including:

```text
├── database
├── settings
├── security database and master key
├── run and system logs
├── manager backups
├── Borg cache
└── archive metadata cache
```

Example:

```dotenv
BBM_DATA_PATH=/docker_data/borgbackup-manager/data
```

### `BBM_REPOSITORY_PATH`

Mounted as `/repositories` inside the container:

```dotenv
BBM_REPOSITORY_PATH=/docker_data/borgbackup-manager/repositories
```

On first start, an empty directory created by Docker as `root` is initialized only at the mount root for `BBM_BORG_UID:BBM_BORG_GID`. Existing content is never recursively changed with `chown`.

### `BBM_ARCHIVE_MOUNT_PATH` and default FUSE support

Archive mounts are enabled by the normal `compose.yaml`. The host must provide `/dev/fuse`; no additional Compose file is required.

```dotenv
BBM_ARCHIVE_MOUNT_PATH=/docker_data/borgbackup-manager/archive-mounts
```

Prepare the host path for the configured Borg UID/GID:

```bash
sudo modprobe fuse
sudo mkdir -p /docker_data/borgbackup-manager/archive-mounts
sudo chown 1000:1000 /docker_data/borgbackup-manager/archive-mounts
sudo chmod 700 /docker_data/borgbackup-manager/archive-mounts

docker compose config
docker compose pull
docker compose up -d
```

The standard configuration uses `/dev/fuse`, `CAP_SYS_ADMIN`, an AppArmor allowance, and `rshared` mount propagation. These permissions require a trusted Docker host. Mounted archives appear below:

```text
BBM_ARCHIVE_MOUNT_PATH/
└── REPOSITORY-rID/
    └── ARCHIVE-HASH/
```

Mounts are read-only. This release supports the feature only for **locally managed repositories**; external SSH repositories are not mounted. At most one archive mount is allowed per repository. While it is active, backup, archive-cleanup, and compact runs for that repository wait; archive deletion and renaming are blocked. All active mounts are unmounted during a controlled container stop. After a hard stop, stale database rows are reconciled on the next start.

On the Docker host, FUSE access is intended for the numeric identity `BBM_BORG_UID:BBM_BORG_GID`. The host user accessing the files should therefore use the same UID; FUSE may reject access by other users.

`/data/exports` remains separate and is used only for temporary TAR.GZ downloads from the archive browser.

### `BBM_BORG_UID` and `BBM_BORG_GID`

Both values must be positive numeric IDs other than `0`:

```dotenv
BBM_BORG_UID=1000
BBM_BORG_GID=1000
```

Check them on the host:

```bash
id USERNAME
stat -c '%u:%g %A %n' /docker_data/borgbackup-manager/repositories
```

For a non-empty repository path, the configured user must be able to read, write, and traverse it. Correct ownership, group permissions, or ACLs on the host when necessary.

## Initial sign-in

### `BBM_SHOW_INITIAL_ADMIN_ON_START`

```dotenv
BBM_SHOW_INITIAL_ADMIN_ON_START=1
```

On a genuine new installation, the administrator name and temporary password are written exactly once to:

```bash
docker compose logs --tail=200 borg-manager
```

Change the password immediately after the first sign-in. Restrict Docker access and Docker logs to administrators.

Disable automatic output with:

```dotenv
BBM_SHOW_INITIAL_ADMIN_ON_START=0
```

Until the first password change, display the credentials explicitly with:

```bash
docker compose exec -T borg-manager python -m app.initial_admin
```

## Sessions, cookies, and reverse proxies

### `BBM_SESSION_TTL_SECONDS`

Absolute maximum session lifetime in seconds. Minimum: `300`.

```dotenv
BBM_SESSION_TTL_SECONDS=86400
```

### `BBM_SESSION_IDLE_TIMEOUT_SECONDS`

Signs the user out after inactivity. The value must be at least `60` seconds and no greater than `BBM_SESSION_TTL_SECONDS`.

```dotenv
BBM_SESSION_IDLE_TIMEOUT_SECONDS=3600
```

This is the initial value for a new installation and can later be changed in the Web UI.

### `BBM_SESSION_COOKIE_NAME`

Browser session cookie name:

```dotenv
BBM_SESSION_COOKIE_NAME=bbm_session_v2
```

Change it only when multiple independent manager installations share the same domain and need distinct cookie names.

### `BBM_SESSION_COOKIE_SECURE`

Valid values:

```text
always   send the cookie only over HTTPS; recommended default
auto     derive the behavior from the detected connection
never    disable the Secure attribute; use only for a deliberately verified exception
```

Recommended:

```dotenv
BBM_SESSION_COOKIE_SECURE=always
```

### `BBM_TRUSTED_PROXY_CIDRS`

`Forwarded` and `X-Forwarded-*` headers are accepted only from these networks:

```dotenv
BBM_TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128
```

When using a reverse proxy, explicitly add its real Docker or host network. Do not trust broad networks unless they are required.

## Login limits and security events

All values below must be positive integers.

| Variable | Default | Purpose |
|---|---:|---|
| `BBM_LOGIN_RATE_WINDOW_SECONDS` | `300` | Window used to evaluate failed sign-ins. |
| `BBM_LOGIN_RATE_BLOCK_SECONDS` | `900` | Duration of a temporary sign-in block. |
| `BBM_LOGIN_RATE_MAX_PER_IP` | `20` | Maximum failures per source IP during the window. |
| `BBM_LOGIN_RATE_MAX_PER_IP_USER` | `5` | Maximum failures per source-IP and user combination. |
| `BBM_SECURITY_EVENT_RETENTION_DAYS` | `90` | Retention period for security events. |
| `BBM_SECURITY_EVENT_MAX_ROWS` | `10000` | Maximum number of stored security events. |

The defaults are intended for normal installations and should be changed only for a specific operational reason.

## Manager backup and restore limits

These values limit uploaded backup files and extracted content, protecting the manager from oversized or highly compressed archives. Sizes are specified in bytes, and every value must be greater than `0`.

### Manager configuration backup

| Variable | Default | Purpose |
|---|---:|---|
| `BBM_BACKUP_MAX_FILE_BYTES` | `268435456` | Maximum uploaded backup file size: 256 MiB. |
| `BBM_BACKUP_MAX_UNCOMPRESSED_BYTES` | `1073741824` | Maximum total extracted size: 1 GiB. |
| `BBM_BACKUP_MAX_ENTRIES` | `5000` | Maximum number of archive entries. |
| `BBM_BACKUP_MAX_COMPRESSION_RATIO` | `250` | Maximum ratio between extracted and compressed size. |

### Borg cache backup

| Variable | Default | Purpose |
|---|---:|---|
| `BBM_BACKUP_CACHE_MAX_FILE_BYTES` | `34359738368` | Maximum cache-backup file size: 32 GiB. |
| `BBM_BACKUP_CACHE_MAX_UNCOMPRESSED_BYTES` | `137438953472` | Maximum total extracted size: 128 GiB. |
| `BBM_BACKUP_CACHE_MAX_ENTRIES` | `250000` | Maximum number of archive entries. |
| `BBM_BACKUP_CACHE_MAX_COMPRESSION_RATIO` | `5000` | Maximum compression ratio. |

### `BBM_COMMAND_TIMEOUT`

Maximum runtime of a single Borg or system command in seconds:

```dotenv
BBM_COMMAND_TIMEOUT=86400
```

The value must be positive. Long-running backups may require a correspondingly high limit.

## Initial Web UI settings

These variables provide defaults for a new `settings.json`. Values saved later through the Web UI take precedence.

| Variable | Default | Valid values / purpose |
|---|---:|---|
| `BBM_APPEARANCE` | `auto` | `auto`, `light`, or `dark`. |
| `BBM_REPOSITORY_SIZE_AFTER_RUN` | `1` | `1` enables repository-size calculation after runs; `0` disables it. |
| `BBM_MAX_PARALLEL_RUNS` | `0` | Global parallel-run limit; `0` means unlimited, valid range `0` to `64`. |
| `BBM_SOURCE_STATS_PARALLEL_LIMIT` | `1` | Parallel source-statistics scans, valid range `1` to `64`. |
| `BBM_STORAGE_GUARD_ENABLED` | `1` | Enable (`1`) or disable (`0`) the default storage guard. |
| `BBM_STORAGE_GUARD_THRESHOLD_PERCENT` | `95` | Storage-use threshold, valid range `1` to `100`. |

## Access and authentication log

### `BBM_ACCESS_LOG_PATH`

Internal container path of the machine-readable JSON Lines access log:

```dotenv
BBM_ACCESS_LOG_PATH=/data/logs/access.log
```

The default is below persistent `BBM_DATA_PATH` and normally appears on the host as `${BBM_DATA_PATH}/logs/access.log`. It contains HTTP access plus successful, failed and rate-limited sign-ins. Passwords, 2FA values, recovery codes and session tokens are never stored. Fail2ban or CrowdSec can consume the `login_failed` and `login_blocked` events. Change this path only if it remains inside a persistent directory readable exclusively by administrators.

## Readiness and log rotation

### `BBM_HEALTH_REQUIRE_SSHD`

```dotenv
BBM_HEALTH_REQUIRE_SSHD=1
```

With `1`, the container is ready only when both the Web application and the internal repository SSH service are running. `0` relaxes this check.

### `BBM_LOG_MAX_BYTES`

Maximum size of an access, repository-SSH or error log before rotation:

```dotenv
BBM_LOG_MAX_BYTES=10485760
```

The default is 10 MiB.

### `BBM_LOG_ROTATIONS`

Number of rotated logs to retain:

```dotenv
BBM_LOG_ROTATIONS=5
```

The value must be at least `1`.

## Migrating old TLS files

The commented variables are needed only when an old installation still has certificate files inside the container data path:

```dotenv
# BBM_TLS_CERT_FILE=/data/tls/fullchain.pem
# BBM_TLS_KEY_FILE=/data/tls/privkey.pem
```

Do not enable them for current new installations. The certificate and private key are managed in the encrypted security database.

## Start and verify

```bash
cd /opt/borgbackup-manager
docker compose config
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail=200 borg-manager
```

Web UI:

```text
https://SERVER:BBM_HTTPS_PORT
```

## Apply `.env` changes

After changing `.env`:

```bash
cd /opt/borgbackup-manager
docker compose up -d
```

After changing the image tag, also pull the image:

```bash
docker compose pull
docker compose up -d
```

Persistent state, repositories, and archive mount paths remain in the host directories configured by `BBM_DATA_PATH`, `BBM_REPOSITORY_PATH`, and `BBM_ARCHIVE_MOUNT_PATH`. All later `pull`, `up`, `stop`, and `down` commands use only the normal `compose.yaml`.
