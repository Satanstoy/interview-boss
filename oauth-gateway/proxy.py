"""MCP proxy: validate OAuth token, forward to InterviewBoss."""

from __future__ import annotations

import os

import httpx
from fastapi import Request, Response
from fastapi.responses import JSONResponse

import auth
import db

_BACKEND_URL = ""


def _backend_url() -> str:
    global _BACKEND_URL
    if not _BACKEND_URL:
        _BACKEND_URL = os.getenv("INTERVIEW_BOSS_URL", "http://backend:8000").rstrip(
            "/"
        )
    return _BACKEND_URL


def _public_base_url(request: Request) -> str:
    """Build public URLs from the reverse-proxy request host when available."""
    forwarded_host = request.headers.get("x-forwarded-host")
    host = (forwarded_host or request.headers.get("host", "")).split(",", 1)[0].strip()

    if host and not host.startswith(("127.0.0.1", "localhost")):
        proto = request.headers.get("x-forwarded-proto", "https").split(",", 1)[0].strip()
        return f"{proto}://{host}".rstrip("/")

    return os.getenv("GATEWAY_BASE_URL", "https://81.71.140.248").rstrip("/")


def _mcp_error(request: Request, status: int, detail: str) -> JSONResponse:
    public = _public_base_url(request)
    # The protected resource is the canonical /mcp endpoint.  Point clients
    # at the path-aware RFC 9728 metadata URL so they do not have to guess
    # which MCP resource the challenge belongs to.
    return JSONResponse(
        {"detail": detail},
        status_code=status,
        headers={
            "WWW-Authenticate": (
                'Bearer '
                f'resource_metadata="{public}/.well-known/oauth-protected-resource/mcp", '
                'scope="mcp:read mcp:write"'
            )
        },
    )


async def proxy_mcp(request: Request) -> Response:
    """Proxy /mcp requests to InterviewBoss, converting OAuth tokens to MCP tokens."""
    auth_header = request.headers.get("authorization", "")

    if not auth_header:
        return _mcp_error(request, 401, "Bearer token required")

    if not auth_header.lower().startswith("bearer "):
        return _mcp_error(request, 401, "Bearer token required")

    token = auth_header[7:].strip()

    # Determine token type and get user_id
    if token.startswith("eyJ"):
        # OAuth JWT token — verify and extract user_id
        resource = f"{_public_base_url(request)}/mcp"
        claims = auth.verify_access_token(token, resource)
        if not claims:
            return _mcp_error(request, 401, "Invalid or expired OAuth token")
        user_id = int(claims["sub"])
    elif token.startswith("ib_mcp_"):
        # Static MCP token — forward directly (pass-through)
        return await _forward_to_backend(request, token)
    else:
        return _mcp_error(request, 401, "Unknown token format")

    # Get the user's InterviewBoss MCP token
    mcp_token = db.get_user_mcp_token(user_id)
    if not mcp_token:
        return _mcp_error(
            request,
            403, "User has no MCP token. Generate one in InterviewBoss settings."
        )

    return await _forward_to_backend(request, mcp_token)


async def _forward_to_backend(request: Request, mcp_token: str) -> Response:
    """Forward the request to InterviewBoss backend with the given MCP token."""
    backend = _backend_url()
    path = request.url.path
    if path == "/mcp":
        path = "/mcp/"
    elif not path.startswith("/mcp"):
        path = "/mcp" + path

    url = f"{backend}{path}"
    if request.url.query:
        url += f"?{request.url.query}"

    # Build headers, replacing Authorization
    headers = {}
    for key, value in request.headers.items():
        if key.lower() not in ("host", "authorization", "content-length"):
            headers[key] = value
    headers["Authorization"] = f"Bearer {mcp_token}"

    body = await request.body()

    async with httpx.AsyncClient(timeout=300) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
            )
        except httpx.ConnectError:
            return JSONResponse({"detail": "Backend unavailable"}, status_code=502)

    # Relay response
    relay_headers = {}
    for key, value in resp.headers.items():
        if key.lower() not in ("content-length", "transfer-encoding", "connection"):
            relay_headers[key] = value

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=relay_headers,
    )
