# BorgBackup Manager – Project Status

Last updated: 3 August 2026  
Current release: **v1.3.8**  
Repository: `the-ab/BorgBackup-Manager`  
Default branch: `main`

## Supported baseline

- Direct updates are supported from a complete and regularly started **v1.3.5** installation.
- v1.3.7 introduced lossless normalization of valid v1.3.5 databases that still contain unused legacy objects.
- Older or incomplete database schemas are intentionally rejected rather than guessed or silently repaired.
- Current Manager and Cache backup formats from v1.3.5 and later remain supported.

## Current architecture

- FastAPI application with SQLite databases.
- `manager.db` stores configuration, jobs, schedules, repositories, run metadata, source statistics and backup size information.
- `security.db` stores users, sessions, two-factor data, encrypted secrets and encrypted saved SSH actions.
- `/data/security/master.key` is required together with `security.db` for restoration of encrypted security state.
- Full Manager backups preserve devices, repositories, jobs, schedules, users, settings, source statistics, backup sizes and current security state.

## Current release state

v1.3.8 restores the complete Release Notes history and ensures both German and English Release Notes are included in the Docker image.

Important recent changes:

- v1.3.5 removed historical plaintext SSH action details from `manager.db`, run fields, logs, notifications and unsafe maintenance copies.
- v1.3.6 established the one-time compatibility baseline.
- v1.3.7 corrected the v1.3.5 update path and losslessly removes unused legacy database objects.
- v1.3.8 restored the complete Release Notes history and fixed German Release Notes packaging.

## Release policy

- Releases are prepared manually.
- GitHub Actions, Dependabot and automatic release workflows are not required unless the project owner explicitly changes this policy.
- Every release must include:
  - source ZIP
  - SHA-256 file
  - German and English Release Notes
  - updated version and release date
  - completed release checklist
  - tests and static validation
- Release Notes retain the full version history.
- README, installation documentation and integrated help describe only the current supported state and must not accumulate obsolete one-time upgrade instructions.

## Validation expectations

Before release:

1. Run the complete test suite.
2. Run `scripts/project-audit.py`.
3. Compile Python files.
4. Validate JavaScript and shell syntax.
5. Validate both Compose files as YAML.
6. Build a clean ZIP without databases, logs, keys, caches or runtime state.
7. Repeat the tests from a fresh extraction of the final ZIP.
8. Generate and verify the SHA-256 file.
9. Verify Manager backup and restore preservation whenever data models, security state or database handling change.

## GitHub publication model

Changes should normally be published through a dedicated branch and draft pull request. The final ZIP and SHA-256 file may additionally be uploaded to a GitHub Release after the pull request is reviewed and merged.

See:

- `PROJECT_HANDOVER.md`
- `GITHUB_RELEASE_WORKFLOW.md`
- `RELEASE_CHECKLIST.md`
- `RELEASE_CHECKLIST.de.md`
