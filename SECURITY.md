# Security Policy

## Supported versions

Security fixes are released only for the current BorgBackup Manager release.
Versions before 1.0.38 are explicitly unsupported and should not be deployed or
published as supported releases because they predate substantial security
hardening.

| Version | Security support |
|---|---|
| Current release | Yes |
| 1.0.38 through the previous release | Upgrade assistance only |
| Earlier than 1.0.38 | No |

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
