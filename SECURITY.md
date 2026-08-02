# Security Policy

## Supported versions

Security fixes are released only for the current BorgBackup Manager release.
Direct updates, manager backups, and cache backups are supported only from
BorgBackup Manager v1.1.0 or newer. Earlier releases are explicitly unsupported
and require a clean installation.

| Version | Security support |
|---|---|
| Current release | Yes |
| v1.1.0 through the previous release | Upgrade assistance only |
| Earlier than v1.1.0 | No |

## Reporting a vulnerability

Do not disclose suspected vulnerabilities in a public issue, discussion, log or
screenshot. Use GitHub's private vulnerability reporting feature for this
repository. If that feature is unavailable, contact the maintainer privately
through the contact method listed on the repository owner's GitHub profile.

Include, where possible:

- affected version and deployment method;
- a concise description of the impact;
- reproducible steps or a minimal proof of concept;
- relevant sanitized logs;
- whether credentials, repositories or backup data may have been exposed.

Never attach real passwords, passphrases, private keys, session cookies,
production databases or unredacted customer data.

The maintainer will acknowledge a complete report, assess severity, prepare a
fix and coordinate disclosure. No fixed response or release deadline is
promised. Please allow a reasonable remediation period before public disclosure.

## Scope

The policy covers the BorgBackup Manager application, its release scripts and
its container configuration. Vulnerabilities in BorgBackup, OpenSSH, OpenSSL,
Docker, the host operating system or other third-party components should also be
reported to their respective upstream projects.
## Authentication hardening and external blocking

BorgBackup Manager supports per-user TOTP two-factor authentication with one-time recovery codes. TOTP secrets are encrypted in the security database and recovery codes are stored only as hashes. The setup QR code is generated locally from the provisioning URI; no external QR service receives the secret. Recovery codes are explicitly labelled, shown in full only at creation or regeneration, and each code is valid once. Enabling, disabling or administratively resetting 2FA revokes existing sessions for that account.

Saved host SSH action commands are authenticated-encrypted with the same master-key trust anchor in `security.db`. Upgrading from the legacy plaintext table imports and verifies all rows before dropping the source table, detects empty or interrupted legacy tables, checkpoints SQLite WAL state, vacuums `manager.db`, and scans the database plus WAL/SHM files for migrated command remnants. Run previews and normal diagnostics do not include command text. General database-maintenance VACUUM work is deferred to application startup so an exclusive SQLite lock cannot disrupt live API requests.

The persistent JSON Lines log `/data/logs/access.log` is intended for security monitoring and external blocking tools. Events include `login_failed`, `login_blocked`, `login_success`, `login_two_factor_required`, `logout` and ordinary `http_access`. Credentials, second-factor values, recovery codes and session tokens are never included. Log rotation uses `BBM_LOG_MAX_BYTES` and `BBM_LOG_ROTATIONS`.

When Fail2ban, CrowdSec or a reverse proxy performs blocking, ensure that the manager receives the real client address only from trusted proxies configured through `BBM_TRUSTED_PROXY_CIDRS`. Never trust forwarded headers from arbitrary sources. Test every filter/parser with sanitized sample lines before enabling a firewall action, and whitelist administrative networks where appropriate.

## Database maintenance

The WebUI database-maintenance action is deliberately conservative. It previews candidate rows and refuses to run while executions or backup tasks are active. Historical SSH action runs created by releases that embedded the full command in `runs.command_preview` are treated as security-sensitive legacy data: BBM preserves status, timestamps and labels, but removes their command preview, free-form output/error/log fields and file-backed SSH run log. Existing maintenance copies that still contain this plaintext are deleted. A new verified SQLite safety copy is created only after that scrub, so `/data/maintenance-backups` does not reintroduce the removed credentials. Normal devices, repositories, jobs and completed backup history are never bulk-deleted. SQLite connections use `secure_delete=ON`; checkpoint and `VACUUM` at startup remove recoverable remnants from database and WAL pages. Maintenance copies are not included in update rollback archives.

