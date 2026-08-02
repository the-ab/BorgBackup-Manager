# Security Policy

## Supported version

Security fixes are released only for the current BorgBackup Manager release.
BorgBackup Manager v1.3.8 is the maintained product version.

v1.3.8 keeps v1.3.5 as the one-time compatibility boundary. Every regularly
started v1.3.5 installation can update directly; harmless surplus database
objects are normalized only after verified lossless copying. Earlier releases
are not maintained and may require a clean v1.3.8 deployment. Manager and cache
backups must use the supported v1.3.5-or-newer backup baseline.

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

## Deployment expectations

- Run the current release behind its built-in HTTPS endpoint or a correctly
  configured trusted reverse proxy.
- Restrict access to the Web UI and repository SSH port with host or network
  firewall rules.
- Keep `/data/security/security.db`, `/data/security/master.key`, manager backup
  files and their passphrases private.
- Keep `.env` files at mode `0600` and do not commit them.
- Use the provided checksum before applying an update.
- Create and verify an encrypted manager backup before every update.
- Do not publish unsanitized access, debug, SSH or Borg logs.
