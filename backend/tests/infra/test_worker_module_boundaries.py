"""Structural contracts for the first worker/admin god-file extraction."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_admin_evaluation_read_model_has_a_separate_module():
    module = PROJECT_ROOT / "backend/app/services/admin_evaluation_read_model.py"
    router = PROJECT_ROOT / "backend/app/routers/admin_evaluation.py"

    assert module.is_file(), "评测 read model helper 应从 admin router 拆出"
    assert "admin_evaluation_read_model" in router.read_text()
    assert "def _refresh_experiment" not in router.read_text()


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


def test_llm_protocol_and_status_have_separate_modules():
    protocol = PROJECT_ROOT / "backend/app/services/llm_protocol.py"
    status = PROJECT_ROOT / "backend/app/services/llm_status.py"
    service = PROJECT_ROOT / "backend/app/services/llm.py"

    assert protocol.is_file()
    assert status.is_file()
    source = service.read_text()
    assert "from app.services.llm_protocol import" in source
    assert "from app.services.llm_status import" in source
    assert "def resolve_api_format_async" not in source


def test_react_prompt_context_and_chat_empty_state_have_separate_modules():
    react_context = PROJECT_ROOT / "backend/app/agents/chat/react_prompt_context.py"
    react_loop = PROJECT_ROOT / "backend/app/agents/chat/react_loop.py"
    chat_empty = PROJECT_ROOT / "frontend/src/components/business/ChatEmptyState.vue"
    chat_view = PROJECT_ROOT / "frontend/src/components/business/ChatView.vue"

    assert react_context.is_file()
    assert chat_empty.is_file()
    assert "react_prompt_context" in react_loop.read_text()
    assert "ChatEmptyState" in chat_view.read_text()
