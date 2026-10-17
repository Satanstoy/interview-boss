"""Contracts for the disposable real-stack smoke test.

These tests keep the real-stack job separate from mocked Playwright tests and
make sure it cannot accidentally reuse the production env/data mounts.
"""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "docker-compose.real-e2e.yml"
RUNNER = ROOT / "scripts" / "real_stack_smoke.sh"
PLAYWRIGHT_CONFIG = ROOT / "frontend" / "tests" / "playwright.config.js"
SPEC = ROOT / "frontend" / "tests" / "e2e" / "real-stack-smoke.spec.js"


def test_real_stack_compose_is_disposable_and_has_required_services():
    document = yaml.safe_load(COMPOSE.read_text())
    services = document["services"]

    assert {"redis", "redis-cache", "llm-stub", "backend", "worker", "oauth-gateway", "nginx"} <= set(services)
    assert "env_file" not in services["backend"]
    assert "env_file" not in services["worker"]
    assert "./backend/data" not in str(services["backend"].get("volumes", []))
    assert "real-e2e-data" in str(services["backend"]["volumes"])
    assert "real-e2e-data" in str(services["worker"]["volumes"])
    assert services["backend"]["healthcheck"]["test"]
    assert services["worker"]["healthcheck"]["test"]
    assert services["nginx"]["healthcheck"]["test"]
    assert services["nginx"]["depends_on"]["backend"]["condition"] == "service_healthy"
    assert services["worker"]["depends_on"]["backend"]["condition"] == "service_healthy"
    assert document["volumes"]["real-e2e-data"] in (None, {})


def test_real_stack_runner_uses_ephemeral_compose_project_and_cleans_up():
    source = RUNNER.read_text()

    assert "docker-compose.real-e2e.yml" in source
    assert "--project-name" in source
    assert "down --volumes --remove-orphans" in source
    assert "trap" in source
    assert "REAL_STACK_E2E=1" in source
    assert "--timeout" in source


def test_real_stack_playwright_mode_has_no_local_dev_server():
    config = PLAYWRIGHT_CONFIG.read_text()
    spec = SPEC.read_text()

    assert "REAL_STACK_E2E" in config
    assert "PLAYWRIGHT_BASE_URL" in config
    assert "webServer" in config
    assert "stubbed provider" in spec.lower()
    assert "失败" in spec
