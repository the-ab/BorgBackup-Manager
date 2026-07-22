# BorgBackup Manager 1.0.62

BorgBackup Manager is a self-hosted web interface for centrally operating BorgBackup 1.x across multiple Linux devices. It manages devices, repositories, backup jobs, schedules, archives, restores, execution history, notifications, users and encrypted manager backups. Source devices do not need their own backup scripts or local cron jobs.

> **Independent project:** BorgBackup Manager is an independent third-party community project. It is not affiliated with, endorsed by or maintained by the BorgBackup project.

Portions of this project were developed with assistance from OpenAI ChatGPT. All generated code was reviewed, adapted and tested by the project maintainer, who assumes responsibility for the published software.

German documentation is available in [`README.de.md`](README.de.md). Installation instructions are provided in [`INSTALLATION.md`](INSTALLATION.md) and [`INSTALLATION.de.md`](INSTALLATION.de.md).

## Platform

- Container base: Debian 13 Trixie
- Borg inside the manager: Borg 1.4.x
- Supported client versions: Borg 1.2.0 through 1.4.x
- Web interface: HTTPS only
- Managed-repository service: integrated OpenSSH with restricted `borg serve`
- Persistent application data: `/docker_data/borgbackup-manager/data` by default
- Persistent managed repositories: `/docker_data/borgbackup-manager/repositories` by default
- Docker image: `borgbackup-manager:latest`
- Default timezone: `Europe/Berlin`
- Container name: `borgbackup-manager`
- Container hostname: `bbm`

## Release package

Every release ZIP contains the same top-level directory:

```text
BorgBackup-Manager/
```

Only the ZIP filename contains the version, for example:

```text
BorgBackup-Manager-1.0.62.zip
```

The documentation naming convention is:

```text
README.md                 English, default
README.de.md              German
INSTALLATION.md           English, default
INSTALLATION.de.md        German
RELEASE_NOTES.md          English, default
RELEASE_NOTES.de.md       German
```


## Security model

- FastAPI, Starlette and all direct and transitive Python runtime dependencies are pinned and hash-locked for Linux amd64 and arm64.
- Browser-side state-changing requests require the application header `X-BBM-Request: 1`; supplied `Origin` headers must match the effective manager URL.
- Expensive password checks are rate-limited persistently per source address and per source/user pair without allowing a third party to globally lock a user account.
- Sessions expire after 24 hours by default and after 60 minutes of inactivity.
- `Forwarded` and `X-Forwarded-*` headers are trusted only from explicitly configured proxy networks.
- New manager backups are always encrypted with AES-256-GCM and require a passphrase of at least 12 characters. Historical unencrypted ZIP backups remain restorable.
- Restore archives are checked for path traversal, symbolic links, duplicate normalized paths, entry count, uncompressed size and compression ratio.
- The Web API runs as the unprivileged `borg` user. Root is retained only by the supervised container entrypoint and `sshd`.
- OpenSSH uses `StrictModes yes`, forced commands and disabled forwarding for managed-repository access.
- The container uses `no-new-privileges` and does not require the Docker socket.
- Security events and notification delivery records are bounded by retention and row limits.

## Architecture

```text
Backup
Web UI / scheduler
        |
        `-- SSH to the source device
                  |
                  |-- Borg reads local source data
                  `-- Borg connects to the selected repository

Restore
Web UI
  |
  `-- SSH to the target device
           `-- Borg extracts data on the target device

Managed repository administration
Web UI -> Borg 1.4 inside the manager -> /repositories/REPOSITORY

External repository administration
Web UI -> Borg 1.4 inside the manager -> SSH -> external repository
```

Backup and restore operations run on the relevant device because that is where source and destination paths exist. Archive listing, archive information, check, prune, compact, diff, rename, delete, browser and export operations for managed repositories run directly inside the manager container.

## Borg compatibility

| Client version | Status |
|---|---|
| 1.2.0–1.2.4 | Usable, critical security warning |
| 1.2.5–1.2.7 | Usable, update warning |
| 1.2.8–1.4.x | Supported |
| older than 1.2.0 | Unsupported |
| 2.x | Incompatible |

Version detection tries several commands for compatibility:

```bash
borg --version
borg -V
borg --show-version help
```

## Authentication, users and secrets

A new installation creates a temporary administrator account. Display its one-time password locally:

```bash
cd /opt/BorgBackup-Manager
docker compose exec -T borg-manager python -m app.initial_admin
```

The password must be changed after the first sign-in. Authentication uses scrypt password hashes, revocable server-side sessions, hashed session tokens, Secure/HttpOnly/SameSite=Strict cookies, absolute and idle expiry, and source-scoped rate limits.

Administrators can manage users, devices, repositories, jobs, schedules, archives, restores, settings, notifications and manager backups. The regular **User** role is intentionally read-only: it can view the dashboard, lists and summarized execution states and can change only personal language and appearance settings.

Repository passwords, Borg passphrases, keyfiles, SMTP credentials, webhook URLs, Telegram tokens, private SSH keys and TLS material are encrypted in the security database. Back up `/data/security/security.db` and `/data/security/master.key` together.

## Navigation

The **Infrastructure** group contains only:

```text
Devices
System
```

The **System** workspace contains a sticky tab row in the page header:

1. Notifications
2. Users
3. Manager Backup
4. Settings
5. System Diagnostics

The selected tab has a dedicated dark active color in light and dark mode and is marked with `active`, `aria-selected="true"` and `aria-current="page"`. Direct URLs remain valid:

```text
#notifications
#users
#backups
#settings
#diagnostics
```

## Dashboard

The dashboard provides:

- job, running, queued and failed execution counts,
- repository count and cached size summary,
- a sortable backup-job overview,
- direct start buttons for usable jobs,
- the latest execution per job with run ID/date on the first line and duration/status directly below,
- compact source statistics with size/file count and the value timestamp on a second line,
- deduplicated, original and compressed backup sizes as three compact label/value rows,
- recent activities,
- attention items for failed runs, outdated Borg clients and incomplete access configuration.

Opening the dashboard does not trigger repository scans. It uses already stored execution and repository metadata.

## Devices

A device represents a Linux system reachable over SSH. The manager stores its address, SSH user, port and verified host fingerprint. The controller public key must be installed for the selected SSH account.

Device actions include:

- fingerprint verification,
- Borg version and connectivity checks,
- editing,
- enabling and disabling,
- controlled controller-key rotation guidance.

Disabling a device automatically disables all active backup jobs assigned to it. Re-enabling the device does not automatically enable those jobs, preventing unexpected scheduled backups after maintenance.

## Repositories

### Managed repositories

Managed repositories are stored below `BBM_REPOSITORY_PATH` and are served through the integrated restricted SSH service. The manager can initialize, check, compact, list archives, calculate size and administer repository access.

The repository overview shows the numerical manager repository ID. The same ID appears in isolated cache paths:

```text
/data/borg-cache/repository-ID
$HOME/.cache/borgbackup-manager/repository-ID
```

If a managed repository was deleted at filesystem level, the UI reports **Repository missing**. A safe reset action clears stale manager state only when the target directory is present, empty and contains no Borg configuration. It never deletes repository files.

### External repositories

External repositories are addressed by a Borg repository URL. The manager supports SSH host-key verification, repository passphrases, keyfiles and additional safe environment settings. Dangerous process-control variables such as `PATH`, `HOME`, `PYTHONPATH`, `LD_PRELOAD` and `SSH_AUTH_SOCK` are rejected.

### Encryption modes

Supported modes depend on the installed Borg 1.x version and include unencrypted, repokey and keyfile variants. Passphrases and imported keyfiles are stored encrypted.

### Storage guard

A global storage guard can block new write operations when repository filesystem usage reaches a configured percentage. Managed repositories can override the global threshold. Multiple repository mounts are evaluated independently.

## Backup jobs

A backup job combines:

- one enabled device,
- one repository,
- one or more source paths,
- optional exclusion templates and patterns,
- archive naming rules,
- compression,
- filesystem and Borg create options,
- retention settings.

Jobs can be enabled or disabled from **Backup Jobs -> More -> Manage**. A disabled job cannot be started manually or by a schedule. Disabling is blocked while the job is running or queued.

### Source statistics

The job overview displays source size, entry count, timestamp and value origin.

- After a successful or warning-completed backup, exact values are taken from Borg's final statistics without an additional scan.
- The manual **Refresh** action runs a read-only live scan on the source device. It does not create an archive or require repository access. This value is labelled **Live scan before exclusions**.
- Changing source paths, exclusions, device or relevant filesystem/create options invalidates stale statistics automatically.

### Exclusions

Central exclusion templates can be reused by multiple jobs. Jobs may additionally define their own patterns. Patterns are passed to Borg as argument values rather than evaluated by a shell.

### Archive names

Archive naming supports stable per-job prefixes and timestamps. The manager records historical archive series so archives can remain associated with their originating device after job changes.

### Job actions

Depending on state and permissions, actions include:

- start,
- refresh source statistics,
- check access,
- edit,
- enable/disable,
- view executions,
- open archives,
- delete job configuration.

Deleting a job does not automatically delete its archives.

## Schedules

Schedules are managed centrally and can target selected jobs, selected devices, or all jobs belonging to a repository. Jobs without an active schedule remain manual.

A backup job may belong to only one active schedule. Multiple execution times for the same job are configured inside that schedule.

### Parallelism

Three limits work together:

1. one Borg write/administration action per physical repository,
2. an optional global maximum across all repositories,
3. an optional maximum per schedule.

A schedule limit of `1` serializes its jobs even when they use different repositories, preventing excessive CPU, disk or network load.

## Execution queue and logs

Every operation is stored as an execution with status, timestamps, readable output and technical details. Repository actions are serialized by physical repository identity and by a persistent FIFO admission check.

The manager distinguishes:

- repository locks,
- local Borg cache locks,
- global parallelism waits,
- schedule parallelism waits,
- repository queue waits.

For remote backup cancellation, a supervised control channel first signals the remote Borg process group and waits for confirmed termination before releasing the queue. Automatic `borg break-lock` is deliberately not performed.

Warning causes are captured while Borg is running, before log truncation. Changed files, missing files, permission errors, I/O errors and general Borg warnings are persisted separately. If Borg returns warning status without a detail line, the UI explicitly reports that no cause was emitted. Full file-list output uses a raw-byte path: ordinary Borg item blocks are not fully decoded or split line by line. Complete status/path output is stored only in `/data/run-logs`; SQLite keeps cleaned metadata/diagnostic previews and bounded structured warning causes, not the ordinary file list. With the run dialog closed, status polling reads no file-backed log. An open live dialog requests only bytes appended since its previous file offset; the initial request and background poll are serialized so stale responses cannot duplicate the header. The browser view remains bounded and the configured complete head/tail view is loaded once after completion.

## Archives

The archive overview supports:

- repository refresh,
- cached metadata,
- filtering by device,
- checkpoint visibility,
- archive information,
- rename,
- single and multiple deletion with one confirmation,
- optional compact after deletion,
- restore and export workflows.

Mixed archive selections are labelled **Multiple devices**. Mounted archives block destructive actions.

## Archive browser

The archive browser is structured like a file browser and uses Borg JSON metadata. It provides:

- breadcrumb navigation,
- folders first,
- parent-directory navigation,
- file and directory selection,
- name, size, type, permissions, owner, group and modification time,
- symbolic-link targets,
- export and restore of selected paths.

## Restore

Restore supports archive and path selection, dry-run, original paths and an alternative destination. Extraction runs on the selected target device. Existing destination data should be protected with an application-consistent backup before restore.

## Manager backups

New manager backups are encrypted `.bbm` files. The Web UI can create, download, upload, restore and delete them. Historical `.zip` backups can still be uploaded and restored.

Uploads are streamed, size-limited and validated. Existing files are never overwritten. Before a Web UI restore, the manager requires a separate passphrase and creates an encrypted safety backup of the current state.

Manager backups contain application databases, security database and master key, SSH/TLS material, settings, notification configuration and other persistent manager state. Repository contents and regenerable Borg/archive caches are excluded.

## Notifications

The notification center supports:

- SMTP with STARTTLS, implicit TLS or an explicitly allowed internal plain connection,
- generic JSON webhooks,
- Discord webhooks,
- Telegram bots.

Events can be selected independently for backup failures, warnings, successes, cancellations, schedule results, repository operations and other manager executions. Structured Borg warning notifications include the concrete affected file or path for every stored warning cause, up to ten entries plus a count of additional causes. Delivery failures never change the Borg result. Notification dispatch starts only after execution slots have been released.

Secrets are encrypted and are not returned to the browser. A bounded delivery log records channel, event, result and sanitized error details.

## Personal settings

Each user can store language, light/dark/system appearance, density and list-height preferences. English and German are supported. Administrative system pages remain inaccessible to regular users even through direct URLs.

## System settings and diagnostics

System settings include timezone-related display behavior, repository size refresh, global parallelism, storage guard, UI defaults and controller-key management.

System diagnostics cover:

- Borg version,
- repository filesystems and usage,
- storage guard,
- Web-user read/write/execute access,
- SSH listener and root-validated `sshd` configuration,
- `authorized_keys`, forced commands and wrapper access,
- repository access completeness,
- recent `sshd` and `borg-serve` logs.

## Installation

```bash
cd /opt
unzip /path/BorgBackup-Manager-1.0.62.zip
cd BorgBackup-Manager
chmod +x install.sh update.sh recovery.sh restore-backup.sh
bash install.sh
```

The guided installer creates `.env`, validates paths and ports, builds the image and starts the services. See [`INSTALLATION.md`](INSTALLATION.md) for the complete procedure.

Default endpoints and paths:

```text
Web UI:          https://SERVER:8443
Repository SSH:  SERVER:2222
Data:            /docker_data/borgbackup-manager/data
Repositories:    /docker_data/borgbackup-manager/repositories
Image:           borgbackup-manager:latest
Container:       borgbackup-manager
```

## Update

Verify the release checksum and run the updater:

```bash
cd /opt/BorgBackup-Manager
cp /path/BorgBackup-Manager-NEW-VERSION.zip updates/
cp /path/BorgBackup-Manager-NEW-VERSION.zip.sha256 updates/
sha256sum -c updates/BorgBackup-Manager-NEW-VERSION.zip.sha256
bash update.sh \
  --file updates/BorgBackup-Manager-NEW-VERSION.zip \
  --sha256 PUBLISHED_SHA256
```

The updater validates the checksum before opening the ZIP, validates package paths and required files, stops the container for a consistent manager-data backup, excludes repositories and regenerable caches, applies the project files, builds, starts and verifies readiness. On failure it rolls back the project and restarts the previous container where possible.

### Historical transitions

Very old versions may require a one-time updater or recovery-script replacement. The complete commands remain documented in [`INSTALLATION.md`](INSTALLATION.md) and [`INSTALLATION.de.md`](INSTALLATION.de.md).

## Recovery

Local account recovery is available without a network recovery endpoint:

```bash
cd /opt/BorgBackup-Manager
./recovery.sh
```

Direct commands:

```bash
./recovery.sh status
./recovery.sh status-json
./recovery.sh initial-admin
./recovery.sh unlock USER
./recovery.sh reset USER
./recovery.sh reset-admin USER
```

Password resets revoke existing sessions and create a temporary password.

## Importing an existing managed repository

Besides **Search automatically**, the repository page provides **Select folder**. The browser is restricted to `/repositories`, does not follow symbolic links and marks direct child folders containing a Borg `config` as selectable. Selecting a folder fills the existing import form; the repository is checked before it is registered and is never initialized or overwritten.

## Diagnostics

```bash
cd /opt/BorgBackup-Manager
docker compose ps
docker compose logs --tail=200 borg-manager
curl -k https://127.0.0.1:8443/api/ready
```

Repository service logs and unexpected application errors:

```bash
docker compose exec -T borg-manager pgrep -a sshd
docker compose exec -T borg-manager tail -n 200 /data/logs/sshd.log
docker compose exec -T borg-manager tail -n 200 /data/logs/borg-serve.log
docker compose exec -T borg-manager tail -n 200 /data/logs/debug.log
```

## Development checks

```bash
python -m compileall app
node --check app/static/app.js
bash -n install.sh update.sh recovery.sh restore-backup.sh
sh -n docker/entrypoint.sh docker/borg-serve.sh
PYTHONPATH=. pytest -q
```

## Repository and archive statistics

The repository overview can show:

| Value | Meaning |
|---|---|
| Original | Sum of original data reported by Borg |
| Compressed | Compressed data before repository-wide deduplication |
| Deduplicated | Unique compressed chunks stored repository-wide |
| Filesystem | Managed repositories only: actual repository-directory disk usage |

Archive metadata is cached after loading and includes start/end time, duration, file count, original/compressed/deduplicated archive size, hostname, user, comment and archive ID. An archive's deduplicated size represents chunks required only by that archive and must not be summed to calculate repository-wide deduplicated size.

The cache contains metadata only, is regenerable, is excluded from update backups and can be replaced through **Reload from repository** after external Borg changes.

## License, security and contributions

The project source code is licensed under the [Apache License 2.0](LICENSE). Important third-party licenses and project-independence notices are summarized in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

Security reports must follow [SECURITY.md](SECURITY.md) and must not be submitted as public issues. Contribution requirements are documented in [CONTRIBUTING.md](CONTRIBUTING.md). The repository is maintained and released manually; automated dependency-update pull requests and hosted CI/container-build workflows are intentionally not included.

Only the current release receives security fixes. Versions before 1.0.38 are unsupported and should not be published as supported releases.
