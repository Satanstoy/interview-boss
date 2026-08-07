"""embedding 重算 job：模型变化触发、执行、失败回滚。"""
import pytest
from unittest.mock import patch

import numpy as np

from app.core.auth import create_access_token
from app.db.connection import get_db_connection

ARQ_OFF = {"EMBEDDING_RECOMPUTE_USE_ARQ": "0"}


@pytest.fixture(autouse=True)
def reset_embedding_module():
    """重置 embedding_service 模块级状态为旧配置，避免跨测试污染触发判断。"""
    import app.services.embedding_service as es

    saved = {n: getattr(es, n) for n in (
        "_BACKEND", "_EMBEDDING_API_MODEL", "_DIMENSION", "_MODEL_REPO",
    )}
    es._BACKEND = "onnx"
    es._EMBEDDING_API_MODEL = ""
    es._DIMENSION = 512
    es._MODEL_REPO = "Xenova/bge-small-zh-v1.5"
    yield
    for n, v in saved.items():
        setattr(es, n, v)


def _admin_headers():
    token = create_access_token({"user_id": 1, "type": "access"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seed_admin_users(test_db):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM users")
        conn.execute(
            "INSERT INTO users (id, username, password_hash, is_admin, bank_mode) "
            "VALUES (1, 'admin', 'hash', 1, 'public')"
        )
        conn.execute(
            "INSERT INTO users (id, username, password_hash, is_admin, bank_mode) "
            "VALUES (2, 'user', 'hash', 0, 'public')"
        )
        conn.commit()


def _insert_question(qid, question, model="old", dim=512, blob=None):
    if blob is None:
        blob = np.full(dim, 0.5, dtype=np.float32).tobytes()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO question_bank (id, question, status, embedding, embedding_model, embedding_dim) "
            "VALUES (?, ?, 'approved', ?, ?, ?)",
            (qid, question, blob, model, dim),
        )
        conn.commit()


def _job_status(job_id):
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()["status"]


def _save_embedding(client, **overrides):
    payload = {
        "backend": "siliconflow",
        "api_model": "BAAI/bge-m3",
        "api_key": "sk-x",
        "dimension": 1024,
    }
    payload.update(overrides)
    with patch("app.services.embedding_service.reload_embedding_config"):
        return client.put("/api/profile/embedding", json=payload, headers=_admin_headers())


def test_put_embedding_model_change_creates_recompute_job(client, test_db, seed_admin_users, monkeypatch):
    monkeypatch.setenv("EMBEDDING_RECOMPUTE_USE_ARQ", "0")
    resp = _save_embedding(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["recompute_triggered"] is True
    assert body["recompute_job_id"] is not None

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT job_type, status FROM jobs WHERE id = ?",
            (body["recompute_job_id"],),
        ).fetchone()
    assert row["job_type"] == "recompute_embedding"
    assert row["status"] == "pending"


def test_put_embedding_same_config_skips_recompute(client, test_db, seed_admin_users, monkeypatch):
    monkeypatch.setenv("EMBEDDING_RECOMPUTE_USE_ARQ", "0")
    r1 = _save_embedding(client)
    r2 = _save_embedding(client)  # 相同配置（不带 api_key）
    assert r1.json()["recompute_triggered"] is True
    assert r2.json()["recompute_triggered"] is False


async def test_recompute_updates_vectors_and_completes(client, test_db, seed_admin_users, monkeypatch):
    monkeypatch.setenv("EMBEDDING_RECOMPUTE_USE_ARQ", "0")
    _insert_question(10, "什么是缓存穿透", model="old", dim=512)
    _insert_question(11, "什么是缓存击穿", model="old", dim=512)

    fake_vec = np.full(1024, 0.25, dtype=np.float32)
    with patch(
        "app.services.embedding_service.encode_texts",
        return_value=np.stack([fake_vec, fake_vec]),
    ):
        resp = _save_embedding(client)
        job_id = resp.json()["recompute_job_id"]

        from app.services.embedding_recompute import run_recompute

        await run_recompute(job_id)

    assert _job_status(job_id) == "completed"
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, embedding_model, embedding_dim FROM question_bank WHERE id IN (10, 11) ORDER BY id"
        ).fetchall()
    assert [(r["embedding_model"], r["embedding_dim"]) for r in rows] == [
        ("BAAI/bge-m3", 1024),
        ("BAAI/bge-m3", 1024),
    ]


async def test_recompute_failure_rolls_back_updated_rows(client, test_db, seed_admin_users, monkeypatch):
    monkeypatch.setenv("EMBEDDING_RECOMPUTE_USE_ARQ", "0")
    # 33 题 → 首批 32 成功、第二批失败，验证首批回滚
    for i in range(33):
        _insert_question(100 + i, f"题目 {i}", model="old", dim=512)

    with get_db_connection() as conn:
        old = {
            r["id"]: r["embedding"]
            for r in conn.execute(
                "SELECT id, embedding FROM question_bank WHERE id >= 100 ORDER BY id"
            ).fetchall()
        }

    call_count = {"n": 0}

    def _encode_with_failure(texts):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return np.stack([np.full(1024, 0.25, dtype=np.float32)] * len(texts))
        raise RuntimeError("API 限流")

    with patch(
        "app.services.embedding_service.encode_texts",
        side_effect=_encode_with_failure,
    ):
        resp = _save_embedding(client)
        job_id = resp.json()["recompute_job_id"]

        from app.services.embedding_recompute import run_recompute

        await run_recompute(job_id)

    assert _job_status(job_id) == "failed"
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, embedding, embedding_model FROM question_bank WHERE id >= 100 ORDER BY id"
        ).fetchall()
    for r in rows:
        assert r["embedding"] == old[r["id"]]
        assert r["embedding_model"] == "old"
