"""JWT signing secret loading must fail closed in production."""

from pathlib import Path

import pytest

from app.core import auth


def test_missing_production_secret_is_distinguishable(tmp_path):
    with pytest.raises(auth.JWTSecretConfigurationError, match="missing"):
        auth._load_jwt_secret({"ENV": "production"}, tmp_path / ".env")


def test_empty_production_secret_is_distinguishable(tmp_path):
    with pytest.raises(auth.JWTSecretConfigurationError, match="empty"):
        auth._load_jwt_secret(
            {"ENV": "production", "JWT_SECRET": "   "}, tmp_path / ".env"
        )


def test_short_production_secret_is_distinguishable(tmp_path):
    with pytest.raises(auth.JWTSecretConfigurationError, match="format"):
        auth._load_jwt_secret(
            {"ENV": "production", "JWT_SECRET": "too-short"}, tmp_path / ".env"
        )


def test_secret_file_permission_error_is_distinguishable(monkeypatch, tmp_path):
    def deny_read(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", deny_read)
    with pytest.raises(auth.JWTSecretConfigurationError, match="permission"):
        auth._load_jwt_secret({"ENV": "production"}, tmp_path / ".env")


def test_nonproduction_missing_secret_is_ephemeral_and_does_not_write(tmp_path):
    env_file = tmp_path / ".env"
    secret = auth._load_jwt_secret({"ENV": "development"}, env_file)

    assert len(secret) >= 32
    assert not env_file.exists()
