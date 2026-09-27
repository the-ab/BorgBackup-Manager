# Release package checks – BorgBackup Manager

[Deutsche Version](RELEASE_CHECKLIST.de.md)

This public technical checklist accompanies the release package. Keep this file and its German counterpart in ZIP packages: installed updaters validate these filenames before applying an update.

- Run `bash scripts/release-check.sh` in a clean source tree with the documented Python test environment.
- Keep the fixed top-level ZIP directory `BorgBackup-Manager/` and include all tracked public files.
- Exclude local configuration, credentials, databases, logs and runtime directories.
- Generate and verify the ZIP SHA-256 sidecar before distribution.
- Build the image and ZIP from the same reviewed source commit and record image provenance.
- Validate installation and update from the supported baseline, including backup and recovery, on disposable test data.
- Publish a new version only after its functional checks and release review are complete.
