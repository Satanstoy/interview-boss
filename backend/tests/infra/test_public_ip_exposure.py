import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_IP = ".".join(("81", "71", "140", "248"))


def test_public_runtime_and_documentation_do_not_contain_origin_ip():
    tracked_paths = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT
    ).decode().split("\0")
    leaked = []
    for relative_path in tracked_paths:
        if not relative_path:
            continue
        path = REPO_ROOT / relative_path
        try:
            if PUBLIC_IP in path.read_text(encoding="utf-8"):
                leaked.append(path)
        except UnicodeDecodeError:
            continue

    assert leaked == []


def test_gateway_defaults_to_public_domain():
    source = (REPO_ROOT / "oauth-gateway/oauth.py").read_text(encoding="utf-8")

    assert 'os.getenv("GATEWAY_BASE_URL", PUBLIC_BASE_URL)' in source
    assert "return request_base_url(request, _base_url())" in source


def test_gateway_and_mcp_defaults_share_www_canonical_origin(monkeypatch):
    from app.routers.profile_pkg import mcp

    monkeypatch.delenv("GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("MCP_PUBLIC_URL", raising=False)

    gateway_source = (REPO_ROOT / "oauth-gateway/public_url.py").read_text(
        encoding="utf-8"
    )
    assert 'PUBLIC_BASE_URL = "https://www.interviewboss.online"' in gateway_source
    assert mcp._PUBLIC_MCP_ENDPOINT == "https://www.interviewboss.online/mcp"


def test_gateway_public_url_helper_never_echoes_ip_hosts():
    import sys

    sys.path.insert(0, str(REPO_ROOT / "oauth-gateway"))
    try:
        from public_url import request_base_url, sanitize_base_url

        for host in (
            PUBLIC_IP,
            f"{PUBLIC_IP}:443",
            f"{PUBLIC_IP}.",
            "2130706433",
            "0x7f000001",
            "017700000001",
            "0177.0.0.1",
            "[::1]",
            "localhost",
        ):
            request = type("Request", (), {
                "headers": {"host": host},
            })()
            assert request_base_url(request, f"https://{PUBLIC_IP}") == "https://www.interviewboss.online"
        forwarded = type("Request", (), {
            "headers": {"x-forwarded-host": f"{PUBLIC_IP}:443"},
        })()
        assert request_base_url(forwarded, "https://interviewboss.online") == "https://interviewboss.online"
        attacker = type("Request", (), {
            "headers": {"host": "attacker.example"},
        })()
        assert request_base_url(attacker, "https://interviewboss.online") == "https://interviewboss.online"
        assert sanitize_base_url(f"https://{PUBLIC_IP}") == "https://www.interviewboss.online"
    finally:
        sys.path.pop(0)


def test_mcp_endpoint_defaults_to_public_domain_when_request_has_no_host(monkeypatch):
    from app.routers.profile_pkg import mcp

    monkeypatch.delenv("MCP_PUBLIC_URL", raising=False)
    request = type("Request", (), {
        "headers": {},
        "url": type("URL", (), {"scheme": "https", "netloc": ""})(),
    })()

    assert mcp._mcp_endpoint(request) == "https://www.interviewboss.online/mcp"


def test_mcp_endpoint_does_not_reflect_arbitrary_host(monkeypatch):
    from app.routers.profile_pkg import mcp

    monkeypatch.delenv("MCP_PUBLIC_URL", raising=False)
    request = type("Request", (), {
        "headers": {"host": "attacker.example", "x-forwarded-host": "attacker.example"},
        "url": type("URL", (), {"scheme": "https", "netloc": "attacker.example"})(),
    })()

    assert mcp._mcp_endpoint(request) == "https://www.interviewboss.online/mcp"


def test_mcp_endpoint_does_not_echo_ip_from_private_config_or_request(monkeypatch):
    from app.routers.profile_pkg import mcp

    private_ip = PUBLIC_IP
    monkeypatch.setenv("MCP_PUBLIC_URL", f"https://{private_ip}/mcp")
    request = type("Request", (), {
        "headers": {"host": private_ip},
        "url": type("URL", (), {"scheme": "https", "netloc": private_ip})(),
    })()

    assert mcp._mcp_endpoint(request) == "https://www.interviewboss.online/mcp"
