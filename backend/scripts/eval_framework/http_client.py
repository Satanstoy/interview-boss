"""HTTP/SSE client utilities for eval framework."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import timedelta
from typing import Any
from uuid import uuid4

from .types import CandidateLLMConfig, JudgeLLMConfig


def _call_openai_compatible_chat(
    config: CandidateLLMConfig | JudgeLLMConfig,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 1400,
) -> str:
    """Call an OpenAI-compatible chat API and return the assistant text."""
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    body = json.dumps({
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=config.timeout) as response:
        data = json.loads(response.read().decode())
    return data["choices"][0]["message"]["content"]


def _json_request(
    method: str,
    url: str,
    *,
    body: dict | None = None,
    token: str | None = None,
    timeout: int = 30,
) -> dict:
    """Make a JSON HTTP request and return the parsed response."""
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
        headers["X-Requested-With"] = "XMLHttpRequest"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def _login(base_url: str, username: str, password: str) -> str:
    response = _json_request(
        "POST",
        f"{base_url}/api/auth/login",
        body={"username": username, "password": password, "remember_me": False},
    )
    token = response.get("access_token") or response.get("token")
    if not token:
        raise RuntimeError("login response did not contain access_token/token")
    return str(token)


def _ensure_internal_e2e_token(internal_username: str) -> str:
    from app.core.auth import create_access_token, hash_password
    from app.db.connection import get_db_connection

    fallback_username = "__interview_eval_e2e__"
    with get_db_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (internal_username,)).fetchone()
        if not row:
            row = conn.execute("SELECT id FROM users WHERE username = ?", (fallback_username,)).fetchone()
        if row:
            user_id = int(row["id"] if hasattr(row, "keys") else row[0])
        else:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, bank_mode) VALUES (?, ?, ?, ?)",
                (fallback_username, hash_password(uuid4().hex), 0, "public"),
            )
            conn.commit()
            user_id = int(cursor.lastrowid)
    return create_access_token({"user_id": user_id, "username": fallback_username}, expires_delta=timedelta(hours=2))


def _resolve_token(args: Any) -> str:
    if args.token:
        return args.token
    if args.username and args.password:
        return _login(args.base_url, args.username, args.password)
    return _ensure_internal_e2e_token(args.username or "eval_user")


def _parse_sse_event(raw: str) -> dict:
    """Parse a single SSE event string."""
    data = ""
    for line in raw.strip().split("\n"):
        if line.startswith("data: "):
            data = line[6:]
        elif line.startswith("data:"):
            data = line[5:]
    if data == "[DONE]":
        return {"type": "done"}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {"type": "raw", "content": data}
    return parsed if isinstance(parsed, dict) else {"type": "raw", "content": parsed}


def _iter_sse_events(
    base_url: str,
    token: str,
    conversation_id: str,
    message: str,
    model: str | None = None,
    timeout: int = 120,
) -> list[dict]:
    """Send a message and collect all SSE events."""
    url = f"{base_url}/api/chat/conversations/{conversation_id}/messages"
    body: dict[str, Any] = {"content": message}
    if model:
        body["model"] = model

    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    events = []
    buffer = ""
    with urllib.request.urlopen(request, timeout=timeout) as response:
        while True:
            chunk = response.read(4096)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                raw_event, buffer = buffer.split("\n\n", 1)
                if raw_event.strip():
                    events.append(_parse_sse_event(raw_event))
    return events


def _assistant_text_from_events(events: list[dict]) -> str:
    """Extract the assistant's text from chunk events."""
    return "".join(e.get("content", "") for e in events if e.get("type") == "chunk")
