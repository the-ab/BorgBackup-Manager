# Release Notes

## v1.0.53

### Diagnostics for disabled devices

- Repository access diagnostics now compare `authorized_keys` only with enabled devices. Stored access assignments for disabled devices are retained for later reactivation but no longer cause false **Forced Command** or **Accesses complete** failures.
- Disabled access assignments are shown separately as informational counts. Existing active keys are still checked for the repository-scoped forced command.

### Switchable server logs and persistent debug log

- System diagnostics now uses three log tabs for `sshd`, `borg-serve` and the new debug/error log instead of rendering two long logs consecutively.
- `/data/logs/debug.log` captures unexpected HTTP tracebacks, scheduler failures, unhandled thread exceptions and asyncio/background-task errors. It uses the existing size limit and rotation policy.
- Expected Borg run output remains in the corresponding run log and is not duplicated into the debug log.

### Managed repository folder browser

- The automatic discovery of existing local repositories remains available.
- A separate folder browser lists the contents below `/repositories`, supports safe directory navigation and allows a detected direct-child Borg repository to be selected deliberately.
- Traversal outside `/repositories` and symbolic-link navigation are rejected; listings are limited to 500 entries.

### Verification

- Regression tests cover disabled-device diagnostics, active access failures, forced-command validation, repository-browser containment, symlink rejection, debug-log persistence and the three-tab UI.

## v1.0.52

### Compact dashboard and improved mobile layouts

- **Latest run** now uses three compact rows: run ID with date/time, status with duration, and schedule or manual trigger. The dashboard column width is unchanged.
- On mobile devices the latest-backup size stack no longer inherits the desktop table minimum width, so values remain inside the visible card instead of appearing after a large empty horizontal scroll area.
- Archive overview cards wrap metadata and actions directly below one another on narrow screens, removing the large gap between archive ID/details and action buttons.
- The archive browser switches to readable metadata cards on mobile while preserving name, size, type, permissions, owner and modification time.
- System diagnostics now render server checks as compact status cards; filesystem tables and logs stay within the mobile viewport and long log lines wrap safely.

### Verification

- Regression tests cover the three-row latest-run layout, mobile dashboard width overrides, archive-card wrapping, mobile archive-browser cards and responsive diagnostics.

## v1.0.51

### Bulk archive deletion with encrypted repositories

- Fixed multi-selection archive deletion for passphrase-protected repositories.
- The previous supervised wrapper exposed the passphrase through one shared `BORG_PASSPHRASE_FD`. The first Borg process consumed that descriptor, so the second archive deletion or the following Compact received EOF and reported an incorrect passphrase.
- The wrapper now uses a protected temporary passphrase file through `BORG_PASSCOMMAND`. Borg opens that file anew for every delete and Compact invocation; the passphrase itself is not placed in argv or a normal environment variable.
- Single archive deletion, multi-selection, optional one-time Compact, controlled cancellation and temporary-file cleanup use the same corrected path.

### Verification

- A regression test executes two Borg deletions and one Compact in sequence and verifies that all three receive the correct passphrase.

## v1.0.50

### Compact dashboard backup-job metadata

- **Latest backup size** now shows deduplicated, original and compressed sizes as three tightly spaced label/value rows without widening the dashboard table.
- **Latest run** keeps run ID and date/time on the first row and places duration, status and trigger information directly below it.
- **Source statistics** now use two compact rows: size/file count first, followed by the value origin and timestamp.

### Warning notifications include affected files

- Backup-warning notifications now include the concrete file or path stored for every structured Borg warning cause.
- Messages such as `changed – file changed while we backed it up` are followed by the affected path instead of only the generic reason.
- Up to ten structured entries are included; additional entries are reported as a count.
- The notification uses the warning summary captured during the Borg run and does not depend on a later truncated log excerpt.

### Documentation and update package

- English remains the default Markdown language (`.md`) and German remains available only through `.de.md` files.
- The updater validates `RELEASE_NOTES.md` and `RELEASE_NOTES.de.md`; no `.en.md` file is required.

### Verification

- Dashboard layout, German/English notification text, affected warning paths, JavaScript syntax and package documentation are covered by regression tests.

## v1.0.49

### System tab active state made visually reliable

- System tabs now use the dedicated `system-tab` class and are excluded from the generic primary-button styling that previously painted every tab identically.
- The selected tab uses explicit high-contrast colors for light and dark mode instead of relying on `color-mix()`.
- The active tab is marked with `active`, `aria-selected="true"` and `aria-current="page"`.
- Session restore, direct hash navigation and page reload continue to resynchronize the selected System area.

### English default Markdown documentation

- `README.md`, `INSTALLATION.md` and `RELEASE_NOTES.md` are now English by default.
- The complete German documents are named `README.de.md`, `INSTALLATION.de.md` and `RELEASE_NOTES.de.md`.
- The in-application release-note endpoint now reads the English default file and the German `.de.md` file explicitly.
- Because updater versions through v1.0.48 require the former `RELEASE_NOTES.en.md` filename, upgrading to v1.0.49 requires a one-time replacement of `update.sh` from the new ZIP before the normal update command.
- Build, update, tests and documentation references were adjusted to the new convention.

### Verification

- Active-tab CSS precedence, fixed light/dark active colors, reload synchronization, bilingual release-note loading and package documentation completeness are covered by regression tests.

## v1.0.48

### Reliable System tabs after page reload

- The System view is resynchronized with the current URL hash and user role after sign-in, automatic session restoration and page reload.
- The tab row therefore remains visible for direct links such as `#notifications`, `#users`, `#backups`, `#settings` and `#diagnostics`.
- The selected tab is now emphasized through both its active class and `aria-selected="true"`, using a visibly darker filled style.
- Administrator authorization remains unchanged; regular users still cannot access or see the System tabs.
- A new regression test prevents the tab row from disappearing again after a future reload-related change.

### Verification

- The project contains 404 automated tests; the new navigation tests and static checks pass.

## v1.0.47

### Sticky System navigation

- The five System tabs now live directly inside the sticky page header and remain visible while scrolling.
- The active area is shown as a dark filled tab; the mobile tab row remains horizontally scrollable.
- Existing direct links, administrator authorization and the active **System** sidebar state remain unchanged.

### Backup-job source statistics

- The Backup Jobs overview now shows original size, file count, timestamp and value origin below the configured source paths.
- After a successful or warning-completed backup, size and file count are taken directly from Borg's final statistics.
- **Refresh** and **More → Checks → Source statistics** start a repository-independent live scan on the source device. It never creates an archive and counts configured sources before Borg exclusions.
- The live scan runs as the same SSH user as the backup job, supports `one_file_system`, controlled cancellation and a `find`/`stat` fallback when Python 3 is unavailable.
- Changes to source paths, exclusions or relevant filesystem options automatically discard stale statistics.
- The database is migrated automatically with the source and file-count fields.

### File-style archive browser

- The archive browser now uses breadcrumb navigation and a file table.
- It shows name, size, type, permissions, owner/group and modification time.
- Directories sort first, symbolic links display their target and the visible entry count is shown.
- Metadata comes directly from `borg list --json-lines`; no FUSE mount is required.

### Verification

- 403 automated tests pass, including real live-scan, persistence, database migration, UI and archive-metadata tests.

## v1.0.46

### Centralized system administration areas

- Under **Infrastructure**, the sidebar now contains only **Devices** and **System**.
- The former **Notifications**, **Users**, **Manager Backup** and **Settings** sidebar entries have been removed and grouped under **System**.
- The System workspace provides a top tab row in the order **Notifications**, **Users**, **Manager Backup**, **Settings** and **System Diagnostics**.
- Switching among these five areas keeps **System** selected in the sidebar and the page heading consistently set to **System**.
- Existing direct hash URLs remain valid so bookmarks and internal links continue to work.

### Dashboard and responsive layout

- System diagnostics have been removed from the dashboard and moved into the dedicated **System Diagnostics** tab.
- The tab row remains horizontally scrollable on narrow screens and supports compact display density.
- Administrator authorization continues to protect all five system areas; read-only users following a direct URL are safely returned to the dashboard.
- Controller key management, notifications, user administration, manager backups and system settings retain their existing functions and APIs.

### Documentation and tests

- README, installation guide and the integrated German and English manuals now describe the new navigation and relocated diagnostics.
- New regression tests cover sidebar contents, tab order, active states, authorization, responsive behavior and the absence of diagnostics from the dashboard.
- The complete test suite contains 391 passing tests.

## v1.0.45

### Central notifications for backup and system events

- The new administrator-only **Notifications** area sends selected events through SMTP email, a generic JSON webhook, a Discord webhook or a Telegram bot.
- Configurable events include backup failures, backup warnings, optional success notifications, cancellations, repository actions, schedule failures and other manager runs.
- Every channel has a test action. Current form values are saved securely before testing, so no separate intermediate save is required.
- The delivery log shows channel, event, title, time and success or the concrete delivery error. It can be cleared independently of Borg run logs.

### Secure secret and execution handling

- SMTP password, webhook URL and Telegram bot token are stored only in encrypted form in the security database and are never returned to the Web UI.
- Stored secrets remain unchanged when their input is left blank and can be removed only through an explicit delete option.
- Delivery failures never change the Borg return code or run status. Repository, schedule and global execution slots are released before external services are contacted.
- Diagnostic excerpts are filtered and limited to 4,000 characters and can be disabled completely. Secrets contained in webhook or Telegram addresses are also removed from delivery errors.
- Generic webhooks receive structured JSON containing source, event, severity, title, message, run ID and UTC timestamp.

### Backup, documentation and tests

- Manager backups now include the non-secret notification settings; the corresponding secrets were already included through the backed-up security database.
- Restoring an older backup without notification configuration removes a newer local configuration so stale channels cannot remain active with a restored security database.
- README, installation guide and the integrated German and English manuals document setup, testing, event selection, security and failure behavior.
- The complete test suite contains 388 passing tests.

## v1.0.44

### Kept device and backup-job enabled states consistent

- Disabling a connected device now automatically disables every currently enabled backup job assigned to that device in the same database transaction.
- The cascade applies both to the direct **Disable** action in the device list and to saving an edited device with its enabled state cleared.
- Active or queued runs continue to block disabling, so no running Borg or SSH process is interrupted by a configuration-state change.
- Re-enabling the device intentionally leaves its backup jobs disabled. This prevents schedules from resuming unexpectedly after maintenance or an incident; the required jobs must be enabled explicitly.
- The confirmation dialog and success message state how many backup jobs are disabled together with the device.

### Documentation and tests

- README, installation guide and the integrated German and English help now document the cascade and the deliberate non-restoration of job enabled states.
- Regression coverage verifies the direct device control, the device edit form, active-run protection and the state after re-enabling the device.

## v1.0.43

### Upload manager backups through the Web UI

- The **Manager Backup** area now provides a dedicated upload for existing encrypted `.bbm` files and historical `.zip` manager backups.
- Upload uses a raw streaming transfer without an additional multipart dependency. File name and size are constrained before and during transfer.
- The manager validates the backup format before accepting it. Historical ZIP files pass the complete path, entry-count, size and compression checks; encrypted backups are checked for a valid BBM header, supported AES-256-GCM/scrypt parameters and a complete encrypted payload.
- Uploaded backups are stored atomically with mode `0600`. An existing file with the same name is never overwritten.
- An encrypted backup does not require its passphrase during upload; full cryptographic authentication still occurs immediately before restore.

### Enable or disable devices and backup jobs directly

- The **Connected Devices** table now includes a direct **Enable/Disable** action.
- Backup jobs provide the same control under **More → Management**.
- Active or queued runs block disabling so an active SSH or Borg process cannot be interrupted by a configuration change.
- Disabled devices retain their configuration but are removed from active schedules and managed repository access. Their jobs cannot be started manually either.
- Disabled jobs retain sources, options, retention and schedule assignments, but are not started manually or by schedules. Re-enabling automatically synchronizes scheduler configuration.

### Documentation and tests

- README, installation guide and the integrated German and English operations manuals were checked against the current feature set and updated for upload, enabled state, scheduler behavior, security limits and restore workflow.
- New regression tests cover upload validation, overwrite protection, direct enabled-state endpoints, active-run safeguards and CSP-compliant registration of the new controls.
- The complete test suite contains 379 passing tests.

## v1.0.42

### Restored portable startup of remote backup jobs

- The supervised remote wrapper used the GNU coreutils extension `env --default-signal` to reset inherited signal dispositions. Devices using BusyBox, older coreutils releases or another `env` implementation therefore failed before Borg started with `env: unrecognized option '--default-signal=HUP'`.
- The wrapper no longer depends on that non-portable `env` option. When Python 3 is available, a small launcher restores default handling for `HUP`, `INT` and `TERM`, unblocks those signals when supported, and then starts Borg through `exec`.
- When `setsid` is available, Borg still runs in its own process session so cancellation can stop the complete process group in a controlled way.
- Minimal devices using a standalone Borg binary without Python 3 remain supported: the job starts directly and uses `SIGTERM` as the portable first cancellation signal. The failing GNU `env` option is never used.

### Tests

- A regression test provides an intentionally incompatible `env` implementation that rejects every `--default-signal` option. The remote backup command still starts successfully.
- The existing supervised remote cancellation test continues to verify signal delivery and confirmed process exit before the queue slot is released.
- The complete test suite contains 373 passing tests.

## v1.0.41

### Fixed manager-side repository actions under the unprivileged Web process

- The Web API has run as user `borg` since the security hardening release. Manager-side Borg calls still prepended `runuser -u borg`; however, `runuser` may only be invoked by root and therefore failed with `runuser: may not be used by non-root users`.
- Repository validation, archive listings and information, compact, check, deletion, size queries and other Borg commands executed directly by the Manager now run directly when the process is already unprivileged. Only an actual root caller continues to use `runuser`.
- Repository validation therefore reaches Borg again, and archive refresh receives the expected JSON instead of the preceding `runuser` error.

### Adapted system diagnostics to the root/borg service split

- Repository R/W/X, log directory, borg-serve wrapper and `authorized_keys` are checked with the Web API's actual permissions without an invalid second user switch.
- `sshd -t` remains a root-only check. The entrypoint performs it before startup and exposes the successful result through a root-controlled runtime marker readable by the Web API.
- Diagnostics no longer report false failures merely because `runuser` was invoked by a non-root process or because the Web API cannot read the root-owned SSH host private key.

### Tests

- Regression coverage verifies root and non-root command construction, manager-side repository commands without `runuser` in the Web process, and hand-off of root sshd validation to unprivileged diagnostics.
- The complete test suite contains 370 passing tests.

## v1.0.40

### Restored CSP-compliant Web UI controls

- The strict Content Security Policy from the security update remains enabled and still does not allow JavaScript `unsafe-inline`.
- All dynamically generated HTML handlers such as `onclick=...` have been removed. User editing, the job **More** button, dashboard metrics, run details, repository actions, and device, schedule and archive navigation now use central event delegation.
- Every dynamic action must be registered in a fixed handler whitelist. Parameters are transported as HTML-escaped JSON in `data-bbm-*` attributes and processed without `eval` or dynamic code execution.
- A failure in one UI action is logged and displayed without disabling the page-wide action dispatcher.

### More robust Borg JSON processing

- Borg information and archive lists are still parsed as exact JSON whenever possible.
- If Borg, OpenSSH, `runuser` or the supervised process wrapper adds harmless informational lines before or after the document, the manager now extracts a complete Borg JSON object with expected top-level fields.
- Archive requests consider both stdout and stderr. Output without a valid Borg document is still rejected.
- This prevents “Borg information output is not valid JSON” from being raised solely because of additional wrapper or SSH output.

### Tests

- Regression tests prohibit dynamic inline event handlers, verify every used UI action against the fixed whitelist, and preserve the strict CSP.
- Additional tests cover Borg JSON with leading and trailing informational text and the unchanged rejection of genuine non-JSON output.
- The complete test suite contains 367 passing tests.

## v1.0.39

### Fixed container startup after the security privilege split

- The root entrypoint still materializes TLS and repository SSH keys below `/run/bbm-secrets` before privileges are dropped.
- The Web API, which then runs as user `borg`, no longer repeats that root-only operation. This prevents `PermissionError: Operation not permitted: /run/bbm-secrets` during startup.
- Runtime materialization is additionally idempotent: unchanged root-owned private runtime files are neither overwritten nor chmodded by an unprivileged follow-up process.
- Direct development and test starts without the entrypoint continue to bootstrap security material themselves.

### Tests

- Regression coverage verifies the root/non-root hand-off, the entrypoint marker and preservation of the root-owned SSH host key. The complete test suite contains 363 passing tests.

## v1.0.38

### Security update

- FastAPI has been updated to 0.139.2; the fully pinned runtime resolution uses Starlette 1.3.1 and removes the unauthenticated Range-header denial-of-service vulnerability in the previous version.
- Sign-in now has persistent source and source/user limits before expensive Scrypt verification. Failed attempts no longer lock an account globally, and security events have time and row-count retention limits.
- Browser mutations require an application-specific anti-CSRF header and, when present, an exact Origin match. Cookies default to Secure, HttpOnly and SameSite=Strict; sessions also have an idle timeout.
- `Forwarded` and `X-Forwarded-*` headers are accepted only from networks in `BBM_TRUSTED_PROXY_CIDRS`. Uvicorn starts with `--no-proxy-headers`.
- New manager backups must be encrypted and use passphrases of at least twelve characters. Web UI restore creates a separately encrypted safety backup first. Existing ZIP backups remain restorable.
- Restore validation blocks path traversal in `permissions.json`, symbolic links, duplicate paths, oversized packages, excessive entry counts and invalid compression ratios.
- Process-control environment variables including `PATH`, `HOME`, `LD_PRELOAD`, `PYTHONPATH`, `BASH_ENV` and SSH agent variables can no longer be configured as repository extras.
- The Web API runs as the `borg` user inside the container while SSH host private keys remain root-owned. OpenSSH uses `StrictModes yes`, Compose enables `no-new-privileges`, and the official Python 3.13.14-slim-trixie multi-platform image is pinned by digest. Runtime packages and their amd64/arm64 wheels are locked by SHA-256 and installed with `--require-hashes`.
- The public readiness response now contains only `status`; detailed information remains behind authenticated diagnostics endpoints.
- The normal `user` role is now a read-only viewer for the dashboard, lists and summarized run status. Full logs, archives, restore/export/mount, manual runs and all configuration changes require an administrator.
- The updater reads release contents only after a successful SHA-256 comparison. Explicit updates require `--sha256`, `BBM_UPDATE_SHA256` or a matching `.sha256` sidecar; automatic discovery considers only ZIP files with a valid sidecar checksum.

### Compatibility and tests

- Existing repositories, jobs, schedules, devices, users and legacy manager backups remain compatible. `update.sh` automatically adds missing new `.env` values.
- Dedicated security regression tests cover anti-CSRF/origin protection, rate limiting, idle expiry, restore traversal, archive limits, mandatory backup encryption, environment-variable blocking and container hardening.

## v1.0.37

### Repository ID shown directly in the overview

- The repository table now displays the numeric manager ID of every repository record in a dedicated column directly beside its status. This is the same ID used in BBM cache paths such as `/data/borg-cache/repository-<ID>` and `$HOME/.cache/borgbackup-manager/repository-<ID>`.
- The status column is narrower on wide layouts. The new ID column is intentionally compact and displays values as `#<ID>`.
- Padding between the size and action columns has been reduced so the additional information fits without unnecessary table width.
- In the responsive card layout, the ID remains visible as its own labelled row.

### Tests

- Regression coverage verifies the new column order, ID output, desktop widths, tighter spacing and the English label.

## v1.0.36

### Fixed HTTP 504 responses while testing external repositories

- **Test Connection** no longer performs a potentially long Borg command inside the HTTP request. The test is queued as a normal repository run, returns a run ID immediately, and can be followed in the live log. A reverse proxy can therefore no longer terminate the Borg operation with an HTTP 504 response.
- In the supervised remote wrapper introduced in version 1.0.35, the separate `cat` process watching the control channel could survive after Borg had completed successfully. It kept SSH and HTTP pipes open even though Borg had already exited. The watchdog now uses only a shell `read` loop and terminates reliably with the wrapper.
- Repository tests use the same repository queue and global concurrency limits as other manager actions.

### Isolated Borg caches per repository

- Manager-side Borg commands now use a dedicated cache for each repository record below `/data/borg-cache/repository-<ID>` instead of a shared cache root.
- Borg commands on a source device use a BBM-private cache below `$HOME/.cache/borgbackup-manager/repository-<ID>`. For the SSH user `root`, `$HOME` is `/root`; the previously visible path `/root/.cache/borg/<Repository-ID>/lock.exclusive` was therefore a local client-cache lock, not a repository lock.
- Manually executed Borg commands and older BBM versions using the general `$HOME/.cache/borg` can no longer block new manager runs through a stale cache lock there.
- After the Borg process has demonstrably exited, the remote wrapper removes only remaining lock files from its private BBM cache. Repository locks and the user's general Borg cache are never modified.

### Hardened cache cleanup and diagnostics

- **Clear Cache** removes the repository-scoped manager cache directly from the filesystem. Cleanup no longer needs to start Borg and can therefore repair a cache whose own `lock.exclusive` prevents Borg from starting.
- Managed repositories additionally clean known legacy cache locations from earlier versions. Legacy external cache data remains unused and cannot block new tests or jobs.
- Run diagnostics now distinguish a local cache lock on the source device from a real repository lock. For `/root/.cache/...`, the message explicitly explains that `/root` is the home directory of the SSH user and that `borg break-lock` must not be used for this condition.

### Tests

- Regression coverage includes the formerly orphaned watchdog process, asynchronously queued connection tests, separate manager and device caches, direct cache cleanup, and unambiguous cache-lock diagnostics.
- The complete test suite contains 345 passing tests.

## v1.0.35

### Reliably release external repository locks when cancelling a job

- Backup commands carrying temporary repository credentials now use a supervised cancellation channel between the manager and the device. The channel remains open after the one-time secret payload and is used only for controlled process shutdown.
- Cancellation no longer starts by merely terminating the local SSH client. The remote wrapper detects closure of the control channel, sends `SIGINT` to the complete Borg process group on the device, and waits for the process to actually finish.
- Borg therefore gets an opportunity to close its checkpoint, cache and repository lock for external SSH repositories before the manager connection and repository queue slot are released.
- Non-interactive shells can pass an ignored `SIGINT` disposition to background processes. The wrapper explicitly restores default handling for `HUP`, `INT` and `TERM` before starting Borg in a separate session.
- If Borg does not react within the controlled shutdown window, the existing `SIGTERM` and `SIGKILL` escalation remains available as a fallback. Run logs distinguish confirmed remote cleanup from forced termination.
- Automatic `borg break-lock` remains intentionally disabled because a legitimate client outside the manager may still be using an external repository.

### Tests

- A new regression test keeps the control channel open, cancels the run, and verifies that the supervised remote wrapper actually terminates the encapsulated process group with `SIGINT`.
- The complete test suite contains 341 passing tests.

## v1.0.34

### Global and per-schedule concurrency limits

- **Settings → Concurrency limits** now provides a global cap from 1 to 64 concurrently running manager executions. `0` keeps parallel work across different repositories unlimited as before.
- Every central schedule also has an optional individual cap. `0` uses only the global limit; a schedule value of `1`, for example, queues backups for multiple devices and different repositories one after another.
- Repository serialization remains a hard rule independently of these limits: no more than one Borg action can run against the same actual repository target.
- Global, schedule and repository limits are evaluated together. The narrowest applicable limit determines admission.
- The queue fills free global slots with eligible runs and skips older entries that are themselves waiting for a busy repository or schedule. Independent capacity therefore remains usable.
- Run logs clearly state whether a run is waiting for the repository, the schedule cap or the global concurrency cap.

### Queue protected against orphaned run state

- Only live manager tasks consume concurrency slots. Orphaned `queued` or `running` database rows can no longer block the global queue indefinitely after an interrupted task.
- Live-run registration is cleaned up reliably on every exit path, including early returns and cancellation.
- Finished tasks and invalid task placeholders are removed while building the execution plan.

### Persistent sorting for central lists

- The dashboard backup-job block, full Backup Jobs list, Repositories and Connected Devices each provide dedicated sort selectors.
- Depending on the list, options include name, status, device, repository, last run, size, type, job count, address and Borg version.
- The selection is stored per signed-in user and browser and restored automatically.

### Database, configuration and tests

- Existing installations automatically receive additive fields for schedule limits and run snapshots.
- `BBM_MAX_PARALLEL_RUNS` can define the initial global default; the Web UI setting is then persisted.
- Regression coverage includes global serialization across different repositories, per-schedule caps, free capacity despite an older blocked run, orphaned state, migration and sorting UI.

## v1.0.33

### Harden repository queueing against Borg lock conflicts

- Repository actions now pass a database-backed FIFO admission gate before process start in addition to the local `asyncio` lock. A run therefore remains **Queued** until every older action for the same repository target has finished.
- Queue identity is based on the actual managed directory or external repository URL instead of only the repository database ID. Legacy duplicate records addressing the same physical target are serialized together.
- FIFO admission is checked again after the local lock is acquired, protecting against concurrent starts across different event loops or application contexts.
- The complete run log identifies the blocking run, for example `QUEUE: waiting for repository run #123` in the localized interface.

### Queue relocated-repository confirmation safely

- **Confirm changed repository location** now uses `--lock-wait 600`, consistent with normal Borg operations, instead of the previous 30-second limit.
- Multiple confirmations for the same device and repository are deduplicated. Starting the action from another job on that device reuses the already queued or running run instead of creating a duplicate Borg process.
- Confirmations for different devices remain separate runs but execute strictly one after another on the shared repository.
- If Borg still cannot acquire the lock after 600 seconds, diagnostics now distinguish a functioning manager queue from an external or stale Borg lock. Automatic `break-lock` remains intentionally disabled.

### Regression coverage

- Tests cover FIFO serialization without a shared in-memory lock, duplicate database records pointing at the same physical repository, and deduplication of repeated location confirmations.

## v1.0.32

### Safely reset a deleted managed repository

- Managed repositories are now checked against the actual Borg state in the target directory. A previously stored `initialized=true` can no longer present a missing Borg `config` as ready.
- Affected entries are marked **Repository missing** and expose the new administrator action **Reset**.
- Reset is permitted only for managed repositories whose target is a direct directory below the repository root, contains no Borg `config`, and is completely empty.
- The function never deletes repository files. Existing files, partial remnants, symbolic links, active archive mounts, and queued or running repository operations cause a safe refusal.
- Initialization, validation, and size metadata plus the persistent archive cache are cleared. Jobs, schedules, device assignments, passphrase, and the repository registration remain intact.
- For keyfile encryption, the key belonging to the deleted repository ID is removed; the next initialization creates and stores a new key.
- Every successful reset is recorded as a dedicated `repository-reset` run explicitly stating that no files were deleted.

### Block operations when the repository structure is missing

- Backup, prune, compact, archive, size, and cache actions are no longer enabled solely from the database flag.
- Repository and backup-job views use the actually present Borg configuration and show a clear warning until reset and reinitialization are complete.
- The initialization endpoint now requests the required reset for stale manager state instead of returning the contradictory “already initialized” message.

## v1.0.31

### Persist warning causes before log truncation

- Borg warnings are now collected line by line from `stdout` and `stderr` while the process is running.
- Split process chunks are reassembled correctly, so warning lines remain available even when very large file lists or statistics follow.
- The structured warning summary is stored in a dedicated run field and no longer depends on SQLite previews, the 256 KiB diagnostic tail or the truncated live-log view.
- The Web UI can show detected causes while a backup is still running.
- Existing runs without a stored summary continue to use retrospective log parsing.

### Honest fallback for Borg rc 1 without a detail line

- If Borg truly emits only `terminating with warning status, rc 1`, the Web UI no longer presents a seemingly concrete diagnosis.
- The run is explicitly marked as “Cause not emitted” and includes an appropriate recommendation.
- Additional forms such as `Remote: C <path>` and unmatched include/exclude patterns are recognized.

### Database and tests

- Existing installations automatically receive the additive `runs.warning_summary_json` column on startup.
- Regression coverage simulates an early warning split across two chunks followed by more than 300 KiB of output.
- API, migration, parser and UI fallback tests were added.

## v1.0.30

### Repository-wide archive deletion

- Archives are first assigned to the correct job and device through current or historic archive series.
- For legacy and foreign archives, the manager additionally compares the Borg hostname and the device name inferred from the archive name.
- The archive list supports single and multiple selection, including “Select visible archives” for the active filter.
- All selected archives are handled by one shared safety confirmation and one repository-wide run.
- When archives from different devices are selected, the confirmation, response and run log clearly show “Multiple devices”.
- The unsafe fallback to the repository's first job has been removed. Deletion no longer requires a backup job; restore and rename still require an unambiguous job/device assignment.
- Every exact archive name is verified directly in the repository before the run starts. Selected mounted archives and active or queued repository operations block the request.
- Compact can optionally run exactly once after the complete deletion series.

### Compact directly on the repository

- Administrators can start Compact from the repository list even when no backup job exists.
- The action uses manager-local repository access, the repository-wide lock and a regular run log.
- Active archive mounts and running or queued operations for the same repository prevent a parallel start.

### Cache, logging and integration

- After an archive deletion has started, its archive cache is invalidated even on cancellation or failure because a multi-delete may already have been partially effective.
- Repository-wide runs store the repository or device in the run header; mixed deletions are recorded as “Multiple devices”.
- German and English UI resources, operations manuals, README and installation guide were updated.
- Regression tests cover input validation, exact Borg commands, one-time Compact, concurrency guards, device resolution, multiple selection and the new API/UI paths.

## v1.0.29

### Concrete causes for Borg warnings

- Backup runs with Borg return code `1` no longer show only `terminating with warning status, rc 1`.
- The manager evaluates Borg item-status lines and warning messages as structured causes.
- Status `C` is shown as “file changed during backup” together with the affected path.
- Status `E`, disappeared files, permission errors and I/O errors are reported separately.
- The run dialog contains a compact, bounded and separately scrollable “Warning causes” section.
- The run list shows a readable summary such as “1 file changed during the backup”.

### Warning-relevant logging without a full file list

- When “Show processed files in the live log” is disabled, the backup command internally uses `--list --filter CE`.
- This records only warning-relevant item statuses without filling the log with every unchanged file.
- The filtered error/warning preview stored in SQLite was increased from 8 KiB to 32 KiB so multiple affected paths remain available.
- Complete live logs remain stored unchanged under `/data/run-logs`.

### Tests and documentation

- Added regression coverage for changed, unreadable, disappeared and permission-denied files.
- Updated the German and English manuals and technical documentation.

## v1.0.28

- Fixes the entire Web UI freezing after updating to the first bilingual release.
- The translation layer now writes text and attribute values only when the target value actually differs.
- Prevents a self-triggered `MutationObserver` loop that blocked sign-in and navigation.
- Adds a regression test for mutation-stable translations.

## v1.0.27

### Fixed the update build from v1.0.25 to v1.0.26

- Fixed the Docker build failure reporting `RELEASE_NOTES.en.md: not found`.
- The failure was caused by the transition between the still-running v1.0.25 updater and the v1.0.26 Dockerfile: the old updater did not copy the newly introduced top-level English release-notes file, while the new Dockerfile already required it.
- The image build now relies on `app/RELEASE_NOTES.en.md`, which is transferred reliably because old updaters replace the complete `app` directory.
- The top-level `RELEASE_NOTES.en.md` remains part of the release and is copied by current updaters, but it is no longer a hard image-build dependency.
- A regression test simulates the exact v1.0.25 updater whitelist and validates the resulting Docker build context.

### Lock release after cancelling a task

- Cancellation now targets the complete process group instead of only the immediate parent process.
- Borg receives `SIGINT` first so it can terminate cleanly and release repository and cache locks.
- The manager escalates to `SIGTERM` and finally `SIGKILL` only if the process group does not respond.
- The cancellation API waits for process cleanup before reporting completion.
- Automatic `borg break-lock` remains disabled because shared repositories may be used by independent clients.
- Regression tests cover process-group signalling and the API cancellation path.

## v1.0.26

### Direct live-log access from the header

- The header status control no longer opens an intermediate task menu.
- A click always opens the live log of the currently running task.
- When no task is running yet, the next queued task is opened.
- Additional active tasks are indicated by a compact `+N` count without changing the click target.

### Personal language and theme preferences

- German and English are available for every user account.
- Language and theme (`automatic`, `light`, or `dark`) are stored per user in the security database.
- The header theme button changes only the current user's preference.
- The system settings no longer modify a global theme.
- Static pages, dynamically rendered tables, forms, dialogs, status messages, the manual and current release notes are translated.

### Manual audit

- The integrated operations manual was audited against the complete current feature set.
- Separate German and English manuals cover installation flow, authentication, dashboard, devices, repositories, jobs, schedules, runs, archives, restore, manager backups, users, settings, diagnostics and mobile operation.
- Invalid HTML nesting in the previous archive chapter was removed.

### Tests and migration

- Additive security-store migration adds `language` and `appearance` columns to existing users.
- Existing users default to German and automatic theme.
- Regression tests cover direct active-run selection, personal preferences, translations and both manual variants.

## v1.0.25

- Backup-job actions were made more compact and grouped by purpose.
- Active tasks were added to the header status area with live-log links.

## v1.0.24

- Fixed the JavaScript startup error introduced in v1.0.18 that prevented session restoration after page reload.

## v1.0.23

- Added a tab-bound reload session as a fallback when browsers do not return the HttpOnly cookie.

## v1.0.22

- Removed an invalid in-place edit of the bind-mounted host `.env` file and improved update health-check output.

## v1.0.21

- Improved reverse-proxy scheme detection and session-cookie configuration.

## v1.0.20

- Limited local sign-out to actual HTTP 401 responses and moved controller-key rotation to Settings.

## v1.0.19

- Improved session cookie handling, controller-key copying and inline fingerprint confirmation.

## v1.0.18

- Moved repository-access setup to backup jobs, added direct dashboard starts and improved the live-log dialog.

## v1.0.17

- Shortened Borg error output, enabled verbose compact statistics and added the dashboard backup-job table.

## v1.0.16

- Added per-repository storage guards and filesystem-aware diagnostics for multiple mounted repositories.

## v1.0.15

- Fixed installer variable initialization and strengthened all management scripts.

## v1.0.14

- Expanded archive-name recognition and audited `.env.example`, install, update and restore scripts.

## v1.0.13

- Added newest-first archive sorting, device-name filtering, dashboard cleanup and better diagnostics handling.

## v1.0.12

- Added the persistent repository archive-list cache and schedule-completion size refresh.

## v1.0.11

- Added action-specific completion tracking and targeted UI refreshes.

## v1.0.10

- Fixed update backups that could include repository mounts and added explicit relocated-repository confirmation.

Earlier releases established the core repository, device, job, archive, restore, scheduling, security and update functionality. The complete historic German changelog remains available in `RELEASE_NOTES.md` in the release package.
