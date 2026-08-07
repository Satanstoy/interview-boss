# 管理员全局模型配置 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理员在设置页 → 管理员管理 → 新增「模型配置」tab，统一配置全局 LLM（Base URL/模型名/API Key/超时，测试连接）与 embedding（backend 模式/模型/维度/API Key，测试连接），更换 embedding 模型时自动触发全量向量重算并显示进度。

**Architecture:** 全局 LLM 复用现有 `user_profile` KV 存储 + `GET/PUT /api/profile`（admin-only），只补一个全局测试连接端点；embedding 新增独立端点 `GET/PUT/POST /api/profile/embedding*`（admin-only）写 `user_profile` 新 key，`embedding_service.py` 增加 `reload_embedding_config()` 从 DB 覆盖 env 常量热加载，模型变化时经 `jobs` 表 + `/api/jobs/{id}/stream` SSE 触发全量重算并推进度到前端。

**Tech Stack:** FastAPI (admin auth) / SQLite user_profile KV / ARQ worker / Vue3 + shadcn-vue + profileApi.js

---

### Task 1: `embedding_service.py` 支持 DB 覆盖配置 + `reload_embedding_config()`

**Files:**
- Modify: `backend/app/services/embedding_service.py`
- Test: `backend/tests/services/test_embedding_config_reload.py`（新建）

**背景：** 当前 `_MODEL_REPO/_BACKEND/_DIMENSION/_SILICONFLOW_*` 等全部是模块级 env 常量。本任务把它们改为"启动 env 兜底 + `reload_embedding_config()` 从 DB 覆盖"，并让新配置立即生效（重建 session/client/FAISS 缓存）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/services/test_embedding_config_reload.py
"""验证 embedding 配置可从 user_profile 热加载覆盖 env 常量。"""
import importlib
import pytest
from unittest.mock import patch

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
    with patch.dict("os.environ", {"EMBEDDING_BACKEND": "onnx", "EMBEDDING_DIMENSION": "512"}, clear=False):
        es.reload_embedding_config()
    # DB 无 embedding_* key → 保持 env 值
    assert es._BACKEND == "onnx"
    assert es.get_embedding_dimension() == 512
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_embedding_config_reload.py -v`
Expected: `FAIL` — `es.reload_embedding_config` 不存在（AttributeError）

- [ ] **Step 3: 实现 `reload_embedding_config()`**

在 `embedding_service.py` 顶部（`_MODEL_REPO` 等 env 常量之后）新增函数：

```python
# 用户可通过 DB（user_profile 表）覆盖的配置 key → (模块级变量名, 转换函数)
_DB_CONFIG_MAP = {
    "embedding_backend": ("_BACKEND", lambda v: v.lower()),
    "embedding_model_repo": ("_MODEL_REPO", str),
    "embedding_model_dir": ("_MODEL_DIR", lambda v: Path(v)),
    "embedding_dimension": ("_DIMENSION", int),
    "embedding_api_key": ("_SILICONFLOW_API_KEY", str),
    "embedding_api_model": ("_EMBEDDING_API_MODEL", str),
    "embedding_api_base_url": ("_SILICONFLOW_BASE_URL", str),
}


def reload_embedding_config() -> None:
    """从 user_profile 表读取 embedding 配置覆盖模块级常量。

    在保存配置后调用，使新配置立即生效。会重置已缓存的
    ONNX session / tokenizer / SiliconFlow client / FAISS 索引缓存。
    """
    from app.core.config import get_profile_setting

    changed = False
    for profile_key, (attr_name, transform) in _DB_CONFIG_MAP.items():
        raw = get_profile_setting(profile_key)
        if raw:
            try:
                val = transform(raw)
                globals()[attr_name] = val
                changed = True
            except (ValueError, TypeError):
                logger.warning("无效的 embedding 配置 %s=%r", profile_key, raw)

    if not changed:
        return

    # 重建运行时资源
    global _SESSION, _TOKENIZER
    _SESSION = None
    _TOKENIZER = None
    _SILICONFLOW_CLIENTS.clear()

    from app.services.faiss_index_manager import get_index_manager
    get_index_manager().invalidate()

    logger.info(
        "embedding 配置已从 DB 加载: backend=%s dim=%d model=%s",
        _BACKEND, _DIMENSION, _EMBEDDING_API_MODEL,
    )
```

注意：`_MODEL_DIR` 已在模块级声明为 `Path`，覆盖时同样转 `Path`。

- [ ] **Step 4: 跑测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_embedding_config_reload.py -v`
Expected: `PASS`（2 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/embedding_service.py backend/tests/services/test_embedding_config_reload.py
git commit -m "feat(backend): embedding config hot-reload from user_profile"
```

---

### Task 2: 后端 embedding 配置读写 + 测试连接端点

**Files:**
- Create: `backend/app/routers/profile_pkg/embedding.py`
- Modify: `backend/app/routers/profile_pkg/__init__.py`
- Test: `backend/tests/security/test_admin_embedding_config.py`（新建，放 security 因含 admin 权限校验）

**背景：** 新增 admin-only 端点写 `user_profile` 的 `embedding_*` key。参考 `profile_pkg/llm.py` 的掩码与校验模式。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/security/test_admin_embedding_config.py
"""管理员 embedding 配置端点：权限、校验、掩码。"""
import pytest
from app.core.auth import create_access_token
from app.db.connection import get_db_connection


def _admin_headers(admin_user_id=1):
    token = create_access_token({"sub": str(admin_user_id), "is_admin": True})
    return {"Authorization": f"Bearer {token}"}


def test_embedding_config_get_requires_admin(client, test_db):
    resp = client.get("/api/profile/embedding")
    assert resp.status_code == 403  # 普通登录或未登录都不能访问


def test_embedding_config_roundtrip(client, test_db):
    # 写入
    resp = client.put(
        "/api/profile/embedding",
        json={"backend": "siliconflow", "api_key": "sk-secret-1234", "api_model": "BAAI/bge-m3", "dimension": 1024},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # 读取掩码
    resp = client.get("/api/profile/embedding", headers=_admin_headers())
    data = resp.json()["settings"]
    assert data["backend"] == "siliconflow"
    assert data["api_model"] == "BAAI/bge-m3"
    assert data["api_key_set"] is True
    assert "sk-secret" not in data["api_key"]  # 掩码不泄露明文
    assert data["api_key"].startswith("sk-")


def test_embedding_config_rejects_bad_backend(client, test_db):
    resp = client.put(
        "/api/profile/embedding",
        json={"backend": "bogus", "api_model": "x"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/security/test_admin_embedding_config.py -v`
Expected: `FAIL` — 404（路由不存在）

- [ ] **Step 3: 创建 `profile_pkg/embedding.py`**

```python
"""全局 Embedding 配置管理端点（仅管理员）"""
import logging
import re
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_admin_user
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

router = APIRouter()

_SENSITIVE_KEYS = {"embedding_api_key"}


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


_VALID_BACKENDS = {"onnx", "siliconflow", "auto"}

# user_profile key → (default, env_fallback_source)
# 读取时回退到当前 embedding_service 生效值（即 env 兜底）
_KEYS = ("embedding_backend", "embedding_model_repo", "embedding_model_dir",
         "embedding_dimension", "embedding_api_key", "embedding_api_model",
         "embedding_api_base_url")


def _read_current() -> dict:
    """从 user_profile 读取，未设置的 key 回退 embedding_service 当前值。"""
    import app.services.embedding_service as es
    fallback = {
        "embedding_backend": es._BACKEND,
        "embedding_model_repo": es._MODEL_REPO,
        "embedding_model_dir": str(es._MODEL_DIR),
        "embedding_dimension": str(es._DIMENSION),
        "embedding_api_key": es._SILICONFLOW_API_KEY,
        "embedding_api_model": es._EMBEDDING_API_MODEL,
        "embedding_api_base_url": es._SILICONFLOW_BASE_URL,
    }
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT key, value FROM user_profile WHERE key IN ({})".format(
                ",".join("?" * len(_KEYS))
            ),
            _KEYS,
        ).fetchall()
    stored = {r["key"]: r["value"] for r in rows}
    merged = {k: stored.get(k, fallback.get(k, "")) for k in _KEYS}
    return merged


@router.get("/api/profile/embedding")
async def get_embedding_config(admin: dict = Depends(get_admin_user)):
    """读取全局 embedding 配置（API key 掩码返回）。"""
    current = _read_current()
    settings = {}
    for k, v in current.items():
        if k in _SENSITIVE_KEYS:
            settings[k] = _mask_key(v) if v else ""
            settings["embedding_api_key_set"] = bool(v)
        else:
            settings[k] = v
    return {"settings": settings}


@router.put("/api/profile/embedding")
async def update_embedding_config(req: dict, admin: dict = Depends(get_admin_user)):
    """更新全局 embedding 配置并热加载；模型变化时触发全量重算。"""
    backend = (req.get("backend") or "").strip().lower()
    if backend not in _VALID_BACKENDS:
        raise HTTPException(status_code=400, detail="backend 必须是 onnx / siliconflow / auto")

    dimension = req.get("dimension")
    if dimension is not None:
        try:
            dimension = int(dimension)
            if dimension <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="dimension 必须是正整数")

    api_model = (req.get("api_model") or "").strip()
    base_url = (req.get("api_base_url") or "").strip()
    if backend == "siliconflow" and not api_model:
        raise HTTPException(status_code=400, detail="siliconflow 模式必须填写模型名")

    current = _read_current()

    def _save():
        with get_db_connection() as conn:
            updates = {
                "embedding_backend": backend,
            }
            if api_model:
                updates["embedding_api_model"] = api_model
            if base_url:
                updates["embedding_api_base_url"] = base_url
            if dimension:
                updates["embedding_dimension"] = str(dimension)
            # API key：空值保留旧 key（与 per-user LLM 一致）
            new_key = (req.get("api_key") or "").strip()
            if new_key:
                updates["embedding_api_key"] = new_key
            elif current.get("embedding_api_key"):
                updates["embedding_api_key"] = current["embedding_api_key"]

            for k, v in updates.items():
                conn.execute(
                    "INSERT OR REPLACE INTO user_profile (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (k, v),
                )
            conn.commit()

    await run_db(_save)

    # 热加载
    from app.services.embedding_service import reload_embedding_config
    reload_embedding_config()

    # 模型变化 → 触发全量重算 job
    old_key = (current.get("embedding_backend"), current.get("embedding_api_model"))
    new_key = (backend, api_model or current.get("embedding_api_model", ""))
    recompute_triggered = old_key != new_key

    recompute_job_id = None
    if recompute_triggered:
        recompute_job_id = await _create_recompute_job(admin["id"])

    return {
        "status": "success",
        "message": "Embedding 配置已保存",
        "recompute_triggered": recompute_triggered,
        "recompute_job_id": recompute_job_id,
    }


async def _create_recompute_job(admin_id: int) -> int:
    """创建全量 embedding 重算 job 并入队（复用 jobs 表 + SSE 机制）。"""
    import asyncio
    import os

    def _create():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            try:
                existing = cursor.execute(
                    "SELECT id FROM jobs WHERE job_type = 'recompute_embedding' AND status IN ('pending', 'running')",
                ).fetchone()
                if existing:
                    conn.commit()
                    return existing["id"]
                cursor.execute(
                    "INSERT INTO jobs (job_type, status, created_by, progress_total) VALUES ('recompute_embedding', 'pending', ?, 1)",
                    (admin_id,),
                )
                job_id = cursor.lastrowid
                conn.commit()
                return job_id
            except Exception:
                conn.rollback()
                raise

    job_id = await run_db(_create)

    # 优先 ARQ，失败回退内联
    arq_scheduled = False
    if os.environ.get("EMBEDDING_RECOMPUTE_USE_ARQ", "1").lower() in ("1", "true", "yes"):
        try:
            from app.worker import enqueue_recompute_embedding_job
            await enqueue_recompute_embedding_job(job_id)
            arq_scheduled = True
        except Exception as e:
            logger.warning(f"ARQ 调度重算失败，回退内联: {e}")

    if not arq_scheduled:
        from app.services.embedding_recompute import run_recompute_inline
        asyncio.create_task(run_recompute_inline(job_id))

    return job_id


@router.post("/api/profile/embedding/test")
async def test_embedding_config(req: dict, admin: dict = Depends(get_admin_user)):
    """用提交的配置测试 embedding 连通性（不保存）。"""
    backend = (req.get("backend") or "").strip().lower()
    if backend not in _VALID_BACKENDS:
        raise HTTPException(status_code=400, detail="backend 必须是 onnx / siliconflow / auto")

    if backend == "siliconflow":
        api_key = (req.get("api_key") or "").strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="siliconflow 模式需要填写 API Key")
        api_model = (req.get("api_model") or "").strip() or "BAAI/bge-m3"
        base_url = (req.get("api_base_url") or "").strip() or "https://api.siliconflow.cn/v1"
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=30)
            resp = client.embeddings.create(model=api_model, input="测试")
            return {"ok": True, "dimension": len(resp.data[0].embedding)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    if backend in ("onnx", "auto"):
        from pathlib import Path
        model_dir = Path((req.get("model_dir") or "").strip() or "/app/models/bge-small-zh-v1.5")
        onnx_file = model_dir / "onnx" / "model_quantized.onnx"
        tok_file = model_dir / "tokenizer.json"
        if not (onnx_file.exists() and tok_file.exists()):
            return {"ok": False, "error": f"模型文件缺失：{model_dir} 下需有 onnx/model_quantized.onnx 和 tokenizer.json"}
        return {"ok": True, "dimension": req.get("dimension") or 512}

    return {"ok": False, "error": "未知 backend"}
```

- [ ] **Step 4: 在 `profile_pkg/__init__.py` 注册子路由**

参照现有子路由 import 模式（读 `__init__.py` 看 `llm` 怎么 import 合并），新增 `embedding`：

```python
from app.routers.profile_pkg import embedding  # 按现有 import 风格添加
# 并把 embedding.router 加入合并列表（保持与 llm 一致）
```

- [ ] **Step 5: 跑测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/security/test_admin_embedding_config.py -v`
Expected: `PASS`

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/profile_pkg/embedding.py backend/app/routers/profile_pkg/__init__.py backend/tests/security/test_admin_embedding_config.py
git commit -m "feat(backend): admin embedding config endpoints with hot-reload + recompute trigger"
```

---

### Task 3: 全量 embedding 重算 job（worker + inline）

**Files:**
- Create: `backend/app/services/embedding_recompute.py`
- Modify: `backend/app/worker.py`

**背景：** 遍历 `question_bank` 重编码向量，更新 `embedding`/`embedding_model`/`embedding_dim` 列，重建 FAISS 缓存。用 `jobs` 表 + `/api/jobs/{id}/stream`（已存在，bank_build.py:20）推送进度。

- [ ] **Step 1: 创建 `embedding_recompute.py`**

```python
"""全量 embedding 重算 job（模型更换后自动触发）。"""
import json
import logging
import numpy as np
from app.db.connection import get_db_connection, run_db
from app.services import embedding_service as es
from app.services.faiss_index_manager import get_index_manager

logger = logging.getLogger("interview-boss")


def _update_job(job_id: int, status: str, current: int, total: int, message: str = "", result: str = None, error: str = None):
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, progress_current = ?, progress_total = ?, progress_message = ?, result = ?, error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, current, total, message, result, error, job_id),
        )
        conn.commit()


async def run_recompute(job_id: int):
    """主入口：供 ARQ task 调用。"""
    try:
        rows = await run_db(lambda: (
            lambda conn: conn.execute(
                "SELECT id, question FROM question_bank WHERE deleted_at IS NULL AND status = 'approved'"
            ).fetchall()
        )(get_db_connection()))

        total = len(rows)
        _update_job(job_id, "running", 0, max(total, 1), "开始重算 embedding")

        current_model = es._EMBEDDING_API_MODEL if es._BACKEND == "siliconflow" else es._MODEL_REPO
        dim = es.get_embedding_dimension()
        BATCH = 32

        def _encode_batch(texts):
            return es.encode_texts(texts)

        def _persist(updates: list):
            with get_db_connection() as conn:
                conn.executemany(
                    "UPDATE question_bank SET embedding = ?, embedding_model = ?, embedding_dim = ? WHERE id = ?",
                    updates,
                )
                conn.commit()

        for start in range(0, total, BATCH):
            batch_rows = rows[start : start + BATCH]
            texts = [r["question"] for r in batch_rows]
            vecs = _encode_batch(texts)
            updates = [
                (vecs[i].tobytes(), current_model, dim, batch_rows[i]["id"])
                for i in range(len(batch_rows))
            ]
            _persist(updates)
            _update_job(job_id, "running", min(start + len(batch_rows), total), max(total, 1),
                        f"已重算 {min(start + len(batch_rows), total)}/{total}")

        # 重建 FAISS 索引缓存
        get_index_manager().invalidate()
        _update_job(job_id, "completed", total, max(total, 1),
                    f"重算完成 {total} 题", result=json.dumps({"total": total}))
    except Exception as e:
        logger.exception("embedding 重算失败 job=%s", job_id)
        _update_job(job_id, "failed", 0, 1, error=str(e)[:500])
```

- [ ] **Step 2: worker.py 注册任务 + enqueue 函数**

在 `worker.py` 添加（参照 `submit_import_task` 模式）：

```python
async def enqueue_recompute_embedding_job(job_id: int):
    """将全量 embedding 重算任务入队"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("recompute_embedding_task", job_id)
    finally:
        await pool.close()


async def recompute_embedding_task(ctx, job_id: int):
    """ARQ: 全量 embedding 重算。"""
    from app.services.embedding_recompute import run_recompute
    await run_recompute(job_id)
```

并把 `recompute_embedding_task` 加入 `functions` 列表（worker.py:669 附近）。

- [ ] **Step 3: 写后端测试（重算 job 创建 + 进度更新）**

```python
# backend/tests/security/test_embedding_recompute.py
"""embedding 重算 job：创建、进度、完成。"""
import pytest
from app.core.auth import create_access_token
from app.db.connection import get_db_connection


def _admin_headers(admin_user_id=1):
    token = create_access_token({"sub": str(admin_user_id), "is_admin": True})
    return {"Authorization": f"Bearer {token}"}


def test_put_embedding_with_model_change_creates_recompute_job(client, test_db, monkeypatch):
    # monkeypatch ARQ 调度为内联，避免依赖 redis
    monkeypatch.setenv("EMBEDDING_RECOMPUTE_USE_ARQ", "0")

    resp = client.put(
        "/api/profile/embedding",
        json={"backend": "siliconflow", "api_model": "BAAI/bge-m3", "api_key": "sk-x", "dimension": 1024},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recompute_triggered"] is True
    assert body["recompute_job_id"] is not None

    # job 已创建
    with get_db_connection() as conn:
        row = conn.execute("SELECT job_type, status FROM jobs WHERE id = ?", (body["recompute_job_id"],)).fetchone()
    assert row["job_type"] == "recompute_embedding"


def test_put_embedding_same_model_skips_recompute(client, test_db, monkeypatch):
    monkeypatch.setenv("EMBEDDING_RECOMPUTE_USE_ARQ", "0")
    resp = client.put(
        "/api/profile/embedding",
        json={"backend": "siliconflow", "api_model": "BAAI/bge-m3", "api_key": "sk-x", "dimension": 1024},
        headers=_admin_headers(),
    )
    assert resp.json()["recompute_triggered"] is True
    # 相同配置再保存 → 不触发
    resp2 = client.put(
        "/api/profile/embedding",
        json={"backend": "siliconflow", "api_model": "BAAI/bge-m3", "dimension": 1024},
        headers=_admin_headers(),
    )
    assert resp2.json()["recompute_triggered"] is False
```

- [ ] **Step 4: 跑测试**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/security/test_embedding_recompute.py backend/tests/security/test_admin_embedding_config.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/embedding_recompute.py backend/app/worker.py backend/tests/security/test_embedding_recompute.py
git commit -m "feat(backend): full embedding recompute job triggered on model change"
```

---

### Task 4: 全局 LLM 测试连接端点

**Files:**
- Modify: `backend/app/routers/profile_pkg/llm.py`
- Test: `backend/tests/security/test_global_llm_test.py`（新建）

**背景：** 现有 `check_llm_status(user_id)` 探测 per-user 配置。全局需要一个用 `_get_global_llm_config()` 探测的端点。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/security/test_global_llm_test.py
"""全局 LLM 测试连接端点。"""
import pytest
from unittest.mock import patch
from app.core.auth import create_access_token


def _admin_headers(admin_user_id=1):
    token = create_access_token({"sub": str(admin_user_id), "is_admin": True})
    return {"Authorization": f"Bearer {token}"}


def test_test_global_llm_requires_admin(client, test_db):
    resp = client.post("/api/profile/llm/test-global", json={})
    assert resp.status_code == 403


def test_test_global_llm_success(client, test_db):
    with patch("app.core.config._get_global_llm_config", return_value={
        "api_key": "sk-test", "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o", "timeout": 30,
    }), patch("app.services.llm.check_llm_status") as mock_status:
        mock_status.return_value = {"configured": True, "connected": True, "error": None, "model": "gpt-4o"}
        resp = client.post("/api/profile/llm/test-global", json={}, headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["connected"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/security/test_global_llm_test.py -v`
Expected: `FAIL` — 404

- [ ] **Step 3: 实现端点**

在 `profile_pkg/llm.py` 添加：

```python
@router.post("/api/profile/llm/test-global")
async def test_global_llm(admin: dict = Depends(get_admin_user)):
    """用全局配置探测 LLM 连通性（仅管理员）。"""
    from app.core.config import _get_global_llm_config
    cfg = _get_global_llm_config()
    if not cfg or not cfg.get("api_key"):
        raise HTTPException(status_code=400, detail="全局 LLM 尚未配置 API Key")

    # 复用 per-user 探测逻辑，但强制全局配置生效
    from app.services import llm as llm_service
    from unittest.mock import patch

    with patch("app.core.config.get_user_llm_config", return_value=cfg):
        status = await llm_service.check_llm_status(admin["id"], force_probe=True)
    return status
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/security/test_global_llm_test.py -v`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/profile_pkg/llm.py backend/tests/security/test_global_llm_test.py
git commit -m "feat(backend): global LLM connectivity test endpoint"
```

---

### Task 5: 前端 profileApi.js 新增 API

**Files:**
- Modify: `frontend/src/services/profileApi.js`

- [ ] **Step 1: 新增 API 函数**

在 `profileApi.js` 的 per-user LLM Config 区后追加：

```javascript
// ── Admin: Global embedding config ──
export const fetchGlobalEmbeddingConfig = () => get(`${API}/profile/embedding`, { noCache: true })
export const updateGlobalEmbeddingConfig = (settings) => put(`${API}/profile/embedding`, settings)
export const testGlobalEmbedding = (settings) => post(`${API}/profile/embedding/test`, settings)
export const testGlobalLLM = () => post(`${API}/profile/llm/test-global`, {})

// ── Admin: 重算 job SSE 复用 useSubmitJobs 的 job stream 机制 ──
```

- [ ] **Step 2: 检查 api/index.js re-export**

`frontend/src/api/index.js` 是否 re-export `profileApi` 全部？若是，无需改动；否则把新函数加进去。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/profileApi.js frontend/src/api/index.js
git commit -m "feat(frontend): admin global model config API helpers"
```

---

### Task 6: 前端 `SettingsGlobalModel.vue` 组件

**Files:**
- Create: `frontend/src/components/business/SettingsGlobalModel.vue`
- Test: `frontend/tests/e2e/admin-global-model.spec.js`（新建）

**背景：** 两段表单（全局 LLM + Embedding），参考 `SettingsAIConfig.vue` 的字段/保存/测试连接交互风格。

- [ ] **Step 1: 写失败 E2E 测试**

```javascript
// frontend/tests/e2e/admin-global-model.spec.js
import { test, expect } from '@playwright/test'

const MOCK_USER = { id: 1, username: 'admin', is_admin: true, current_position_id: 1, current_position: '前端开发工程师' }

async function mockAdminAPIs(page) {
  await page.route('**/api/auth/refresh', async (route) => route.fulfill({ json: { token: 't', user: MOCK_USER } }))
  await page.route('**/api/auth/me', async (route) => route.fulfill({ json: MOCK_USER }))
  await page.route('**/api/auth/logout', async (route) => route.fulfill({ json: {} }))
  await page.route('**/api/master-bank**', async (route) => route.fulfill({ json: [] }))
  await page.route('**/api/data/jd**', async (route) => route.fulfill({ json: [] }))
  await page.route('**/api/data/interview**', async (route) => route.fulfill({ json: [] }))
  await page.route('**/api/analytics**', async (route) => route.fulfill({ json: {} }))
  await page.route('**/api/practice/stats**', async (route) => route.fulfill({ json: {} }))
  await page.route('**/api/practice/history**', async (route) => route.fulfill({ json: [] }))
  await page.route('**/api/profile**', async (route) => {
    if (route.request().url().includes('/embedding')) {
      await route.fulfill({ json: { settings: { backend: 'siliconflow', api_model: 'BAAI/bge-m3', api_key: 'sk-****abcd', api_key_set: true, dimension: '1024' } } })
    } else {
      await route.fulfill({ json: { settings: { llm_model: 'gpt-4o', llm_base_url: 'https://api.openai.com/v1', llm_api_key: 'sk-****abcd', llm_api_key_set: true, llm_timeout: '120' } } })
    }
  })
  await page.route('**/api/health', async (route) => route.fulfill({ json: { status: 'ok' } }))
  await page.route('**/api/chat**', async (route) => route.fulfill({ json: [] }))
  await page.route('**/api/bank-build**', async (route) => route.fulfill({ json: {} }))
  await page.route('**/api/submit-jobs/active', async (route) => route.fulfill({ json: [] }))
}

test('admin 设置页出现模型配置 tab', async ({ page }) => {
  await mockAdminAPIs(page)
  await page.goto('/')
  await page.waitForSelector('main', { timeout: 15000 })
  await page.getByRole('button', { name: '设置' }).click()
  await page.waitForTimeout(500)
  await page.getByText('管理员设置').click()
  await page.waitForTimeout(500)
  await expect(page.getByText('模型配置')).toBeVisible()
})

test('模型配置 tab 显示全局 LLM 和 embedding 表单', async ({ page }) => {
  await mockAdminAPIs(page)
  await page.goto('/')
  await page.waitForSelector('main', { timeout: 15000 })
  await page.getByRole('button', { name: '设置' }).click()
  await page.waitForTimeout(500)
  await page.getByText('管理员设置').click()
  await page.waitForTimeout(500)
  await page.getByText('模型配置').click()
  await page.waitForTimeout(500)
  await expect(page.getByText('全局 LLM 配置')).toBeVisible()
  await expect(page.getByText('Embedding 配置')).toBeVisible()
  await expect(page.locator('input[value="gpt-4o"]')).toBeVisible()
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx playwright test tests/e2e/admin-global-model.spec.js --reporter=list`
Expected: `FAIL` — '模型配置' 不可见

- [ ] **Step 3: 创建组件**

`frontend/src/components/business/SettingsGlobalModel.vue` 骨架：

```vue
<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useToast } from '@/composables/useNotification.js'
import { fetchProfile, updateProfile, fetchGlobalEmbeddingConfig, updateGlobalEmbeddingConfig, testGlobalLLM, testGlobalEmbedding } from '@/services/profileApi.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, Cpu, Sparkles } from '@lucide/vue'

const { success: toastSuccess, error: toastError } = useToast()

// ── 全局 LLM ──
const llmForm = reactive({ llm_model: '', llm_base_url: '', llm_api_key: '', llm_timeout: '120', llm_api_key_set: false })
const llmSaving = ref(false)
const llmTesting = ref(false)

onMounted(async () => {
  try {
    const profile = await fetchProfile({ noCache: true })
    const s = profile.settings || {}
    llmForm.llm_model = s.llm_model || ''
    llmForm.llm_base_url = s.llm_base_url || ''
    llmForm.llm_api_key = s.llm_api_key || ''
    llmForm.llm_timeout = String(s.llm_timeout || '120')
    llmForm.llm_api_key_set = !!s.llm_api_key_set
  } catch (e) {
    toastError('加载全局 LLM 配置失败：' + e.message)
  }
  await loadEmbedding()
})

const saveGlobalLLM = async () => {
  llmSaving.value = true
  try {
    const settings = { llm_model: llmForm.llm_model, llm_base_url: llmForm.llm_base_url, llm_timeout: llmForm.llm_timeout }
    if (llmForm.llm_api_key) settings.llm_api_key = llmForm.llm_api_key
    await updateProfile(settings)
    toastSuccess('全局 LLM 配置已保存')
    llmForm.llm_api_key = ''
    llmForm.llm_api_key_set = true
  } catch (e) {
    toastError('保存失败：' + e.message)
  } finally {
    llmSaving.value = false
  }
}

const handleTestGlobalLLM = async () => {
  llmTesting.value = true
  try {
    const status = await testGlobalLLM()
    if (status.connected) toastSuccess(`连接成功：模型 ${status.model || ''} 可正常使用`)
    else toastError(status.error || '连接失败')
  } catch (e) {
    toastError('测试失败：' + e.message)
  } finally {
    llmTesting.value = false
  }
}

// ── Embedding ──
const embForm = reactive({ backend: 'auto', api_model: '', api_key: '', dimension: '512', api_key_set: false })
const embSaving = ref(false)
const embTesting = ref(false)
const recomputeInfo = ref(null) // { jobId, message }

const loadEmbedding = async () => {
  try {
    const data = await fetchGlobalEmbeddingConfig()
    const s = data.settings || {}
    embForm.backend = s.backend || 'auto'
    embForm.api_model = s.api_model || ''
    embForm.api_key = s.api_key || ''
    embForm.dimension = String(s.dimension || '512')
    embForm.api_key_set = !!s.api_key_set
  } catch (e) {
    toastError('加载 embedding 配置失败：' + e.message)
  }
}

const saveEmbedding = async () => {
  embSaving.value = true
  recomputeInfo.value = null
  try {
    const settings = { backend: embForm.backend, api_model: embForm.api_model, dimension: Number(embForm.dimension) }
    if (embForm.api_key) settings.api_key = embForm.api_key
    const result = await updateGlobalEmbeddingConfig(settings)
    embForm.api_key = ''
    embForm.api_key_set = true
    toastSuccess('Embedding 配置已保存')
    if (result.recompute_triggered) {
      recomputeInfo.value = { jobId: result.recompute_job_id, message: '模型已更换，正在后台重算全部向量...' }
      // 轮询 job 状态（复用 job stream 端点）
      pollRecompute(result.recompute_job_id)
    }
  } catch (e) {
    toastError('保存失败：' + e.message)
  } finally {
    embSaving.value = false
  }
}

const pollRecompute = (jobId) => {
  const sse = new EventSource(`/api/jobs/${jobId}/stream`)
  sse.onmessage = (ev) => {
    const data = JSON.parse(ev.data)
    if (data.type === 'done') {
      recomputeInfo.value = { jobId, message: '重算完成' }
      sse.close()
    } else if (data.type === 'error') {
      recomputeInfo.value = { jobId, message: '重算失败：' + (data.message || '') }
      sse.close()
    } else {
      recomputeInfo.value = { jobId, message: data.message || `进度 ${data.current}/${data.total}` }
    }
  }
}

const handleTestEmbedding = async () => {
  embTesting.value = true
  try {
    const result = await testGlobalEmbedding({
      backend: embForm.backend,
      api_key: embForm.api_key || undefined,
      api_model: embForm.api_model || undefined,
      model_dir: undefined,
    })
    if (result.ok) toastSuccess(`连接成功：维度 ${result.dimension}`)
    else toastError(result.error || '连接失败')
  } catch (e) {
    toastError('测试失败：' + e.message)
  } finally {
    embTesting.value = false
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- 全局 LLM -->
    <div class="rounded-xl border bg-card p-6">
      <div class="flex items-center gap-2 mb-4">
        <Sparkles class="size-4 text-primary" />
        <h3 class="text-sm font-semibold">全局 LLM 配置</h3>
        <span class="text-xs text-muted-foreground ml-2">用户未配置自己的模型时回退到此配置</span>
      </div>
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>Base URL</Label>
          <Input v-model="llmForm.llm_base_url" placeholder="https://api.openai.com/v1" />
        </div>
        <div class="space-y-1.5">
          <Label>模型名称</Label>
          <Input v-model="llmForm.llm_model" placeholder="gpt-4o" />
        </div>
        <div class="space-y-1.5">
          <Label>API Key {{ llmForm.llm_api_key_set ? '（已配置，留空保持不变）' : '' }}</Label>
          <Input v-model="llmForm.llm_api_key" type="password" :placeholder="llmForm.llm_api_key_set ? '••••••••' : 'sk-...'" />
        </div>
        <div class="space-y-1.5">
          <Label>超时（秒）</Label>
          <Input v-model="llmForm.llm_timeout" type="number" min="5" max="600" />
        </div>
        <div class="flex gap-2">
          <Button size="sm" @click="saveGlobalLLM" :disabled="llmSaving">
            <Loader2 v-if="llmSaving" class="size-3.5 animate-spin" /> {{ llmSaving ? '保存中...' : '保存' }}
          </Button>
          <Button variant="outline" size="sm" @click="handleTestGlobalLLM" :disabled="llmTesting">
            {{ llmTesting ? '测试中...' : '测试连接' }}
          </Button>
        </div>
      </div>
    </div>

    <!-- Embedding -->
    <div class="rounded-xl border bg-card p-6">
      <div class="flex items-center gap-2 mb-4">
        <Cpu class="size-4 text-primary" />
        <h3 class="text-sm font-semibold">Embedding 配置</h3>
      </div>
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>后端模式</Label>
          <Select v-model="embForm.backend">
            <SelectTrigger class="w-[220px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">自动（ONNX 优先）</SelectItem>
              <SelectItem value="onnx">ONNX 本地模型</SelectItem>
              <SelectItem value="siliconflow">SiliconFlow API</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <template v-if="embForm.backend === 'siliconflow'">
          <div class="space-y-1.5">
            <Label>模型名</Label>
            <Input v-model="embForm.api_model" placeholder="BAAI/bge-m3" />
          </div>
          <div class="space-y-1.5">
            <Label>API Key {{ embForm.api_key_set ? '（已配置，留空保持不变）' : '' }}</Label>
            <Input v-model="embForm.api_key" type="password" :placeholder="embForm.api_key_set ? '••••••••' : 'sk-...'" />
          </div>
        </template>
        <div class="space-y-1.5">
          <Label>向量维度</Label>
          <Input v-model="embForm.dimension" type="number" min="1" placeholder="512" />
        </div>
        <div class="flex gap-2">
          <Button size="sm" @click="saveEmbedding" :disabled="embSaving">
            <Loader2 v-if="embSaving" class="size-3.5 animate-spin" /> {{ embSaving ? '保存中...' : '保存' }}
          </Button>
          <Button variant="outline" size="sm" @click="handleTestEmbedding" :disabled="embTesting">
            {{ embTesting ? '测试中...' : '测试连接' }}
          </Button>
        </div>
        <p v-if="recomputeInfo" class="text-xs text-amber-600 dark:text-amber-400">
          ⏳ {{ recomputeInfo.message }}
        </p>
      </div>
    </div>
  </div>
</template>
```

注意：`/api/jobs/{id}/stream` 是 SSE 轮询端点，用 `EventSource` 可行；但项目规范（`services/http.js`）建议 SSE 用 fetch + ReadableStream。若 `getSSE` 暴露给业务组件可直接用它。实现时优先复用 `getSSE`。

- [ ] **Step 4: `SettingsAdmin.vue` 注册 tab**

在 `adminTabs`（SettingsAdmin.vue:14-17）加一项，并挂载组件：

```javascript
const adminTabs = [
  { id: 'taxonomy', label: '分类管理' },
  { id: 'quality', label: '聚合质量' },
  { id: 'model', label: '模型配置' },
]
```

在 template 的 quality 分支后加：

```html
<div v-else-if="adminTab === 'model'" class="rounded-xl border bg-card p-6">
  <SettingsGlobalModel />
</div>
```

并在 script 顶部 import：

```javascript
import SettingsGlobalModel from './SettingsGlobalModel.vue'
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npx playwright test tests/e2e/admin-global-model.spec.js --reporter=list`
Expected: `PASS`

- [ ] **Step 6: 前端 build 验证**

Run: `cd frontend && npm run build`
Expected: build 成功

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/business/SettingsGlobalModel.vue frontend/src/components/business/SettingsAdmin.vue frontend/tests/e2e/admin-global-model.spec.js frontend/src/services/profileApi.js
git commit -m "feat(frontend): admin global model config tab with LLM + embedding"
```

---

### Task 7: 文档更新 + 全量验证

- [ ] **Step 1: 更新 CLAUDE.md**

按修改铁律更新：
- `backend/app/services/CLAUDE.md` — 新增 `embedding_recompute.py` 职责行
- `backend/app/routers/profile_pkg/CLAUDE.md` — 新增 `embedding.py` 子路由
- `frontend/src/components/business/CLAUDE.md` — 新增 `SettingsGlobalModel.vue` 行
- `frontend/src/services/CLAUDE.md` — 若 profileApi 职责描述需更新
- 根 `CLAUDE.md` — 若代码路由表涉及全局模型配置

- [ ] **Step 2: 后端全量测试**

Run: `./deploy/docker-deploy.sh test -q`
Expected: 全绿

- [ ] **Step 3: 前端门禁**

Run: `cd frontend && npm run build`
Expected: build 成功

- [ ] **Step 4: Commit**

```bash
git add -A backend/app/services/CLAUDE.md backend/app/routers/profile_pkg/CLAUDE.md frontend/src/components/business/CLAUDE.md frontend/src/services/CLAUDE.md
git commit -m "docs: record admin global model config components"
```

---

## 关键实现决策记录

1. **全局 LLM 复用 `PUT /api/profile`**：后端零新增存储，`_reload_from_db()` + `rebuild_clients()` 已保证热生效。只补 `POST /api/profile/llm/test-global`（用 `_get_global_llm_config()` + patch `get_user_llm_config` 复用 `check_llm_status`）。
2. **embedding 独立端点**：写 `user_profile` 新 key（`embedding_*`），不受 `ALLOWED_PROFILE_KEYS` 限制（独立路由直接 SQL）。`embedding_service.reload_embedding_config()` 从 DB 覆盖 env 常量，重建 session/client/FAISS 缓存。
3. **重算触发条件**：`(backend, api_model)` 变化才触发，避免每次保存都重算。重算 job 复用 `jobs` 表 + `/api/jobs/{id}/stream` SSE（bank_build.py:20），前端用 `getSSE`/EventSource 消费。
4. **API key 掩码**：`embedding_api_key` 沿用 `llm_api_key` 明文存 `user_profile` + `_mask_key` 读取模式；PUT 时空 key 保留旧值（与 per-user LLM 一致）。
5. **ARQ 优先 + inline 回退**：重算 job 遵循项目 worker 模式（`enqueue_recompute_embedding_job` + `functions` 注册 + `EMBEDDING_RECOMPUTE_USE_ARQ=0` 时 `asyncio.create_task` 内联），测试用 env 关 ARQ 避免依赖 redis。
