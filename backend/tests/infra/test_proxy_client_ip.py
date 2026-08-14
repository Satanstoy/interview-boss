from types import SimpleNamespace

from app.core.request_ip import get_client_ip


def _request(peer: str, headers: dict[str, str]):
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers=headers,
    )


def test_untrusted_peer_cannot_override_client_ip_header():
    request = _request("10.0.0.8", {"x-forwarded-for": "198.51.100.10"})
    assert get_client_ip(request) == "10.0.0.8"


def test_trusted_proxy_chain_uses_first_untrusted_address(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "172.16.0.0/12")
    request = _request(
        "172.18.0.5",
        {"x-forwarded-for": "198.51.100.10, 172.18.0.1"},
    )
    assert get_client_ip(request) == "198.51.100.10"
