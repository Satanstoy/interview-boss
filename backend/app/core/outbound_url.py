"""Outbound URL validation for user-configurable upstream services."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class OutboundURLBlocked(ValueError):
    """Raised when an outbound URL targets a private or otherwise unsafe host."""


_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "instance-data.ec2.internal",
}


def _blocked_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False

    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return not address.is_global


def _split_url(url: str):
    if not isinstance(url, str) or not url.strip():
        raise OutboundURLBlocked("上游 URL 不能为空")
    if any(char.isspace() or ord(char) < 32 for char in url):
        raise OutboundURLBlocked("上游 URL 不得包含空白或控制字符")
    try:
        parsed = urlsplit(url.strip())
        scheme = parsed.scheme.lower()
        username = parsed.username
        password = parsed.password
        hostname = parsed.hostname
        # Accessing ``port`` validates malformed numeric ports before use.
        parsed.port
    except ValueError as exc:
        raise OutboundURLBlocked("上游 URL 格式无效") from exc

    if scheme not in _ALLOWED_SCHEMES:
        raise OutboundURLBlocked("上游 URL 只允许 http 或 https")
    if username or password:
        raise OutboundURLBlocked("上游 URL 不允许携带用户名或密码")
    if not hostname:
        raise OutboundURLBlocked("上游 URL 缺少主机名")

    host = hostname.rstrip(".").lower()
    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost") or host.endswith(".local"):
        raise OutboundURLBlocked("上游 URL 不允许访问本地保留主机名")
    if _blocked_ip(host):
        raise OutboundURLBlocked("上游 URL 不允许访问内网或保留 IP")
    return parsed


def validate_outbound_url_syntax(url: str) -> str:
    """Validate a custom URL without doing network I/O."""

    _split_url(url)
    return url.strip()


def _resolved_addresses(host: str, port: int | None) -> set[str]:
    infos = socket.getaddrinfo(
        host,
        port or 443,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    addresses: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            addresses.add(str(sockaddr[0]))
    return addresses


def _check_resolved(url: str) -> str:
    parsed = _split_url(url)
    try:
        addresses = _resolved_addresses(parsed.hostname, parsed.port)
    except OSError as exc:
        raise OutboundURLBlocked("上游主机无法解析") from exc
    if not addresses or any(_blocked_ip(address) for address in addresses):
        raise OutboundURLBlocked("上游主机解析到了内网或保留 IP")
    return url.strip()


async def assert_safe_outbound_url(url: str, *, resolve: bool = True) -> str:
    """Validate a URL and, by default, resolve it before making a request."""

    if not resolve:
        return validate_outbound_url_syntax(url)
    return await asyncio.to_thread(_check_resolved, url)


def assert_safe_outbound_url_sync(url: str, *, resolve: bool = True) -> str:
    """Synchronous variant for client construction paths."""

    if not resolve:
        return validate_outbound_url_syntax(url)
    return _check_resolved(url)
