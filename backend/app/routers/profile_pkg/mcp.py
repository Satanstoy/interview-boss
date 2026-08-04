"""Per-account MCP connection settings."""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, Request

from app.core.auth import get_current_user
from app.db.connection import run_db
from app.services.mcp_token_service import (
    get_mcp_token_metadata,
    issue_mcp_token,
    revoke_mcp_token,
)


router = APIRouter()


def _mcp_endpoint(request: Request) -> str:
    """Build the externally reachable MCP URL behind Nginx or a tunnel."""
    configured = os.getenv("MCP_PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        return configured if configured.endswith("/mcp") else f"{configured}/mcp"

    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    forwarded_host = request.headers.get("x-forwarded-host", "")
    scheme = (forwarded_proto.split(",", 1)[0].strip() or request.url.scheme).lower()
    host = forwarded_host.split(",", 1)[0].strip() or request.headers.get("host", "")
    if not host:
        host = request.url.netloc
    return f"{scheme}://{host}/mcp"


def _client_config(endpoint: str, token: str) -> dict:
    return {
        "mcpServers": {
            "interview-boss": {
                "url": endpoint,
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    }


def _stdio_client_config(endpoint: str, token: str) -> dict:
    """Build an npx bridge config for clients that only support stdio MCP."""
    auth_env = "INTERVIEW_BOSS_MCP_AUTH"
    args = [
        "-y",
        "mcp-remote",
        endpoint,
        "--transport",
        "http-only",
    ]
    if endpoint.lower().startswith("http://"):
        args.append("--allow-http")
    args.extend(["--header", f"Authorization:${{{auth_env}}}"])
    return {
        "mcpServers": {
            "interview-boss": {
                "command": "npx",
                "args": args,
                "env": {auth_env: f"Bearer {token}"},
            }
        }
    }


def _response_metadata(metadata: dict | None, endpoint: str) -> dict:
    return {
        "endpoint": endpoint,
        "transport": "streamable-http",
        "configured": metadata is not None,
        "token_hint": metadata.get("token_hint") if metadata else None,
        "created_at": metadata.get("created_at") if metadata else None,
        "rotated_at": metadata.get("rotated_at") if metadata else None,
        "last_used_at": metadata.get("last_used_at") if metadata else None,
        "warning": (
            "当前地址使用 HTTP，Bearer Token 可能被窃听。请优先通过 HTTPS、内网/VPN 或安全隧道暴露 MCP。"
            if endpoint.lower().startswith("http://")
            else None
        ),
    }


@router.get("/api/profile/mcp")
async def get_my_mcp_config(request: Request, user: dict = Depends(get_current_user)):
    """Return MCP endpoint and token metadata, never the raw token."""
    metadata = await run_db(lambda: get_mcp_token_metadata(user["id"]))
    return _response_metadata(metadata, _mcp_endpoint(request))


@router.post("/api/profile/mcp/token")
async def rotate_my_mcp_token(request: Request, user: dict = Depends(get_current_user)):
    """Issue the account's only MCP token; issuing again rotates it."""
    issued = await run_db(lambda: issue_mcp_token(user["id"]))
    endpoint = _mcp_endpoint(request)
    response = _response_metadata(issued, endpoint)
    response.update(
        {
            "token": issued["token"],
            "config": _client_config(endpoint, issued["token"]),
            "stdio_config": _stdio_client_config(endpoint, issued["token"]),
            "config_json": json.dumps(
                _client_config(endpoint, issued["token"]),
                ensure_ascii=False,
                indent=2,
            ),
            "stdio_config_json": json.dumps(
                _stdio_client_config(endpoint, issued["token"]),
                ensure_ascii=False,
                indent=2,
            ),
        }
    )
    return response


@router.delete("/api/profile/mcp/token")
async def revoke_my_mcp_token(user: dict = Depends(get_current_user)):
    """Revoke the account's MCP token until the user issues a new one."""
    revoked = await run_db(lambda: revoke_mcp_token(user["id"]))
    return {"status": "success", "revoked": revoked}
