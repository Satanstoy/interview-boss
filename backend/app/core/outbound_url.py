"""Outbound URL validation for user-configurable upstream services."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlsplit

import httpcore
import httpx


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

    # Allow RFC 2544 benchmark range (198.18.0.0/15) if configured
    # This is used by proxy tools like Clash, Surge, Mihomo in fake-IP mode
    if address.version == 4 and address in ipaddress.ip_network("198.18.0.0/15"):
        from app.core.config import ALLOW_RFC2544_BENCHMARK_RANGE

        if ALLOW_RFC2544_BENCHMARK_RANGE:
            return False

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


def _is_disposable_e2e_stub(parsed) -> bool:
    """Allow only the named local test provider in the disposable E2E stack."""
    return (
        os.environ.get("ENV", "").strip().lower() == "test"
        and os.environ.get("E2E_STUB_PROVIDER", "") == "1"
        and (parsed.hostname or "").rstrip(".").lower() == "llm-stub"
    )


def _resolve_and_validate(url: str) -> tuple[object, tuple[str, ...]]:
    parsed = _split_url(url)
    if _is_disposable_e2e_stub(parsed):
        return parsed, ()
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = _resolved_addresses(parsed.hostname, port)
    except OSError as exc:
        raise OutboundURLBlocked("上游主机无法解析") from exc
    if not addresses or any(_blocked_ip(address) for address in addresses):
        raise OutboundURLBlocked("上游主机解析到了内网或保留 IP")
    return parsed, tuple(sorted(addresses))


def _check_resolved(url: str) -> str:
    _resolve_and_validate(url)
    return url.strip()


class _PinnedNetworkBackend(httpcore.NetworkBackend):
    """Synchronous network backend restricted to pre-validated addresses."""

    def __init__(self, addresses: tuple[str, ...]):
        self._addresses = addresses
        self._backend = httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        last_error: Exception | None = None
        for address in self._addresses:
            try:
                return self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # pragma: no cover - network-specific fallback
                last_error = exc
        if last_error is not None:
            raise last_error
        raise OSError(f"no validated address available for {host}")

    def connect_unix_socket(self, path: str, timeout: float | None = None, socket_options=None):
        raise OSError("Unix sockets are not valid outbound HTTP targets")

    def sleep(self, seconds: float) -> None:
        return self._backend.sleep(seconds)


class _PinnedAsyncNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect to the addresses checked before the request was created.

    The HTTP request keeps the original hostname, so HTTP Host and HTTPS SNI
    remain correct while the TCP dial cannot be redirected by a second DNS
    answer. Each new connection tries only the already-validated addresses.
    """

    def __init__(self, addresses: tuple[str, ...]):
        self._addresses = addresses
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        last_error: Exception | None = None
        for address in self._addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # pragma: no cover - network-specific fallback
                last_error = exc
        if last_error is not None:
            raise last_error
        raise OSError(f"no validated address available for {host}")

    async def connect_unix_socket(self, path: str, timeout: float | None = None, socket_options=None):
        raise OSError("Unix sockets are not valid outbound HTTP targets")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """httpx transport whose DNS result is pinned for the client lifetime."""

    def __init__(self, addresses: tuple[str, ...]):
        super().__init__(trust_env=False)
        self._pool._network_backend = _PinnedAsyncNetworkBackend(addresses)


class PinnedHTTPTransport(httpx.HTTPTransport):
    """Synchronous httpx transport whose DNS result is pinned."""

    def __init__(self, addresses: tuple[str, ...]):
        super().__init__(trust_env=False)
        self._pool._network_backend = _PinnedNetworkBackend(addresses)


def build_pinned_async_http_transport(url: str) -> PinnedAsyncHTTPTransport | None:
    """Build an async transport that dials only the validated addresses."""
    _parsed, addresses = _resolve_and_validate(url)
    if not addresses:
        # The disposable E2E provider is a Docker DNS name. It is explicitly
        # allowed only in test mode and must be resolved by the container DNS.
        return None
    return PinnedAsyncHTTPTransport(addresses)


def build_pinned_http_transport(url: str) -> PinnedHTTPTransport | None:
    """Build a sync transport that dials only the validated addresses."""
    _parsed, addresses = _resolve_and_validate(url)
    if not addresses:
        return None
    return PinnedHTTPTransport(addresses)


async def build_pinned_http_transport_async(url: str) -> PinnedAsyncHTTPTransport | None:
    """Async wrapper so DNS resolution never blocks the event loop."""
    return await asyncio.to_thread(build_pinned_async_http_transport, url)


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
