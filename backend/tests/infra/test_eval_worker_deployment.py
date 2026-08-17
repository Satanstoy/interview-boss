"""Deployment contracts for the on-demand evaluation worker."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]


def test_eval_worker_deployment_commands_install_and_report_timer_status():
    source = (ROOT / "deploy" / "docker-deploy.sh").read_text()

    assert "eval-worker-install" in source
    assert "eval-worker-status" in source
    assert "systemctl enable --now interview-boss-eval-worker.timer" in source


def test_eval_worker_launcher_has_runtime_preflight_checks():
    source = (ROOT / "deploy" / "eval-worker-launcher.sh").read_text()

    assert "docker info" in source
    assert "redis" in source
    assert "quick_check" in source
    assert "flock -n" in source
    assert "docker ps" in source
    assert "com.docker.compose.service=eval-worker" in source


def test_eval_worker_deployment_scripts_are_valid_shell():
    for script in ("deploy/docker-deploy.sh", "deploy/eval-worker-launcher.sh"):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / script)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
