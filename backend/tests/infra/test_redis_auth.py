from urllib.parse import urlsplit


def test_redis_url_injects_password_without_logging_it(monkeypatch):
    import app.core.config as config

    monkeypatch.setattr(config, "REDIS_PASSWORD", "unit-test-secret")
    url = config.build_redis_url("redis://redis:6379/0", "redis://localhost:6379/0")
    parsed = urlsplit(url)
    assert parsed.password == "unit-test-secret"
    assert "unit-test-secret" not in config.redact_redis_url(url)


def test_redis_url_preserves_explicit_credentials(monkeypatch):
    import app.core.config as config

    monkeypatch.setattr(config, "REDIS_PASSWORD", "new-secret")
    url = config.build_redis_url(
        "redis://existing:old-secret@redis:6379/0",
        "redis://localhost:6379/0",
    )
    assert url == "redis://existing:old-secret@redis:6379/0"


def test_compose_cache_default_uses_redis_service_port(monkeypatch):
    import app.core.config as config

    monkeypatch.setattr(config, "REDIS_PASSWORD", "cache-secret")
    assert config.build_redis_url("", "redis://redis-cache:6379/0").endswith(
        "@redis-cache:6379/0"
    )
