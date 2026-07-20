# Installation and Operations — BorgBackup Manager 1.0.54

German instructions are available in [`INSTALLATION.de.md`](INSTALLATION.de.md).

## 1. Manager host requirements

Recommended:

- Debian or Ubuntu Docker host,
- Docker Engine,
- Docker Compose v2,
- reachable TCP ports 8443 and 2222,
- persistent local storage or a suitable mounted filesystem for managed repositories,
- correct system time and timezone.

The container is based on Debian 13 Trixie and includes Borg 1.4.x.

## 2. Extract the release

The ZIP filename contains the version while the directory inside does not:

```text
BorgBackup-Manager-1.0.54.zip
`-- BorgBackup-Manager/
```

Install under `/opt`:

```bash
cd /opt
unzip /path/BorgBackup-Manager-1.0.54.zip
cd BorgBackup-Manager
chmod +x install.sh update.sh recovery.sh restore-backup.sh
```

Verify the checksum before installation:

```bash
sha256sum -c /path/BorgBackup-Manager-1.0.54.zip.sha256
```

## 3. Guided installation

Run:

```bash
cd /opt/BorgBackup-Manager
bash install.sh
```

The installer:

1. checks Docker and Docker Compose,
2. asks for public hostnames, ports and persistent paths,
3. creates or updates `.env`,
4. validates paths, ports, booleans, timeouts and timezone,
5. creates persistent directories,
6. builds `borgbackup-manager:latest`,
7. starts the container,
8. waits for readiness.

Default values:

```text
HTTPS port:             8443
Repository SSH port:    2222
Application data:       /docker_data/borgbackup-manager/data
Managed repositories:   /docker_data/borgbackup-manager/repositories
Timezone:               Europe/Berlin
Container:              borgbackup-manager
Hostname:               bbm
```

The data and repository paths must be absolute and must not be identical. Avoid placing the data directory inside the repository directory or vice versa.

### Non-interactive configuration

For automated deployments, set the relevant environment variables and use:

```bash
BBM_INSTALL_NONINTERACTIVE=1 bash install.sh
```

To create or validate configuration without starting the stack:

```bash
bash install.sh --config-only
```

## 4. `.env` configuration

The guided installer writes a complete `.env`. Supported host variables include:

```dotenv
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
BBM_MAX_PARALLEL_RUNS=0
BBM_STORAGE_GUARD_ENABLED=1
BBM_STORAGE_GUARD_THRESHOLD_PERCENT=95
BBM_HEALTH_REQUIRE_SSHD=1
BBM_LOG_MAX_BYTES=10485760
BBM_LOG_ROTATIONS=5
BBM_DEBUG_LOG_LEVEL=WARNING
```

### Reverse proxy

The Web UI itself always serves HTTPS. When a reverse proxy is used, add only the proxy's actual address or network to `BBM_TRUSTED_PROXY_CIDRS`:

```dotenv
BBM_TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128,172.20.0.0/16
```

Do not add broad untrusted networks. Uvicorn starts with proxy-header processing disabled; the application performs its own trust validation.

### TLS hosts

`BBM_TLS_HOSTS` is used when the manager initially creates its self-signed TLS certificate. Changing the variable does not silently replace an already encrypted certificate.

## 5. Start and verify

```bash
cd /opt/BorgBackup-Manager
docker compose up -d --build
docker compose ps
docker compose logs --tail=200 borg-manager
```

Readiness:

```bash
curl -k https://127.0.0.1:8443/api/ready
curl -k -I https://127.0.0.1:8443/api/health/strict
```

Open:

```text
https://MANAGER:8443
```

## 6. Initial administrator

Display the generated one-time credentials locally:

```bash
cd /opt/BorgBackup-Manager
docker compose exec -T borg-manager python -m app.initial_admin
```

Sign in and replace the temporary password immediately. The bootstrap secret is deleted after the mandatory password change.

## 7. Prepare a source device

Requirements on every source/restore device:

- supported Borg 1.x,
- OpenSSH server,
- an SSH account able to read the configured source paths,
- outbound access to the selected repository,
- Python 3 recommended for the best supervised SIGINT cancellation behavior.

The remote wrapper also works on minimal systems without GNU `env` and without Python 3. On such systems it uses a safe TERM-based fallback for cancellation.

Install Borg, for example:

```bash
apt update
apt install borgbackup openssh-server
borg --version
```

## 8. Add a device

In **Infrastructure -> Devices**:

1. copy the controller public key,
2. install it in the selected device account's `authorized_keys`,
3. enter name, address, SSH user and port,
4. scan and verify the SSH host fingerprint,
5. save the device,
6. run the Borg/connectivity check.

Do not accept an unverified host-key change. Compare the fingerprint through a trusted channel.

Disabling a device automatically disables all active backup jobs assigned to it. Re-enabling the device does not re-enable those jobs automatically.

## 9. Create or attach a repository

### Managed repository

In **Repositories**:

1. add a repository with managed storage,
2. choose its relative storage name,
3. select encryption,
4. initialize it,
5. assign device access as required,
6. test the connection.

Managed repositories are stored under `BBM_REPOSITORY_PATH` and exposed through the integrated SSH service on port 2222.

Use a firewall to allow port 2222 only from known source devices.

### External repository

Provide the Borg repository URL, SSH identity and verified host key. Examples:

```text
ssh://backup@example.org:22/./srv/borg/repository
backup@example.org:/srv/borg/repository
```

Configure a passphrase or keyfile when required. Secrets are encrypted in the manager security database.

### Import an existing repository

Use the repository import/attach workflow and test access before assigning production jobs. The manager does not create archives during import.

### Deleted managed repository

When the repository directory was deleted outside the manager, the UI reports **Repository missing**. Use **Reset** only when the managed target directory exists and is completely empty. The action clears stale manager initialization metadata and never deletes repository data. Then initialize the repository again.

### Repository IDs and caches

The repository table shows the numerical manager ID. Repository-specific caches use that ID:

```text
Manager:       /data/borg-cache/repository-ID
Source device: $HOME/.cache/borgbackup-manager/repository-ID
```

A path below `/root/.cache/...` refers to the local cache of the SSH user `root` on the source device, not to the repository itself.

## 10. Configure exclusion templates

Create reusable templates in the central exclusion section. Assign one or more templates to jobs and add job-specific patterns where needed.

Typical exclusions:

```text
/proc
/sys
/dev
/run
/tmp
/var/tmp
/mnt
/media
/lost+found
```

Do not exclude application data blindly. Databases generally need dumps, snapshots or application-native backup procedures.

## 11. Create a backup job

In **Backup Jobs** select:

- device,
- repository,
- one or more source paths,
- exclusion templates/patterns,
- archive prefix,
- compression,
- filesystem and create options,
- retention policy.

Save the job and run its access checks before the first backup.

### Source statistics

The dashboard presents source size/file count on one compact row and the value origin/timestamp directly below. Latest-run metadata and deduplicated/original/compressed sizes use the same compact stacked layout without increasing the table width.


The job overview shows source size and entry count.

- A completed backup stores exact Borg statistics automatically.
- **Refresh** performs a read-only live scan on the source device without creating an archive.
- The live scan is marked **before exclusions** because Borg 1.x does not provide useful create statistics for a dry run with the same semantics.
- Relevant job changes invalidate old statistics.

### Enable and disable

Use **More -> Manage -> Enable/Disable**. A disabled job cannot be started manually or by a schedule. The manager prevents disabling while an execution is running or queued.

## 12. Create schedules

Schedules can target:

- selected backup jobs,
- all jobs of selected devices,
- all jobs assigned to a repository.

A job may belong to only one active schedule. Configure multiple times inside that single schedule when required.

### Parallelism

The repository lock always permits only one write/administration operation per physical repository. In addition, configure:

- **System -> Settings -> Global maximum parallel executions**,
- **Maximum parallel executions** inside each schedule.

Set a schedule limit to `1` to serialize jobs across different repositories when concurrent jobs would overload CPU, storage or network links.

## 13. Run and monitor backups

Start a job from the dashboard or job list. Open the live log from the task indicator or execution list.

Queue reasons are displayed explicitly:

- repository busy,
- global limit reached,
- schedule limit reached,
- waiting for an older FIFO repository operation.

A controlled cancellation first signals the remote Borg process group and waits for confirmed termination. The manager does not automatically execute `borg break-lock`.

## 14. Warnings and failures

Borg warning causes are captured while output is streaming and stored separately from the truncated log preview. The UI can identify changed files, missing files, permission errors, I/O errors and general Borg warnings.

If Borg emits only return code 1 without a detailed warning line, the execution states that the cause was not emitted rather than inventing one.

## 15. Archive overview

Use **Archives** to:

- load or refresh archives,
- filter by device,
- show checkpoint archives when required,
- view archive details,
- rename archives,
- delete one or multiple archives,
- optionally compact once after a deletion batch,
- open restore/export workflows.

Checkpoint archives may be incomplete and should be handled deliberately.

## 16. Archive browser and export

The browser provides breadcrumb navigation, directories first and metadata columns for size, type, permissions, owner/group and modification time. Symbolic-link targets are shown where available.

Select files or directories for export or restore. Borg JSON is parsed strictly; harmless SSH/wrapper lines around the JSON are tolerated, but output without a valid Borg document remains an error.

## 17. Restore

Restore modes:

- dry-run,
- original path,
- alternative target directory.

Extraction runs on the target device. Verify free space, ownership and application consistency first. A dry-run is strongly recommended for large or destructive restores.

## 18. Notifications

Open **System -> Notifications** and configure one or more channels:

- SMTP,
- generic JSON webhook,
- Discord webhook,
- Telegram.

Use the channel test before enabling events. Select failures, warnings, successes and cancellations independently for backups, schedules, repository actions and other executions.

Delivery failures are logged separately and never change the Borg result. Notification secrets are encrypted and are not returned to the browser.

## 19. Manager backup and restore

Open **System -> Manager Backup**.

### Create

Enter a passphrase of at least 12 characters and create an encrypted `.bbm` file. Download and store it separately from the manager host.

### Upload

Upload encrypted `.bbm` or historical `.zip` backups. Files are streamed, size-limited and structurally checked. Existing filenames are never overwritten.

### Restore in the Web UI

1. select the backup,
2. provide its passphrase when required,
3. provide a separate passphrase for the automatic safety backup,
4. review the confirmation,
5. start restore.

The current manager state is backed up first. Repository contents and regenerable caches are not part of a manager backup.

### Server migration

1. install the same or newer manager version on the new server,
2. copy/upload the manager backup,
3. restore it,
4. verify `.env`, public hostname, ports, persistent mounts and firewall rules,
5. verify devices and repositories before enabling schedules.

## 20. Users and personal preferences

Administrators manage accounts in **System -> Users**. New or reset accounts must change their temporary password.

The last active administrator cannot be disabled, deleted or demoted. Regular users are read-only and cannot access administrative APIs through direct URLs.

Every user can store language, appearance, density and list height. English and German are available.

## 21. System settings and diagnostics

The sticky System tabs are:

```text
Notifications | Users | Manager Backup | Settings | System Diagnostics
```

The active tab has a dedicated dark fill and remains selected after page reload and direct hash navigation.

System diagnostics include repository filesystem usage, Web-user permissions, SSH listener/configuration, forced commands, wrapper access and repository-access completeness.

## 22. Update

### Normal update

```bash
cd /opt/BorgBackup-Manager
cp /path/BorgBackup-Manager-NEW-VERSION.zip updates/
cp /path/BorgBackup-Manager-NEW-VERSION.zip.sha256 updates/
sha256sum -c updates/BorgBackup-Manager-NEW-VERSION.zip.sha256
bash update.sh \
  --file updates/BorgBackup-Manager-NEW-VERSION.zip \
  --sha256 PUBLISHED_SHA256
```

The updater:

1. verifies SHA-256 before opening the ZIP,
2. validates safe paths and package completeness,
3. builds the new image,
4. stops the current container,
5. creates a consistent persistent manager-data backup while excluding repositories and regenerable caches,
6. applies the project files,
7. starts and checks the new container,
8. rolls back project files and restarts the prior container on failure where possible.

Reload the browser with `Ctrl+F5` after a frontend update.

### Historical transition from v1.0.4 or older to v1.0.5

The old updater did not know `recovery.sh`. Copy it once before the normal update:

```bash
cd /opt/BorgBackup-Manager
cp /path/BorgBackup-Manager-1.0.5.zip updates/
unzip -p updates/BorgBackup-Manager-1.0.5.zip BorgBackup-Manager/recovery.sh > recovery.sh
chmod 755 recovery.sh
bash update.sh --file updates/BorgBackup-Manager-1.0.5.zip
```

### Historical transition from v1.0.9 to v1.0.10

If the old updater appears stuck after stopping the container, interrupt it and restart the current stack:

```bash
cd /opt/BorgBackup-Manager
docker compose up -d
```

Then replace the updater once:

```bash
cd /opt/BorgBackup-Manager
cp /path/BorgBackup-Manager-1.0.10.zip updates/
unzip -p updates/BorgBackup-Manager-1.0.10.zip BorgBackup-Manager/update.sh > update.sh.new
chmod 755 update.sh.new
mv update.sh.new update.sh
bash update.sh --file updates/BorgBackup-Manager-1.0.10.zip
```

Do not trust an incomplete `*.partial` or interrupted persistent backup.

### Historical v1.0.25 to v1.0.26 build failure

The old updater did not copy a newly introduced release-note file. v1.0.28 restored compatibility. A rolled-back v1.0.25 installation can update directly to v1.0.28 without manually extracting the old English release notes.

## 23. Health checks

Public minimal endpoints:

```text
/api/ready
/api/health
/api/health/strict
```

Detailed component information is administrator-only at:

```text
/api/system/health
```

When `BBM_HEALTH_REQUIRE_SSHD=1`, strict readiness also requires the internal repository SSH service.

## 24. Docker diagnostics

```bash
cd /opt/BorgBackup-Manager
docker compose ps
docker compose logs --tail=300 borg-manager
docker inspect borgbackup-manager --format '{{json .State.Health}}'
```

Check persistent paths:

```bash
grep -E '^(BBM_DATA_PATH|BBM_REPOSITORY_PATH|BBM_HTTPS_PORT|BBM_REPOSITORY_SSH_PORT)=' .env
```

## 25. Repository SSH diagnostics

```bash
docker compose exec -T borg-manager pgrep -a sshd
docker compose exec -T borg-manager tail -n 200 /data/logs/sshd.log
docker compose exec -T borg-manager tail -n 200 /data/logs/borg-serve.log
docker compose exec -T borg-manager tail -n 200 /data/logs/debug.log
```

In **System -> System Diagnostics**, verify:

```text
Repository R/W/X: OK
sshd listening: OK
sshd configuration: OK
authorized_keys readable: OK
Forced Command: OK
Log writable: OK
Wrapper executable: OK
Access complete: OK
```

The Web API runs as `borg`. Manager-side Borg commands therefore run directly as that user. `runuser` is used only from a root context. The root-only `sshd -t` validation is performed by the entrypoint and exposed through a protected status marker.

## 26. Security rules

- Restrict port 2222 to known clients.
- Protect `/data/security/security.db` and `/data/security/master.key` together.
- Do not expose the manager data directory through a web server or shared filesystem.
- Use application-consistent database dumps or snapshots.
- Verify current backups before prune, compact, archive deletion and restore.
- Do not use automatic `break-lock`; first prove no Borg process is active.
- Trust forwarded headers only from the actual reverse proxy.
- Warning notifications include the concrete affected files or paths from the structured Borg warning summary.
- Keep success notifications optional to avoid excessive message volume.

## 27. Local account recovery

```bash
cd /opt/BorgBackup-Manager
./recovery.sh
```

Available direct commands:

```bash
./recovery.sh status
./recovery.sh status-json
./recovery.sh initial-admin
./recovery.sh unlock USER
./recovery.sh reset USER
./recovery.sh reset-admin USER
```

The script operates locally through `docker compose exec`; it does not expose an additional recovery endpoint.

## 28. Uninstall without deleting data

Stop and remove the container while retaining persistent directories:

```bash
cd /opt/BorgBackup-Manager
docker compose down
```

Do not delete `BBM_DATA_PATH` or `BBM_REPOSITORY_PATH` unless you intentionally want to destroy manager state or managed repositories.

To rebuild later:

```bash
cd /opt/BorgBackup-Manager
docker compose up -d --build
```

## 29. Validation commands

```bash
python -m compileall app
node --check app/static/app.js
bash -n install.sh update.sh recovery.sh restore-backup.sh
sh -n docker/entrypoint.sh docker/borg-serve.sh
PYTHONPATH=. pytest -q
```
