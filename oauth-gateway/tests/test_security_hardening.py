import sys
import os
import tempfile
from pathlib import Path

GATEWAY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GATEWAY_ROOT))
os.environ.setdefault("OAUTH_DB_PATH", str(Path(tempfile.mkdtemp()) / "oauth.db"))
os.environ.setdefault("OAUTH_SECRET_KEY", "test-only-oauth-secret-0123456789abcdef")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app
import auth
import db
import oauth


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    oauth._DCR_LIMITER.clear()
    oauth._AUTHORIZE_LIMITER.clear()
    oauth._TOKEN_LIMITER.clear()


def test_oauth_secret_missing_fails_closed(monkeypatch):
    monkeypatch.setattr(auth, "_SECRET", "")
    with pytest.raises(RuntimeError):
        auth.require_configured_secret()


def test_oauth_secret_must_have_minimum_entropy_length(monkeypatch):
    monkeypatch.setattr(auth, "_SECRET", "too-short")
    with pytest.raises(RuntimeError):
        auth.require_configured_secret()


def test_client_registration_rejects_oversized_redirect_list(monkeypatch):
    monkeypatch.setattr(db, "create_client", lambda *args, **kwargs: pytest.fail("must reject"))
    payload = {
        "client_name": "client",
        "redirect_uris": [f"https://client.example/{i}" for i in range(11)],
    }
    with TestClient(app.app) as client:
        response = client.post("/oauth/register", json=payload)
    assert response.status_code == 400


def test_client_registration_rejects_malformed_redirect_uri(monkeypatch):
    monkeypatch.setattr(db, "create_client", lambda *args, **kwargs: pytest.fail("must reject"))
    payload = {"client_name": "client", "redirect_uris": ["javascript:alert(1)"]}
    with TestClient(app.app) as client:
        response = client.post("/oauth/register", json=payload)
    assert response.status_code == 400


def test_client_registration_is_rate_limited(monkeypatch):
    monkeypatch.setattr(db, "create_client", lambda *args, **kwargs: {})
    payload = {"client_name": "client", "redirect_uris": ["https://client.example/cb"]}
    with TestClient(app.app) as client:
        responses = [client.post("/oauth/register", json=payload) for _ in range(11)]
    assert responses[-1].status_code == 429


def test_chatgpt_registration_shape_remains_supported(monkeypatch):
    monkeypatch.setattr(db, "create_client", lambda *args, **kwargs: {})
    payload = {
        "client_name": "ChatGPT",
        "redirect_uris": ["https://chatgpt.com/connector/oauth/callback"],
        "token_endpoint_auth_method": "none",
    }
    with TestClient(app.app) as client:
        response = client.post("/oauth/register", json=payload)
    assert response.status_code == 201


def test_client_secret_post_requires_the_registered_secret(monkeypatch):
    monkeypatch.setattr(
        db,
        "get_client",
        lambda _client_id: {
            "client_id": "confidential",
            "auth_method": "client_secret_post",
            "client_secret": auth.hash_token("expected-secret"),
            "redirect_uris": ["https://client.example/callback"],
        },
    )
    with pytest.raises(HTTPException) as exc_info:
        oauth._authenticate_client({"client_id": "confidential", "client_secret": "wrong"})
    assert exc_info.value.status_code == 401


def test_client_secret_post_accepts_the_registered_secret(monkeypatch):
    monkeypatch.setattr(
        db,
        "get_client",
        lambda _client_id: {
            "client_id": "confidential",
            "auth_method": "client_secret_post",
            "client_secret": auth.hash_token("expected-secret"),
            "redirect_uris": ["https://client.example/callback"],
        },
    )
    client = oauth._authenticate_client(
        {"client_id": "confidential", "client_secret": "expected-secret"}
    )
    assert client["client_id"] == "confidential"
