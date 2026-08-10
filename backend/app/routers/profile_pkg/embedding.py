"""全局 Embedding 配置管理端点（仅管理员）"""
import logging
from fastapi import APIRouter, HTTPException, Depends

from app.core.auth import get_admin_user
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

router = APIRouter()

_SENSITIVE_KEYS = {"api_key"}
_VALID_BACKENDS = {"onnx", "siliconflow", "auto"}

# 前端 key → user_profile key 与 embedding_service 生效值兜底属性
_PROFILE_KEYS = {
    "backend": "embedding_backend",
    "model_repo": "embedding_model_repo",
    "model_dir": "embedding_model_dir",
    "dimension": "embedding_dimension",
    "api_key": "embedding_api_key",
    "api_model": "embedding_api_model",
    "api_base_url": "embedding_api_base_url",
}
_FALLBACK_ATTRS = {
    "backend": "_BACKEND",
    "model_repo": "_MODEL_REPO",
    "model_dir": "_MODEL_DIR",
    "dimension": "_DIMENSION",
    "api_key": "_SILICONFLOW_API_KEY",
    "api_model": "_EMBEDDING_API_MODEL",
    "api_base_url": "_SILICONFLOW_BASE_URL",
}


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def _read_current() -> dict:
    """从 user_profile 读取，未设置的 key 回退 embedding_service 当前生效值。"""
    import app.services.embedding_service as es

    fallback = {k: str(getattr(es, attr)) for k, attr in _FALLBACK_ATTRS.items()}
    profile_keys = tuple(_PROFILE_KEYS.values())
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT key, value FROM user_profile WHERE key IN ({})".format(
                ",".join("?" * len(profile_keys))
            ),
            profile_keys,
        ).fetchall()
    stored = {r["key"]: r["value"] for r in rows}
    return {k: stored.get(pk, fallback.get(k, "")) for k, pk in _PROFILE_KEYS.items()}


@router.get("/api/profile/embedding")
async def get_embedding_config(admin: dict = Depends(get_admin_user)):
    """读取全局 embedding 配置（API key 掩码返回）。"""
    current = _read_current()
    settings = {}
    for k, v in current.items():
        if k in _SENSITIVE_KEYS:
            settings[k] = _mask_key(v) if v else ""
            settings["api_key_set"] = bool(v)
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
    api_base_url = (req.get("api_base_url") or "").strip()
    if backend == "siliconflow" and not api_model:
        raise HTTPException(status_code=400, detail="siliconflow 模式必须填写模型名")

    current = _read_current()

    def _save():
        with get_db_connection() as conn:
            updates = {"embedding_backend": backend}
            if api_model:
                updates["embedding_api_model"] = api_model
            if api_base_url:
                updates["embedding_api_base_url"] = api_base_url
            if dimension:
                updates["embedding_dimension"] = str(dimension)
            # API key：空值保留旧 key（与 per-user LLM 一致）
            new_key = (req.get("api_key") or "").strip()
            if new_key:
                updates["embedding_api_key"] = new_key
            elif current.get("api_key"):
                updates["embedding_api_key"] = current["api_key"]

            for k, v in updates.items():
                conn.execute(
                    "INSERT OR REPLACE INTO user_profile (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (k, v),
                )
            conn.commit()

    await run_db(_save)

    from app.services.embedding_service import reload_embedding_config

    reload_embedding_config()

    old_key = (current.get("backend"), current.get("api_model"), current.get("dimension"))
    new_key = (
        backend,
        api_model or current.get("api_model", ""),
        str(dimension) if dimension else current.get("dimension", ""),
    )
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
    """创建全量 embedding 重算 job 并尝试入队。

    jobs 是事实源；Redis/ARQ 不可用时只保留 pending，由周期 dispatcher
    补偿投递，不能在 FastAPI 进程内启动一个不可恢复的临时 task。
    """

    def _create():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            try:
                existing = cursor.execute(
                    "SELECT id FROM jobs WHERE job_type = 'recompute_embedding' AND status IN ('pending', 'queued', 'running')",
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

    try:
        from app.worker import enqueue_recompute_embedding_job
        from app.services.job_lifecycle import mark_job_dispatched

        arq_job = await enqueue_recompute_embedding_job(job_id)
        arq_job_id = getattr(arq_job, "job_id", None)
        if not arq_job_id:
            raise RuntimeError("ARQ 未返回 job_id")

        def _mark():
            with get_db_connection() as conn:
                if not mark_job_dispatched(conn, job_id, str(arq_job_id)):
                    raise RuntimeError(f"Embedding 重算任务不可再投递: job_id={job_id}")
                conn.commit()

        await run_db(_mark)
        logger.info(
            "Embedding 重算任务已通过 ARQ 调度: job_id=%s arq_job_id=%s",
            job_id,
            arq_job_id,
        )
    except Exception as e:
        logger.warning("ARQ 调度 embedding 重算失败，任务保留 pending 等待 dispatcher: %s", e)
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
            return {
                "ok": False,
                "error": f"模型文件缺失：{model_dir} 下需有 onnx/model_quantized.onnx 和 tokenizer.json",
            }
        return {"ok": True, "dimension": req.get("dimension") or 512}

    return {"ok": False, "error": "未知 backend"}
