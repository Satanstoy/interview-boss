"""Runtime secret policy tests (P0-A)."""

import pytest

from app.core import config


def _valid_production_env() -> dict[str, str]:
    return {
        "ENV": "production",
        "ADMIN_PASSWORD": "A" * 16,
        "JWT_SECRET": "J" * 32,
        "OAUTH_SECRET_KEY": "O" * 32,
    }


def test_runtime_secret_policy_accepts_strong_production_values():
    validator = getattr(config, "validate_runtime_secrets", None)
    assert callable(validator)

    validator(_valid_production_env())


def test_runtime_secret_policy_rejects_short_admin_password():
    validator = getattr(config, "validate_runtime_secrets", None)
    assert callable(validator)

    env = _valid_production_env()
    env["ADMIN_PASSWORD"] = "short-password"

    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        validator(env)


def test_runtime_secret_policy_rejects_short_signing_secret():
    validator = getattr(config, "validate_runtime_secrets", None)
    assert callable(validator)

    env = _valid_production_env()
    env["JWT_SECRET"] = "too-short"

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validator(env)
