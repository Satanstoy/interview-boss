"""Transport-level regression tests for the public MCP endpoint.

FastMCP defaults ``host`` to ``127.0.0.1`` and then auto-enables DNS rebinding
protection with a loopback-only allowlist.  External MCP traffic reaches the
backend through nginx -> oauth-gateway, so the forwarded ``Host`` header is
``backend:8000``.  With the protection left at its default, every request died
with ``421 Invalid Host header`` before reaching the MCP transport.
"""

import httpx

INITIALIZE_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}


async def test_proxied_host_reaches_mcp_transport():
    """A non-loopback Host from the reverse proxy must not be rejected."""
    from app.mcp_server.app import mcp

    settings = mcp.settings.transport_security
    assert settings is not None
    assert settings.enable_dns_rebinding_protection is False

    app = mcp.streamable_http_app()
    async with mcp.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://backend:8000") as client:
            response = await client.post(
                "/",
                json=INITIALIZE_PAYLOAD,
                headers={"Accept": "application/json, text/event-stream"},
            )

    assert response.status_code != 421
    assert response.status_code == 200
    assert '"result"' in response.text
