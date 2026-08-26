import asyncio
import socket

import pytest

from app.core.outbound_url import (
    OutboundURLBlocked,
    assert_safe_outbound_url,
    validate_outbound_url_syntax,
)


def test_private_literal_url_is_rejected():
    with pytest.raises(OutboundURLBlocked):
        validate_outbound_url_syntax("http://127.0.0.1:8000/v1")


def test_metadata_literal_url_is_rejected():
    with pytest.raises(OutboundURLBlocked):
        validate_outbound_url_syntax("http://169.254.169.254/latest/meta-data")


@pytest.mark.parametrize(
    "url",
    [
        "http://[::1",
        "http://example.com:bad-port",
        "http://exa[mple.com",
        "http://bad host",
    ],
)
def test_malformed_url_is_rejected_as_outbound_url_error(url):
    with pytest.raises(OutboundURLBlocked):
        validate_outbound_url_syntax(url)


def test_public_custom_url_is_allowed_without_provider_allowlist():
    assert validate_outbound_url_syntax("https://my-provider.example/v1") == (
        "https://my-provider.example/v1"
    )


def test_disposable_stub_bypass_requires_explicit_test_environment(monkeypatch):
    monkeypatch.setenv("E2E_STUB_PROVIDER", "1")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.20.0.8", 8080))],
    )
    assert asyncio.run(assert_safe_outbound_url("http://llm-stub:8080/v1")) == (
        "http://llm-stub:8080/v1"
    )

    monkeypatch.setenv("ENV", "production")
    with pytest.raises(OutboundURLBlocked):
        asyncio.run(assert_safe_outbound_url("http://llm-stub:8080/v1"))


def test_dns_result_is_checked_before_connect(monkeypatch):
    def fake_getaddrinfo(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(OutboundURLBlocked):
        asyncio.run(assert_safe_outbound_url("https://provider.example/v1"))


def test_pinned_transport_dials_only_the_validated_dns_answer(monkeypatch):
    from app.core.outbound_url import build_pinned_async_http_transport

    calls = []

    def fake_getaddrinfo(host, port, **_kwargs):
        assert host == "provider.example"
        assert port == 443
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    class FakeNetworkBackend:
        async def connect_tcp(self, address, port, **_kwargs):
            calls.append((address, port))
            return object()

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    transport = build_pinned_async_http_transport("https://provider.example/v1")
    transport._pool._network_backend._backend = FakeNetworkBackend()

    asyncio.run(
        transport._pool._network_backend.connect_tcp(
            "provider.example", 443, timeout=1
        )
    )

    assert calls == [("93.184.216.34", 443)]


def test_llm_clients_disable_redirects(monkeypatch):
    from app.services import llm

    captured = {}

    class DummyClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "AsyncOpenAI", DummyClient)
    monkeypatch.setattr(llm, "assert_safe_outbound_url_sync", lambda _url: None)
    monkeypatch.setattr(llm, "build_pinned_async_http_transport", lambda _url: None)

    llm._make_client("key", "https://provider.example/v1", 30, "openai")

    http_client = captured["http_client"]
    assert http_client.follow_redirects is False
    asyncio.run(http_client.aclose())


def test_sync_pinned_transport_implements_httpx_sync_protocol(monkeypatch):
    import httpx
    from app.core.outbound_url import build_pinned_http_transport

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    transport = build_pinned_http_transport("https://provider.example/v1")

    assert hasattr(transport, "handle_request")
    with httpx.Client(transport=transport, follow_redirects=False) as client:
        assert client._transport is transport


def test_embedding_client_rejects_private_base_url(monkeypatch):
    from app.services import embedding_service

    monkeypatch.setattr(embedding_service, "_SILICONFLOW_API_KEY", "key")
    monkeypatch.setattr(embedding_service, "_SILICONFLOW_BASE_URL", "http://127.0.0.1/v1")
    embedding_service._SILICONFLOW_CLIENTS.clear()

    with pytest.raises(OutboundURLBlocked):
        embedding_service._get_siliconflow_client()


def test_profile_upstream_probe_paths_use_pinned_transports():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    llm_source = (root / "backend/app/routers/profile_pkg/llm.py").read_text()
    embedding_source = (root / "backend/app/routers/profile_pkg/embedding.py").read_text()

    assert "build_pinned_http_transport_async" in llm_source
    assert "follow_redirects=False" in llm_source
    assert "trust_env=False" in llm_source
    assert "build_pinned_http_transport(" in embedding_source
    assert "follow_redirects=False" in embedding_source
    assert "trust_env=False" in embedding_source
