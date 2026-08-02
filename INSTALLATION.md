# Installation and Operations — BorgBackup Manager 1.3.8

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
BorgBackup-Manager-1.3.8.zip
`-- BorgBackup-Manager/
```

Install under `/opt`:

```bash
cd /opt
unzip /path/BorgBackup-Manager-1.3.8.zip
cd BorgBackup-Manager
chmod +x install.sh update.sh recovery.sh restore-backup.sh
```

Verify the checksum before installation:

```bash
sha256sum -c /path/BorgBackup-Manager-1.3.8.zip.sha256
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

### Standalone installation with the published GHCR image

Hosts that should not keep the project source tree or run `install.sh` can use the separate `docker-compose/` bundle from the release:

```text
docker-compose/
├── compose.yaml
├── .env.example
├── README.md
└── README.de.md
```

Copy both files into a dedicated operations directory:

```bash
sudo mkdir -p /opt/borgbackup-manager
sudo cp docker-compose/compose.yaml /opt/borgbackup-manager/compose.yaml
sudo cp docker-compose/.env.example /opt/borgbackup-manager/.env
cd /opt/borgbackup-manager
sudo chmod 600 .env
sudo editor .env
```

Review at least `BBM_REPOSITORY_PUBLIC_HOST`, `BBM_TLS_HOSTS`, `BBM_DATA_PATH` and `BBM_REPOSITORY_PATH`, then start the published image:

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail=200 borg-manager
```

`BBM_IMAGE_TAG=latest` selects `ghcr.io/the-ab/borgbackup-manager:latest`. Pin `BBM_IMAGE_TAG=v1.3.8` for a controlled and reproducible release. Update an image-only deployment by changing the tag when required, running `docker compose pull`, and recreating it with `docker compose up -d`; persistent host paths remain unchanged.

During first start the entrypoint checks `/repositories` using `BBM_BORG_UID` and `BBM_BORG_GID`. If the mount is empty and is owned by `root` only because Docker created the host directory, only the mount root is assigned to the configured UID/GID and receives owner read/write/execute access. The entrypoint never runs recursive `chown` on repositories. Existing non-empty data therefore requires correct host ownership, group permissions or ACLs. NFS deployments with `root_squash` must configure matching numeric UID/GID or server-side permissions.

#### Read-only archive mounts enabled by default

The normal `compose.yaml` enables Borg FUSE support without an additional Compose file. The Docker host must provide `/dev/fuse`. Prepare the host path configured by `BBM_ARCHIVE_MOUNT_PATH` for the selected Borg UID/GID before first start:

```bash
sudo modprobe fuse
sudo mkdir -p /docker_data/borgbackup-manager/archive-mounts
sudo chown 1000:1000 /docker_data/borgbackup-manager/archive-mounts
sudo chmod 700 /docker_data/borgbackup-manager/archive-mounts

docker compose config
docker compose pull
docker compose up -d
```

The standard configuration passes through `/dev/fuse`, adds `CAP_SYS_ADMIN`, permits FUSE through AppArmor, and uses `rshared` mount propagation. These permissions expand container privileges and require a trusted Docker host. Archive mounts support locally managed repositories only; external SSH repositories are rejected. Mounts use FUSE `allow_other`; the image enables `user_allow_other` in `/etc/fuse.conf`. The propagated mount can therefore be entered from the Docker host while archived file permissions remain visible.


On a genuinely new installation, the container writes the one-time administrator credentials exactly once to its local startup log. The image-only example enables this with `BBM_SHOW_INITIAL_ADMIN_ON_START=1`:

```bash
cd /opt/borgbackup-manager
docker compose logs --tail=200 borg-manager
```

Until the mandatory password change, the same encrypted bootstrap credentials can be displayed explicitly again:

```bash
docker compose exec -T borg-manager python -m app.initial_admin
```

Set `BBM_SHOW_INITIAL_ADMIN_ON_START=0` to disable automatic log output. When enabled, the temporary password is present in the local Docker log; change it immediately and restrict Docker and log access to administrators.

## 4. `.env` configuration

A focused reference grouped by required values, networking, paths, sessions, security limits, backup limits, and performance settings is included at [`docker-compose/README.md`](docker-compose/README.md). The German version is available at [`docker-compose/README.de.md`](docker-compose/README.de.md).

The guided installer writes a complete `.env`. During supported updates from the v1.3.5 baseline, `update.sh` preserves values of documented current variables, adds missing current variables from the template, and discards unsupported keys. Supported host variables include:

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

The WebUI does not expose an ad-hoc SSH console. Only saved actions can be started, and every start requires confirmation. Name, command, target device, enabled state and timeout are protected with the existing master key; command text is authenticated-encrypted in `/data/security/security.db`. `manager.db` contains no SSH-action command table and run previews expose only the action name and target device. Interactive password prompts remain unsupported; use a narrowly scoped sudoers rule with `sudo -n` when elevated privileges are required. Output and errors are recorded as regular runs and can be cancelled from the live log.

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
- **Refresh** performs a read-only, exclusion-aware live scan on the source device without creating an archive.
- Borg path exclusions are checked before `stat()` so excluded files and complete directory trees avoid unnecessary metadata traffic where possible. Cache tags, `nodump` and the configured filesystem boundary are applied as well.
- Normal successful scans show only origin and timestamp. Unsupported patterns, unavailable `nodump` checks or read warnings are shown only when present, with a concrete limitation reason.
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

- one fixed execution slot per physical Borg repository,
- **global** maximum parallel manager executions (`0` = unlimited),
- **per detected repository filesystem** (managed mount or detected external SSH filesystem; `0` = unlimited),
- **per schedule** maximum parallel executions.

The repository slot is intentionally not configurable because Borg serializes writers to one repository. Repositories stored on the same physical/NFS mount or the same detected external SSH filesystem share the configured filesystem limit. External groups are derived from the SSH identity and the mount returned by the remote `df` probe. A limit of `2`, for example, allows two different repositories on that filesystem to run concurrently while further repositories wait. A run starts only when every applicable limit has free capacity.
A changed filesystem limit is reloaded by already waiting runs and therefore applies without draining the whole queue first. Persisted runs are admitted only by the database-backed FIFO execution plan and no longer reserve a second process-local slot. External groups become configurable after a successful storage probe or after loading System Diagnostics; until then only per-repository serialization applies. **System → System diagnostics → Repository filesystems** displays the effective limit, current **active / queued** occupancy and the global/source-statistics limits for both managed and detected external filesystems.

## 13. Run and monitor backups

Start a job from the dashboard or job list. Open the live log from the task indicator or execution list.

Queue reasons are displayed explicitly:

- repository already in use,
- repository mount capacity reached,
- global limit reached,
- schedule limit reached,
- waiting for an older FIFO repository operation.

A controlled cancellation first signals the remote Borg process group and waits for confirmed termination. The manager does not automatically execute `borg break-lock`.

During a backup the live dialog shows processed files, Borg original/compressed/deduplicated volumes, the current source/path and lightweight A/M/C/E counters. When the complete file list is disabled, BBM uses `--list --filter AMCE`: A/M are live counters only, C/E remain available for warning diagnosis, and unchanged U entries are not requested. With a usable source baseline, the run freezes the last known source size and file count when it is queued. Borg O/N are subtracted directly from that frozen baseline. Remaining time is calculated deterministically from remaining bytes using a fixed 1-Gbit/s interface assumption with 80% usable throughput (100 MB/s effective); remaining file count adds only the fixed small-file factor. Measured network throughput, short-term Borg rates, files-cache phases and previous runtimes are not used. If the frozen byte baseline is exceeded, remaining time is suppressed rather than showing a false zero or negative value.

## 14. Warnings and failures

Borg warning causes are captured while output is streaming and stored separately from the truncated log preview. The UI can identify changed files, missing files, permission errors, I/O errors and general Borg warnings.

If Borg emits only return code 1 without a detailed warning line, the execution states that the cause was not emitted rather than inventing one.

Complete status and path output is stored in `/data/run-logs/run-ID.log`. SQLite contains only bounded metadata and diagnostic previews plus structured warning causes; ordinary file paths are removed from database previews at run completion.

## 15. Archive overview

The archive list is cached persistently per repository below `/data/archive-cache`. Opening the archive view does not run Borg automatically.

1. Select the repository.
2. Checkpoint archives are shown automatically in the normal archive overview and are clearly marked as incomplete.
3. Choose **Show Archives**. This reads only the existing persistent cache and returns immediately.
4. If no cache exists yet, or if the repository changed outside BBM, choose **Reload from Repository**. BBM queues a normal background run and returns a run ID immediately; `borg info`/`borg list` therefore no longer depend on the HTTP or reverse-proxy timeout.
5. The previous cached list remains visible while a refresh is running and is replaced atomically only after a successful scan.
6. Optionally filter the cached archives by an identified device, select individual archives, or use **Select visible archives** for batch deletion.

Backup, prune, rename and delete operations invalidate only the affected repository cache. Archive listing, archive details and browsing do not require a backup job. Managed repositories are read locally; external repositories are opened by the manager with the centrally stored Borg/SSH repository credentials.

Archive deletion is queued immediately from the strictly validated selected names and returns a run ID without enumerating the complete repository again inside the HTTP request. The run log is opened immediately; stale or externally removed names are reported by Borg in that visible run. This keeps deletion responsive for very large repositories and avoids HTTP/reverse-proxy timeouts before a run exists.

The list is always sorted newest first regardless of Borg output order. Device filtering uses cached archive metadata and never starts another repository scan. Checkpoint archives are displayed automatically, clearly marked as incomplete, and should be handled deliberately. Restore keeps a separate opt-in control.

## 16. Archive browser and export

The browser provides breadcrumb navigation, directories first and metadata columns for size, type, permissions, owner/group and modification time. Symbolic-link targets are shown where available.

Select files or directories for export or restore. Borg JSON is parsed strictly; harmless SSH/wrapper lines around the JSON are tolerated, but output without a valid Borg document remains an error.

## 17. Restore

Restore modes:

- dry-run,
- original path,
- alternative target directory.

Extraction runs on the target device. Verify free space, ownership and application consistency first. A dry-run is strongly recommended for large or destructive restores.

BBM first performs a streamed Borg metadata pass over the selected archive objects to determine total count and original size. The live dialog then displays processed/total files and objects, processed/remaining bytes, percentage, current rate, ETA and current path. Dry-runs use the same progress view. Large selections therefore require one additional metadata pass, but the complete item list is never loaded into manager memory.

## 18. Notifications

Open **System -> Notifications** and configure one or more channels:

- SMTP,
- generic JSON webhook,
- Discord webhook,
- Telegram.

Use the channel test before enabling events. Select failures, warnings, successes and cancellations independently for backups, schedules, repository actions and other executions.

Delivery failures are logged separately and never change the Borg result. Notification secrets are encrypted and are not returned to the browser.

## 19. Manager backup and cache backup

Manager state and Borg caches are separate backup types. Newly created manager backups never include Borg caches, keeping the recovery artifact small even when repositories or client caches are very large.

### Create manager backup

Manager backups contain the application database, security database, master key, settings, notification configuration and `migration.env`. Controller keys, repository SSH host keys, Borg keyfiles/passphrases, TLS material and notification secrets are encrypted inside the security database; the master key is the mandatory decryption anchor. `authorized_keys` and clear-text files below `/run/bbm-secrets` are regenerated from the databases after restore. Before storing the artifact, BBM validates both SQLite databases, the required security tables, the master key and decryptability of every stored secret. A missing component or mismatched key makes backup creation fail. Repository data, existing backup artifacts, exports, complete run/debug logs, `/data/borg-cache`, `/data/borg-security` and client Borg caches are excluded.

New manager backups are mandatory streaming AES-256-GCM encrypted `.bbm` files protected by a non-stored passphrase of at least twelve characters. Compression is selectable: none, Deflate 1, Deflate 6 (default), or Deflate 9. Import and restore require backup metadata version v1.3.5 or newer. The Web UI shows live phase/progress/event output and resumes an active status after reload.

### Create split cache artifacts

One cache-backup run emits independent files:

- `borgbackup-manager-cache-manager-v...` for `/data/borg-cache` and `/data/borg-security`
- `borgbackup-manager-cache-client-<device-name>-h<ID>-v...` for each selected device

Manager cache inclusion is independent. Client collection supports **All devices** or a multi-selection under **Selected devices**. Unselected devices are not contacted over SSH. Each device artifact groups all currently assigned repository caches and matching Borg security state for that device. The device name and stable ID are present in the filename and internal archive paths.

A device failure does not abort the remaining artifacts. The affected device is reported as a warning, and no empty device file is retained when no cache/security data could be saved. `lock.exclusive`, `lock.roster` and symbolic links are excluded. No run may be queued or active during creation.

Encryption remains enabled and recommended by default. Each artifact is encrypted separately with AES-256-GCM/scrypt and uses `.bbm`; deliberately unencrypted artifacts use `.zip`. All artifacts from one run share the entered passphrase and compression choice. Live progress reports `artifact x/y`, device, repository and transferred bytes.

Under **Cache backup restore**, a manager-cache artifact is restored through its dedicated action. A device artifact lists each contained repository cache. The target can be the original device or another enabled device assigned to the same repository. Existing target caches are preserved under `pre-bbm-restore` names, and existing Borg security state is never overwritten by an older saved state.

Under **Manage Borg cache**, manager and client state can still be scanned, reset and cleaned independently from backup creation. The client scan likewise supports all devices or a multi-selection.

### Upload

Upload supported manager or cache `.bbm`/`.zip` artifacts in the compact **Upload backup** section directly below **Create manager backup** under **System -> Manager Backup**. Type, filename, limits and structure are validated, files are stored with mode `0600`, and existing names are never overwritten. Manager backups use the normal backup limits; cache artifacts use the separate `BBM_BACKUP_CACHE_*` limits.

### Restore manager backup

Select a manager backup, provide its passphrase, provide a separate passphrase for the automatic encrypted safety backup, confirm replacement, and start restore. The manager verifies the artifact type and minimum metadata version v1.3.5 before replacing manager/security databases, master key, settings and SSH/TLS/repository keys. A standalone cache artifact is rejected as full manager state.

### Restore cache backup

Open **Cache backup restore**. Select the cache artifact and enter its passphrase only when encrypted. The manager Borg cache/security state can be restored as one explicit action. Saved client caches can be listed and restored one current device/repository assignment at a time. Existing manager or client caches are preserved under timestamped `pre-bbm-restore` names before replacement. No run may be queued or active during cache restore. Cache backup metadata must identify BorgBackup Manager v1.3.5 or newer.

### Server migration

Restore the manager artifact first with `restore-backup.sh`. Restore the separate cache artifact afterwards through the Web UI as needed. `restore-backup.sh` explicitly rejects a standalone cache artifact as full manager state.

## 20. Users and personal preferences

Administrators manage accounts in **System -> Users**. New or reset accounts must change their temporary password.

The last active administrator cannot be disabled, deleted or demoted. Regular users are read-only and cannot access administrative APIs through direct URLs.

Every user opens **Profile** directly below the username in the sidebar. It opens a dedicated profile page with an account overview, directly editable **Appearance & Language** settings, an inline password form, and **Two-factor authentication** management. Language, appearance, density and list height are stored per user. English and German are available.

## 21. System settings and diagnostics

The sticky System tabs are:

```text
Notifications | Users | Manager Backup | Settings | System Diagnostics
```

The active tab has a dedicated dark fill and remains selected after page reload and direct hash navigation.

System diagnostics include repository filesystem usage, Web-user permissions, SSH listener/configuration, forced commands, wrapper access and repository-access completeness.

## 22. Update

### Supported baseline

v1.3.8 keeps v1.3.5 as the one-time backward-compatibility cutoff. Every regularly started v1.3.5 installation can update directly. Historical update helpers, additive pre-v1.3.5 schema migrations, old public API aliases and obsolete backup formats are no longer included.

Before updating, create and verify a fresh encrypted manager backup and verify the new ZIP with its SHA-256 file. A separate cleanup or manual SQLite command is not required for a normally running v1.3.5 installation. Then run:

```bash
bash update.sh \
  --file updates/BorgBackup-Manager-1.3.8.zip \
  --sha256 <SHA-256>
```

The updater rejects a source version below v1.3.5. At startup, v1.3.8 accepts every complete v1.3.5 manager and security schema, creates restricted safety copies, copies all current tables into the exact current schema, verifies row counts, SHA-256 content digests, foreign keys and SQLite integrity, and only then removes unused surplus objects such as `archive_mounts`. Missing current tables or columns still identify a genuinely older unsupported structure. If an older installation cannot first reach v1.3.5, deploy v1.3.8 cleanly and restore a supported v1.3.5-or-newer manager backup.

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

The incident log `/data/logs/debug.log` stores unexpected tracebacks, unhandled background/application failures, critical framework or system errors, and application-side HTTP 5xx responses. It does not store ordinary backup runs, source-statistics output, expected Borg warnings or long but non-technical messages. Protected failures are shown with a short `BBM-...` error ID. Failed/cancelled-run notices disappear after six seconds; other actionable red errors remain visible until explicitly closed.

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

## Two-factor authentication, access log and external blocking tools

Each user can start TOTP setup under **Profile -> Two-factor authentication** in the sidebar. The current password is verified again. BBM locally renders a QR code from the same `otpauth://` URI for direct scanning; the Base32 secret and URI remain available for manual setup, and no external QR service is contacted. Confirm setup with a current six-digit code. The ten codes appear in an explicitly labelled **Recovery codes** section stating that they are shown in full only during this setup and that every code is valid only once. Store them outside the manager.

The persistent access log is stored on the host at:

```text
${BBM_DATA_PATH}/logs/access.log
```

With default paths:

```text
/docker_data/borgbackup-manager/data/logs/access.log
```

A Fail2ban filter at `/etc/fail2ban/filter.d/borgbackup-manager.conf` can use:

```ini
[Definition]
failregex = ^\{.*"event":"login_(?:failed|blocked)".*"remote_address":"<HOST>".*\}$
ignoreregex =
```

Example `/etc/fail2ban/jail.d/borgbackup-manager.local`:

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

Adapt `port` and `logpath`, then test before enabling:

```bash
sudo fail2ban-regex \
  /docker_data/borgbackup-manager/data/logs/access.log \
  /etc/fail2ban/filter.d/borgbackup-manager.conf
```

CrowdSec can acquire the same file as a custom file source. The custom parser must decode the JSON fields, set `evt.Meta.source_ip` from `remote_address`, and assign a custom `evt.Meta.log_type` to `login_failed`/`login_blocked`. A `leaky` scenario can evaluate that log type. Exact paths and YAML schemas depend on the installed CrowdSec version; verify the parser/scenario with `cscli explain` and CrowdSec configuration checks before allowing a bouncer to enforce firewall decisions.

The access log never contains passwords, TOTP/recovery codes or session tokens. Behind a reverse proxy, configure `BBM_TRUSTED_PROXY_CIDRS` so only trusted proxy addresses may supply the real client IP.

## Maintaining the manager database

Under **System → System diagnostics → Clean manager database**, run **Inspect database** first. The current cleanup handles stale interrupted runs, inactive archive-mount rows, orphan assignments and notifications, invalid schedule targets and reclaimable SQLite pages. Devices, repositories, jobs, schedules, source statistics, backup-size metadata and completed backup runs remain unchanged. A full SQLite rebuild is queued for the next startup so it cannot hold an exclusive lock while the WebUI is serving requests.
