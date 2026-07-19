from __future__ import annotations

import os
import re


_PERMISSION_PATH_RE = re.compile(
    r"Permission(?:Error)?:?\s*(?:\[Errno 13\]\s*)?Permission denied:\s*[\"\'](?P<path>[^\"\']+)[\"\']",
    re.IGNORECASE,
)

_DEBUG_LINE = re.compile(r"^(?:Remote:\s*)?debug\d+:\s*", re.IGNORECASE)
_NOISE_PATTERNS = (
    "reading configuration data",
    "applying options for",
    "kex algorithms:",
    "host key algorithms:",
    "ciphers ctos:",
    "ciphers stoc:",
    "macs ctos:",
    "macs stoc:",
    "compression ctos:",
    "compression stoc:",
    "languages ctos:",
    "languages stoc:",
    "first_kex_follows",
    "reserved 0",
    "fd 3 setting",
    "fd 3 clearing",
    "identity file ",
    "local version string",
    "remote protocol version",
    "compat_banner:",
    "ssh2_msg_kexinit",
)


def compact_repository_diagnostic(output: str, error: str, return_code: int) -> tuple[str, str]:
    """Return a concise user message and copyable technical details.

    Borg/SSH diagnostics can contain hundreds of verbose OpenSSH lines. The
    repository list only needs an actionable summary; relevant details remain
    available separately without turning a table row into a terminal dump.
    """
    raw = "\n".join(part.strip() for part in (error, output) if part and part.strip()).strip()
    lowered = raw.lower()

    permission_match = _PERMISSION_PATH_RE.search(raw)
    if permission_match and permission_match.group("path").startswith("/repositories/"):
        path = permission_match.group("path")
        uid = os.getenv("BBM_BORG_UID", "1000")
        gid = os.getenv("BBM_BORG_GID", "1000")
        summary = (
            f"Zugriff auf Repository-Datei verweigert: {path}. "
            f"Eigentümer und Leserechte prüfen; der Manager greift als UID:GID {uid}:{gid} zu."
        )
    elif "was previously located at" in lowered and ("do you want to continue" in lowered or "repository access aborted" in lowered):
        summary = (
            "Borg hat dieses Repository unter einer früheren URL gespeichert. "
            "Den geänderten Repository-Standort beim betroffenen Backup-Job einmalig bestätigen."
        )
    elif "lock.exclusive" in lowered and any(marker in lowered for marker in (
        "/data/borg-cache/",
        "/repositories/.cache/borg/",
    )):
        summary = (
            "Der lokale Borg-Cache des Managers ist gesperrt oder beschädigt. "
            "Unter Repository-Aktionen den Cache löschen und die Verbindung erneut prüfen."
        )
    elif "lock.exclusive" in lowered and any(marker in lowered for marker in (
        "/.cache/borgbackup-manager/",
        "/.cache/borg/",
    )):
        summary = (
            "Der lokale Borg-Cache des ausführenden Benutzers ist gesperrt. "
            "Der angezeigte Home-Pfad gehört zum ausführenden System und ist nicht der Repository-Pfad."
        )
    elif "permission denied" in lowered or "no more authentication methods" in lowered:
        summary = (
            "SSH-Anmeldung abgelehnt. Der öffentliche Manager-Schlüssel ist am externen Ziel "
            "noch nicht autorisiert oder dem falschen Benutzer zugeordnet."
        )
    elif "connection timed out" in lowered or "operation timed out" in lowered:
        summary = "SSH-Verbindung zum externen Repository ist in ein Zeitlimit gelaufen. Host, Port und Firewall prüfen."
    elif "connection refused" in lowered:
        summary = "SSH-Verbindung wurde abgelehnt. Host und SSH-Port des externen Repositorys prüfen."
    elif "host key verification failed" in lowered or "remote host identification has changed" in lowered:
        summary = "SSH-Hostkey-Prüfung fehlgeschlagen. Den gespeicherten Hostkey/Fingerprint kontrollieren und neu übernehmen."
    elif "could not resolve hostname" in lowered or "name or service not known" in lowered or "temporary failure in name resolution" in lowered:
        summary = "Der Hostname des externen Repositorys konnte nicht aufgelöst werden."
    elif "passphrase" in lowered and any(token in lowered for token in ("incorrect", "wrong", "invalid", "not accepted")):
        summary = "Repository-Passphrase wurde abgelehnt. Gespeicherte Passphrase und Verschlüsselungsmodus prüfen."
    elif "repository" in lowered and any(token in lowered for token in ("does not exist", "not found", "is not a valid", "not a borg repository")):
        summary = "Am angegebenen Pfad wurde kein vorhandenes Borg-Repository gefunden. Repository-URL und Unterverzeichnis prüfen."
    elif "connection closed by remote host" in lowered:
        summary = "Die Gegenstelle hat die SSH-Verbindung vor dem Öffnen des Repositorys beendet. SSH-Zugang und Borg-Unterstützung prüfen."
    elif "remote: borg: command not found" in lowered or "borg: not found" in lowered:
        summary = "Borg ist auf der externen Gegenstelle nicht verfügbar oder nicht für diesen SSH-Zugang freigeschaltet."
    elif return_code == 1:
        summary = "Repository-Prüfung wurde mit einer Borg-Warnung beendet. Technische Details prüfen."
    else:
        summary = f"Repository-Zugriff fehlgeschlagen (Rückgabecode {return_code})."

    if permission_match and permission_match.group("path").startswith("/repositories/"):
        details = permission_match.group(0).strip()
        return summary, details

    relevant: list[str] = []
    for original in raw.splitlines():
        line = original.strip()
        if not line:
            continue
        normalized = line.removeprefix("Remote: ").strip()
        if _DEBUG_LINE.match(line):
            debug_text = _DEBUG_LINE.sub("", line).strip().lower()
            if any(pattern in debug_text for pattern in _NOISE_PATTERNS):
                continue
        lower_line = normalized.lower()
        if lower_line.startswith("debug") and any(pattern in lower_line for pattern in _NOISE_PATTERNS):
            continue
        # Keep actionable OpenSSH/Borg messages and a small amount of context.
        if (
            not lower_line.startswith("debug")
            or any(token in lower_line for token in (
                "authenticating to", "offering public key", "server accepts key",
                "permission denied", "connection", "host key", "repository",
                "passphrase", "error", "warning", "traceback", "borg",
            ))
        ):
            relevant.append(normalized)

    if not relevant and raw:
        relevant = [line.strip() for line in raw.splitlines() if line.strip()][-20:]
    # Deduplicate consecutive/repeated wrapper lines and cap storage/UI payload.
    deduplicated: list[str] = []
    for line in relevant:
        if line not in deduplicated[-8:]:
            deduplicated.append(line)
    details = "\n".join(deduplicated[-80:]).strip()
    if not details:
        details = summary
    if len(details) > 16000:
        details = details[:8000] + "\n… technische Ausgabe gekürzt …\n" + details[-7000:]
    return summary, details
