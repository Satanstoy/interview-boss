"""验证 embedding 配置可从 user_profile 热加载覆盖 env 常量。"""
import pytest

from app.db.connection import get_db_connection


@pytest.fixture
def clean_embedding_module():
    """每次测试后重置 embedding_service 模块级状态，避免跨测试污染。"""
    import app.services.embedding_service as es
    # 记录初始值以便恢复
    saved = {name: getattr(es, name) for name in (
        "_MODEL_REPO", "_MODEL_DIR", "_BACKEND", "_DIMENSION",
        "_SILICONFLOW_API_KEY", "_SILICONFLOW_BASE_URL", "_EMBEDDING_API_MODEL",
    )}
    yield es
    for name, val in saved.items():
        setattr(es, name, val)
    es._SESSION = None
    es._TOKENIZER = None
    es._SILICONFLOW_CLIENTS = {}


def test_reload_embedding_config_reads_from_user_profile(test_db, clean_embedding_module):
    es = clean_embedding_module
    # 写入 user_profile 配置
    with get_db_connection() as conn:
        for k, v in {
            "embedding_backend": "siliconflow",
            "embedding_api_key": "sk-test-reload",
            "embedding_api_model": "BAAI/bge-m3",
            "embedding_dimension": "1024",
        }.items():
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (k, v),
            )
        conn.commit()

    es.reload_embedding_config()

    assert es._BACKEND == "siliconflow"
    assert es._SILICONFLOW_API_KEY == "sk-test-reload"
    assert es._EMBEDDING_API_MODEL == "BAAI/bge-m3"
    assert es._DIMENSION == 1024
    assert es.get_embedding_dimension() == 1024


def test_reload_embedding_config_keeps_env_default_when_unset(test_db, clean_embedding_module):
    es = clean_embedding_module
    # 模拟 env 兜底已生效：模块变量为 env 值，DB 无 embedding_* key
    es._BACKEND = "onnx"
    es._DIMENSION = 512
    es.reload_embedding_config()
    # DB 无 embedding_* key → 保持模块变量（env 兜底）不动
    assert es._BACKEND == "onnx"
    assert es.get_embedding_dimension() == 512
