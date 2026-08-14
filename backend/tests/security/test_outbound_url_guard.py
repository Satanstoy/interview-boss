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


def test_dns_result_is_checked_before_connect(monkeypatch):
    def fake_getaddrinfo(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(OutboundURLBlocked):
        asyncio.run(assert_safe_outbound_url("https://provider.example/v1"))


def test_llm_clients_disable_redirects(monkeypatch):
    from app.services import llm

    captured = {}

    class DummyClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "AsyncOpenAI", DummyClient)
    monkeypatch.setattr(llm, "assert_safe_outbound_url_sync", lambda _url: None)

    llm._make_client("key", "https://provider.example/v1", 30, "openai")

    http_client = captured["http_client"]
    assert http_client.follow_redirects is False
    asyncio.run(http_client.aclose())


def test_embedding_client_rejects_private_base_url(monkeypatch):
    from app.services import embedding_service

    monkeypatch.setattr(embedding_service, "_SILICONFLOW_API_KEY", "key")
    monkeypatch.setattr(embedding_service, "_SILICONFLOW_BASE_URL", "http://127.0.0.1/v1")
    embedding_service._SILICONFLOW_CLIENTS.clear()

    with pytest.raises(OutboundURLBlocked):
        embedding_service._get_siliconflow_client()
