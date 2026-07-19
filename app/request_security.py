from __future__ import annotations

import ipaddress
from functools import lru_cache
from urllib.parse import urlsplit

from fastapi import Request

from app.config import SESSION_COOKIE_SECURE_MODE, TRUSTED_PROXY_CIDRS


@lru_cache(maxsize=1)
def trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    networks: list[ipaddress._BaseNetwork] = []
    for raw in TRUSTED_PROXY_CIDRS.split(","):
        value = raw.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError as exc:
            raise ValueError(f"Invalid network in BBM_TRUSTED_PROXY_CIDRS: {value}") from exc
    return tuple(networks)


def is_trusted_proxy(address: str | None) -> bool:
    if not address:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in trusted_proxy_networks())


def _first_header_value(value: str) -> str:
    return value.split(",", 1)[0].strip()


def forwarded_request_scheme(request: Request) -> str:
    """Return a proxy-reported browser scheme only for explicitly trusted peers."""
    peer = request.client.host if request.client else None
    if not is_trusted_proxy(peer):
        return ""
    for header in ("x-forwarded-proto", "x-forwarded-scheme"):
        value = _first_header_value(request.headers.get(header, "")).lower()
        if value in {"http", "https"}:
            return value
    forwarded = _first_header_value(request.headers.get("forwarded", ""))
    for item in forwarded.split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name.lower() == "proto":
            normalized = value.strip().strip('"').lower()
            if normalized in {"http", "https"}:
                return normalized
    forwarded_ssl = request.headers.get("x-forwarded-ssl", "").strip().lower()
    if forwarded_ssl in {"on", "1", "true"}:
        return "https"
    return ""


def request_uses_https(request: Request) -> bool:
    if SESSION_COOKIE_SECURE_MODE == "always":
        return True
    if SESSION_COOKIE_SECURE_MODE == "never":
        return False
    forwarded = forwarded_request_scheme(request)
    if forwarded:
        return forwarded == "https"
    return request.url.scheme.lower() == "https"


def client_address(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if not is_trusted_proxy(peer):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    for raw in forwarded.split(","):
        value = raw.strip()
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            continue
    return peer


def browser_origin(request: Request) -> str:
    scheme = forwarded_request_scheme(request) or request.url.scheme.lower()
    host = request.headers.get("host", "").strip()
    peer = request.client.host if request.client else None
    if is_trusted_proxy(peer):
        forwarded_host = _first_header_value(request.headers.get("x-forwarded-host", ""))
        if forwarded_host:
            host = forwarded_host
    if not host or any(character in host for character in "\x00\r\n/@\\") or any(character.isspace() for character in host):
        return ""
    try:
        parsed_host = urlsplit(f"//{host}")
        if not parsed_host.hostname or parsed_host.username or parsed_host.password:
            return ""
        # Accessing port performs strict numeric/range validation.
        parsed_host.port
    except ValueError:
        return ""
    return f"{scheme}://{host}".lower()


def origin_matches_request(request: Request) -> bool:
    origin = request.headers.get("origin", "").strip()
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or not parsed.scheme or not parsed.netloc:
        return False
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}" == browser_origin(request)
