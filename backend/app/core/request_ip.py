"""Trusted reverse-proxy client IP extraction."""

from __future__ import annotations

import ipaddress
import os


_DEFAULT_TRUSTED_PROXY_CIDRS = "127.0.0.1/32,::1/128,172.16.0.0/12"


def _trusted_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    raw = os.getenv("TRUSTED_PROXY_CIDRS", _DEFAULT_TRUSTED_PROXY_CIDRS)
    networks = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _as_ip(value: str | None):
    if not value:
        return None
    value = value.strip().strip("[]")
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _is_trusted(value: str | None) -> bool:
    address = _as_ip(value)
    return bool(address and any(address in network for network in _trusted_networks()))


def get_client_ip(request) -> str:
    """Return the client IP only when proxy headers come from a trusted peer."""

    peer = getattr(getattr(request, "client", None), "host", None) or "unknown"
    if not _is_trusted(peer):
        return peer

    forwarded_for = request.headers.get("x-forwarded-for", "")
    for candidate in reversed([part.strip() for part in forwarded_for.split(",") if part.strip()]):
        if not _is_trusted(candidate):
            return candidate

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip and not _is_trusted(real_ip):
        return real_ip
    return peer
