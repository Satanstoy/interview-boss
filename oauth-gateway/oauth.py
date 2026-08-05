"""OAuth 2.1 endpoints: discovery, registration, authorization, token."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import auth
import db

router = APIRouter()
templates = Jinja2Templates(directory="/app/templates")

_BASE_URL = ""


def _base_url() -> str:
    global _BASE_URL
    if not _BASE_URL:
        import os

        _BASE_URL = os.getenv("GATEWAY_BASE_URL", "https://81.71.140.248").rstrip("/")
    return _BASE_URL


def _request_base_url(request: Request) -> str:
    """Use the public reverse-proxy host for browser-facing OAuth metadata."""
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        host = forwarded_host.split(",", 1)[0].strip()
        proto = request.headers.get("x-forwarded-proto", "https").split(",", 1)[0].strip()
        return f"{proto}://{host}".rstrip("/")
    host = request.headers.get("host", "")
    if host and not host.startswith(("127.0.0.1", "localhost")):
        return f"https://{host}".rstrip("/")
    return _base_url()


# ── Discovery ──


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata(request: Request):
    base = _request_base_url(request)
    return JSONResponse(
        {
            "resource": f"{base}/mcp",
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
            "scopes_supported": ["mcp:read", "mcp:write"],
        }
    )


@router.get("/.well-known/oauth-protected-resource/{resource_path:path}")
async def protected_resource_metadata_for_path(request: Request, resource_path: str):
    """Serve path-aware OAuth PRM discovery required for MCP /mcp resources."""
    return await protected_resource_metadata(request)


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata(request: Request):
    base = _request_base_url(request)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "client_id_metadata_document_supported": True,
            "code_challenge_methods_supported": ["S256"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "response_types_supported": ["code"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
            "scopes_supported": ["mcp:read", "mcp:write", "offline_access"],
        }
    )


@router.get("/.well-known/oauth-authorization-server/{resource_path:path}")
async def authorization_server_metadata_for_path(
    request: Request, resource_path: str
):
    """Compatibility alias for clients that append the MCP path to discovery."""
    return await authorization_server_metadata(request)


@router.get("/.well-known/openid-configuration")
async def openid_configuration(request: Request):
    """Return OAuth metadata for clients that probe the OIDC discovery URL."""
    return await authorization_server_metadata(request)


@router.get("/.well-known/openid-configuration/{resource_path:path}")
async def openid_configuration_for_path(request: Request, resource_path: str):
    """Compatibility alias for path-aware OIDC discovery probes."""
    return await authorization_server_metadata(request)


@router.get("/oauth/token/.well-known/openid-configuration")
async def token_openid_configuration(request: Request):
    """Compatibility alias used by some OAuth discovery clients."""
    return await authorization_server_metadata(request)


# ── Dynamic Client Registration ──


@router.post("/oauth/register")
async def register_client(request: Request):
    body = await request.json()
    client_name = body.get("client_name", "Unnamed Client")
    redirect_uris = body.get("redirect_uris", [])
    auth_method = body.get("token_endpoint_auth_method", "none")

    if not redirect_uris:
        raise HTTPException(400, "redirect_uris required")

    client_id = f"chatgpt_{secrets.token_hex(16)}"
    client_secret_hash = None
    raw_secret = None

    if auth_method != "none":
        raw_secret = secrets.token_urlsafe(32)
        client_secret_hash = auth.hash_token(raw_secret)

    db.create_client(
        client_id, client_secret_hash, client_name, redirect_uris, auth_method
    )

    resp = {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": auth_method,
        "client_id_issued_at": int(time.time()),
    }
    if auth_method != "none":
        resp["client_secret"] = raw_secret

    return JSONResponse(resp, status_code=201)


# ── Authorization ──


def _is_chatgpt_client(client: dict) -> bool:
    """Check if client is a ChatGPT connector (allowlist by redirect_uri prefix)."""
    return any(_is_chatgpt_redirect_uri(uri) for uri in client.get("redirect_uris", []))


def _is_chatgpt_redirect_uri(uri: str) -> bool:
    return uri.startswith(
        ("https://chatgpt.com/connector/oauth/", "https://chatgpt.com/connector_platform_oauth_redirect")
    )


def _is_chatgpt_cimd_client_id(client_id: str) -> bool:
    parsed = urlparse(client_id)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "chatgpt.com"
        and parsed.path.startswith("/oauth/")
        and parsed.path.endswith("/client.json")
        and not parsed.query
        and not parsed.fragment
    )


def _get_or_register_cimd_client(
    client_id: str, redirect_uri: str
) -> dict | None:
    """Accept OpenAI's HTTPS CIMD client identity with a strict redirect allowlist."""
    if not _is_chatgpt_cimd_client_id(client_id) or not _is_chatgpt_redirect_uri(
        redirect_uri
    ):
        return None

    client = db.get_client(client_id)
    if client:
        return client

    try:
        db.create_client(client_id, None, "ChatGPT", [redirect_uri], "none")
    except sqlite3.IntegrityError:
        pass
    return db.get_client(client_id)


@router.get("/oauth/authorize")
async def authorize(
    request: Request,
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    code_challenge: str = Query(""),
    code_challenge_method: str = Query("S256"),
    state: str = Query(""),
    resource: str = Query(""),
    scope: str = Query("mcp:read mcp:write"),
):
    if response_type != "code":
        raise HTTPException(400, "unsupported response_type")

    client = db.get_client(client_id) or _get_or_register_cimd_client(
        client_id, redirect_uri
    )
    if not client:
        raise HTTPException(400, "unknown client_id")

    if redirect_uri not in client["redirect_uris"]:
        raise HTTPException(400, "invalid redirect_uri")

    # PKCE: required for non-ChatGPT clients, optional for ChatGPT
    if not _is_chatgpt_client(client) and not code_challenge:
        raise HTTPException(
            400, "code_challenge required (PKCE mandatory for this client)"
        )

    if code_challenge and code_challenge_method != "S256":
        raise HTTPException(400, "only S256 code_challenge_method supported")

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "client_name": client["client_name"],
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "state": state,
            "resource": resource,
            "scope": scope,
            "error": None,
        },
    )


@router.post("/oauth/authorize")
async def authorize_post(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    client_id: str = Form(""),
    redirect_uri: str = Form(""),
    code_challenge: str = Form(""),
    code_challenge_method: str = Form("S256"),
    state: str = Form(""),
    resource: str = Form(""),
    scope: str = Form(""),
):
    # Graceful error on missing required fields (don't 500)
    if not client_id or not redirect_uri:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "client_name": "",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "state": state,
                "resource": resource,
                "scope": scope,
                "error": "缺少必要参数",
            },
        )

    client = db.get_client(client_id) or _get_or_register_cimd_client(
        client_id, redirect_uri
    )
    if not client:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "client_name": "Unknown",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "state": state,
                "resource": resource,
                "scope": scope,
                "error": "未知的 client_id",
            },
        )

    if redirect_uri not in client["redirect_uris"]:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "client_name": client["client_name"],
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "state": state,
                "resource": resource,
                "scope": scope,
                "error": "redirect_uri 不匹配",
            },
        )

    if not _is_chatgpt_client(client) and not code_challenge:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "client_name": client["client_name"],
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "state": state,
                "resource": resource,
                "scope": scope,
                "error": "此客户端必须提供 code_challenge (PKCE)",
            },
        )

    if not username or not password:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "client_name": client["client_name"],
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "state": state,
                "resource": resource,
                "scope": scope,
                "error": "请输入用户名和密码",
            },
        )

    user_id = db.verify_interviewboss_user(username, password)
    if user_id is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "client_name": client["client_name"],
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "state": state,
                "resource": resource,
                "scope": scope,
                "error": "用户名或密码错误",
            },
        )

    # Generate authorization code
    code = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

    db.save_code(code, client_id, user_id, code_challenge, scope, resource, expires_at)

    # Redirect back to client
    params = {"code": code}
    if state:
        params["state"] = state

    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(
        url=f"{redirect_uri}{separator}{urlencode(params)}",
        status_code=302,
    )


# ── Token ──


@router.post("/oauth/token")
async def token_endpoint(request: Request):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)

    grant_type = body.get("grant_type")

    if grant_type == "authorization_code":
        return await _handle_authorization_code(body)
    elif grant_type == "refresh_token":
        return await _handle_refresh_token(body)
    else:
        raise HTTPException(400, "unsupported grant_type")


async def _handle_authorization_code(body: dict) -> JSONResponse:
    code = body.get("code")
    redirect_uri = body.get("redirect_uri")
    client_id = body.get("client_id")
    code_verifier = body.get("code_verifier")

    if not all([code, redirect_uri, client_id]):
        raise HTTPException(400, "missing required parameters")

    # Verify and consume the code
    code_data = db.get_and_use_code(code)
    if not code_data:
        raise HTTPException(400, "invalid or expired code")

    if code_data["client_id"] != client_id:
        raise HTTPException(400, "client_id mismatch")

    # PKCE verification: only if code_challenge was bound to the authorization code
    stored_challenge = code_data.get("code_challenge") or ""
    if stored_challenge:
        if not code_verifier:
            raise HTTPException(400, "code_verifier required (PKCE)")
        challenge = hashlib.sha256(code_verifier.encode()).digest()
        import base64

        computed_challenge = base64.urlsafe_b64encode(challenge).rstrip(b"=").decode()
        if not secrets.compare_digest(computed_challenge, stored_challenge):
            raise HTTPException(400, "PKCE verification failed")
    # If no code_challenge was stored (ChatGPT client without PKCE), skip verification.
    # code_verifier is ignored if present without a stored challenge.

    # Issue tokens
    user_id = code_data["user_id"]
    scopes = code_data["scopes"] or "mcp:read mcp:write"
    resource = code_data.get("resource") or ""

    access_token = auth.create_access_token(user_id, client_id, scopes, resource)
    refresh_token = auth.create_refresh_token(user_id, client_id, scopes)

    now = datetime.now(timezone.utc)
    db.save_access_token(
        auth.hash_token(access_token),
        user_id,
        client_id,
        scopes,
        (now + timedelta(seconds=auth._ACCESS_TTL)).isoformat(),
    )
    db.save_refresh_token(
        auth.hash_token(refresh_token),
        user_id,
        client_id,
        scopes,
        (now + timedelta(seconds=auth._REFRESH_TTL)).isoformat(),
        resource,
    )

    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": auth._ACCESS_TTL,
            "refresh_token": refresh_token,
            "scope": scopes,
        }
    )


async def _handle_refresh_token(body: dict) -> JSONResponse:
    refresh_token = body.get("refresh_token")
    client_id = body.get("client_id")

    if not all([refresh_token, client_id]):
        raise HTTPException(400, "missing required parameters")

    token_hash = auth.hash_token(refresh_token)
    token_data = db.get_refresh_token(token_hash)
    if not token_data:
        raise HTTPException(400, "invalid or expired refresh_token")

    if token_data["client_id"] != client_id:
        raise HTTPException(400, "client_id mismatch")

    # Rotate refresh token
    db.delete_refresh_token(token_hash)

    user_id = token_data["user_id"]
    scopes = token_data["scopes"] or "mcp:read mcp:write"
    stored_resource = token_data.get("resource") or ""
    requested_resource = body.get("resource") or stored_resource
    if stored_resource and requested_resource != stored_resource:
        raise HTTPException(400, "resource mismatch")

    new_access_token = auth.create_access_token(
        user_id, client_id, scopes, requested_resource
    )
    new_refresh_token = auth.create_refresh_token(user_id, client_id, scopes)

    now = datetime.now(timezone.utc)
    db.save_access_token(
        auth.hash_token(new_access_token),
        user_id,
        client_id,
        scopes,
        (now + timedelta(seconds=auth._ACCESS_TTL)).isoformat(),
    )
    db.save_refresh_token(
        auth.hash_token(new_refresh_token),
        user_id,
        client_id,
        scopes,
        (now + timedelta(seconds=auth._REFRESH_TTL)).isoformat(),
        requested_resource,
    )

    return JSONResponse(
        {
            "access_token": new_access_token,
            "token_type": "Bearer",
            "expires_in": auth._ACCESS_TTL,
            "refresh_token": new_refresh_token,
            "scope": scopes,
        }
    )
