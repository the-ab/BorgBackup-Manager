from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

from app.config import MASTER_KEY_PATH

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


def encrypt_value(value: str) -> str:
    return _MASTER_PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_value(value: str) -> str:
    if not value.startswith(_MASTER_PREFIX):
        raise ValueError("Geheimnis verwendet ein nicht unterstütztes Verschlüsselungsformat")
    token = value[len(_MASTER_PREFIX):]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("Geheimnis kann mit dem aktuellen Master-Key nicht entschlüsselt werden") from exc


