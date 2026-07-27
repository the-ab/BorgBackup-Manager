# Installation and Operations — BorgBackup Manager 1.1.3

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
BorgBackup-Manager-1.1.3.zip
`-- BorgBackup-Manager/
```

Install under `/opt`:

```bash
cd /opt
unzip /path/BorgBackup-Manager-1.1.3.zip
cd BorgBackup-Manager
chmod +x install.sh update.sh recovery.sh restore-backup.sh
```

Verify the checksum before installation:

```bash
sha256sum -c /path/BorgBackup-Manager-1.1.3.zip.sha256
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
BBM_SOURCE_STATS_PARALLEL_LIMIT=1
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

### Saved SSH actions

**Devices -> Saved SSH actions** lets administrators store recurring maintenance commands for a device. For example, a host mount already defined in fstab can be controlled with commands such as:

```bash
sudo -n mount /mnt/offline-backup
sudo -n umount /mnt/offline-backup
```

The WebUI does not expose an ad-hoc SSH console. Only saved actions can be started, and every start requires confirmation. Name, command, target device, enabled state, and timeout are stored in `manager.db`. **Do not put credentials or tokens into commands**, because command text is not encrypted. Interactive password prompts are unsupported; use a narrowly scoped sudoers rule with `sudo -n` when elevated privileges are required. Output and errors are recorded as regular runs and can be cancelled from the live log.

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

Create reusable templates in the central exclusion section. Existing templates are selected from a drop-down and only the selected template is loaded into the editor. Assign a template to jobs and add job-specific patterns where needed. New jobs default to the CPU-efficient mode with the complete processed-file list disabled.

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

Each schedule runs in three phases: all backups first, then the configured prune runs, and, when the system setting is enabled, finally at most one compact per affected repository. Several jobs sharing one repository therefore no longer trigger redundant compact operations. This system setting applies only to scheduled prune phases; a manually started prune does not trigger compact through it.

For manual starts, a job can optionally enable **Prune after manual backup** and **Compact after successful manual prune** in its retention settings. While that chain is active, later runs for the same repository remain queued until backup, prune and optional compact have finished.

### Parallelism

Parallel execution is controlled at four additive levels:

- **global** maximum parallel manager executions (`0` = unlimited),
- **per repository** maximum parallel backup runs (default `1`; repository maintenance/check operations remain exclusive),
- **per detected managed mount** below `/repositories` (`0` = unlimited for that mount),
- **per schedule** maximum parallel executions.

Repositories stored on the same physical filesystem or NFS mount share the configured mount limit, so separate repository directories cannot bypass the intended disk/I/O concurrency cap. A run starts only when every applicable limit has free capacity.

## 13. Run and monitor backups

Start a job from the dashboard or job list. Open the live log from the task indicator or execution list.

Queue reasons are displayed explicitly:

- repository capacity reached,
- repository mount capacity reached,
- global limit reached,
- schedule limit reached,
- waiting for an older FIFO repository operation.

A controlled cancellation first signals the remote Borg process group and waits for confirmed termination. The manager does not automatically execute `borg break-lock`.

During a backup the live dialog shows processed files, Borg original/compressed/deduplicated volumes, the current source/path and lightweight A/M/C/E counters. When the complete file list is disabled, BBM uses `--list --filter AMCE`: A/M are live counters only, C/E remain available for warning diagnosis, and unchanged U entries are not requested. With a usable source baseline, the run freezes the last known source size and file count when it is queued. Borg O/N are subtracted directly from that frozen baseline. Remaining time is calculated deterministically from remaining bytes using a fixed 1-Gbit/s interface assumption with 80% usable throughput (100 MB/s effective); remaining file count adds only the fixed small-file factor. Measured network throughput, short-term Borg rates, files-cache phases and previous runtimes are not used. If the frozen byte baseline is exceeded, remaining time is suppressed rather than showing a false zero or negative value.

## 14. Warnings and failures

Borg warning causes are captured while output is streaming and stored separately from the truncated log preview. The UI can identify changed files, missing files, permission errors, I/O errors and general Borg warnings.

If Borg emits only return code 1 without a detailed warning line, the execution states that the cause was not emitted rather than inventing one.

Complete status and path output is stored in `/data/run-logs/run-ID.log`. SQLite contains only bounded metadata and diagnostic previews plus structured warning causes; ordinary file paths are removed from database previews at run completion and from older previews during startup cleanup.

## 15. Archive overview

The archive list is cached persistently per repository below `/data/archive-cache`. Opening the archive view does not run Borg automatically.

1. Select the repository.
2. Optionally enable incomplete checkpoint archives.
3. Choose **Show Archives**. This reads only the existing persistent cache and returns immediately.
4. If no cache exists yet, or if the repository changed outside BBM, choose **Reload from Repository**. BBM queues a normal background run and returns a run ID immediately; `borg info`/`borg list` therefore no longer depend on the HTTP or reverse-proxy timeout.
5. The previous cached list remains visible while a refresh is running and is replaced atomically only after a successful scan.
6. Optionally filter the cached archives by an identified device, select individual archives, or use **Select visible archives** for batch deletion.

Backup, prune, rename and delete operations invalidate only the affected repository cache. Archive listing, archive details and browsing do not require a backup job. Managed repositories are read locally; external repositories are opened by the manager with the centrally stored Borg/SSH repository credentials.

The list is always sorted newest first regardless of Borg output order. Device filtering uses cached archive metadata and never starts another repository scan. Checkpoint archives may be incomplete and should be handled deliberately.

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

## 19. Manager backup and cache backup

Since v1.0.77 manager state and Borg caches are separate backup types. Newly created manager backups never include Borg caches, keeping the recovery artifact small even when repositories or client caches are very large.

### Create manager backup

Manager backups contain the application database, security database, master key, settings, controller/repository SSH keys, Borg keyfiles and TLS files. Repository data, full run logs, `/data/borg-cache`, `/data/borg-security` and client Borg caches are excluded from newly created manager backups.

New manager backups are mandatory streaming AES-256-GCM encrypted `.bbm` files protected by a non-stored passphrase of at least twelve characters. Compression is selectable: none, Deflate 1, Deflate 6 (default), or Deflate 9. Historical manager `.zip` files and combined v1.0.75/v1.0.76 artifacts remain readable. The Web UI shows live phase/progress/event output and resumes an active status after reload.

### Create separate cache backup

A cache backup is a separate `borgbackup-manager-cache-v...` artifact and may include either or both of:

- manager Borg cache and security state: `/data/borg-cache` and `/data/borg-security`
- managed client caches: `$HOME/.cache/borgbackup-manager/repository-<ID>` for current device/repository assignments

At least one cache group must be selected. `lock.exclusive` and `lock.roster` are excluded. Client caches are streamed directly over verified controller SSH. Disabled devices are recorded as skipped, a missing cache is allowed, and failure to reach an enabled device aborts cache creation. Symbolic links are rejected. No run may be queued or active while a cache backup is created.

Cache encryption is enabled and recommended by default but may be disabled deliberately. Encrypted cache artifacts use streaming AES-256-GCM/scrypt and `.bbm`; unencrypted cache artifacts use `.zip`. Compression and passphrase are independent from the manager backup. Live progress reports the current device/repository, `Client x/y`, transferred bytes, manager-cache file/byte progress, and the encryption phase when enabled.

Under **Manage Borg cache**, manager and client state can be scanned on demand. Client scans can target all devices or a selected subset. BBM checks its managed client cache `$HOME/.cache/borgbackup-manager/`, the normal Borg cache `$HOME/.cache/borg/` or `BORG_CACHE_DIR`, alternate historical cache roots derived from XDG/SSH-user settings, and Borg security state below `$HOME/.config/borg/security/` or `BORG_SECURITY_DIR`. Restore safety copies remain separate. Unknown regular Borg/security directories are never preselected, and every destructive cleanup performs a fresh association check first. Manager-side `/data/borg-cache` and `/data/borg-security` use the same conservative checks.

### Upload

Upload supported manager or cache `.bbm`/`.zip` artifacts under **System -> Manager Backup -> Upload backup**. Type, filename, limits and structure are validated, files are stored with mode `0600`, and existing names are never overwritten. Manager backups use the normal backup limits; cache artifacts use the separate `BBM_BACKUP_CACHE_*` limits.

### Restore manager backup

Select a manager backup, provide its passphrase when needed, provide a separate passphrase for the automatic encrypted safety backup, confirm replacement, and start restore. The manager verifies the artifact type before replacing manager/security databases, master key, settings and SSH/TLS/repository keys. A standalone cache artifact is rejected as full manager state. Historical combined v1.0.75/v1.0.76 manager backups remain compatible.

### Restore cache backup

Open **Cache backup restore**. Select the cache artifact and enter its passphrase only when encrypted. The manager Borg cache/security state can be restored as one explicit action. Saved client caches can be listed and restored one current device/repository assignment at a time. Existing manager or client caches are preserved under timestamped `pre-bbm-restore` names before replacement. No run may be queued or active during cache restore. Legacy combined v1.0.75/v1.0.76 artifacts remain usable here for their embedded caches.

### Server migration

Restore the manager artifact first with `restore-backup.sh`. Restore the separate cache artifact afterwards through the Web UI as needed. `restore-backup.sh` explicitly rejects a standalone cache artifact as full manager state.

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

WebUI sessions expire after 60 minutes of inactivity by default. The inactivity timeout can be changed later under **System → Settings → Session** without restarting the container. `BBM_SESSION_IDLE_TIMEOUT_SECONDS` provides the initial default, while `BBM_SESSION_TTL_SECONDS` remains the absolute maximum session lifetime.

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
