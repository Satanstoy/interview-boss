"""Container runtime contracts for the non-root deployment baseline."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "Dockerfile"
ENTRYPOINT = ROOT / "deploy" / "entrypoint.sh"
NGINX_CONF = ROOT / "nginx" / "nginx.conf"
COMPOSE = ROOT / "docker-compose.yml"
DEPLOY = ROOT / "deploy" / "docker-deploy.sh"


def test_app_runtime_drops_privileges_before_entrypoint():
    dockerfile = DOCKERFILE.read_text()
    entrypoint = ENTRYPOINT.read_text()
    runtime = dockerfile.split("FROM python-base AS app-runtime", 1)[1].split(
        "FROM python-base AS test-runtime", 1
    )[0]

    assert "USER appuser" in runtime
    assert "chown -R appuser:appuser /app/backend/data" not in entrypoint
    assert "runuser -u appuser" not in entrypoint
    assert entrypoint.strip().endswith('exec "$@"')


def test_nginx_runtime_is_unprivileged_and_uses_writable_runtime_paths():
    dockerfile = DOCKERFILE.read_text()
    nginx_runtime = dockerfile.split("FROM nginx:1.29-alpine AS nginx-runtime", 1)[1]
    nginx_conf = NGINX_CONF.read_text()

    assert "USER nginx" in nginx_runtime
    assert "listen 8080" in nginx_conf
    assert "pid /tmp/nginx.pid" in nginx_conf
    assert "/tmp/nginx/" in nginx_conf


def test_compose_ports_and_healthcheck_match_non_root_nginx():
    document = yaml.safe_load(COMPOSE.read_text())
    nginx = document["services"]["nginx"]

    assert "127.0.0.1:8081:8080" in nginx["ports"]
    assert "http://127.0.0.1:8080/" in str(nginx["healthcheck"]["test"])


def test_deploy_preflights_bind_mounted_data_for_appuser():
    source = DEPLOY.read_text()

    assert "ensure_runtime_data_dir" in source
    assert "chown -R \"${APP_RUNTIME_UID}:${APP_RUNTIME_GID}\"" in source
    assert 'write_probe="$data_dir/.write-test.$$"' in source
    assert 'setpriv --reuid="${APP_RUNTIME_UID}"' in source
    assert 'touch "$write_probe"' in source
    assert source.index("ensure_runtime_data_dir") < source.index(
        "docker compose up -d --wait --wait-timeout 60 redis redis-cache backend nginx oauth-gateway"
    )
