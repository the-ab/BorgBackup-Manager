# BorgBackup Manager – Project Handover

This file is the entry point when development continues in a new chat, workstation or contributor session.

## 1. Establish the authoritative state

1. Read `PROJECT_STATUS.md`.
2. Read the current `VERSION` and `app/release.py`.
3. Read the newest entries in `RELEASE_NOTES.md` or `RELEASE_NOTES.de.md`.
4. Read `RELEASE_CHECKLIST.md` or `RELEASE_CHECKLIST.de.md`.
5. Inspect the current default branch and open pull requests before making changes.
6. Treat the Git repository as the authoritative code state. Do not rebuild from an older ZIP when the repository contains a newer release.

## 2. Preserve supported data and restore behavior

The Manager backup and restore workflow is considered a core compatibility contract.

Changes must preserve, unless explicitly approved otherwise:

- devices and repository assignments
- repositories and encrypted repository credentials
- backup jobs and schedules
- users, roles, settings and two-factor state
- encrypted saved SSH actions
- latest source statistics, source size and file count
- original, compressed and deduplicated backup sizes
- archive and run metadata required by the current UI
- `security.db` together with `/data/security/master.key`

Never introduce a database cleanup that silently removes these data classes.

## 3. Database baseline

- v1.3.5 is the minimum supported direct-update baseline.
- A complete v1.3.5 installation may contain unused legacy SQLite objects.
- Current code must normalize those known harmless extras losslessly.
- Missing current tables or columns remain an unsupported old schema.
- Plaintext SSH action storage is not supported.
- Saved SSH commands belong encrypted in `security.db`.
- Confidential command history, logs, notifications, WAL/SHM remnants and unsafe maintenance copies must not reappear.

When database code changes, test both:

1. a fresh installation, and
2. a realistic long-lived v1.3.5+ database containing harmless legacy objects.

## 4. Documentation policy

- Release Notes retain the complete release history.
- README, installation guides, Compose guides and integrated help describe the current supported state.
- Do not re-add obsolete one-time migration instructions to current operational documentation.
- All user-visible changes require equivalent German and English text.
- Root and application copies of Release Notes must remain synchronized where both are present.

## 5. Release workflow

For each change set:

1. Create a dedicated branch.
2. Implement the smallest coherent scope.
3. Add regression tests for every reported failure.
4. Run focused tests early.
5. Run the complete release checklist.
6. Update version, date, cache-busting markers, documentation and Release Notes.
7. Create the clean source ZIP and SHA-256 file.
8. Test from a fresh extraction of the final ZIP.
9. Push the branch and open a draft pull request.
10. After review and merge, create or update the GitHub Release and attach the ZIP and SHA-256 file.
11. Also provide the same ZIP and SHA-256 file directly in the chat when the working environment supports downloads.

## 6. Pull request expectations

A pull request should state:

- what changed
- why it changed
- root cause for fixes
- database, backup, restore and security impact
- user-visible behavior
- tests and static checks performed
- checks not possible in the current environment
- final release artifact names and SHA-256 when it is a release PR

Default to a draft pull request until the project owner has reviewed the result.

## 7. GitHub constraints

- Repository: `the-ab/BorgBackup-Manager`
- Default branch: `main`
- Manual publication is the current policy.
- Do not add GitHub Actions, Dependabot or automatic release workflows unless explicitly requested.
- Source changes can be pushed and submitted as pull requests through the connected GitHub access.
- Release asset upload may require GitHub CLI or a GitHub Release API capability in the active environment.

## 8. Before continuing work in a new session

Record at minimum:

- current release and commit
- active branch and pull request
- requested changes
- files already modified
- tests already run and their exact result
- known failures or environment limitations
- database or backup implications
- next version number
- expected ZIP and SHA-256 filenames
- remaining manual verification

Use `PROJECT_STATUS.md` for stable public project state. Keep temporary work-in-progress details in the active pull request description or issue rather than permanently adding them to this file.
