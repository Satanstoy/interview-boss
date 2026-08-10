"""全量 embedding 重算 job（模型更换后自动触发）。

遍历全部未删除题重编码向量，更新 embedding/embedding_model/embedding_dim，
重建 FAISS 索引。失败时回滚本 job 已更新的行 —— "全成功或全不动"，
避免新旧模型向量混库导致 FAISS 维度不一致崩溃。
"""
import json
import logging

from app.db.connection import get_db_connection, run_db
from app.services import embedding_service as es
from app.services.faiss_index_manager import get_index_manager

logger = logging.getLogger("interview-boss")

_BATCH = 32


def _update_job(job_id: int, status: str, current: int, total: int,
                message: str = "", result: str = None, error: str = None,
                worker_id: str = None):
    with get_db_connection() as conn:
        where = "WHERE id = ?"
        params = [status, current, total, message, result, error, job_id]
        if worker_id:
            where += " AND worker_id = ?"
            params.append(worker_id)
        conn.execute(
            "UPDATE jobs SET status = ?, progress_current = ?, progress_total = ?, "
            "progress_message = ?, result = ?, error = ?, updated_at = CURRENT_TIMESTAMP "
            + where,
            params,
        )
        conn.commit()


def _load_questions():
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT id, question FROM question_bank WHERE deleted_at IS NULL ORDER BY id"
        ).fetchall()


def _read_old(ids):
    ph = ",".join("?" * len(ids))
    with get_db_connection() as conn:
        return {
            r["id"]: (r["embedding"], r["embedding_model"], r["embedding_dim"])
            for r in conn.execute(
                f"SELECT id, embedding, embedding_model, embedding_dim FROM question_bank "
                f"WHERE id IN ({ph})",
                ids,
            ).fetchall()
        }


def _persist(updates):
    with get_db_connection() as conn:
        conn.executemany(
            "UPDATE question_bank SET embedding = ?, embedding_model = ?, embedding_dim = ? WHERE id = ?",
            updates,
        )
        conn.commit()


async def run_recompute(job_id: int):
    """主入口：由 ARQ 执行，数据库负责 claim、重试和最终失败状态。"""
    from app.services.job_lifecycle import (
        RECOMPUTE_EMBEDDING_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
    )

    worker_id = default_worker_id()

    def _claim():
        with get_db_connection() as conn:
            claimed = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=RECOMPUTE_EMBEDDING_JOB_TYPE,
            )
            conn.commit()
            return bool(claimed)

    if not await run_db(_claim):
        logger.info("Embedding 重算任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    # worker 进程可能未加载管理员保存的配置，先从 DB 同步
    es.reload_embedding_config()

    updated = {}  # id -> (old_embedding, old_model, old_dim)
    total = 0
    try:
        rows = await run_db(_load_questions)
        total = len(rows)
        _update_job(
            job_id, "running", 0, max(total, 1), "开始重算 embedding",
            worker_id=worker_id,
        )

        current_model = (
            es._EMBEDDING_API_MODEL if es._BACKEND == "siliconflow" else es._MODEL_REPO
        )
        dim = es.get_embedding_dimension()

        for start in range(0, total, _BATCH):
            batch_rows = rows[start : start + _BATCH]
            ids = [r["id"] for r in batch_rows]
            old = _read_old(ids)
            texts = [r["question"] for r in batch_rows]
            vecs = es.encode_texts(texts)
            updates = [
                (vecs[i].tobytes(), current_model, dim, batch_rows[i]["id"])
                for i in range(len(batch_rows))
            ]
            _persist(updates)
            for row_id in ids:
                updated[row_id] = old[row_id]
            done = min(start + len(batch_rows), total)
            _update_job(
                job_id, "running", done, max(total, 1), f"已重算 {done}/{total}",
                worker_id=worker_id,
            )

        get_index_manager().invalidate()
        _update_job(
            job_id, "running", total, max(total, 1),
            f"重算完成 {total} 题", worker_id=worker_id,
        )
        with get_db_connection() as conn:
            complete_job(
                conn,
                job_id,
                worker_id,
                result=json.dumps({"total": total}),
            )
            conn.commit()
        logger.info("embedding 重算完成 job=%s total=%d", job_id, total)
        return {"status": "completed", "job_id": job_id, "total": total}
    except Exception as e:
        logger.exception("embedding 重算失败 job=%s", job_id)
        if updated:
            try:
                with get_db_connection() as conn:
                    for row_id, (old_emb, old_model, old_dim) in updated.items():
                        conn.execute(
                            "UPDATE question_bank SET embedding = ?, embedding_model = ?, embedding_dim = ? WHERE id = ?",
                            (old_emb, old_model, old_dim, row_id),
                        )
                    conn.commit()
                logger.info("embedding 重算失败已回滚 %d 行 job=%s", len(updated), job_id)
            except Exception as rollback_err:
                logger.exception("embedding 重算回滚失败 job=%s: %s", job_id, rollback_err)
        with get_db_connection() as conn:
            fail_job(conn, job_id, worker_id, str(e)[:500])
            conn.commit()
        return {"status": "failed", "job_id": job_id, "error": str(e)[:500]}
