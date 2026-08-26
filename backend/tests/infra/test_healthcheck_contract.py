"""Compose healthcheck contracts for edge and authentication services."""

from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _compose_services() -> dict:
    compose = yaml.safe_load((PROJECT_ROOT / "docker-compose.yml").read_text())
    return compose["services"]


def _healthcheck(service_name: str) -> dict:
    healthcheck = _compose_services()[service_name].get("healthcheck")
    assert isinstance(healthcheck, dict), f"{service_name} 必须声明 healthcheck"
    assert healthcheck.get("disable") is not True, f"{service_name} 不得禁用 healthcheck"
    for key in ("interval", "timeout", "retries", "start_period"):
        assert key in healthcheck, f"{service_name} healthcheck 缺少 {key}"
    assert healthcheck["retries"] >= 1
    return healthcheck


def test_nginx_healthcheck_probes_local_http_entrypoint():
    healthcheck = _healthcheck("nginx")
    command = " ".join(str(part) for part in healthcheck["test"])

    assert "127.0.0.1" in command or "localhost" in command
    assert "http" in command
    assert "/" in command


def test_oauth_gateway_healthcheck_probes_health_endpoint():
    healthcheck = _healthcheck("oauth-gateway")
    command = " ".join(str(part) for part in healthcheck["test"])

    assert "127.0.0.1" in command or "localhost" in command
    assert "/health" in command
    assert "8082" in command


def test_edge_services_wait_for_healthy_backend():
    services = _compose_services()

    for service_name in ("nginx", "oauth-gateway"):
        backend_dependency = services[service_name]["depends_on"]["backend"]
        assert backend_dependency["condition"] == "service_healthy"
