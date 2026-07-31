# Release Notes

## v1.2.3 – 31.07.2026

### Bilingual `.env` reference for the GHCR Compose stack

- The `docker-compose/` directory now also contains `README.md` and `README.de.md`. Both guides document every variable in the image-only `.env`, including required values, valid ranges, defaults, host paths, UID/GID permissions, TLS, sessions, reverse-proxy trust, sign-in throttling, restore safety limits, parallelism, and log rotation.
- The reference marks `BBM_REPOSITORY_PUBLIC_HOST` as mandatory and separately highlights the image tag, ports, certificate names, persistent paths, numeric repository permissions, and one-time administrator output that should be reviewed before first start.
- The root README files and installation guides link to the new language-specific references; `.env.example` and `compose.yaml` also point directly to the detailed documentation.
- The empty runtime `data/` directory accidentally included in the previous project archive has been removed. Release checks, project audit, and regression tests now reject the top-level runtime directories `data/` and `repositories/`, including empty directory trees.

## v1.2.2 – 30.07.2026

### Standalone GHCR deployment and safe repository first-start initialization

- The release now includes `docker-compose/` with a dedicated `compose.yaml` and `.env.example` for the published image. It uses `ghcr.io/the-ab/borgbackup-manager:${BBM_IMAGE_TAG}` with either `latest` or a pinned tag such as `v1.2.2`, requiring neither the project source tree nor `install.sh` on the Docker host.
- README and installation guides now describe local source builds and image-only deployments as separate operating modes, including startup, updates, initial sign-in and persistent host paths.
- A genuinely new installation through the GHCR Compose profile writes the administrator username and temporary password exactly once to the local container startup log. `BBM_SHOW_INITIAL_ADMIN_ON_START` controls this behavior, while encrypted manual retrieval remains available until the mandatory password change.
- Before the existing access check, `docker/entrypoint.sh` initializes a fresh empty `/repositories` mount that Docker created as `root` for the configured `BBM_BORG_UID:BBM_BORG_GID`. Only the mount root is changed; existing contents are never recursively re-owned.
- Non-empty or safely uninspectable repository directories remain unchanged and continue to produce a clear permission diagnostic. ACLs, group access and NFS UID/GID mappings remain respected.
- The obsolete `BBM_DEBUG_LOG_LEVEL` variable was removed from the remaining example configurations.
- The updater now recognizes and preserves the new top-level `docker-compose/` directory for future release transitions.

## v1.2.1 – 29.07.2026

### Size-based ETA fallback, list search and modal editing

- When a running backup exceeds only the frozen file-count baseline, the remaining-time estimate now stays active. From that point it uses only the still-valid size baseline and the fixed effective 1-Gbit/s throughput; no file factor is applied without a reliable remaining-file count.
- **Source baseline exceeded** is shown for remaining time only after the stored source size has also been exceeded. Progress and ETA therefore remain useful longer when many new small files have appeared.
- The repository list now adds search by name, manager ID, type, path and encryption alongside sorting. Connected devices can be searched by name, address, SSH user, port and Borg version.
- **Edit** for backup jobs, repositories and connected devices opens a dedicated modal dialog. The existing validated form is reused, preserving fingerprint checks and repository-secret handling.
- An equal-height placeholder keeps the original list position stable. After save, cancel, close or Escape, the form returns to its original location and the page stays at the previously selected table row.
- The edit dialog has its own vertical scrolling area on desktop and mobile and locks background-page scrolling while open.

## v1.2.0 – 28.07.2026

### Debug log restricted to real incidents

- The previous size rule was removed: long but normal backup output and source-statistics scans are no longer treated as technical failures merely because of their length and are no longer copied to `/data/logs/debug.log`.
- The debug log now acts strictly as an incident log. It records unexpected tracebacks, unhandled application/background failures, critical framework or system errors, and application-side HTTP 5xx responses. Ordinary INFO/WARNING records remain excluded even when an older installation still sets `BBM_DEBUG_LOG_LEVEL`.
- Application-side HTTP errors 500, 502, 503 and 504 are recorded with method, path, status and error ID. Existing `BBM-...` references are not logged a second time.
- The browser safeguard now detects only actual traceback/framework patterns. A merely long error message is no longer incorrectly replaced by the generic debug-log notice.
- The short red notice after a failed or cancelled run now disappears automatically after six seconds. It can still be closed with `×` during that interval; other actionable error notices remain visible until closed.
- Regression tests and the project audit cover exclusion of normal backup/source-statistics output, fixed incident filtering, HTTP 504 logging and the six-second run-notice timeout.

## v1.1.10 – 28.07.2026

### Central traceback logging and compact browser errors

- Unexpected HTTP and background failures now receive a short `BBM-...` error ID. The browser and run status show only the compact reference; the complete traceback is written to `/data/logs/debug.log` under the same ID.
- HTTP errors containing Python tracebacks, framework internals or unusually large technical payloads are sanitized centrally. Expected validation and compact Borg diagnostic messages remain specific and actionable.
- Existing repository import no longer sends raw Borg/Python tracebacks to the browser. Unexpected import failures are logged completely before the temporary repository registration and secrets are removed.
- Backup runs, repository initialization, archive scans, manual maintenance chains, scheduled queueing, manager/cache backup workers and notification delivery failures now preserve unexpected tracebacks in the debug log instead of exposing or discarding them.
- Red WebUI error notices no longer disappear automatically. They remain readable until explicitly closed; an additional client-side guard replaces any leaked traceback-sized response with the compact debug-log hint.
- Project audit and regression tests now protect the centralized error boundary, traceback persistence, error-ID response, persistent error toast and repository-import behavior.

## v1.1.9 – 28.07.2026

### External filesystem parallelism and wider archive statistics

- **Settings → Parallel limits** can now also limit detected external SSH filesystems. Multiple external Borg repositories using the same SSH identity and the same filesystem detected by `df` share one limit; `0` means unlimited.
- Queue planning and direct manager-side Borg calls use the same external filesystem group. Each repository itself remains limited to one execution.
- External groups appear after a successful filesystem probe or after loading System Diagnostics. Without a detected remote mount, safe per-repository serialization remains in effect.
- **System Diagnostics → Repository filesystems** now shows the configured limit and active/queued runs for external filesystems as well.
- The archive overview now gives **Duration** and **Files** wider columns and more separation so long durations no longer overlap the file count.

## v1.1.8 – 28.07.2026

### Archive-scan mount capacity is released and checkpoint display is simplified

- Direct manager-side Borg calls did not release their reserved mount capacity after completion. After the first archive scan an invisible mount slot therefore remained occupied, and a later scan could wait indefinitely until the container was restarted.
- Mount capacity is now released reliably in the `finally` path after success, warning, failure or cancellation.
- A checkpoint-enabled scan could deadlock itself with mount limit `1`: `borg info` kept the slot while the following `borg list --consider-checkpoints` waited for that same slot. This self-deadlock is fixed.
- The normal archive overview continues to show detected checkpoint archives automatically and marks them as incomplete. Checkpoint metadata is now retained directly from `borg info`, and the resulting cache can be reused immediately for deliberate restore selection. The redundant **Show incomplete checkpoint archives** option was removed from this view.
- Restore keeps its separate checkpoint opt-in so restoring from an incomplete archive remains a deliberate action.
- Regression tests cover mount-capacity release and prevent the redundant archive-overview checkpoint control from returning.

## v1.1.7 – 28.07.2026

### Archive deletion becomes immediately visible on large repositories

- Repository-wide archive deletion no longer performs a synchronous full `borg list` scan inside the HTTP request before creating a run. On large repositories the UI could otherwise remain on **Deletion is starting …** or hit an HTTP/reverse-proxy timeout before any visible execution existed.
- Selected archive names remain strictly validated. Existing cache metadata is now used only for the device/run label, after which the exact Borg deletion is queued immediately as a normal repository run.
- A stale archive cache or an archive already removed outside the manager is reported by Borg in the visible deletion run. The browser is no longer blocked before a run ID is created.
- The WebUI starts status tracking, toast feedback and the live run log immediately after receiving the run ID. Dashboard and execution-list refreshes happen afterwards.
- Repository exclusivity, mounted-archive protection, optional single compact execution and cache invalidation after potentially partial failed deletion remain unchanged.
- The project audit now prevents synchronous repository scans from returning to the archive-delete endpoint and verifies that the live run opens before secondary view refreshes.

## v1.1.6 – 28.07.2026

### Mount parallelism now uses one authoritative queue decision

- Persisted backup and repository runs no longer reserve mount capacity twice. Up to v1.1.5, a process-local mount limiter was acquired before the database-backed queue decision. Under real mount/path conditions this could still leave only one run active even when the effective mount limit was `2`.
- Global, schedule, mount and repository limits are now assigned atomically by the database-backed FIFO execution plan alone. A second eligible job targeting another repository on the same mount can therefore use the second mount slot.
- The additional runtime repository lock is acquired only after queue admission and is scoped to one repository database record. It now only coordinates direct interactive Borg calls for that repository and cannot silently serialize distinct repositories on the same mount.
- Physical repository exclusivity remains enforced by the queue plan: multiple jobs targeting the same actual Borg repository still never run concurrently.
- **System diagnostics → Repository filesystems** now shows current occupancy beside the effective limit as `active X · queued Y`, making it immediately visible whether the mount itself is full or another layer blocks a run.
- Added regression coverage proving that persisted runs no longer request a second process-local mount slot and that two distinct repositories run concurrently with mount limit `2`.

## v1.1.5 – 28.07.2026

### Live mount-limit updates and clearer diagnostics

- Fixed a stale process-local mount semaphore that could keep an old limit of `1` even after the administrator changed the mount to `2`. With a continuously occupied queue, the previous semaphore might never become fully idle and therefore never adopt the new limit.
- Mount capacity now uses a live-resizable limiter. Waiting runs reload the configured mount limit every 250 ms, so increases, reductions and switching to `0` (unlimited) take effect without draining the entire mount queue first.
- The database-backed queue planner remains authoritative: `0` for the global limit is still unlimited, source-statistics limit `1` applies only to manual source scans, and different repositories on a mount with limit `2` can run concurrently.
- **System diagnostics → Repository filesystems** now shows the effective parallel limit for every detected managed mount. The diagnostics header also reports the global and source-statistics limits, making path mismatches or unexpected serialization easier to identify.
- External repository filesystems are marked as not applicable for managed-mount limits because they remain serialized by repository identity.
- Added regression coverage for raising a mount limit from `1` to `2` while one run is active and another is already waiting.

## v1.1.4 – 28.07.2026

### Exclusion-optimized source scan and unambiguous parallelism

- The preferred manual source-statistics scanner now evaluates path-based Borg exclusion patterns before `stat()`. Excluded files and complete directory trees therefore avoid unnecessary metadata requests, especially on NFS/CIFS sources. `CACHEDIR.TAG`, `nodump` and **one file system per source** remain fully effective.
- Paths rejected before metadata lookup are counted separately. Read/access warnings, patterns that cannot be mirrored safely, unavailable `nodump` checks or the `find/stat` fallback are exposed as concrete limitations. A normal complete scan no longer shows a quality level.
- The source-statistics line is now compact: normal results show only **Exclusion-aware source scan · date/time** or **Latest backup · date/time**. Source count, **high quality** and **observed from the latest Borg run** are removed; real limitations remain visible with their cause.
- Every physical Borg repository now has exactly one fixed execution slot. The former repository setting **Maximum parallel backup runs** was removed from the WebUI, API, data model and current documentation because Borg already serializes writing operations on the same repository.
- Mount limits independently control different repositories on the same filesystem. With a mount limit of `2`, two different repositories may run concurrently and a third waits. Runs targeting the same repository always remain serialized.
- Unneeded progress-history and observed per-source-statistics helpers were removed. Live status retains only the latest Borg progress frame; the fixed remaining-time calculation and current-source display require no rolling history.
- The project audit now also verifies pre-`stat()` exclusion checks, fixed repository exclusivity, removal of the old repository parallelism setting, compact source-statistics output and absence of obsolete progress-history logic.

## v1.1.3 – 27.07.2026

### Unified modern button design

- Restored the global base rule for normal action buttons that was accidentally removed during the v1.1.2 cleanup. Unclassified action buttons therefore no longer fall back to browser-default styling.
- Normal action buttons now use one shared design system for height, padding, radius, typography, focus presentation and hover/active/disabled states.
- Primary, secondary and danger/ghost variants share the same base geometry and interaction model; compact table and job actions keep only their intentionally reduced density.
- Navigation, tabs, link-style controls, breadcrumbs and status pills keep their role-specific presentation while still using common focus and transition behavior.
- The project audit now explicitly guards the shared button foundation so a future cleanup cannot remove this dynamically used CSS rule as an apparent orphan again.

## v1.1.2 – 27.07.2026

### Consistency and cleanup release

- Synchronized the current version and feature descriptions across README, installation guides, integrated DE/EN help, static asset markers and release metadata. The installation guides now describe the v1.1.1 cache-only archive view/background repository scan, current Borg-cache inspection scope and the deterministic 1-Gbit/s remaining-time model.
- Completed the English archive-scan translations and consolidated the translation dictionary so duplicate keys can no longer silently override earlier values. Obsolete archive-refresh strings were removed.
- Removed verified dead private helpers, an unused schema type, unused imports/constants and obsolete CSS selectors that had no references in the current HTML/JavaScript/help surfaces. Compatibility helpers that still have an explicit supported purpose remain in place.
- Removed the redundant `app/VERSION`; the project now has a single authoritative root `VERSION` file. Old-updater compatibility copies of the release notes remain intentionally duplicated and are still checked byte-for-byte.
- The fixed 1-Gbit/s remaining-time calculation no longer copies the bounded Borg progress history on every live-status poll. That history remains process-local only for current-source attribution and post-run per-source statistics.
- Legacy manager-backup cache fields are no longer part of the current request schema. Unknown legacy fields are rejected explicitly instead of being silently accepted.
- Expanded `scripts/project-audit.py` to validate version/document markers, redundant version files, duplicate translation keys, selected current UI translations, dead private top-level definitions, unused imports, unreferenced static assets/CSS classes and release-note compatibility copies.
- The release-check test phase now runs Pytest as a normal subprocess inside an isolated temporary data directory. This avoids test runtime data in the project tree and makes the release check match the standalone test execution path.
- Runner command tests now initialize their own temporary security store and validate resolved manager-cache paths explicitly, removing a hidden dependency on earlier test modules and their initialization order.

## v1.1.1 – 27.07.2026

### Large repository archive lists without HTTP 504

- **Reload from Repository** no longer performs the potentially long repository-wide Borg scan inside the HTTP request. It now queues a normal background run with its own run ID and returns immediately to the Web UI.
- **Show Archives** is now strictly cache-only: when `/data/archive-cache` does not exist yet, no hidden `borg info`/`borg list` request is started. The UI instead explains that a repository scan must be run first.
- The background run still uses `borg info --json --glob-archives '*'` and adds `borg list --json` when checkpoint visibility or a compatibility fallback requires it. Both steps use the existing repository and manager-cache locks and can be cancelled cleanly.
- After successful completion the persistent archive cache is written atomically and an open archive view reloads automatically. Existing cached data remains visible while a refresh is running.
- The large Borg JSON stream is not duplicated into SQLite or the run log. Only compact status/error information is stored there; normalized archive metadata is written only to the regenerable archive cache.
- The shared `borg list --json` parser was moved from the API module into the Borg statistics layer so synchronous exact checks and the queued refresh use the same normalization.

## v1.1.0 – 27.07.2026

### More conservative fixed remaining-time baseline and leaner source display

- The deterministic remaining-time estimate now assumes a fixed **1-Gbit/s interface** while retaining 80% usable throughput. The effective calculation rate therefore drops from 250 MB/s to **100 MB/s**. The frozen run baseline, Borg O/N subtraction and fixed file-count factor remain unchanged.
- The live **Current source** row now shows the source path only. The redundant per-source percentage was removed from both frontend rendering and backend calculation; global live progress remains the only percentage display.
- Unneeded fields and calculation paths for `current_source_percent`, `completed_source_count` and `total_source_count` were removed.
- Version advanced to **v1.1.0**.

## v1.0.99 – 27.07.2026

### Deterministic remaining-time calculation from a frozen source baseline

- The adaptive O/N/D ETA introduced in v1.0.96–v1.0.98 has been removed completely from active code. There are no 30/120-second ETA rates, cache/content phase detection, estimate-quality levels or ETA frontier anymore.
- Every newly queued backup freezes the last known source size and file count as a per-run baseline. Later changes to job statistics therefore cannot alter an already running backup's calculation.
- Borg `O` and `N` are subtracted directly from that baseline. Remaining time is calculated only from remaining bytes using a fixed 2.5-Gbit/s interface assumption with 80% usable throughput, i.e. 2.0 Gbit/s or 250 MB/s effective.
- Remaining file count contributes only a fixed, transparent small-file correction factor. Short-term Borg rates, measured network throughput, files-cache state and previous total runtimes do not affect the result.
- If the frozen byte baseline is exceeded, remaining time becomes unavailable. Any still-valid byte or file dimension may continue to drive the percentage display.
- The separate A/M/C/E history of up to 300 samples and the complete ETA-frontier migration were removed. A/M/C/E remain only as current live counters. The existing bounded Borg progress buffer is retained solely for current-source attribution and post-run per-source statistics.
- The live tile now shows only the calculated time value. Quality badges, ranges and the old cache-ETA explanation are gone; the fixed 2.5-Gbit/s/80% assumption is available compactly as a tooltip.

## v1.0.98 – 27.07.2026

### Files-cache phase-aware remaining-time estimate

- The ETA now uses Borg's already available `A` and `M` status counters as a files-cache phase signal. A very fast scan containing almost exclusively cached files can no longer project its O/N rate onto a later uncached section. `U` output is still not requested, avoiding an extra output line for millions of unchanged files.
- Failed or cancelled backup runs can leave a tiny internal **ETA frontier** on the job: only O, N, current path/source, cache phase and, when reliable, a conservative 30/120-second content-processing rate. This hint is not a backup state and never affects run-log retention protection.
- The first start after updating also covers older jobs: when the latest backup is failed/cancelled and no precise frontier exists yet, BBM stores one constant-size uncertainty marker. This specifically prevents a files cache partially rebuilt under v1.0.97 from resuming with a false minute-scale ETA even though the old live-progress frames were intentionally not persisted.
- When the same partially rebuilt files cache is restarted, BBM separates the fast already-cached prefix from the still-cold suffix. If the previous incomplete run supplied a content rate, that conservative rate is used for the cold remainder. Without one, the live view reports **“not reliable yet”** instead of an obviously false minute-scale ETA.
- As soon as A/M identify a real content-processing phase, the ETA uses the current slower 30/120-second content rate rather than the complete-run average distorted by the fast prefix.
- Memory remains strictly bounded: the existing progress history stays capped at 720 samples; at most 300 coarse A/M/C/E counter snapshots without file paths are added. The persisted ETA frontier is one small JSON object per job and never grows with runtime or file count.

## v1.0.97 – 27.07.2026

### More conservative long-run ETA and compact live block

- The adaptive ETA long-run rate now comes from the complete current job's `O`/`N` counters divided by its elapsed runtime. On long backups, the bounded rolling buffer can therefore no longer replace an hours-long trend with only a few unusually fast minutes.
- Short-term slowdowns may still increase ETA quickly. Short-term acceleration is capped asymmetrically and must prove itself over the complete run, preventing a fast scan of unchanged/cached files from reducing several TiB of remaining work to a minute-scale ETA.
- Current `O`/`N` rates far above the complete-run average also reduce estimate quality. Network throughput and previous total backup runtimes remain deliberately excluded from the estimator.
- ETA requires no growing long-term history in RAM. The existing progress buffer remains hard-limited to 720 process-local samples per active job; the new complete-run rate needs no additional history, so memory usage does not grow with backup duration.
- The live tile now labels the value **Remaining estimate** and renders `high`, `medium` or `low` compactly beside the time. The separate estimate-quality row and the two explanatory text rows below the tile are removed.

## v1.0.96 – 27.07.2026

### Adaptive current-run ETA and precise run-retention protection

- The live view now uses an **adaptive current-run ETA** based only on the currently running Borg backup: `O` (original bytes), `N` (files) and changes in `D` (deduplicated/new data), smoothed over short and medium time windows. Host/network throughput and previous total backup runtimes are deliberately excluded from the ETA.
- ETA source statistics are stored **per configured source path**. The preferred manual live scan applies Borg exclusion patterns, `--exclude-caches`, `--exclude-nodump` and `--one-file-system`; patterns that cannot be mirrored safely downgrade the source-stat quality rather than creating false precision.
- After a successful or warning backup, BBM can retain the per-source distribution observed from the current Borg progress stream and scale it to Borg's exact final totals. High-frequency ETA samples remain process-local and do not grow SQLite or persistent run logs.
- Remaining time combines current byte and file rates. Depending on stability the live view shows a single ETA or a range, together with **estimate quality** and the **current source**. Strong changes in the `D/O` ratio reduce confidence and make the estimator react more strongly to recent current-run rates.
- If a running backup exceeds a stored byte or file baseline, BBM discards that stale dimension. If both known totals are exceeded, ETA deliberately becomes unavailable instead of showing a false 100% or zero remaining time.
- Retention protection is now precise: **Latest state protected applies only to the newest successful or warning backup of an existing job.** Failed, cancelled/aborted or otherwise unsuccessful backup runs remain subject to normal retention and can be deleted individually.

## v1.0.95 – 27.07.2026

### Consistent run-log protection, up to five header interfaces and configurable session timeout

- **Recent activity** now receives the same `retention_protected` state as the full run-log view. The delete button therefore also disappears on the dashboard for the protected latest backup state and is replaced by **Latest state protected**. The DELETE endpoint continues to enforce the protection server-side as well.
- Run actions were audited across the project: protected single-run deletion is exposed only through the centralized run-row logic; **Delete all logs** remains the only action that also removes protected latest states.
- The persistent header interface monitor can now display **1 to 5 interfaces**. Automatic/manual selection and backend validation use the same limit, and lowering the configured display count also limits how many manual selections can be stored.
- **System → Settings → Session** now provides a configurable WebUI inactivity timeout in minutes. The default remains 60 minutes. The absolute lifetime from `BBM_SESSION_TTL_SECONDS` remains a hard ceiling. Changes apply without a container restart and affect existing sessions on their next validation.

## v1.0.94 – 27.07.2026

### Effective status for disabled repositories

- An enabled backup job is no longer shown as **active** while its repository is disabled. Its effective state is now **blocked**, while the explicit **Repository is disabled** reason remains visible.
- The job status filter therefore adds **Blocked**; **Active** now shows only enabled jobs that are operationally runnable. **Active first** sorting also uses the effective operating state.
- The same effective-state logic is used in the dashboard job overview so a job blocked by its device or repository is not shown as green/active.
- Central schedules now visually reflect the jobs that can actually run. Mixed assignments show **partially blocked** when only some jobs are runnable; when none of the assigned jobs can run, the schedule state is **blocked**.
- The schedule list additionally shows **runnable / assigned**, for example `1 / 2`. Jobs blocked by disabled repositories are counted separately so multi-client schedules using different repositories immediately show why they are only partially runnable.
- The stored enabled state of jobs and schedules is unchanged. Re-enabling the repository automatically returns affected jobs and schedules to active/fully runnable state without reconfiguration.

## v1.0.93 – 27.07.2026

### Improved external repository display and diagnostics

- External filesystem run-log messages no longer show raw byte counters. Free space is shown in MB below 1 GB, in GB below 1 TB and in TB from 1 TB upward; for example `534925803520 bytes` is rendered as `498.2 GB free`. The same readable formatting is used for the pre-job storage message.
- Backup jobs now prioritize the explicit **Repository is disabled** state over the generic **Repository is missing or not initialized** warning. The existing warning remains unchanged for genuinely missing or uninitialized repositories.
- System Diagnostics now groups external repository filesystems by the actual remote filesystem. Multiple repositories using the same SSH identity and the same mount reported by `df` are shown in one row, with all repositories and their individual storage-guard thresholds listed under **Repositories / guard**.
- This matches the existing grouping used for managed repositories that share one local mount.

## v1.0.92 – 27.07.2026

### Persistent interface display in the header

- The header can optionally show up to three network interfaces permanently, including interface name, IPv4 address and current download/upload rates. The feature is disabled by default.
- The data source can be the **BBM host system** or one enabled managed device. Remote devices are queried only through the existing controller SSH access; no Borg process is started.
- For the BBM host system, host `/sys` and host `/proc/net` are mounted read-only into the container so the display is not limited to the Docker container interface. If host metrics are unavailable, the UI explicitly falls back to the container network view.
- Interfaces can be selected automatically or manually. Discovery can list more than three interfaces while the header itself remains strictly limited to three. The refresh interval is configurable from 2 to 60 seconds.
- Rate calculation reuses kernel RX/TX byte counters like the live-log network display and derives bit/s between two samples. These are live-only values and are not persisted.
- On mobile devices the interface display uses its own compact horizontally scrollable area in the sticky header and does not move the other action buttons.

## v1.0.91 – 27.07.2026

- External repositories are now included in **Repository filesystems** in System Diagnostics together with managed repositories. Loading diagnostics refreshes external filesystem usage over SSH and shows total, used, free, percentage, storage-guard threshold and probe status.
- Repositories can now be **enabled/disabled**. Disabled repositories remain fully configured but are excluded from backup execution, schedules, storage/size probes and System Diagnostics.
- Managed repository access for disabled repositories is omitted from `authorized_keys`. Existing assignments are reused after re-enabling.
- A repository cannot be disabled while it has a queued or running execution.
- Jobs remain configured while their repository is disabled and become usable again after re-enabling it.

## v1.0.90 – 27.07.2026

### External storage-guard edits no longer reset repository state

- In v1.0.89, editing an external repository unconditionally reset its stored repository state to “not initialized”. Merely enabling or changing the storage guard therefore made a previously validated repository appear uninitialized.
- Non-connection changes such as storage guard mode, threshold, parallel limit, or name now preserve the validated repository state and the last successful external filesystem measurement.
- Only actual changes to the repository location, manager SSH key, or stored host key reset the external repository state and require a new connection test. In that case, filesystem measurements belonging to the old target are cleared as well.
- New regression tests cover both a storage-guard-only edit and an actual repository-location change.

## v1.0.89 – 27.07.2026

### Fixed HTTP 500 after external storage probe

- A successful external `df -m` probe in v1.0.88 could subsequently end with **Repository action failed · HTTP 500**. The cause was a missing import of `effective_storage_guard` in the service module.
- Storage values had already been determined when the failure occurred; calculating the effective storage guard afterwards raised a `NameError`.
- The missing import has been added. External usage probing, guard evaluation and repository size refresh now complete as one successful operation again.
- A new API regression test explicitly covers `df -m` success → persist external usage → determine guard state → reload repository list so this failure cannot silently return.

## v1.0.88 – 27.07.2026

### External storage probing for restricted SSH services

- External filesystem probing now uses `df -m` instead of `LC_ALL=C df -Pk`. The target no longer needs a full remote shell, making the probe compatible with restricted services such as Hetzner Storage Box.
- For relative Borg locations such as `./borg`, BBM first tries `df -m <repository-path>` and, if rejected, safely falls back to Hetzner's documented pathless `df -m`. Absolute repository paths deliberately have no pathless fallback so BBM cannot accidentally monitor an unrelated filesystem.
- The parser now converts the MiB blocks returned by `df -m` to bytes correctly. The existing pre-job, 15-second in-job and post-job probes remain unchanged.
- The SSH probe still uses only the stored repository key and `known_hosts`; remote pipes, redirects, environment assignments and uploaded helper scripts are not required.

## v1.0.87 – 26.07.2026

### External repository filesystem usage and dynamic storage guard

- External SSH repositories can now query their actual filesystem usage through a separate host-key-verified `df -Pk` probe. The repository view shows percentage used, used/total bytes, free space, detected filesystem/mount path and the time of the last successful probe.
- The repository table combines **Status and ID** into a more compact column and adds **Usage** directly beside it. Borg repository statistics remain separate in the existing size column.
- The external storage guard is explicitly configurable per repository. Existing external repositories stay unguarded after upgrade unless enabled; when enabled, an empty repository threshold inherits the global percentage.
- A fresh filesystem probe is required before every external backup. If the guard is enabled and usage cannot be determined or is already at the threshold, Borg is not started.
- While `borg create` is running, an independent SSH monitor refreshes usage every 15 seconds. Crossing the configured threshold stops Borg through the existing graceful SIGINT/SIGTERM path and marks the run failed with a clear storage-guard message.
- With the external guard enabled, two consecutive probe failures also stop the job so a backup cannot continue without enforceable free-space protection.
- When Borg finishes, the monitor is stopped and one final filesystem probe is performed immediately so the repository row receives the freshest possible end state. A failed final refresh preserves the timestamp of the last successful measurement and is shown as a separate refresh error.
- The probe reuses the protected external repository SSH key and `known_hosts`; key material remains out of process arguments and environment variables. IPv6 destinations are bracketed correctly.
- Accounts restricted to `borg serve` or another forced command that does not permit `df` are shown as **usage unavailable**. With the guard enabled the manager fails safe instead of starting an unmonitored backup; with the guard disabled normal Borg access remains available.

## v1.0.86 – 26.07.2026

### Borg 1.4.3 live progress fixed

- There is no fixed limit of three simultaneously displayed live-progress jobs. Missing progress on some parallel jobs was caused by a Borg 1.4.3 output-format difference.
- Borg `create --progress` records in `O / C / D / N` format are now recognized with both carriage-return (`\r`) and normal newline (`\n`) delimiters, covering older Borg 1.x output and Borg 1.4.x over a pipe.
- Progress records such as `1.80 GB O 593.79 MB C 17.60 MB D 10758 N <path>` are no longer persisted as a full file listing in the live/run log. They update only the compact in-memory live-progress state.
- Progress records split across process/pipe chunks are buffered and reconstructed, including splits inside the path or before the `O` marker.
- The CPU-efficient fast path for real `--list` file output remains intact: ordinary high-volume file listings continue to pass through as bytes rather than being line-split unconditionally in Python.

## v1.0.85 – 26.07.2026

### Real system health with notifications

- The former static **Service available** indicator is replaced with a real **System status**. The manager database, authentication/security store, scheduler and repository SSH service are checked. Administrators see component details in the tooltip and can open System diagnostics by clicking the status.
- The Web UI refreshes health every 30 seconds. A separate internal watchdog runs independently from APScheduler so a stopped scheduler can itself be detected.
- The notification center adds the default-enabled **System status: outage and recovery** option. Two consecutive degraded checks are required before exactly one outage notification is sent; two healthy checks then produce exactly one recovery notification. Repeated checks in the same state do not generate notification storms.
- System-health notifications use the already enabled email, webhook/Discord and Telegram channels. If the manager database itself is unavailable, an otherwise possible notification delivery is no longer blocked merely because its delivery-log row cannot be written.
- Visible system health always treats repository SSH as a core component. `BBM_HEALTH_REQUIRE_SSHD` continues to control only whether the strict HTTP probe status code must fail for repository SSH; the Web UI and notifications no longer hide that failure.

### Mobile live view and safer run actions

- The large empty header area introduced on mobile by v1.0.84 is fixed. The desktop flex basis is fully reset on small screens, restoring scrolling through progress, network information and the live log.
- **Stop job** and **Close** retain their fixed, separated positions inside the live dialog.
- In the mobile run-log list, **Live log** and **Stop** now have larger touch targets and increased spacing so the destructive stop action is less likely to be hit accidentally.


## v1.0.83 – 26.07.2026

### Preserve the latest job state across log retention

- Normal age-based retention no longer removes the latest completed backup run of an existing backup job. If the newest backup failed or was cancelled, the latest successful/warning backup is retained as well so **Latest backup size** remains available.
- Source statistics stored directly on the job remain independent of run-log retention. Deleted jobs receive no historical exemption; their detached old runs can expire normally.
- Protected latest backup records cannot be accidentally deleted one by one and are labelled **Latest state protected** in the run list.
- **Delete all completed** is renamed to **Delete all logs**. Only this explicit full cleanup removes the protected latest backup states and resets stored source statistics of existing jobs. Active and queued runs remain untouched.

### Notification deliveries share the same retention policy

- Recent notification deliveries now use the same retention period as run logs. `0 = unlimited` therefore applies to both log types.
- The previous hard cap of 1000 delivery rows is removed; daily retention cleanup now bounds this history.
- **Delete all logs** also removes all notification deliveries. The settings storage summary now includes the delivery count and oldest delivery timestamp.

### Clearer system-settings layout

- The former large settings block is separated into individual cards for display/refresh, update checks, controller key, concurrency, logs, storage guard, repository post-processing and exclusion templates.
- The common save action is placed in a dedicated footer card; on small screens it stays in normal document flow.

## v1.0.82 – 26.07.2026

### Correct legacy-cache classification and explicit BBM client-cache reset

- A legacy Borg cache under `$HOME/.cache/borg/<Borg-repository-ID>` is no longer labelled “active” in the sense of “used by BBM” merely because the same Borg repository ID is assigned to a current BBM repository. It is now shown as **“Assigned legacy Borg cache (not used by BBM)”**.
- Assigned legacy Borg caches remain untouched by default but can be selected explicitly and removed with **Clean legacy Borg cache**. This does not affect the BBM client cache; any remaining manual Borg workflow may need to rebuild its own cache on the next run.
- Active BBM client caches can now be selected through the separate **Reset BBM client cache** action. Only `$HOME/.cache/borgbackup-manager/repository-<ID>` is removed; repository data and Borg security state are preserved.
- Reset shows a prominent warning that the next backup can take significantly longer while Borg rebuilds its local cache.
- The server blocks BBM client-cache reset while runs are queued/running or while a manager/cache backup is active. Immediately before deletion the client is scanned again and the cache must still be actively assigned to the selected repository.

## v1.0.81 – 26.07.2026

### Visible client cache paths and more reliable legacy Borg-cache discovery

- `$HOME/.cache/borgbackup-manager/` is now named **BBM client cache**, while `$HOME/.cache/borg/` is named **legacy Borg cache** for earlier or manual Borg runs.
- Every discovered BBM client cache, legacy Borg cache and Borg security entry shows its complete actual path. Each device also shows the cache/security base directories that were actually inspected.
- Legacy Borg caches are no longer searched through only one currently derived cache directory. The scan deduplicates and checks `BORG_CACHE_DIR`, the XDG cache path, `$HOME/.cache/borg`, and the cache path derived from the client's account database home directory. A root SSH session therefore explicitly checks `/root/.cache/borg` even when the current environment differs.
- Scan protocol V5 transfers absolute cache/security paths in encoded form so same-named entries from different legacy roots remain unambiguous.
- Legacy-cache cleanup uses the exact path reported by the scan, performs a fresh scan immediately before deletion, and accepts only direct children of approved legacy cache roots. `CACHEDIR.TAG`, symbolic links and paths outside those roots remain protected.

## v1.0.80 – 26.07.2026

### Complete and correct normal Borg-cache inspection

- `CACHEDIR.TAG` below `$HOME/.cache/borg` is now treated as the standard cache-directory metadata file and is no longer displayed incorrectly as an “Unknown normal Borg cache”.
- Normal Borg-cache inspection now uses a top-level search that also includes hidden entries (`.*`), so old temporary or legacy cache directories can no longer remain invisible.
- Non-standard regular files and directories inside `$HOME/.cache/borg` or `BORG_CACHE_DIR` are shown with their actual size as “Legacy/other normal Borg cache entry”.
- These legacy/other entries can be selected explicitly for cleanup but are never preselected. Symbolic links and other non-regular objects remain protected.
- Cleanup revalidates the current client state immediately before deletion. `CACHEDIR.TAG` can never be removed through the cache-cleanup operation.
- The parser remains compatible with older scan protocols; new client scans use protocol version V4.

## v1.0.79 – 26.07.2026

### Extended Borg cache and security inspection

- Client scans can now target either all devices or a multi-selection of specific devices; devices outside the selection are not contacted over SSH.
- In addition to BBM's private `$HOME/.cache/borgbackup-manager/`, the normal Borg cache `$HOME/.cache/borg/` or `BORG_CACHE_DIR` is inspected and can be cleaned selectively.
- Borg security entries now expose `location` and `manifest-timestamp`. Multiple security directories recording the same repository location are classified as newer or clearly older when their timestamps can be compared.
- A Borg ID confirmed by an actively assigned BBM cache remains protected even when another security state for the same location has a newer `manifest-timestamp`.
- Unknown regular Borg security and normal Borg cache directories can be selected manually for deletion, but are never preselected.
- Orphaned BBM client caches, normal Borg caches, Borg security state and restore safety copies use separate cleanup actions. Every client deletion performs a fresh scan first.
- Manager-side inspection now explicitly covers `/data/borg-security`, including `location`, `manifest-timestamp` and duplicate evaluation. Manager cache/security entries are removed selectively rather than as one blanket cleanup.


## v1.0.78 – 26.07.2026

### Client Borg security state included and managed

- Client cache backups now also save the repository-specific Borg security state from `$HOME/.config/borg/security/<Borg-Repository-ID>` for each BBM-managed device/repository assignment. For root-operated clients this resolves to `/root/.config/borg/security/...`.
- BBM maps the security directory using the real 64-hex Borg repository ID stored in the private client-cache config. If the client cache is missing, an exact `location` match is used only when it is unique; ambiguous state is recorded as unresolved and not backed up blindly.
- Targeted client-cache restore restores a saved Borg security state only when that repository ID has no current security directory on the client. Existing security state is deliberately preserved and is never overwritten by an older backup copy.
- Client-state inspection now also scans Borg security directories. Clearly assigned state is protected, clearly BBM-associated but no-longer-assigned state can be selected as orphaned, and unknown/manual Borg security directories remain read-only/untouched.
- Orphaned Borg security state has its own selection and cleanup button. Every selected entry is rescanned immediately before deletion and must still be unambiguously orphaned.

### Client cache inspection and restore-safety cleanup

- **System → Manager Backup → Manage Borg cache** can now also inspect BBM-private client caches on enabled devices.
- Inspection is restricted to `$HOME/.cache/borgbackup-manager/`; ordinary Borg caches outside this BBM directory are never touched.
- `repository-<ID>` caches with a current device/backup-job/repository assignment are recognized as active and protected. Only clearly unassigned caches are offered as orphaned.
- Immediately before deleting an orphaned client cache, BBM re-checks the current assignment server-side. A cache that has become assigned again is skipped.
- `repository-<ID>.pre-bbm-restore-<time>` safety copies created by client-cache restore are listed in a separate category with size and creation time.
- Orphaned client caches and restore safety copies have separate selections, separate cleanup buttons and separate explicit confirmations.
- Disabled clients are not contacted. Unreachable clients are reported as errors and are not modified.
- Symbolic links, unknown entries and non-directory cache objects are shown or skipped and are never removed automatically.

## v1.0.77 – 26.07.2026

### Manager backup and cache backup fully separated

- Newly created manager backups now contain only BBM state required for manager recovery: databases, settings, master key, SSH/repository keys, Borg keyfiles and TLS data. Borg caches are no longer embedded in new manager backups.
- Borg caches use a dedicated `borgbackup-manager-cache-v...` backup type. Manager Borg cache/security state and client Borg caches can be selected independently.
- Cache backups have their own filenames, lists, size limits and restore actions, keeping the manager backup small regardless of cache size.
- Manager backups remain mandatory encrypted `.bbm` files. Cache backups are encrypted by default and then use `.bbm`; cache encryption can deliberately be disabled, producing a `.zip` artifact.
- Historical combined v1.0.75/v1.0.76 backups remain compatible for complete manager restore and for targeted restoration of their embedded manager/client caches.
- `restore-backup.sh` detects standalone cache artifacts and explicitly rejects them as full manager-restore sources.

### Separate cache restore

- Manager Borg cache `/data/borg-cache` and Borg security state `/data/borg-security` can be restored explicitly from a cache artifact. Existing state is preserved under timestamped `pre-bbm-restore` safety names first.
- Client caches continue to restore only per current device/repository assignment, preserving any existing `repository-<ID>` cache on the client before replacement.
- A standalone cache artifact cannot accidentally be restored as complete manager state.

### Visible live progress for both backup types

- Manager and cache backup creation now runs as a server-side task with visible Web UI status rather than appearing as a long blocked request.
- The UI shows phase, progress bar and a concise event log. Manager backups report preparation, database snapshot, manager data, archive finalization and encryption.
- Cache backups report manager-cache progress and, for client caches, the current device/repository, `Client x/y` and transferred bytes. When encryption is enabled its byte progress is shown as a separate phase.
- Reloading the page resumes the active backup status. Concurrent backup creation is prevented server-side and failures display the concrete cause in the status panel.

### Atomic repository validation status

- Successful external repository-test status and repository readiness are now committed in the same database transaction. This removes a short race where the run could already appear successful while an immediately following archive request still saw the repository as unvalidated.

### Restore script fix

- Removed a duplicate heredoc terminator in `restore-backup.sh` that could abort bare-metal restore after its Python validation phase.

## v1.0.76 – 2026-07-26

### Client Borg caches in manager backups

- Manager backups can now additionally include the private BBM Borg caches from managed source devices. **Include client Borg caches** is separate from the manager-cache/Borg-security option and is disabled by default.
- Only the repository-scoped BBM cache `$HOME/.cache/borgbackup-manager/repository-<ID>` is collected for current device/repository assignments. The user's general Borg cache is never touched.
- Cache data is streamed as TAR directly into the encrypted manager backup over the existing controller SSH connection with verified host keys. No second complete client-cache tree is staged under `/data`.
- Disabled devices are recorded as skipped. A genuinely missing cache on an active device is recorded as missing. If an active device is unreachable or transfer fails, backup creation aborts rather than presenting an incomplete client-cache set as complete.
- Transient `lock.exclusive`/`lock.roster` artifacts and symbolic links are excluded. Client-cache backups, like manager-cache backups, require that no run is queued or active.

### Selective client-cache restore

- **System -> Manager Backup -> Restore client Borg cache** can authenticate a backup and display its client-cache inventory.
- Restore always targets one explicitly selected device/repository pair. That assignment must still exist as a current backup job and the target device must be enabled.
- An existing `repository-<ID>` cache is preserved on the client as `repository-<ID>.pre-bbm-restore-<time>` before the saved cache is activated.
- Restore accepts only the expected repository-scoped top-level path, does not trust archive owner/permission metadata, rejects symbolic links, and removes stale lock artifacts before activation.
- A full manager restore deliberately does not push client caches automatically. Their TAR payloads remain in the original `.bbm` file and can be distributed selectively afterwards.

## v1.0.75 – 2026-07-26

### Optional Borg cache in manager backups

- Manager backups can optionally include the manager-side Borg cache under `/data/borg-cache` and Borg repository security state under `/data/borg-security`.
- The option is disabled by default so normal manager backups stay small.
- Cache-inclusive backups are allowed only while no run is queued or active.
- Volatile Borg locks (`lock.exclusive`, `lock.roster`) are deliberately excluded.
- Restore replaces Borg cache/security state only when those components are present in the selected backup.

### Compression and large backups

- New manager backups support `none`, Deflate 1, Deflate 6 (default), and Deflate 9 compression.
- Compression runs before encryption and can significantly reduce large cache backups.
- New `.bbm` backups use streaming AES-256-GCM instead of loading the complete payload into memory.
- Existing older `.bbm` backups remain readable and restorable.
- Cache backups use separate safety limits by default: 32 GiB backup file size, 128 GiB uncompressed data, and 250000 entries.
- `restore-backup.sh` also supports the new streaming format and separate cache limits.

### Borg cache inspection and cleanup

- **System → Manager Backup** now contains **Manage Borg cache**.
- The scan runs only on demand and reports manager-cache and Borg-security sizes.
- It detects unassigned `repository-<ID>` caches, legacy 64-hex Borg cache directories, and Borg security directories.
- Cleanup performs a fresh server-side association check and removes only entries that are still clearly orphaned.
- Active repository caches and associated Borg security state remain untouched.

## v1.0.74 – 2026-07-26

### External repositories: cache-lock handoff between backup, prune and compact fixed

- Manager-side Borg operations for external repositories, such as archive/info requests, `prune` and `compact`, are now additionally serialized by a dedicated manager-cache lock per repository. Configurable backup parallelism is unaffected.
- Before a manager-side Borg operation accesses an external repository, BBM removes only stale `lock.exclusive`/`lock.roster` artifacts from its private `/data/borg-cache/repository-<ID>` cache. Storage Box repository locks and Borg cache contents are never removed.
- This prevents manual or scheduled prune/compact phases started immediately after a successful client backup from failing on a leftover local manager-cache lock.
- Managed repositories retain their existing behavior.
- When a stale external manager-cache lock is actually repaired, the run log records an informational message.

## v1.0.73 – 2026-07-25

### GitHub release checking

- The sidebar now shows update state directly below **Service available** and immediately above version/release date: **Version current**, **Update available**, **Update check failed**, or **Update check disabled**.
- When **Update available** is shown, clicking it opens the concrete `the-ab/BorgBackup-Manager` GitHub release in a new browser window. No update is installed automatically.
- **System → Settings → Update check** can disable automatic checks or set an interval from 1 to 720 hours; the default is 24 hours. A manual **Check now** action is included.
- The check fetches only GitHub release metadata, stores the last successful state in `/data/update-status.json`, and adds no Python dependency. `BBM_UPDATE_CHECK_ENABLED` and `BBM_UPDATE_CHECK_INTERVAL_HOURS` are available as optional environment defaults.

### Mobile live-log fixes

- The full live dialog now has its own vertical scroll area so progress, network, diagnostics, tabs and log output remain reachable on small screens.
- Background page scrolling is locked while the live dialog is open.
- **Last A/M/C/E status** and its status/path are forced onto separate lines, and long paths can wrap.

## v1.0.72 – 2026-07-25

### Extended live network view

- The **Network** tile in run details now shows cumulative upload and download traffic since the job started on the client interface Linux selected for the route to the repository. These totals remain available after the backup finishes, just like file count and backup sizes.
- The cumulative value is derived from kernel counters of the repository-route interface. Other traffic on that interface during the run is therefore included; this is not packet-exact Borg-only accounting.
- The open live-dialog header now also shows **Client network** with up to three active IPv4 interfaces from the backup client. Each row contains interface name, IP address and current upload/download rate; the repository-route interface is ordered first and marked.
- The additional per-interface rates remain process-local live data and are never written to `manager.db`. Only the two cumulative per-run traffic totals are persisted.
- Automatic schema migration adds `runs.backup_network_download_bytes` and `runs.backup_network_upload_bytes`; existing runs remain unchanged and naturally have no historical network total.

## v1.0.71 – 2026-07-25

### Saved SSH actions per device

- **Devices -> Saved SSH actions** lets administrators persist reusable non-interactive shell commands with target device, name, enabled state, and timeout. Typical use cases are host/NFS mount operations, controlled `systemctl` actions, and diagnostics.
- The WebUI deliberately exposes no ad-hoc shell. Only previously saved action IDs can execute and every start requires confirmation.
- Execution uses the existing controller key and verified device host key with `BatchMode=yes` and `StrictHostKeyChecking=yes`.
- SSH actions are regular runs with live output, exit status, cancellation and history, and they count against the global concurrency limit. A per-action timeout from 5 to 3600 seconds prevents indefinitely hanging maintenance commands.
- Command text is stored in `manager.db` and is not treated as an encrypted secret. The UI and documentation explicitly prohibit passwords, API tokens or other credentials in commands; `sudo -n` with a narrowly scoped sudoers rule is recommended for privileged operations.
- New `host_ssh_actions` database table; existing devices, jobs, repositories and runs remain unchanged.

## v1.0.70 – 2026-07-25

### Source statistics integrated into concurrency control

- Manual source-statistics refreshes now count against the global run limit and also have their own cap under **System → Settings → Parallelism limits**. The default is `1`, preventing several resource-intensive source scans from running simultaneously.
- Source-statistics scans deliberately do not reserve a Borg repository or its mount because only the source device is read. Repository backups therefore are not blocked unnecessarily.
- Queue messages explicitly identify the source-statistics limit. Optional environment default: `BBM_SOURCE_STATS_PARALLEL_LIMIT=1`.

### Clearer compact setting

- The system setting is now labelled **Run compact once per repository after a successful schedule prune phase**.
- It applies only to schedules: after all backups and successful prune runs, at most one compact is started per affected repository.
- A prune started manually through **Retention** does not trigger compact via this setting. Manual backup chains continue to use only the job-specific **Prune after manual backup** and **Compact after successful manual prune** options.

## v1.0.69 – 2026-07-25

### Mount-aware source statistics

- The manual source live scan now detects filesystem boundaries and mounted subdirectories explicitly. With **Stay on each source filesystem** disabled, sub-mounts are included in size and file-count statistics.
- With that option enabled, sub-mounts remain excluded to match the actual Borg backup, but the scan log now reports their count and paths instead of skipping them silently.
- The Python scanner iterates large directories directly through `os.scandir` instead of materializing every directory entry in memory first.

### Full processed-file list disabled by default for new jobs

- **Show processed files in the live log** is no longer selected by default when creating a new backup job. Existing jobs keep their stored setting.
- Borg progress, A/M/C/E live counters and C/E warning detection remain available independently of the full file list.

### Compact exclusion-template management

- **System → Settings → Exclusion templates** no longer renders all templates at once.
- A selector loads one template into the editor; **New template** and **Delete template** manage the current entry. Changes are still committed with **Save settings**.
- The section remains compact with many templates and on mobile layouts.

## v1.0.68 – 2026-07-25

### Schedule maintenance is consolidated per repository

- Central schedules now run as coordinated phases: all target backups first, then all configured prune runs, then at most one compact per affected repository.
- Several jobs sharing one repository therefore no longer start redundant compact operations after the same schedule.
- Repository-size statistics are refreshed once per changed repository after the complete schedule maintenance phase.
- Backups that complete with Borg warning status are still treated as created archives and may continue into configured retention processing; compact starts only when every prune for that repository completed successfully.

### Optional prune/compact after manual backups

- Backup jobs now have two opt-in retention options: **Run prune after a manual backup** and **Run compact after a successful manual prune**. Existing jobs keep both disabled after migration.
- When manual post-processing is enabled, the repository is reserved for the complete backup → prune → optional compact chain. Later runs for the same repository remain queued until the chain finishes.
- Runs already queued before the manual chain keep FIFO precedence until the root backup starts; once it starts, unrelated runs cannot enter the reserved repository between backup, prune and compact.
- The repository-size refresh is delayed until the complete manual chain has finished, avoiding repeated statistics scans between its phases.
- Automatic database-schema migration adds `jobs.manual_prune_after_backup` and `jobs.manual_compact_after_prune` with safe default `false`.

## v1.0.67 – 2026-07-25

### Per-repository and per-mount parallelism limits

- Every repository now has a **Maximum parallel backup runs** value from `1` to `64`. Existing repositories receive the previous safe default `1` through the automatic database migration.
- Backup runs may share a repository up to that configured capacity. Maintenance and verification operations such as check, prune, compact, archive deletion and reset remain repository-exclusive.
- **System -> Settings -> Parallelism limits** can additionally define a shared limit for each detected mount below `/repositories`; `0` means unlimited for that mount.
- Multiple repositories on the same disk or NFS mount share that mount capacity. A run starts only when global, repository, mount and optional schedule limits all have capacity.
- FIFO queue messages identify the exact repository, mount, schedule or global limiter. Mount topology is briefly cached so the 250 ms queue poll does not cause unnecessary filesystem scans.

### BBM network rate and direct live-run cancellation

- The live-dialog header now shows current upload/download traffic for the BorgBackup Manager container next to **Close**. It aggregates non-loopback interfaces from `/proc/net/dev` and samples only during existing live polling.
- BBM traffic is independent of the existing client-network tile and is never persisted to `manager.db`.
- Administrators can stop queued or running executions directly from the live dialog with **Stop job**. The existing controlled Borg/remote-process cancellation path is reused unchanged.
- Responsive layout coverage was added for the new live-dialog controls and mount-limit settings.
- Automatic database-schema migration adds `repositories.parallel_limit`; existing repositories, jobs, archives and settings remain intact.

## v1.0.66 – 2026-07-25

### Live A/M/C/E activity and network bandwidth

- The live backup progress now includes Borg item counters for `A` (added), `M` (modified), `C` (changed while being read) and `E` (file access/read error), plus the most recently reported A/M/C/E path.
- With the full file list disabled, Borg uses `--list --filter AMCE`. A/M lines are consumed only for the in-memory counters and are removed before the persistent run log; C/E remain available for warning diagnosis. Unchanged `U` entries are still not requested.
- Full-file-list jobs retain their complete output while the A/M/C/E counters are derived with a bytes-first parser; only the newest matching path is decoded for the UI.
- The free eighth tile in the live run summary now shows network interface, route-selected source IP, current upload and download rate.
- The source client determines the interface used to reach the repository with its Linux routing table and reads only `/sys/class/net/<interface>/statistics/{rx,tx}_bytes`. No additional privileges and no second SSH session are required.
- Network values represent total traffic of the selected client interface, not Borg-exclusive traffic. Telemetry frames exist only during the active run and are removed from the permanent Borg log and SQLite data.
- No database-schema migration is required.

## v1.0.65 – 2026-07-25

### Local repository discovery and offline mounts

- **Search automatically** now scans safely below `/repositories` up to six levels instead of checking direct children only. Symbolic links are never followed and detected Borg repositories are not traversed further.
- The repository browser can select nested repositories and offers **Select this repository** when the current directory itself contains Borg `config`.
- Managed repository paths may safely be nested below `/repositories`; repository URLs and SSH forced commands retain the full relative path.
- The `/repositories` Linux bind mount now uses `rslave` propagation so host/NFS submounts mounted or unmounted after container startup can become visible in the running container.
- Temporarily missing repositories are shown as **unavailable**. After remounting, **Refresh status** is sufficient; availability changes are also applied by the regular UI refresh.
- **Reset** remains available for repositories that were actually deleted, with an explicit warning not to use it for a temporarily unmounted target.
- No database-schema migration is required.

## v1.0.64 – 2026-07-25

### Live backup progress

- Backup runs now add Borg `--progress` independently of the “Show processed files in the live log” option.
- The live dialog shows processed files, original/compressed/deduplicated data volumes and the currently processed path.
- Existing job source statistics are used only as an estimate basis for percentage and rough ETA. First runs keep an indeterminate progress bar while file count and data volumes are still shown.
- Borg progress frames are not persisted in the run log or `manager.db`; the state exists only in memory while the job is active.
- The high-volume full-file-list fast path remains intact: chunks without Borg carriage-return progress frames pass through without line-by-line Python processing.

### Verification

- Regression coverage added for progress parsing, log filtering, the file-list fast path, live API output and responsive progress rendering.
- No database schema migration is required.

## v1.0.63 – 2026-07-22

### Correct labels for archive comparisons

- The visible archive-comparison run label is now derived from the actually selected archive series instead of the backup job used only for technical repository access.
- Archives from one job show that job name. Archives from two jobs are labelled, for example, `OVPN-C-VPN0 ↔ OVPN-C-VPN1 · Compare archives`.
- When an archive cannot be assigned unambiguously, the device identifier inferred from its archive name is used as a fallback.
- The comparison command, archive selection and readable diff output remain unchanged.

### Project-wide reference and file audit

- The new local `scripts/project-audit.py` checks Python modules, CLI entrypoints, static web assets, frontend API references, Docker `COPY` sources, local Markdown links and the release layout.
- The audit is integrated into `scripts/release-check.sh` and requires no GitHub Actions.
- Release-note files below `app/` intentionally remain compatibility copies for very old updaters and are now required to match the canonical files byte for byte.
- No unused runtime modules, missing static assets, invalid API references or orphaned project files were found.

### Additional performance improvements without feature loss

- The execution list inventories file-backed logs with one directory scan instead of one filesystem lookup per table row.
- Backup statistics already persisted in dedicated database columns are no longer reparsed from log text when the execution list is loaded. The parser remains as a fallback for legacy or incomplete rows.
- Persistent settings are cached by path, modification timestamp and size. WebUI changes update the cache immediately, while manual file edits are detected on the next access.
- Versioned static web assets are cached immutably by the browser. The HTML document and API responses remain uncached.

### Verification

- 456 automated tests passed; the project audit and Python, JavaScript, Bash and POSIX-shell syntax checks also passed.
- Update compatibility, Docker build sources, German and English documentation and old-updater compatibility copies were checked.
- No database-schema migration is required.

## v1.0.62 – 2026-07-22

### Updates from v1.0.60 are compatible again

- The failed v1.0.61 image build was caused by the newly introduced root-level `RELEASE_DATE` file. The still-running v1.0.60 updater did not know this file, while it already copied the new Dockerfile, leaving the Docker build context incomplete.
- Release-date metadata now lives in `app/release.py`. Older updater versions already copy the complete `app/` directory reliably.
- The Dockerfile now requires only `VERSION` as a separate metadata file. No new root-level file unknown to an older updater is needed.
- `update.sh`, release checks and regression tests were updated accordingly.
- According to the updater output, the failed v1.0.61 attempt restored the previous project files before any database migration was involved.

### Verification

- Update compatibility was simulated with the v1.0.60 updater allowlist.
- Every Dockerfile source is present in the resulting Docker build context.
- No database-schema migration is required.

## v1.0.61 – 2026-07-22

### Continuous live output for sparse jobs

- The file-backed live-log writer now also flushes on a timer. The backup header therefore becomes visible while a job is still running even when the complete file list is disabled and Borg emits no further lines until final statistics.
- The normal buffer limit and maximum flush interval remain in place, preserving the CPU optimizations for high-volume file lists.
- Empty incremental polls still leave the visible output unchanged and duplicate header blocks remain prevented.

### More compact backup-job editor

- Source paths, exclusion template and exclusions remain aligned at the top of the right column.
- Archive-name template and compression have moved into the left basic-data column, using the former empty space below name, device and repository and reducing the form height.
- Below 820 pixels the form still collapses into a complete single-column mobile layout.

### Correct and readable archive comparisons

- When both archives belong to the same backup job, the actual owner is resolved from the longest matching archive prefix. The first-created repository job is no longer used as the label.
- Archive options display their assigned job, and a context line identifies the backup job and device or warns about mixed/ambiguous ownership.
- `borg diff` now uses its human-readable default output instead of raw JSON lines. A clear header shows the older archive, newer archive, path scope and content filter.
- The run dialog labels the action **Compare archives** and uses improved line spacing.

### Version and release date

- The sidebar combines version and release date as `v1.0.61 · 22.07.2026`.
- The date is read from the new `RELEASE_DATE` file and is preserved by the Dockerfile and updater.

### Verification

- 448 automated tests passed, including timed live-log flushing, correct archive-owner resolution, readable diff output and the responsive backup-job form.
- Python, JavaScript, Bash and POSIX-shell syntax checks passed.
- No database-schema migration is required. Devices, repositories, backup jobs, schedules, archives, users and settings remain unchanged.

## v1.0.60

### Live log without repeated header blocks

- Empty incremental live-log responses no longer fall back to the SQLite metadata preview. The already visible backup header is therefore not appended again while a job is running.
- The placeholder is still replaced by the first real log block; polls without new bytes leave the visible output unchanged.
- Running backup output is now filtered for SQLite across process-chunk boundaries: ordinary Borg item statuses and paths remain exclusively in the file-backed log, while small metadata remains available live.

### More compact user interface

- Backup jobs now have a direct **Edit** button between **Archives** and **More**.
- The backup-job editor places name, device and repository on the left, with source paths, exclude template and exclusions on the right.
- The central schedule editor places name, target group, cadence and parallel limit on the left, with target selection and execution times on the right.
- **Compare archives** now uses a compact two-column layout and a smaller optional-path field.
- All new layouts automatically collapse to one column on tablets and mobile devices, while action controls remain fully usable.

### Verification

- 443 automated tests passed, including empty live-log deltas, chunk-safe SQLite path filtering, the direct edit button and responsive form layouts.

## v1.0.59

### Live log without duplicated start blocks

- Opening a running job now serializes the initial log request and background polling. They can no longer read the same file offset concurrently and append the same header block repeatedly.
- Late responses from an older live request are discarded using the live session and requested file offset.
- The **No output available yet …** placeholder is replaced by the first real log block instead of remaining in front of it.
- Log-compaction resets remain supported and still replace the visible window safely.

### Complete file paths removed from SQLite previews

- A legacy finalization fallback still copied the last 16 KiB of raw Borg output into `Run.log_output` even though complete logs were already file-backed. Ordinary file paths could therefore reappear in `manager.db` after completion. The fallback has been removed.
- Complete Borg status/path output is stored exclusively in `/data/run-logs/run-ID.log`. SQLite now contains only small metadata and diagnostic previews plus the structured warning summary.
- Ordinary item paths are removed from `output`, `error` and `log_output`. Bounded paths for actual warning causes deliberately remain in `warning_summary_json`, because execution details and notifications depend on them.
- Existing legacy SQLite previews are cleaned automatically at startup. Missing file-backed logs are created from the old payload first, after which the database can be compacted with the existing automatic `VACUUM` step.

### Verification

- 439 automated tests passed, including concurrent live requests, placeholder replacement, SQLite preview cleanup, legacy-log migration and structured warning paths.
- No schema change is required. Devices, repositories, jobs, schedules, archives, users and settings remain unchanged.

## v1.0.58

### Second CPU-optimization stage for complete file lists

- The production high-volume path now processes `borg create --list` as raw byte blocks. Normal file names are no longer fully UTF-8 decoded or split line by line in Python on the manager.
- A fast byte-block filter skips complete blocks containing ordinary Borg item statuses in one operation. Only blocks containing `C`, `E` or textual warnings enter detailed structured warning analysis.
- Ordinary file status lines are no longer mirrored continuously into the SQLite preview. During a run SQLite receives only small stdout metadata and changed warning summaries; the complete log remains unchanged under `/data/run-logs`.
- The subprocess reader consumes raw blocks of up to 256 KiB. The log writer buffers up to 1 MiB or 750 ms and tracks the known file size internally instead of calling `stat()` after every flush.
- Warning collection remains complete: changed files (`C`), file access errors (`E`), permission, I/O, missing-path and textual Borg warnings continue to be stored structurally.

### Incremental live log

- An open live log now requests only bytes appended since the previous poll by using a file offset.
- The Web UI no longer transfers and renders the same 256 KiB window on every poll.
- If the browser falls behind or the log was compacted, the server automatically returns the newest bounded tail and instructs the browser to reset the live view safely.
- The active browser view is bounded to 768 KiB; the configured complete head/tail view is still loaded once after completion. The underlying log file is unaffected.
- Polling runs every 1.8 seconds with the dialog open and every 1.5 seconds while it is closed.

### Verification

- Synthetic comparison with 500,000 ordinary item lines plus one `C` and one `E` warning: pure manager-side processing decreased from about 0.76–0.91 seconds to about 0.17–0.24 seconds in the test environment. The same test also eliminated 62 SQLite preview flushes.
- 436 automated tests passed, including raw-byte streaming, incremental log offsets, log reset handling, warning collection and complete run finalization.
- No database migration is required. Devices, repositories, jobs, schedules, archives, users and settings remain unchanged.

## v1.0.57

### CPU-optimized full file-list processing

- **Show processed files in the live log** remains fully available, but large `borg create --list` streams are now processed in batches instead of performing filesystem work for every small process chunk.
- Each running execution uses one buffered, persistent log writer. Writes, permission handling and size checks happen only at bounded intervals or after larger data blocks.
- The filtered error view is no longer recalculated from up to 256 KiB of text for every Borg output chunk; it is refreshed only with the bounded database preview flush.
- Ordinary Borg item statuses such as `A`, `M`, `U` and `d` bypass the complete warning regular-expression chain. Warning-relevant `C` and `E` statuses and textual Borg warnings are still detected and stored in full.
- The subprocess reader consumes larger chunks and bounded stdout/stderr capture now preserves the exact tail.

### Reduced Web UI live polling

- While the run dialog is closed, the Web UI requests only status and metadata and no longer reads the file-backed live log on every poll.
- While the live log is open, an active run transfers a bounded 256 KiB head/tail view. The configured complete view is loaded once after completion.
- The live polling interval was increased from 850 to 1200 milliseconds without affecting warning collection or run status.

### Verification

- A synthetic comparison with 120,000 Borg item lines and 4.2 MiB of output reduced pure manager-side processing time in the test environment from about 14.4 to 0.46 seconds. This is a reproducible stress test, not a guaranteed production value.
- Warning paths with status `C` and `E` remain available with both full and reduced file listing modes.
- No database migration is required. Devices, repositories, jobs, schedules, archives, users and settings remain unchanged.

## v1.0.56

### Manual GitHub publishing

- Removed the Dependabot configuration and the hosted GitHub Actions test/container-build workflow.
- Removed related README, contribution, release-check and updater references.
- The updater removes a legacy `.github` automation directory left by v1.0.55.
- Local automated tests, syntax checks and `scripts/release-check.sh` remain available for controlled release preparation.

### Upgrade

- No database migration is required. Devices, repositories, jobs, schedules, archives, users and settings remain unchanged.

## v1.0.55

### Public repository preparation

- Added an Apache License 2.0 project license, copyright notice, security policy, contribution guide and third-party notices.
- Added a clear statement that BorgBackup Manager is an independent third-party project and is not affiliated with or maintained by the BorgBackup project.
- Added transparent disclosure of OpenAI ChatGPT assistance and human review responsibility.
- Documented that only the current release receives security fixes and that versions before 1.0.38 are unsupported.

### Local release checks

- Added a reusable local release-check script and pytest path configuration.

### Repository hygiene

- Expanded `.gitignore` and `.dockerignore` for local configuration, runtime data, databases, logs, backups, update archives and build output.
- Reworked synthetic OpenSSH private-key markers in HTML and tests so generic secret scanners are less likely to report test fixtures as real private keys; runtime validation and displayed placeholder text remain unchanged.

### Upgrade

- No database migration is required. Devices, repositories, jobs, schedules, archives, users and settings remain unchanged.

## v1.0.54

### Dashboard warning indicator

- The inline **Warning** status in the dashboard backup-job table no longer inherits the padding, rounded background and enlarged typography of a full warning notice box.
- Warning notice boxes and warning badges retain their existing appearance. The CSS selectors now distinguish inline status text, badges and notice containers explicitly, including compact display mode.

### Static demo alignment

- The separately supplied standalone demo was checked again against the v1.0.54 interface. Repository **Usage** now shows the number of assigned jobs and devices, while repository size remains in the separate **Size** column.
- Dashboard backup metadata, backup-job lists, schedules, users and repository rows now follow the structures and labels of the real interface more closely.

### Verification

- A regression test protects inline warning status text from inheriting warning-box spacing.
- The static demo was rendered and checked with dummy repositories, devices, jobs, schedules, users and runs.

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
