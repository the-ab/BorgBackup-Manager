from __future__ import annotations

import base64
import hashlib
import io
import hmac
import secrets
import struct
import time
from urllib.parse import quote

import qrcode
from qrcode.image.svg import SvgPathImage

TOTP_PERIOD = 30
TOTP_DIGITS = 6


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def _secret_bytes(secret: str) -> bytes:
    normalized = ''.join(secret.strip().upper().split())
    return base64.b32decode(normalized + '=' * (-len(normalized) % 8), casefold=True)


def totp_code(secret: str, at_time: int | float | None = None) -> str:
    counter = int((time.time() if at_time is None else at_time) // TOTP_PERIOD)
    digest = hmac.new(_secret_bytes(secret), struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f'{value % (10 ** TOTP_DIGITS):0{TOTP_DIGITS}d}'


def verify_totp(secret: str, code: str, *, at_time: int | float | None = None, window: int = 1) -> bool:
    candidate = ''.join(character for character in code if character.isdigit())
    if len(candidate) != TOTP_DIGITS:
        return False
    now = time.time() if at_time is None else float(at_time)
    return any(hmac.compare_digest(totp_code(secret, now + offset * TOTP_PERIOD), candidate) for offset in range(-window, window + 1))


def generate_recovery_codes(count: int = 10) -> list[str]:
    return [f'{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}' for _ in range(count)]


def normalize_recovery_code(code: str) -> str:
    return ''.join(character for character in code.upper() if character.isalnum())


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(normalize_recovery_code(code).encode('ascii', errors='ignore')).hexdigest()


def provisioning_uri(secret: str, username: str, issuer: str = 'BorgBackup Manager') -> str:
    label = quote(f'{issuer}:{username}', safe='')
    return f'otpauth://totp/{label}?secret={quote(secret)}&issuer={quote(issuer)}&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}'


def provisioning_qr_data_uri(uri: str) -> str:
    """Return a self-contained SVG QR code for an otpauth provisioning URI."""
    if not uri.startswith("otpauth://totp/"):
        raise ValueError("Ungültige Provisioning-URI")
    image = qrcode.make(
        uri,
        image_factory=SvgPathImage,
        box_size=8,
        border=4,
    )
    buffer = io.BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"
