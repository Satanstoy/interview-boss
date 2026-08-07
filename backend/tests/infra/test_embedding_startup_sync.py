"""结构测试：asgi/worker 启动时同步 embedding 配置（grill Q4 决策）。

管理员通过 UI 保存的 embedding 配置存 user_profile，容器重启后必须
从 DB 重新加载（reload_embedding_config），否则回到 env 默认导致
向量维度回退、配置丢失。与全局 LLM 的 `_reload_from_db()` 启动同步一致。
"""
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = BACKEND_ROOT / "app"


def _read(rel_path: str) -> str:
    return (APP_DIR / rel_path).read_text(encoding="utf-8")


def test_asgi_startup_syncs_embedding_config():
    """asgi.py 应在 _reload_from_db() 之后调用 reload_embedding_config()。"""
    src = _read("asgi.py")
    assert "_reload_from_db()" in src
    assert "reload_embedding_config" in src
    # 必须位于 _reload_from_db() 之后（先同步 LLM，再同步 embedding）
    assert src.index("reload_embedding_config") > src.index("_reload_from_db()")


def test_worker_startup_syncs_embedding_config():
    """worker startup 应在 _reload_from_db() 之后调用 reload_embedding_config()。"""
    src = _read("worker.py")
    assert "def startup" in src
    assert "_reload_from_db()" in src
    assert "reload_embedding_config" in src
