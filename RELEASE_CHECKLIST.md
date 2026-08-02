# Release Checklist – BorgBackup Manager

Complete this checklist for every release. Mark non-applicable items explicitly instead of silently skipping them.

## 1. Baseline and scope

- [ ] Verified the source ZIP and its existing SHA-256 checksum.
- [ ] Built changes only on the intended latest release.
- [ ] Recorded requested features, fixes and intentionally excluded work.
- [ ] Assessed database, backup, restore, update and rollback effects.

## 2. Version and release metadata

- [ ] Updated `VERSION`.
- [ ] Updated `app/release.py` with the correct release date.
- [ ] Updated version markers in the Web UI, sign-in screen, cache-busting URLs and integrated manual.
- [ ] Updated version examples in README, installation, Compose documentation and `.env.example`.
- [ ] Updated package, ZIP, SHA-256 and GHCR tag examples.
- [ ] Confirmed that no stale version marker remains in the project.

## 3. Code, data model and migrations

- [ ] Added regression tests for new and changed behavior.
- [ ] Existing installations migrate automatically and idempotently.
- [ ] Migrations copy and verify data before removing legacy structures.
- [ ] Interruption, restart and repeated migration cases are safe.
- [ ] Considered SQLite WAL/SHM, freelist and plaintext remnants for security-sensitive migrations.
- [ ] Delete, device, repository, backup and maintenance workflows use the new data model.
- [ ] No unused modules, imports, routes or frontend handlers remain.

## 4. Security and secrets

- [ ] No passwords, tokens, passphrases, TOTP secrets, recovery codes or confidential commands appear in logs or previews.
- [ ] New secrets use authenticated encryption and the existing master key.
- [ ] Manager backup includes all required security state and verifies decryptability.
- [ ] Restore keeps related database and key states consistent.
- [ ] Checked file permissions, temporary files and success/error/cancellation cleanup.
- [ ] Checked role and API authorization for new functionality.
- [ ] Verified source, pinned version, hash and license for every new dependency.

## 5. Web UI, usability and translation

- [ ] Checked desktop, narrow and mobile layouts.
- [ ] Dialogs have an appropriate scroll area and do not block normal operation.
- [ ] Labels, warnings, empty states, errors and confirmations are unambiguous.
- [ ] Translated every new visible string in `app/static/i18n.js`.
- [ ] German and English UI are functionally equivalent.
- [ ] Checked navigation, profile, forms, focus, keyboard operation and ARIA labels.
- [ ] No removed DOM IDs or obsolete event handlers remain referenced.

## 6. Documentation

- [ ] Updated `README.de.md` and `README.md`.
- [ ] Updated `INSTALLATION.de.md` and `INSTALLATION.md`.
- [ ] Updated integrated `help.de.html` and `help.en.html`.
- [ ] Updated `SECURITY.md`, `THIRD-PARTY-NOTICES.md` and Compose documentation where applicable.
- [ ] Updated root and application release notes and confirmed byte identity.
- [ ] Documented update, restore, migration and security effects with concrete paths.

## 7. Automated and static checks

- [ ] Complete `pytest` suite passed.
- [ ] Python compilation passed for application, tests and audit scripts.
- [ ] JavaScript syntax passed for `app.js`, `i18n.js` and `theme-init.js`.
- [ ] Shell syntax passed for installation, update, recovery, restore and Docker scripts.
- [ ] Validated both Compose files as YAML.
- [ ] `scripts/project-audit.py` passed.
- [ ] Ran focused tests for security-critical behavior.

## 8. Package content and reproducibility

- [ ] No `.venv`, `.pytest_cache`, `__pycache__`, test runtime or local configuration in the ZIP.
- [ ] No databases, WAL/SHM files, logs, backups, exports, keys or secrets in the ZIP.
- [ ] Preserved the fixed top-level `BorgBackup-Manager/` directory.
- [ ] Verified ZIP integrity.
- [ ] Re-ran the complete tests directly from the final ZIP.
- [ ] Generated a SHA-256 file and verified it with `sha256sum -c`.
- [ ] Matched final filenames and update commands to the actual artifact.

## 9. Completion

- [ ] Release summary includes version, download, SHA-256, update commands, implemented changes and verification results.
- [ ] Clearly identify infrastructure tests that could not be run realistically.
- [ ] Document known limitations or required manual steps.
