from __future__ import annotations

import hmac
from urllib.parse import unquote

from fastapi import Cookie, Header, HTTPException, Request

from app.config import (
    ALLOW_LEGACY_TOKEN_AUTH,
    LEGACY_ADMIN_TOKEN,
    LEGACY_SECRET_KEY,
    SESSION_COOKIE_NAME,
)
from app.security_store import AuthUser, get_session_user, get_session_user_by_reload_token


from app.secret_crypto import decrypt_value, encrypt_value, value_needs_migration


def encrypt_secret(value: str) -> str:
    return encrypt_value(value)


def decrypt_secret(value: str) -> str:
    return decrypt_value(value)


def secret_needs_migration(value: str | None) -> bool:
    return value_needs_migration(value)


def legacy_admin_token_matches(value: str | None) -> bool:
    return bool(
        ALLOW_LEGACY_TOKEN_AUTH
        and value
        and LEGACY_ADMIN_TOKEN
        and LEGACY_ADMIN_TOKEN != "change-me"
        and hmac.compare_digest(value, LEGACY_ADMIN_TOKEN)
    )


def session_cookie_values(request: Request, fallback: str | None = None) -> list[str]:
    """Return all cookies with the configured name, including duplicate stale cookies.

    Browsers may retain host-only and domain cookies with the same name. Starlette's
    normal Cookie dependency exposes only one value, which can make a valid fresh
    session look invalid after a reload when a stale cookie is ordered first.
    """
    values: list[str] = []
    raw_cookie = request.headers.get("cookie", "")
    for item in raw_cookie.split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name == SESSION_COOKIE_NAME:
            candidate = unquote(value.strip())
            if candidate and candidate not in values:
                values.append(candidate)
    if fallback and fallback not in values:
        values.append(fallback)
    return values


def _session_from_request(
    request: Request,
    authorization: str | None,
    session_cookie: str | None,
    *, allow_forced_password_change: bool,
) -> AuthUser:
    if authorization and authorization.startswith("Bearer ") and legacy_admin_token_matches(authorization[7:]):
        return AuthUser(id=0, username="legacy-admin", role="admin", enabled=True, must_change_password=False)
    if authorization and authorization.startswith("BBM-Reload "):
        user = get_session_user_by_reload_token(authorization[len("BBM-Reload "):], request.headers.get("user-agent"))
        if user is not None:
            if user.must_change_password and not allow_forced_password_change:
                raise HTTPException(status_code=403, detail="Password change required")
            return user
    user = None
    for candidate in session_cookie_values(request, session_cookie):
        user = get_session_user(candidate)
        if user is not None:
            break
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or missing session")
    if user.must_change_password and not allow_forced_password_change:
        raise HTTPException(status_code=403, detail="Password change required")
    return user


def require_authenticated_user(
    request: Request,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AuthUser:
    return _session_from_request(request, authorization, session_cookie, allow_forced_password_change=True)


def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AuthUser:
    return _session_from_request(request, authorization, session_cookie, allow_forced_password_change=False)

