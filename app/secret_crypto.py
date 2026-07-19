from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from app.config import LEGACY_SECRET_KEY, MASTER_KEY_PATH

_MASTER_PREFIX = "v2:"


def load_master_key() -> bytes:
    MASTER_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(MASTER_KEY_PATH.parent, 0o700)
    except OSError:
        pass
    if MASTER_KEY_PATH.is_file():
        key = MASTER_KEY_PATH.read_bytes().strip()
        try:
            Fernet(key)
        except (ValueError, TypeError) as exc:
            raise RuntimeError(f"Ungültiger Master-Key: {MASTER_KEY_PATH}") from exc
        return key
    key = Fernet.generate_key()
    descriptor = os.open(MASTER_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, key + b"\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return key


def _fernet() -> Fernet:
    return Fernet(load_master_key())


def _legacy_fernet() -> Fernet | None:
    if not LEGACY_SECRET_KEY or LEGACY_SECRET_KEY == "change-me":
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(LEGACY_SECRET_KEY.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_value(value: str) -> str:
    return _MASTER_PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_value(value: str) -> str:
    candidates: list[Fernet] = []
    token = value
    if value.startswith(_MASTER_PREFIX):
        token = value[len(_MASTER_PREFIX):]
        candidates.append(_fernet())
    else:
        legacy = _legacy_fernet()
        if legacy is not None:
            candidates.append(legacy)
        candidates.append(_fernet())
    for candidate in candidates:
        try:
            return candidate.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError):
            continue
    raise ValueError("Geheimnis kann weder mit dem Master-Key noch mit dem alten BBM_SECRET_KEY entschlüsselt werden")


def value_needs_migration(value: str | None) -> bool:
    return bool(value) and not value.startswith(_MASTER_PREFIX)
