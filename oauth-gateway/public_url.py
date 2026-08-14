"""Build browser-facing URLs without echoing an origin IP address."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


PUBLIC_BASE_URL = "https://interviewboss.online"


def is_ip_host(host: str) -> bool:
    """Return True for ordinary and alternate numeric IP host forms."""
    normalized = host.strip().strip("[]").rstrip(".")
    if not normalized:
        return False
    try:
        socket.inet_aton(normalized)
        return True
    except OSError:
        pass
    try:
        ipaddress.ip_address(normalized)
        return True
    except ValueError:
        pass

    if normalized.isdigit():
        try:
            return 0 <= int(normalized) <= 0xFFFFFFFF
        except ValueError:
            return False
    return False


def sanitize_base_url(value: str) -> str:
    """Use the configured URL only when it has a non-IP HTTP(S) host."""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return PUBLIC_BASE_URL
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or is_ip_host(parsed.hostname)
    ):
        return PUBLIC_BASE_URL
    return value.rstrip("/")


def request_base_url(request, configured: str) -> str:
    """Derive a public base URL while rejecting IP-based Host headers."""
    forwarded_host = request.headers.get("x-forwarded-host", "")
    host = (forwarded_host or request.headers.get("host", "")).split(",", 1)[0].strip()
    if host:
        try:
            hostname = urlsplit(f"//{host}").hostname or ""
        except ValueError:
            hostname = ""
        if hostname and hostname.lower() != "localhost" and not is_ip_host(hostname):
            proto = request.headers.get("x-forwarded-proto", "https").split(",", 1)[0].strip()
            return f"{proto}://{host}".rstrip("/")
    return sanitize_base_url(configured)
