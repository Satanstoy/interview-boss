"""OAuth gateway dependencies must be independently reproducible and audited."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "oauth-gateway" / "requirements.lock"
DOCKERFILE = ROOT / "oauth-gateway" / "Dockerfile"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_oauth_gateway_has_an_exact_dependency_lock():
    lines = [line.strip() for line in LOCK.read_text().splitlines()]
    requirements = [line for line in lines if "==" in line]

    assert requirements
    assert any(line.lower().startswith("fastapi==") for line in requirements)
    assert all("==" in line for line in requirements)
    assert all(">=" not in line and "~=" not in line for line in requirements)
    assert LOCK.read_text().count("--hash=") >= len(requirements)


def test_oauth_gateway_image_installs_the_lock():
    dockerfile = DOCKERFILE.read_text()

    assert "COPY requirements.lock ." in dockerfile
    assert "-r requirements.lock" in dockerfile
    assert "--require-hashes" in dockerfile


def test_ci_audits_oauth_gateway_lock_independently():
    workflow = WORKFLOW.read_text()

    assert "pip-audit" in workflow
    assert "oauth-gateway/requirements.lock" in workflow
