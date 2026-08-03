# BorgBackup Manager – GitHub Release Workflow

This project uses a manual, reviewable publication workflow.

## 1. Prepare the change

- Start from the current `main` branch.
- Create a branch named `agent/<short-description>` for assistant-prepared changes or another descriptive feature/fix branch.
- Keep unrelated changes out of the branch.
- Add or update regression tests with the code change.

## 2. Validate the source tree

Complete `RELEASE_CHECKLIST.md` or `RELEASE_CHECKLIST.de.md`.

At minimum verify:

```bash
pytest -q
python scripts/project-audit.py
python -m compileall app tests scripts
node --check app/static/app.js
node --check app/static/i18n.js
node --check app/static/theme-init.js
bash -n update.sh
```

Validate both Compose files with the available YAML tooling.

## 3. Prepare release metadata

Update all relevant locations:

- `VERSION`
- `app/release.py`
- Web UI and static cache-busting version markers
- `RELEASE_NOTES.md`
- `RELEASE_NOTES.de.md`
- documentation examples that show the current version

Release Notes keep the complete history. Current operational documentation must not accumulate obsolete one-time update paths.

## 4. Create the clean release package

Expected filenames:

```text
BorgBackup-Manager-<version>.zip
BorgBackup-Manager-<version>.zip.sha256
```

The ZIP must contain one top-level directory:

```text
BorgBackup-Manager/
```

Exclude:

- `.git/`
- `.venv/`
- `.pytest_cache/`
- `__pycache__/`
- databases and WAL/SHM files
- logs
- maintenance backups
- exports
- keys and secrets
- local `.env` files
- runtime state

After packaging:

```bash
unzip -t BorgBackup-Manager-<version>.zip
sha256sum BorgBackup-Manager-<version>.zip \
  > BorgBackup-Manager-<version>.zip.sha256
sha256sum -c BorgBackup-Manager-<version>.zip.sha256
```

Extract the final ZIP into a clean temporary directory and repeat the complete tests there.

## 5. Commit and push

- Review the complete diff.
- Stage only files belonging to the release.
- Use a concise commit message such as `Release v1.3.9` or `Fix interface polling cache`.
- Push the branch to GitHub.

## 6. Open a draft pull request

The pull request body should include:

- summary
- root cause for fixes
- implementation details
- database and security impact
- Manager backup and restore impact
- documentation and translation changes
- exact test results
- environment limitations
- artifact filenames and SHA-256 for release PRs

Keep the pull request in draft state until reviewed by the project owner.

## 7. Merge and publish

After approval:

1. Merge the pull request using the project owner's chosen merge method.
2. Confirm that `main` contains the intended version.
3. Create a GitHub Release/tag for the version when desired.
4. Attach:
   - `BorgBackup-Manager-<version>.zip`
   - `BorgBackup-Manager-<version>.zip.sha256`
5. Use the matching Release Notes entry as the release description.
6. Build and publish the GHCR image through the separate build system when required.

## 8. Capabilities and limitations

With connected GitHub access, the assistant can:

- inspect repository files, commits, issues and pull requests
- create branches
- create or update repository text files
- open and manage draft pull requests
- review PR discussions and checks when available

Uploading binary ZIP assets to a GitHub Release requires either:

- an available GitHub Release upload action, or
- an authenticated local GitHub CLI workflow such as:

```bash
gh release create "v<version>" \
  "BorgBackup-Manager-<version>.zip" \
  "BorgBackup-Manager-<version>.zip.sha256" \
  --title "BorgBackup Manager v<version>" \
  --notes-file RELEASE_NOTES_CURRENT.md
```

Do not add automatic GitHub Actions or Dependabot configuration unless the project owner explicitly requests a policy change.
