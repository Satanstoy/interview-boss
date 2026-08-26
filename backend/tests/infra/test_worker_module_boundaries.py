"""Structural contracts for the first worker/admin god-file extraction."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_admin_evaluation_read_model_has_a_separate_module():
    module = PROJECT_ROOT / "backend/app/services/admin_evaluation_read_model.py"
    router = PROJECT_ROOT / "backend/app/routers/admin_evaluation.py"

    assert module.is_file(), "评测 read model helper 应从 admin router 拆出"
    assert "admin_evaluation_read_model" in router.read_text()
    assert "def _refresh_experiment" not in router.read_text()


def test_admin_evaluation_catalog_routes_have_a_separate_module():
    module = PROJECT_ROOT / "backend/app/routers/admin_evaluation_catalog.py"
    router = PROJECT_ROOT / "backend/app/routers/admin_evaluation.py"

    assert module.is_file(), "评测 catalog 只读路由应从主 router 拆出"
    assert "admin_evaluation_catalog" in router.read_text()


def test_worker_observability_has_a_separate_module():
    module = PROJECT_ROOT / "backend/app/services/worker_observability.py"
    worker = PROJECT_ROOT / "backend/app/worker.py"

    assert module.is_file(), "worker observability 应从 worker task registry 拆出"
    assert "worker_observability" in worker.read_text()
    assert "from app.services import worker_observability" in worker.read_text()


def test_worker_cluster_tasks_have_a_separate_module():
    module = PROJECT_ROOT / "backend/app/worker_cluster_tasks.py"
    worker = PROJECT_ROOT / "backend/app/worker.py"

    assert module.is_file(), "聚类与面经重处理任务应从 worker registry 拆出"
    assert "worker_cluster_tasks" in worker.read_text()
