from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


@dataclass(frozen=True)
class ExternalSshTarget:
    host: str
    port: int


def repository_location_uses_ssh(location: str) -> bool:
    parsed = urlsplit(location)
    return parsed.scheme == "ssh" or bool(re.match(r"^[^/@:]+@[^/:]+:.+", location))


def ssh_target_from_location(location: str) -> ExternalSshTarget | None:
    """Return the SSH target used by a Borg repository location.

    Automatic host-key scanning is intentionally limited to explicit ssh://
    locations. SCP-style Borg locations remain usable when known_hosts is
    entered manually.
    """
    parsed = urlsplit(location)
    if parsed.scheme != "ssh" or not parsed.hostname:
        return None
    return ExternalSshTarget(host=parsed.hostname, port=parsed.port or 22)


def generate_ed25519_keypair(comment: str) -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    private_text = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_text = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("ascii")
    safe_comment = "".join(char for char in comment if char.isalnum() or char in "-_.@")[:80]
    return private_text, f"{public_text} {safe_comment or 'borgbackup-manager'}"


def public_key_from_private(private_text: str, comment: str = "borgbackup-manager") -> str:
    try:
        private_key = serialization.load_ssh_private_key(private_text.encode("utf-8"), password=None)
    except (TypeError, ValueError) as exc:
        raise ValueError("Der SSH-Privatschlüssel muss ein unverschlüsselter OpenSSH-Schlüssel sein") from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Für externe Repositories werden ausschließlich Ed25519-SSH-Schlüssel unterstützt")
    public_text = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("ascii")
    safe_comment = "".join(char for char in comment if char.isalnum() or char in "-_.@")[:80]
    return f"{public_text} {safe_comment or 'borgbackup-manager'}"


def normalize_known_hosts(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise ValueError("known_hosts enthält keinen Hostschlüssel")
    for line in lines:
        parts = line.split()
        if len(parts) < 3 or parts[1] not in {"ssh-ed25519", "ecdsa-sha2-nistp256", "rsa-sha2-512", "rsa-sha2-256", "ssh-rsa"}:
            raise ValueError("known_hosts enthält eine ungültige SSH-Hostkey-Zeile")
    return "\n".join(lines) + "\n"


def fingerprint_known_hosts(value: str) -> str:
    normalized = normalize_known_hosts(value)
    first = normalized.splitlines()[0].split()
    raw = base64.b64decode(first[2].encode("ascii"), validate=True)
    digest = base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii").rstrip("=")
    return f"SHA256:{digest}"


async def scan_repository_host_key(location: str) -> tuple[str, str]:
    target = ssh_target_from_location(location)
    if target is None:
        raise ValueError("Automatischer Hostkey-Scan benötigt eine Repository-URL im Format ssh://…")
    process = await asyncio.create_subprocess_exec(
        "ssh-keyscan", "-T", "10", "-H", "-t", "ed25519", "-p", str(target.port), "--", target.host,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    lines = [line for line in stdout.decode(errors="replace").splitlines() if line and not line.startswith("#")]
    if process.returncode != 0 or not lines:
        detail = stderr.decode(errors="replace").strip() or "Kein ed25519-Hostkey empfangen"
        raise ValueError(f"SSH-Hostkey-Scan fehlgeschlagen: {detail}")
    known_hosts = normalize_known_hosts(lines[0])
    return known_hosts, fingerprint_known_hosts(known_hosts)
