"""
ARQ Worker 配置

独立于 FastAPI 进程运行，处理异步聚类任务。
2c4g 资源优化：单并发、10 分钟超时、最多重试 3 次。
"""

import os
import time
import json
import re
import base64
import asyncio
import logging
from functools import wraps
from contextlib import nullcontext
from datetime import datetime
from arq.connections import RedisSettings
from arq.cron import cron
from app.core.config import build_redis_url

logger = logging.getLogger("interview-boss")

REDIS_URL = build_redis_url(
    os.environ.get("REDIS_QUEUE_URL") or os.environ.get("REDIS_URL"),
    f"redis://{os.environ.get('REDIS_HOST', 'localhost')}:6379/0",
)


def _load_public_rebuild_answer_cache(conn, job_position: str) -> dict:
    """Load only answers that are safe to restore into the public bank."""
    rows = conn.execute(
        "SELECT question, ai_answer, answer_sources FROM question_bank "
        "WHERE ai_answer IS NOT NULL AND ai_answer != '' "
        "AND job_position = ? AND owner_id IS NULL AND status = 'approved'",
        (job_position,),
    ).fetchall()
    return {
        row["question"]: {"answer": row["ai_answer"], "sources": row["answer_sources"]}
        for row in rows
    }



from app.services import worker_observability as _worker_observability


def record_worker_heartbeat(*args, **kwargs):
    """Compatibility facade for callers that historically imported this from worker."""
    return _worker_observability.record_worker_heartbeat(*args, **kwargs)


async def record_worker_heartbeat_async(*args, **kwargs):
    """Compatibility facade that preserves monkeypatchable worker fallback behavior."""
    return await _worker_observability.record_worker_heartbeat_async(
        *args, fallback=record_worker_heartbeat, **kwargs
    )


def record_cron_execution(*args, **kwargs):
    """Compatibility facade for durable cron status writes."""
    return _worker_observability.record_cron_execution(*args, **kwargs)


def get_cron_status(*args, **kwargs):
    return _worker_observability.get_cron_status(*args, **kwargs)


def get_eval_worker_status(*args, **kwargs):
    return _worker_observability.get_eval_worker_status(*args, **kwargs)


def observed_cron_task(task):
    def record_execution(*args, **kwargs):
        return record_cron_execution(*args, **kwargs)

    return _worker_observability.observed_cron_task(
        task, record_execution=record_execution
    )
from app.worker_enqueue import (
    _get_redis_pool,
    enqueue_cluster_batch_job,
    enqueue_cluster_rebuild_job,
    enqueue_build_job,
    enqueue_submit_import_job,
    enqueue_generate_answer_job,
    enqueue_generate_recitation_job,
    enqueue_interview_reprocess_job,
    enqueue_interview_import_analysis_job,
    enqueue_interview_distribution_refresh,
    enqueue_recompute_embedding_job,
    enqueue_quality_review_scan_job,
    enqueue_cluster_review_task,
)


from app.worker_cluster_tasks import (
    _schedule_cluster_answer_jobs,
    cluster_batch_task,
    cluster_rebuild_task,
    cluster_review_task,
    interview_reprocess_task,
    quality_review_scan_task,
    recompute_embedding_task,
    refresh_interview_distribution_task,
    shutdown,
    startup,
)
async def process_chat_side_effects_task(ctx, limit: int = 10):
    """Drain durable chat memory handoffs left by cancelled/restarted API workers."""
    from app.services import chat_service
    from app.agents.chat.nodes import MEMORY_EXTRACT_PROMPT, _call_llm_with_retry, _extract_json

    processed = 0
    for _ in range(max(1, min(int(limit), 50))):
        job = await asyncio.to_thread(
            chat_service.claim_side_effect_job,
            worker_id="arq-chat-side-effects",
            kind="memory_extraction",
        )
        if not job:
            break
        payload = job.get("payload") or {}
        history = (
            f"面试官提问: {str(payload.get('prior_question') or '')[:400]}\n"
            f"候选人回答: {str(payload.get('user_message') or '')[:4000]}\n"
            f"面试官追问: {str(payload.get('assistant_response') or '')[:4000]}"
        )
        try:
            result = await _call_llm_with_retry(
                MEMORY_EXTRACT_PROMPT.format(message_history=history),
                user_id=int(job["user_id"]),
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(result)
            memories = (
                parsed
                if isinstance(parsed, list)
                else (
                    parsed.get("memories", parsed.get("items", []))
                    if isinstance(parsed, dict)
                    else []
                )
            )
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            note_parts = []
            for memory in memories if isinstance(memories, list) else []:
                if isinstance(memory, dict) and memory.get("type") in {
                    "weakness",
                    "strength",
                    "preference",
                }:
                    note_parts.append(f"[{memory['type']}] {memory.get('content', '')}")
            selected = metadata.get("selected_question")
            if isinstance(selected, dict) and selected.get("question"):
                note_parts.append(
                    f"[asked] #{selected.get('id')}: {str(selected['question'])[:80]}"
                )
            await asyncio.to_thread(
                chat_service.commit_memory_extraction_job,
                job["id"],
                memories if isinstance(memories, list) else [],
                note_parts,
            )
            processed += 1
        except Exception as exc:
            await asyncio.to_thread(
                chat_service.fail_side_effect_job, job["id"], str(exc), retry=True
            )
            logger.warning("chat side-effect job failed: %s (%s)", job["id"], exc)
    return {"status": "completed", "processed": processed}


from app.services.backpressure import AdaptiveSemaphore

# 重活写任务共享并发闸门(批量答案生成/题库重建),限制同一时刻批量写并发,
# 降低对 SQLite 单写锁的突发抢占(spec M5 / Task 7)。
_WORKER_DB_SEMAPHORE = AdaptiveSemaphore(initial=4, min_concurrency=1)


def _backup_db_online(db_path: str, backup_path: str) -> None:
    """在线备份:用 sqlite backup API 生成一致性快照。

    WAL 模式下 shutil.copy2 只拷主库、漏掉 -wal 未合并帧,是不一致备份;
    改用 sqlite3.Connection.backup()(对照 migrations/__init__.py:32)。
    """
    import sqlite3

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()


async def build_master_bank_task(ctx, job_id: int):
    """后台任务：重建 master bank 题库(经 _WORKER_DB_SEMAPHORE 限流)。"""
    async with _WORKER_DB_SEMAPHORE:
        result = await _build_master_bank_job(ctx, job_id)
        _WORKER_DB_SEMAPHORE.record_success()
    return result


async def interview_turn_task(ctx, turn_id: str):
    """Execute one Harness 2.0 TurnRun outside the HTTP process."""
    from app.services.harness_turn_worker import run_harness_turn

    worker_id = str(ctx.get("job_id") or ctx.get("worker_id") or "arq-interview-turn")
    return await run_harness_turn(str(turn_id), worker_id=worker_id)


async def _build_master_bank_job(ctx, job_id: int):
    """后台任务：重建 master bank 题库"""
    from app.services.pipeline import (
        dequeue_batch,
        cluster_batch,
        mark_batch_done,
        mark_batch_failed,
        BATCH_SIZE,
    )
    from app.db.connection import get_db_connection
    from app.core.config import DB_PATH
    from app.services.job_lifecycle import (
        BUILD_MASTER_BANK_JOB_TYPE,
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
                job_type=BUILD_MASTER_BANK_JOB_TYPE,
            )
            conn.commit()
            return bool(claimed)

    if not await asyncio.to_thread(_claim):
        logger.info("题库重建任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    def _update_progress(current, total, message=""):
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'running', progress_current = ?, progress_total = ?, progress_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (current, total, message, job_id),
            )
            conn.commit()

    def _mark_complete(status, result=None, error=None):
        with get_db_connection() as conn:
            if status == "completed":
                complete_job(conn, job_id, worker_id, result=result)
            else:
                fail_job(conn, job_id, worker_id, error or "题库重建失败")
            conn.commit()

    try:
        # Step 1: 备份
        _update_progress(0, 0, "正在备份数据库...")
        backup_dir = os.path.join(os.path.dirname(DB_PATH), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"interview-boss-build-{int(time.time())}.db")
        _backup_db_online(DB_PATH, backup_path)
        # 清理旧备份（保留最近 3 个）
        try:
            import glob

            backups = sorted(
                glob.glob(os.path.join(backup_dir, "interview-boss-build-*.db")),
                key=os.path.getmtime,
                reverse=True,
            )
            for old in backups[3:]:
                os.remove(old)
        except Exception:
            pass

        # Step 2: 加载数据
        _update_progress(0, 0, "加载题目数据...")
        from app.db.connection import get_current_job_position

        current_pos = get_current_job_position()

        def _load():
            with get_db_connection() as conn:
                raw = conn.execute(
                    "SELECT qd.id, qd.question, qd.cat1, qd.cat2, qd.tags, qd.diff_tag, qd.url, qd.company, qd.round "
                    "FROM questions_detail qd "
                    "JOIN interview i ON qd.interview_id = i.id "
                    "WHERE qd.question IS NOT NULL AND qd.question != '' AND qd.deleted_at IS NULL "
                    "AND i.deleted_at IS NULL AND i.owner_id IS NULL AND i.status = 'approved' "
                    "AND qd.job_position = ?",
                    (current_pos,),
                ).fetchall()
                return raw, _load_public_rebuild_answer_cache(conn, current_pos)

        raw_questions, existing_answers_map = await asyncio.to_thread(_load)
        if not raw_questions:
            _mark_complete("completed", result="没有数据")
            return {"status": "empty"}

        total = len(raw_questions)
        _update_progress(0, total, f"共 {total} 道题目，准备聚类...")

        # Step 3: 清空公共题库
        _update_progress(0, total, "清空旧题库...")

        def _clear_bank():
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN")
                try:
                    cursor.execute(
                        "DELETE FROM user_question_view WHERE question_bank_id IN "
                        "(SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)",
                        (current_pos,),
                    )
                    cursor.execute(
                        "DELETE FROM user_practice_history WHERE question_bank_id IN "
                        "(SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)",
                        (current_pos,),
                    )
                    cursor.execute(
                        "DELETE FROM question_position WHERE question_id IN "
                        "(SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)",
                        (current_pos,),
                    )
                    cursor.execute(
                        "UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP, "
                        "updated_at = CURRENT_TIMESTAMP "
                        "WHERE job_position = ? AND owner_id IS NULL AND deleted_at IS NULL",
                        (current_pos,),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

        await asyncio.to_thread(_clear_bank)

        # Step 4: 入队所有问题
        def _enqueue_all():
            with get_db_connection() as conn:
                queue_columns = {
                    row[1]
                    for row in conn.execute("PRAGMA table_info('analysis_queue')").fetchall()
                }
                if "contribution_request_id" in queue_columns:
                    # Rebuild owns only ordinary public work.  A personal
                    # queue, or a public row attached to an approval request,
                    # is durable user work and must survive a public rebuild.
                    conn.execute(
                        "DELETE FROM analysis_queue "
                        "WHERE owner_id IS NULL AND contribution_request_id IS NULL"
                    )
                else:
                    conn.execute(
                        "DELETE FROM analysis_queue WHERE owner_id IS NULL"
                    )
                qd_rows = conn.execute(
                    "SELECT qd.id, i.id as interview_id FROM questions_detail qd "
                    "JOIN interview i ON qd.interview_id = i.id "
                    "WHERE qd.deleted_at IS NULL AND i.deleted_at IS NULL "
                    "AND i.owner_id IS NULL AND i.status = 'approved' AND qd.job_position = ?",
                    (current_pos,),
                ).fetchall()
                for row in qd_rows:
                    conn.execute(
                        "INSERT OR IGNORE INTO analysis_queue (interview_id, question_detail_id, status) VALUES (?, ?, 'pending')",
                        (row["interview_id"], row["id"]),
                    )
                conn.commit()
                return len(qd_rows)

        enqueued = await asyncio.to_thread(_enqueue_all)
        _update_progress(0, enqueued, f"已入队 {enqueued} 道题目，开始批量聚类...")
        logger.info(f"重建题库(ARQ): 已入队 {enqueued} 道题目")

        # Step 5: 分批聚类
        # 从任务上下文获取 user_id（提交者）
        def _get_job_creator():
            with get_db_connection() as conn:
                row = conn.execute("SELECT created_by FROM jobs WHERE id = ?", (job_id,)).fetchone()
                return row["created_by"] if row else None

        creator_id = await asyncio.to_thread(_get_job_creator)

        total_new = 0
        batch_num = 0
        while True:
            batch = dequeue_batch(BATCH_SIZE, owner_id=None)
            if not batch:
                break
            batch_num += 1
            try:
                cluster_result = await cluster_batch(
                    batch,
                    user_id=creator_id,
                    skip_clean=True,
                    return_new_ids=True,
                )
                if isinstance(cluster_result, dict):
                    new_count = int(cluster_result.get("count", 0))
                    new_qb_ids = cluster_result.get("ids", [])
                else:
                    new_count = int(cluster_result or 0)
                    new_qb_ids = []
                queue_ids = [item["queue_id"] for item in batch]
                mark_batch_done(queue_ids)
                from app.services.public_contributions import mark_public_contribution_queue_done

                with get_db_connection() as connection:
                    mark_public_contribution_queue_done(connection, queue_ids)
                await _schedule_cluster_answer_jobs(
                    job_id,
                    new_qb_ids,
                    owner_id=batch[0].get("owner_id"),
                    actor_id=creator_id,
                )
                total_new += new_count
                _update_progress(
                    batch_num * BATCH_SIZE,
                    enqueued,
                    f"批次 {batch_num}: 新增 {new_count} 个聚类（累计 {total_new}）",
                )
            except Exception as e:
                logger.error(f"重建聚类批次 {batch_num} 失败: {e}")
                queue_ids = [item["queue_id"] for item in batch]
                mark_batch_failed(queue_ids)
                raise

        # Step 6: 恢复 AI 答案
        _update_progress(enqueued, enqueued, "恢复 AI 答案...")

        def _restore_answers():
            with get_db_connection() as conn:
                restored = 0
                rows = conn.execute(
                    "SELECT id, question, original_questions FROM question_bank "
                    "WHERE job_position = ? AND owner_id IS NULL AND (ai_answer IS NULL OR ai_answer = '')",
                    (current_pos,),
                ).fetchall()
                for r in rows:
                    saved = existing_answers_map.get(r["question"])
                    ai_answer = saved["answer"] if saved else None
                    answer_sources = saved["sources"] if saved else None
                    if not ai_answer:
                        try:
                            import json

                            oqs = json.loads(r["original_questions"] or "[]")
                            for oq in oqs:
                                saved = existing_answers_map.get(oq)
                                if saved and saved["answer"]:
                                    ai_answer = saved["answer"]
                                    answer_sources = saved["sources"]
                                    break
                        except Exception:
                            pass
                    if ai_answer:
                        conn.execute(
                            "UPDATE question_bank SET ai_answer = ?, answer_sources = ? WHERE id = ?",
                            (ai_answer, answer_sources, r["id"]),
                        )
                        restored += 1
                conn.commit()
                return restored

        restored = await asyncio.to_thread(_restore_answers)
        logger.info(f"全量重建完成(ARQ): {total_new} 个聚类，恢复 {restored} 个 AI 答案")
        _mark_complete(
            "completed", result=f"重建完成，新增 {total_new} 个聚类，恢复 {restored} 个 AI 答案"
        )
        from app.core.cache import invalidate_master_bank_cache

        await invalidate_master_bank_cache()
        return {"status": "completed", "total_new": total_new, "restored": restored}

    except Exception as e:
        logger.exception(f"全量重建任务(ARQ)失败: job_id={job_id}")
        _mark_complete("failed", error=str(e)[:500])
        raise


def _normalize_error_code(message: str) -> str:
    """把 worker 原始错误消息归一到契约错误码（AC-013）；未知返回原样截断。"""

    text = (message or "").lower()
    if "401" in text or "invalid api key" in text or "unauthorized" in text:
        return "MODEL_AUTH_INVALID"
    if "额度" in text or ("quota" in text and "limit" in text):
        return "QUOTA_EXCEEDED"
    if "429" in text or "rate limit" in text or "rate_limit" in text:
        return "UPSTREAM_RATE_LIMIT"
    if "timeout" in text or "超时" in text:
        return "UPSTREAM_TIMEOUT"
    if re.search(r"\b5\d{2}\b", text):
        return "UPSTREAM_UNAVAILABLE"
    if "api key" in text or "model_config" in text or "配置" in text:
        return "MODEL_CONFIG_MISSING"
    return (message or "UNKNOWN_ERROR")[:64]


async def credential_preflight_task(ctx, job_id: int):
    """R01：凭据预检 ARQ 任务——真实 provider 探测，失败阻塞提取派发。"""

    from app.db.connection import get_db_connection, run_db
    from app.services.job_lifecycle import (
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
    )
    from app.services.credential_preflight import run_credential_preflight

    worker_id = default_worker_id()

    def _claim():
        with get_db_connection() as conn:
            task = claim_job(
                conn, job_id, worker_id, job_type="credential_preflight"
            )
            conn.commit()
            return dict(task) if task else None

    claimed = await asyncio.to_thread(_claim)
    if not claimed:
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    def _run_preflight():
        with get_db_connection() as conn:
            outcome = run_credential_preflight(conn, job_id=job_id)
            if outcome.status == "ok":
                complete_job(conn, job_id, worker_id, result="preflight ok")
            else:
                fail_job(
                    conn,
                    job_id,
                    worker_id,
                    f"{outcome.error_code}: {outcome.message}",
                    max_attempts=1,
                )
            conn.commit()
            return outcome

    outcome = await asyncio.to_thread(_run_preflight)
    logger.info(
        "凭据预检完成: job_id=%s scope=%s status=%s",
        job_id,
        "credential",
        outcome.status,
    )
    if outcome.status == "ok":
        # 预检在上面的事务中创建首个业务 job。立刻尝试持久化 handoff，
        # 避免新上传只能等待周期 dispatcher；投递失败仍可由 cron 补偿。
        from app.worker_scheduled import scheduled_submit_job_dispatch_task

        await scheduled_submit_job_dispatch_task(ctx)
    return {"job_id": job_id, "status": outcome.status, "error_code": outcome.error_code}


async def submit_import_task(ctx, job_id: int):
    """后台任务：执行上传导入（面经/JD 提取 + 打标 + 聚类）

    从 job_payloads 读取 input_state，调用 LangGraph submit graph，
    将进度写入 jobs 表，最终结果写入 jobs.result。
    """
    from app.db.connection import get_db_connection, run_db
    from app.services.job_lifecycle import (
        claim_job_with_generation,
        complete_job,
        default_worker_id,
        fail_job,
        touch_job,
    )
    from app.services.upload_lifecycle import FIRST_WORK_KEY, upload_execution_blocker

    worker_id = default_worker_id()

    def _preflight_ready():
        from app.services.job_lifecycle import (
            defer_job_for_upload_preflight,
            get_successful_upload_preflight,
        )

        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT j.root_import_id, j.upload_attempt_id, r.requester_id, "
                "r.status AS root_status, r.policy_json "
                "FROM jobs AS j LEFT JOIN upload_imports AS r "
                "ON r.id = j.root_import_id WHERE j.id = ?",
                (job_id,),
            ).fetchone()
            if row is None or not row["root_import_id"]:
                return True, None

            policy = {}
            try:
                policy = json.loads(row["policy_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                pass
            credential_scope = policy.get("credential_scope") or "user"
            preflight = get_successful_upload_preflight(
                conn,
                root_import_id=row["root_import_id"],
                attempt_id=row["upload_attempt_id"],
                credential_scope=credential_scope,
            )
            user_id = int(row["requester_id"]) if credential_scope == "user" else None

            current_fingerprint = None
            if preflight and row["root_status"] != "needs_action":
                try:
                    from app.services.upload_credentials import resolve_upload_credentials

                    current = resolve_upload_credentials(
                        credential_scope=credential_scope,
                        user_id=user_id,
                        stage="extract",
                    )
                    current_fingerprint = current.config_fingerprint
                except Exception:
                    # A missing/invalid current config must be checked by a new
                    # preflight job, which records the actionable failure.
                    current_fingerprint = None

                try:
                    result = json.loads(preflight["result_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    result = {}
                if (
                    current_fingerprint
                    and result.get("config_fingerprint") == current_fingerprint
                ):
                    return True, result.get("model")

            # Some API routes enqueue submit_import directly. Defer that early
            # delivery without claiming/consuming an attempt. If the saved
            # checkpoint is absent/stale, create a fresh durable preflight job;
            # the dispatcher will not release submit until that job succeeds.
            if row["root_status"] != "needs_action":
                from app.services.credential_preflight import create_credential_preflight_job

                create_credential_preflight_job(
                    conn,
                    root_import_id=row["root_import_id"],
                    requester_id=int(row["requester_id"]),
                    credential_scope=credential_scope,
                    user_id=user_id,
                    attempt_id=row["upload_attempt_id"],
                )
            defer_job_for_upload_preflight(conn, job_id)
            conn.commit()
            return False, None

    preflight_ready, preflight_model = await asyncio.to_thread(_preflight_ready)
    if not preflight_ready:
        logger.info("上传任务等待同批次模型预检: job_id=%s", job_id)
        return {"status": "waiting_preflight", "job_id": job_id}

    def _claim():
        with get_db_connection() as conn:
            task = claim_job_with_generation(conn, job_id, worker_id=worker_id)
            conn.commit()
            return dict(task) if task else None

    claimed = await asyncio.to_thread(_claim)
    if not claimed:
        logger.info("上传任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}
    # F12：本次领取的 lease_generation 是根状态写入与业务提交的 fence
    lease_generation = int(claimed["lease_generation"])

    def _complete(result: str | None = None):
        with get_db_connection() as conn:
            completed = complete_job(
                conn,
                job_id,
                worker_id,
                result=result,
                lease_generation=lease_generation,
            )
            conn.commit()
            return completed

    def _fail(error: str, terminal: bool = False):
        with get_db_connection() as conn:
            outcome = fail_job(
                conn,
                job_id,
                worker_id,
                error,
                max_attempts=0 if terminal else 3,
                lease_generation=lease_generation,
            )
            conn.commit()
            return outcome

    def _load_payload():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            return json.loads(row["payload"]) if row else None

    payload = await asyncio.to_thread(_load_payload)
    if not payload:
        _fail("任务数据不存在", terminal=True)
        return

    try:
        # R02/R03：worker 按 root 读取完整服务端 policy 与 v2 归属，
        # 不再靠 payload 里的旧字段猜策略（普通 share 审核意图必须贯穿）。
        def _load_root_context():
            with get_db_connection() as conn:
                job = conn.execute(
                    "SELECT j.root_import_id, j.upload_attempt_id, j.work_key, "
                    "j.idempotency_key, a.attempt_no FROM jobs j "
                    "LEFT JOIN upload_attempts a ON a.id = j.upload_attempt_id "
                    "WHERE j.id = ?",
                    (job_id,),
                ).fetchone()
                root = None
                policy = {}
                if job and job["root_import_id"]:
                    root = conn.execute(
                        "SELECT * FROM upload_imports WHERE id = ?",
                        (job["root_import_id"],),
                    ).fetchone()
                if root:
                    try:
                        policy = json.loads(root["policy_json"] or "{}")
                    except (json.JSONDecodeError, TypeError):
                        policy = {}
                return (dict(job) if job else None), (dict(root) if root else None), policy

        job_row, root_row, policy = await asyncio.to_thread(_load_root_context)
        root_import_id = job_row["root_import_id"] if job_row else None
        attempt_id = job_row["upload_attempt_id"] if job_row else None
        attempt_no = job_row["attempt_no"] if job_row else None
        root_status = root_row["status"] if root_row else None

        # R01：预检失败（needs_action）不派发提取——即使 job 已被调度也拒绝执行。
        if root_import_id and root_status == "needs_action":
            _fail("凭据预检未通过，请先修复模型配置", terminal=True)
            return

        if root_import_id and root_row:
            def _check_execution_context():
                with get_db_connection() as conn:
                    fresh_root = conn.execute(
                        "SELECT * FROM upload_imports WHERE id = ?", (root_import_id,)
                    ).fetchone()
                    return upload_execution_blocker(conn, fresh_root, policy)

            blocker = await asyncio.to_thread(_check_execution_context)
            if blocker:
                error_code, error_message = blocker

                def _block_before_processing():
                    from app.services.upload_lifecycle import finalize_attempt_and_aggregate_root

                    with get_db_connection() as conn:
                        outcome = fail_job(
                            conn,
                            job_id,
                            worker_id,
                            f"{error_code}: {error_message}",
                            max_attempts=0,
                            lease_generation=lease_generation,
                        )
                        if outcome.get("status") != "failed":
                            conn.commit()
                            return False
                        current_root = conn.execute(
                            "SELECT input_version, pipeline_version FROM upload_imports WHERE id = ?",
                            (root_import_id,),
                        ).fetchone()
                        conn.execute(
                            "INSERT OR IGNORE INTO upload_stage_results ("
                            "import_id, stage, unit_key, input_version, pipeline_version, "
                            "status, error_code, job_id) "
                            "VALUES (?, 'extract', ?, ?, ?, 'needs_action', ?, ?)",
                            (
                                root_import_id,
                                f"source_validation:job:{job_id}",
                                int(current_root["input_version"] or 1),
                                current_root["pipeline_version"],
                                error_code,
                                job_id,
                            ),
                        )
                        finalize_attempt_and_aggregate_root(
                            conn,
                            import_id=root_import_id,
                            actor_id=int(payload.get("user_id") or 0),
                            error_code=error_code,
                            error_message=error_message,
                            lease_generation=lease_generation,
                        )
                        conn.commit()
                        return True

                blocked = await asyncio.to_thread(_block_before_processing)
                if blocked:
                    logger.info(
                        "上传任务执行前校验阻塞: import_id=%s code=%s",
                        root_import_id,
                        error_code,
                    )
                return {"status": "needs_action", "job_id": job_id, "error_code": error_code}

        work_key = job_row["work_key"] if job_row else FIRST_WORK_KEY

        # F08：恢复执行时读取已成功的 extract/classify 阶段检查点，
        # 注入 input_state 让节点复用（不重跑 LLM、不重复打标）。
        resume_extracted = None
        resume_tagged = None
        if root_import_id:
            def _load_resume():
                with get_db_connection() as conn:
                    extract_ckpt = conn.execute(
                        "SELECT result_json FROM upload_stage_results "
                        "WHERE import_id = ? AND stage IN ('extract','fill') "
                        "AND status = 'succeeded' ORDER BY id DESC LIMIT 1",
                        (root_import_id,),
                    ).fetchone()
                    classify_ckpt = conn.execute(
                        "SELECT result_json FROM upload_stage_results "
                        "WHERE import_id = ? AND stage IN ('classify','tag') "
                        "AND status = 'succeeded' ORDER BY id DESC LIMIT 1",
                        (root_import_id,),
                    ).fetchone()
                    out = {"extracted": None, "tagged": None}
                    if extract_ckpt:
                        try:
                            out["extracted"] = json.loads(extract_ckpt["result_json"] or "{}")
                        except (json.JSONDecodeError, TypeError):
                            out["extracted"] = None
                    if classify_ckpt:
                        try:
                            out["tagged"] = json.loads(classify_ckpt["result_json"] or "{}")
                        except (json.JSONDecodeError, TypeError):
                            out["tagged"] = None
                    return out

            resume = await asyncio.to_thread(_load_resume)
            if resume.get("extracted") and resume["extracted"].get("data"):
                resume_extracted = resume["extracted"]
            if resume.get("tagged") and resume["tagged"].get("tagged_rows"):
                resume_tagged = resume["tagged"]["tagged_rows"]

        # 从 root 派生的策略覆盖 payload 旧字段（R02）
        # graph 的 target 词表是 personal/public（after_classify/jd_persist 都按它
        # 判定），policy.write_scope 是 private/public：在唯一边界做一次规范化，
        # 避免两侧词表漂移导致私人 JD 被当成公共待审数据。
        write_scope = policy.get("write_scope") or payload.get("target", "personal")
        target = "public" if write_scope == "public" else "personal"
        target_intent = policy.get("target_intent") or payload.get("target_intent", "private")
        request_public_review = bool(
            policy.get("request_public_review", False)
            or payload.get("request_public_review", False)
        )
        credential_scope = policy.get("credential_scope") or (
            "global" if payload.get("is_admin") and payload.get("target") == "public" else "user"
        )
        is_admin = bool(
            payload.get("is_admin", False) or policy.get("audit_public_import", False)
        )

        # 首次 job 的 attempt 归属（root 为 v2 时）
        if root_import_id and attempt_id is None:
            def _attach_attempt():
                with get_db_connection() as conn:
                    row = conn.execute(
                        "SELECT id FROM upload_attempts WHERE import_id = ? "
                        "AND status = 'active' ORDER BY attempt_no DESC LIMIT 1",
                        (root_import_id,),
                    ).fetchone()
                    if row:
                        conn.execute(
                            "UPDATE jobs SET upload_attempt_id = ? WHERE id = ?",
                            (row["id"], job_id),
                        )
                        conn.commit()
                        return int(row["id"])
                    return None

            attempt_id = await asyncio.to_thread(_attach_attempt)

        from app.agents.submit.graph import stream_submit_graph
        from app.services.upload_lifecycle import (
            build_thread_id,
            finalize_attempt_and_aggregate_root,
        )

        # 构建 input_state（将 base64 图片还原为 bytes）
        raw_images = payload.get("image_data", [])
        image_data = []
        for img in raw_images:
            if "content_b64" in img:
                image_data.append(
                    {"content": base64.b64decode(img["content_b64"]), "mime": img["mime"]}
                )
            else:
                image_data.append(img)  # 兼容直接传 bytes 的场景

        thread_id = build_thread_id(
            root_import_id or f"legacy-{job_id}", attempt_no or 0, job_id
        )
        input_state = {
            "raw_text": payload.get("raw_text", ""),
            "image_data": image_data,
            "url": payload.get("url", ""),
            "season": payload.get("season", ""),
            "content_type_hint": payload.get("content_type_hint", ""),
            "target": target,
            "target_intent": target_intent,
            "request_public_review": request_public_review,
            "credential_scope": credential_scope,
            "_eval_model": preflight_model,
            "user_id": payload.get("user_id"),
            "is_admin": is_admin,
            "job_position": payload.get("job_position", ""),
            "import_id": root_import_id,
            "attempt_id": attempt_id,
            "_lease_generation": lease_generation,
            "thread_id": thread_id,
            "work_key": work_key,
            "job_id": job_id,
            # F08：检查点复用（恢复执行不重跑已成功阶段）
            "_resume_extracted": resume_extracted,
            "_resume_tagged_rows": resume_tagged,
        }

        # 阶段映射
        PHASES = ["extract", "fill", "tag", "match", "save", "cluster"]
        phase_index = {p: i for i, p in enumerate(PHASES)}

        def _update_progress(phase, message=""):
            idx = phase_index.get(phase, 0)
            from app.services.upload_stage_names import checkpoint_for_upload_phase

            durable_stage, unit_key = checkpoint_for_upload_phase(phase)
            with get_db_connection() as conn:
                if not touch_job(
                    conn,
                    job_id,
                    worker_id,
                    progress_current=idx + 1,
                    progress_total=len(PHASES),
                    progress_message=message,
                    progress_phase=phase,
                    lease_generation=lease_generation,
                ):
                    raise RuntimeError(f"上传任务 lease 已失效: job_id={job_id}")
                # R03：execution 进度持久化进阶段检查点（幂等 UNIQUE）
                if root_import_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO upload_stage_results ("
                        "  import_id, stage, unit_key, input_version, pipeline_version, "
                        "  status, job_id"
                        ") VALUES (?, ?, ?, 1, 'upload-pipeline-v1', 'running', ?)",
                        (root_import_id, durable_stage, unit_key, job_id),
                    )
                conn.commit()

        _update_progress("extract", "正在提取内容...")

        async def _aggregate_root_failure(error_message: str):
            """失败路径：把执行中的阶段检查点标记为 failed，并聚合根状态（R04）。"""

            if not root_import_id:
                return
            code = str(error_message)[:64]
            # 统一错误码归一到契约常量（AC-013）
            normalized = _normalize_error_code(code)

            def _apply():
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE upload_stage_results SET status = 'failed', "
                        "error_code = ?, updated_at = CURRENT_TIMESTAMP "
                        "WHERE import_id = ? AND status IN ('running', 'pending')",
                        (normalized, root_import_id),
                    )
                    conn.commit()
                    return finalize_attempt_and_aggregate_root(
                        conn,
                        import_id=root_import_id,
                        actor_id=int(payload.get("user_id") or 0),
                        error_code=normalized,
                        error_message=error_message,
                        lease_generation=lease_generation,
                    )

            try:
                aggregated = await asyncio.to_thread(_apply)
                logger.info(
                    "上传根任务失败聚合: import_id=%s status=%s code=%s",
                    root_import_id,
                    aggregated["status"],
                    normalized,
                )
            except Exception as exc:
                logger.warning("根任务失败聚合异常: %s", exc)

        result_collector = {}
        last_phase = ""
        emitted_error = None
        saw_done = False

        # 消费 graph 事件流（只读取事件，不产出 SSE）
        try:
            async for sse_data in stream_submit_graph(
                input_state, result_collector=result_collector
            ):
                try:
                    # sse_data 格式: "data: {json}\n\n"
                    if sse_data.startswith("data: "):
                        event = json.loads(sse_data[6:].strip())
                        etype = event.get("type", "")

                        if etype == "error":
                            emitted_error = event.get("message") or "处理失败"
                            # Drain the async SSE generator to completion. Breaking
                            # here closes it from the consumer's context while its
                            # ContextVar token was set in the generator task.
                            continue

                        if etype == "done":
                            saw_done = True

                        step = event.get("step", "")
                        message = event.get("message", "")
                        if step and step in phase_index:
                            _update_progress(step, message)
                            last_phase = step
                        elif etype == "progress" and message:
                            # 有 message 但没有已知 step
                            _update_progress(last_phase or "extract", message)
                except (json.JSONDecodeError, ValueError):
                    pass
        except Exception as e:
            logger.exception(f"graph 流式执行异常: job_id={job_id}")
            emitted_error = str(e)[:500] or "任务执行异常"

        # 如果 graph yield 了 error 事件，立刻标记失败
        if emitted_error:
            await _aggregate_root_failure(emitted_error)
            _fail(emitted_error)
            return

        # 读取最终结果（从 result_collector 获取，避免 thread_id 不匹配）
        final_state_values = result_collector.get("final_state") or {}

        if final_state_values.get("error"):
            await _aggregate_root_failure(final_state_values["error"])
            _fail(final_state_values["error"])
            return

        if not final_state_values and not saw_done:
            await _aggregate_root_failure("任务未返回有效结果")
            _fail("任务未返回有效结果")
            return

        doc_type = final_state_values.get("doc_type", "Interview")
        doc_type = {"jd": "JD", "interview": "Interview"}.get(doc_type, doc_type)
        target = final_state_values.get("target", "personal")
        extracted_data = final_state_values.get("extracted_data", {})

        # 构建结果 JSON（包含尽可能多的有用信息）
        result_data = {
            "doc_type": doc_type,
            "target": target,
            "saved_data": extracted_data,
            "interview_id": final_state_values.get("saved_interview_id"),
            "question_count": len(extracted_data.get("具体题目清单", [])) if extracted_data else 0,
        }

        # 聚类信息（公共题库）
        cluster_result = final_state_values.get("cluster_result", {})
        if cluster_result:
            result_data["new_qb_count"] = cluster_result.get("new_qb_count", 0)

        # 匹配结果摘要（如果 final_state 里有）
        match_result = final_state_values.get("match_result")
        if match_result and isinstance(match_result, dict):
            result_data["match_result"] = {
                "matched_count": match_result.get(
                    "matched_count", len(match_result.get("matched", []))
                ),
                "unmatched_count": match_result.get(
                    "unmatched_count", len(match_result.get("unmatched", []))
                ),
            }

        # 耗时信息（如果 final_state 里有）
        if final_state_values.get("node_timings"):
            result_data["node_timings"] = final_state_values["node_timings"]
        if final_state_values.get("elapsed_seconds"):
            result_data["elapsed_seconds"] = final_state_values["elapsed_seconds"]

        answer_tasks = final_state_values.get("answer_tasks", [])
        uid = result_collector.get("user_id") or payload.get("user_id")
        answer_job_ids = []
        if answer_tasks and uid is not None:
            from app.services.job_lifecycle import create_answer_generation_jobs

            public_answer = bool(payload.get("is_admin") and payload.get("target") == "public")
            answer_llm_scope = "global" if public_answer else "user"
            answer_search_scope = "public" if public_answer else "user"

            def _create_answer_jobs():
                with get_db_connection() as conn:
                    ids = create_answer_generation_jobs(
                        conn,
                        job_id,
                        answer_tasks,
                        uid,
                        llm_scope=answer_llm_scope,
                        search_scope=answer_search_scope,
                    )
                    conn.commit()
                    return ids

            answer_job_ids = await asyncio.to_thread(_create_answer_jobs)
        result_data["answer_job_count"] = len(answer_job_ids)

        # R04：worker 完成时在持久化事务中聚合根状态并推进 revision；
        # 同时把本次执行的各阶段检查点标记 succeeded（幂等）。
        if root_import_id:
            match_failed = int(final_state_values.get("match_failed", 0) or 0) > 0

            def _finalize_root(success_result: str | None):
                with get_db_connection() as conn:
                    seen_units = conn.execute(
                        "SELECT stage, unit_key FROM upload_stage_results "
                        "WHERE import_id = ? AND status = 'running'",
                        (root_import_id,),
                    ).fetchall()
                    for stage_row in seen_units:
                        # AC-006：匹配模型失败 → match 阶段标记 failed（成果
                        # 保留 → 根 partial_failed，失败步骤可重试），其余
                        # 阶段照常 succeeded。
                        if match_failed and stage_row["stage"] in (
                            "resolve", "persist", "match", "save"
                        ):
                            conn.execute(
                                "UPDATE upload_stage_results SET status = 'failed', "
                                "error_code = 'MATCH_FAILED', updated_at = CURRENT_TIMESTAMP "
                                "WHERE import_id = ? AND stage = ? AND unit_key = ? "
                                "AND status = 'running'",
                                (
                                    root_import_id,
                                    stage_row["stage"],
                                    stage_row["unit_key"],
                                ),
                            )
                            continue
                        # F08：extract/tag 阶段把完整结果（含逐题数据）写进
                        # 检查点，恢复时可复用不重跑 LLM。阶段名以 PHASES
                        # （extract/fill/tag/match/save/cluster）为准。
                        if stage_row["stage"] in ("extract", "fill"):
                            stage_payload = json.dumps(
                                {
                                    "doc_type": final_state_values.get("doc_type", ""),
                                    "data": extracted_data,
                                    "url": final_state_values.get("saved_url", ""),
                                },
                                ensure_ascii=False,
                            )
                        elif stage_row["stage"] in ("tag", "classify"):
                            stage_payload = json.dumps(
                                {
                                    "tagged_rows": final_state_values.get("tagged_rows", []),
                                },
                                ensure_ascii=False,
                            )
                        else:
                            stage_payload = success_result
                        conn.execute(
                            "UPDATE upload_stage_results SET status = 'succeeded', "
                            "result_json = ?, updated_at = CURRENT_TIMESTAMP "
                            "WHERE import_id = ? AND stage = ? AND unit_key = ? "
                            "AND status = 'running'",
                            (
                                stage_payload,
                                root_import_id,
                                stage_row["stage"],
                                stage_row["unit_key"],
                            ),
                        )
                    conn.commit()

            await asyncio.to_thread(_finalize_root, json.dumps(result_data, ensure_ascii=False))

        _complete(result=json.dumps(result_data, ensure_ascii=False))

        # 根聚合必须在 complete 之后（读 jobs 最终态），且在当前 worker 进程中
        if root_import_id:
            def _aggregate():
                with get_db_connection() as conn:
                    return finalize_attempt_and_aggregate_root(
                        conn,
                        import_id=root_import_id,
                        actor_id=int(payload.get("user_id") or 0),
                        interview_id=final_state_values.get("saved_interview_id"),
                        lease_generation=lease_generation,
                    )

            aggregated = await asyncio.to_thread(_aggregate)
            logger.info(
                "上传根任务推进: import_id=%s status=%s revision=%s",
                root_import_id,
                aggregated["status"],
                aggregated["revision"],
            )
            # R02：普通 share 优先走公共化申请而非直接完成
            if request_public_review:
                from app.db.connection import get_db_connection
                from app.services.public_contributions import create_public_contribution_request

                def _ensure_contribution():
                    with get_db_connection() as conn:
                        interview_id = aggregated.get("interview_id")
                        if not interview_id:
                            return None
                        return create_public_contribution_request(
                            conn, "interview", int(interview_id), int(payload.get("user_id") or 0)
                        )

                contribution = await asyncio.to_thread(_ensure_contribution)
                if contribution:
                    # 回写根任务关联（此前 upload_imports.contribution_request_id
                    # 零写入，快照 review_status 恒空）。
                    if root_import_id:
                        from app.services.public_contributions import (
                            bind_contribution_request_to_root,
                        )

                        def _bind_root():
                            with get_db_connection() as conn:
                                bind_contribution_request_to_root(
                                    conn,
                                    import_id=root_import_id,
                                    contribution_request_id=int(contribution["id"]),
                                )
                                conn.commit()

                        await asyncio.to_thread(_bind_root)
                    logger.info(
                        "share 已建公共化申请并绑定根任务: request=%s import=%s",
                        contribution["id"],
                        root_import_id,
                    )

    except Exception as e:
        logger.exception(f"上传导入任务失败: job_id={job_id}")
        await _aggregate_root_failure(str(e)[:500])
        _fail(str(e)[:500])


async def _refresh_answer_batch_parent(parent_job_id: int):
    """Finalize a batch parent after one child answer job changes state."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import ANSWER_BATCH_JOB_TYPE

    def _refresh():
        with get_db_connection() as conn:
            parent = conn.execute(
                "SELECT id FROM jobs WHERE id = ? AND job_type = ?",
                (parent_job_id, ANSWER_BATCH_JOB_TYPE),
            ).fetchone()
            if not parent:
                return
            counts = conn.execute(
                "SELECT "
                "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed, "
                "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed, "
                "COUNT(*) AS total "
                "FROM jobs WHERE parent_job_id = ?",
                (parent_job_id,),
            ).fetchone()
            completed = int(counts["completed"] or 0)
            failed = int(counts["failed"] or 0)
            total = int(counts["total"] or 0)
            if total and completed + failed == total:
                status = "failed" if failed else "completed"
                result = json.dumps(
                    {"generated": completed, "failed": failed, "total": total},
                    ensure_ascii=False,
                )
                conn.execute(
                    "UPDATE jobs SET status = ?, progress_current = ?, progress_total = ?, "
                    "result = ?, completed_at = CURRENT_TIMESTAMP, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status NOT IN ('completed', 'failed')",
                    (
                        status,
                        completed + failed,
                        total,
                        result,
                        parent_job_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status = 'running', progress_current = ?, progress_total = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status IN ('pending', 'running')",
                    (completed + failed, total, parent_job_id),
                )
            conn.commit()

    await asyncio.to_thread(_refresh)


async def generate_answer_task(ctx, job_id: int):
    """ARQ task: generate one answer with durable claim/retry semantics.

    经 _WORKER_DB_SEMAPHORE 限流:有限批量写并发,降低对 SQLite 单写锁突发抢占。
    """
    async with _WORKER_DB_SEMAPHORE:
        result = await _generate_answer_job(ctx, job_id)
        _WORKER_DB_SEMAPHORE.record_success()
        return result


async def _generate_answer_job(ctx, job_id: int):
    """ARQ task: generate one answer with durable claim/retry semantics."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        ANSWER_GENERATION_JOB_TYPE,
        JobFenceError,
        claim_job,
        claim_job_with_generation,
        complete_job,
        default_worker_id,
        fail_job,
        heartbeat_job,
    )

    worker_id = default_worker_id()

    def _sync_upload_root(conn, status, *, error_code=None, result_json=None):
        from app.services.job_lifecycle import update_upload_answer_stage
        from app.services.upload_lifecycle import refresh_completed_upload_roots

        root_import_id = update_upload_answer_stage(
            conn,
            job_id,
            status,
            error_code=error_code,
            result_json=result_json,
        )
        if root_import_id:
            refresh_completed_upload_roots(conn, [root_import_id])
        return root_import_id

    def _claim_and_load():
        with get_db_connection() as conn:
            candidate = conn.execute(
                "SELECT root_import_id FROM jobs WHERE id = ? AND job_type = ?",
                (job_id, ANSWER_GENERATION_JOB_TYPE),
            ).fetchone()
            if candidate and candidate["root_import_id"]:
                task = claim_job_with_generation(
                    conn,
                    job_id,
                    worker_id=worker_id,
                    job_type=ANSWER_GENERATION_JOB_TYPE,
                    lease_seconds=120,
                )
            else:
                task = claim_job(
                    conn,
                    job_id,
                    worker_id,
                    job_type=ANSWER_GENERATION_JOB_TYPE,
                )
            if not task:
                return None, None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            if payload_row:
                _sync_upload_root(conn, "running")
            conn.commit()
            return dict(task), json.loads(payload_row["payload"]) if payload_row else None

    claimed, payload = await asyncio.to_thread(_claim_and_load)
    if not claimed:
        logger.info("答案任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    heartbeat_stop = asyncio.Event()
    heartbeat_lost = asyncio.Event()
    lease_heartbeat_task = None
    if claimed.get("root_import_id"):
        generation = int(claimed["lease_generation"])

        def _heartbeat_answer_job():
            with get_db_connection() as conn:
                alive = heartbeat_job(conn, job_id, generation, lease_seconds=120)
                conn.commit()
                return alive

        async def _renew_answer_job():
            while not heartbeat_stop.is_set():
                try:
                    await asyncio.wait_for(heartbeat_stop.wait(), timeout=30)
                    continue
                except asyncio.TimeoutError:
                    pass
                if not await asyncio.to_thread(_heartbeat_answer_job):
                    heartbeat_lost.set()
                    return

        lease_heartbeat_task = asyncio.create_task(_renew_answer_job())

    async def _stop_answer_heartbeat():
        heartbeat_stop.set()
        if lease_heartbeat_task is not None:
            lease_heartbeat_task.cancel()
            await asyncio.gather(lease_heartbeat_task, return_exceptions=True)

    def _finish(result=None):
        with get_db_connection() as conn:
            if claimed.get("root_import_id"):
                conn.execute("BEGIN IMMEDIATE")
                from app.services.job_lifecycle import assert_job_fence

                assert_job_fence(conn, job_id, int(claimed["lease_generation"]))
                _sync_upload_root(conn, "succeeded", result_json=result)
            completed = complete_job(
                conn,
                job_id,
                worker_id,
                result=result,
                lease_generation=(
                    int(claimed["lease_generation"])
                    if claimed.get("root_import_id")
                    else None
                ),
            )
            if completed:
                if not claimed.get("root_import_id"):
                    _sync_upload_root(conn, "succeeded", result_json=result)
            conn.commit()
            return completed

    def _fail(error: str, terminal: bool = False):
        with get_db_connection() as conn:
            if claimed.get("root_import_id"):
                conn.execute("BEGIN IMMEDIATE")
                from app.services.job_lifecycle import assert_job_fence

                assert_job_fence(conn, job_id, int(claimed["lease_generation"]))
            outcome = fail_job(
                conn,
                job_id,
                worker_id,
                error,
                max_attempts=0 if terminal else 3,
                lease_generation=(
                    int(claimed["lease_generation"])
                    if claimed.get("root_import_id")
                    else None
                ),
            )
            if outcome["status"] != "stale":
                error_code = _normalize_error_code(error)
                _sync_upload_root(
                    conn,
                    "failed" if outcome["status"] == "failed" else "pending",
                    error_code=error_code,
                )
            conn.commit()
            return outcome

    if not payload:
        try:
            outcome = _fail("答案任务数据不存在", terminal=True)
        except JobFenceError:
            outcome = {"status": "stale"}
        await _stop_answer_heartbeat()
        return {"status": outcome["status"], "job_id": job_id}

    try:
        from app.services.submit_service import background_generate_answer
        root_import_id = claimed.get("root_import_id")
        if root_import_id:
            from app.services.upload_llm_accounting import upload_llm_context

            with upload_llm_context(
                root_import_id=str(root_import_id),
                stage="answer",
                unit_key=f"question:{int(payload['question_id'])}",
                credential_scope=payload.get("llm_scope", "user"),
                user_id=payload.get("user_id"),
            ):
                answer_result = await background_generate_answer(
                    int(payload["question_id"]),
                    payload["question_text"],
                    payload.get("user_id"),
                    raise_on_error=True,
                    skip_search=bool(payload.get("skip_search", False)),
                    llm_scope=payload.get("llm_scope", "user"),
                    search_scope=payload.get("search_scope", "user"),
                    job_fence=(
                        job_id,
                        int(claimed["lease_generation"]),
                    ),
                )
        else:
            answer_result = await background_generate_answer(
                int(payload["question_id"]),
                payload["question_text"],
                payload.get("user_id"),
                raise_on_error=True,
                skip_search=bool(payload.get("skip_search", False)),
                llm_scope=payload.get("llm_scope", "user"),
                search_scope=payload.get("search_scope", "user"),
            )
        if heartbeat_lost.is_set():
            raise JobFenceError(
                "答案生成期间job lease心跳失败",
                job_id=job_id,
                generation=claimed.get("lease_generation"),
            )
        completed = _finish(
            json.dumps(
                {
                    "question_id": int(payload["question_id"]),
                    **(answer_result or {}),
                },
                ensure_ascii=False,
            )
        )
        if not completed:
            raise JobFenceError(
                "答案任务租约失效，不能完成任务",
                job_id=job_id,
                generation=claimed.get("lease_generation"),
            )
        await _stop_answer_heartbeat()
        if payload.get("parent_job_id"):
            await _refresh_answer_batch_parent(int(payload["parent_job_id"]))
        return {"status": "completed", "job_id": job_id}
    except Exception as exc:
        logger.exception("答案生成任务失败: job_id=%s", job_id)
        try:
            outcome = _fail(str(exc)[:500])
        except JobFenceError:
            outcome = {"status": "stale"}
        await _stop_answer_heartbeat()
        if payload.get("parent_job_id") and outcome["status"] != "stale":
            await _refresh_answer_batch_parent(int(payload["parent_job_id"]))
        return {"status": outcome["status"], "job_id": job_id}


async def interview_import_analysis_task(ctx, job_id: int):
    """ARQ task: analyze one complete external MCP interview import."""
    from app.db.connection import get_db_connection
    from app.services.interview_import_service import analyze_import
    from app.services.job_lifecycle import (
        INTERVIEW_IMPORT_ANALYSIS_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=INTERVIEW_IMPORT_ANALYSIS_JOB_TYPE,
            )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            payload = json.loads(payload_row["payload"]) if payload_row else {}
            conn.commit()
            return payload

    payload = await asyncio.to_thread(_claim_and_load)
    if payload is None:
        logger.info("外部面试导入分析已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    try:
        result = await asyncio.to_thread(analyze_import, str(payload.get("import_id")), int(job_id))
        with get_db_connection() as conn:
            complete_job(
                conn,
                job_id,
                worker_id,
                result=json.dumps(result, ensure_ascii=False),
            )
            conn.commit()
        return {"status": "completed", "job_id": job_id, **result}
    except Exception as exc:
        logger.exception("外部面试导入分析失败: job_id=%s", job_id)
        with get_db_connection() as conn:
            fail_job(conn, job_id, worker_id, str(exc)[:500], max_attempts=0)
            conn.commit()
        raise


async def generate_recitation_task(ctx, job_id: int):
    """ARQ task: generate and persist one user's recitation answer."""
    from app.db.connection import get_db_connection, run_db
    from app.db.queries import get_user_job_position
    from app.services.answer_enrichment import (
        prepare_recitation_prompt,
    )
    from app.services.job_lifecycle import (
        RECITATION_GENERATION_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
    )
    from app.services.llm import _call_llm_with_retry
    from app.services.resume_service import get_resume_text

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=RECITATION_GENERATION_JOB_TYPE,
            )
            if not task:
                return None, None, None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            question = (
                conn.execute(
                    "SELECT question, ai_answer FROM question_bank WHERE id = ?",
                    (int(json.loads(payload_row["payload"])["question_id"]),),
                ).fetchone()
                if payload_row
                else None
            )
            conn.commit()
            return (
                dict(task),
                json.loads(payload_row["payload"]) if payload_row else None,
                dict(question) if question else None,
            )

    claimed, payload, question = await asyncio.to_thread(_claim_and_load)
    if not claimed:
        logger.info("背诵稿任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    def _finish(result=None):
        with get_db_connection() as conn:
            complete_job(conn, job_id, worker_id, result=result)
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    if not payload or not question or not question["ai_answer"]:
        _fail("背诵稿任务数据不存在或公共答案为空")
        return {"status": "failed", "job_id": job_id}

    try:
        user_id = int(payload["user_id"])
        _, job_position = get_user_job_position(user_id)
        resume_text = get_resume_text(user_id)
        prompt, search_sources = await prepare_recitation_prompt(
            question=question["question"],
            reference_answer=question["ai_answer"],
            job_position=job_position or "",
            resume_text=resume_text,
            user_id=user_id,
            skip_search=bool(payload.get("skip_search", False)),
        )
        answer = await _call_llm_with_retry(prompt, user_id=user_id)

        def _upsert():
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO user_question_view "
                    "(user_id, question_bank_id, user_answer, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(user_id, question_bank_id) DO UPDATE SET "
                    "user_answer = ?, updated_at = CURRENT_TIMESTAMP",
                    (user_id, int(payload["question_id"]), answer, answer),
                )
                conn.commit()

        await run_db(_upsert)
        from app.core.cache import invalidate_master_bank_cache

        await invalidate_master_bank_cache()
        _finish(
            json.dumps(
                {
                    "question_id": int(payload["question_id"]),
                    "answer": answer,
                    "search_sources": search_sources,
                },
                ensure_ascii=False,
            )
        )
        return {"status": "completed", "job_id": job_id}
    except Exception as exc:
        logger.exception("背诵稿任务失败: job_id=%s", job_id)
        outcome = _fail(str(exc)[:500])
        return {"status": outcome["status"], "job_id": job_id}


from app.worker_scheduled import (
    _mark_job_complete,
    scheduled_compaction_task,
    scheduled_quality_audit_task,
    scheduled_submit_job_dispatch_task,
    scheduled_harness_turn_dispatch_task,
    scheduled_harness_event_publisher_task,
    scheduled_cluster_review_dispatch_task,
    scheduled_upload_queue_reconcile_task,
    scheduled_source_health_task,
    run_db_retention,
    scheduled_db_retention_task,
    scheduled_wal_checkpoint_task,
    scheduled_eval_expiry_task,
)


async def scheduled_worker_heartbeat_task(ctx):
    """Keep the ARQ worker liveness record fresh between restarts."""
    return await record_worker_heartbeat_async(
        "arq-worker",
        status="online",
        queue_name=os.environ.get("ARQ_QUEUE_NAME", "arq:default"),
        metadata={"pid": os.getpid()},
    )


scheduled_worker_heartbeat_task = observed_cron_task(scheduled_worker_heartbeat_task)
scheduled_compaction_task = observed_cron_task(scheduled_compaction_task)
scheduled_quality_audit_task = observed_cron_task(scheduled_quality_audit_task)
scheduled_submit_job_dispatch_task = observed_cron_task(scheduled_submit_job_dispatch_task)
scheduled_harness_turn_dispatch_task = observed_cron_task(scheduled_harness_turn_dispatch_task)
scheduled_harness_event_publisher_task = observed_cron_task(scheduled_harness_event_publisher_task)
scheduled_cluster_review_dispatch_task = observed_cron_task(scheduled_cluster_review_dispatch_task)
scheduled_upload_queue_reconcile_task = observed_cron_task(scheduled_upload_queue_reconcile_task)
scheduled_source_health_task = observed_cron_task(scheduled_source_health_task)
scheduled_db_retention_task = observed_cron_task(scheduled_db_retention_task)
scheduled_wal_checkpoint_task = observed_cron_task(scheduled_wal_checkpoint_task)
scheduled_eval_expiry_task = observed_cron_task(scheduled_eval_expiry_task)
process_chat_side_effects_task = observed_cron_task(process_chat_side_effects_task)


class WorkerSettings:
    functions = [
        interview_turn_task,
        cluster_batch_task,
        cluster_rebuild_task,
        interview_reprocess_task,
        interview_import_analysis_task,
        refresh_interview_distribution_task,
        process_chat_side_effects_task,
        build_master_bank_task,
        submit_import_task,
        credential_preflight_task,
        generate_answer_task,
        generate_recitation_task,
        quality_review_scan_task,
        scheduled_compaction_task,
        scheduled_quality_audit_task,
        scheduled_submit_job_dispatch_task,
        scheduled_harness_event_publisher_task,
        scheduled_cluster_review_dispatch_task,
        scheduled_upload_queue_reconcile_task,
        cluster_review_task,
        scheduled_source_health_task,
        scheduled_db_retention_task,
        scheduled_wal_checkpoint_task,
        scheduled_eval_expiry_task,
        recompute_embedding_task,
        scheduled_worker_heartbeat_task,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    job_timeout = 900  # 单任务最长 15 分钟（重建可能较慢）
    max_tries = 2  # 最多重试 2 次（重建任务重试成本高）
    keep_result = 3600  # 结果保留 1 小时
    queue_read_limit = 10  # 每次最多读取 10 个任务

    # 定时任务：每天凌晨 3 点运行 compaction，每周日 3:30 质量审查、3:40 来源健康检查
    cron_jobs = [
        cron(scheduled_compaction_task, hour={3}, minute={0}),
        # 降频(spec R1 / ADR 0046):派发/兜底调度不需要分钟级,降低对 SQLite
        # 单写锁的获取(原每分钟/每5分钟 → 每5分钟/每30分钟)。
        cron(scheduled_submit_job_dispatch_task, minute=set(range(0, 60, 5))),
        cron(scheduled_harness_turn_dispatch_task, minute=set(range(0, 60, 5))),
        cron(scheduled_harness_event_publisher_task, minute=set(range(0, 60))),
        # 质量评估从数据库 outbox 选取“当前版本未审核”的聚类，
        # 不再由固定 frequency 前 20 条的 cron 直接生成清单。
        cron(scheduled_cluster_review_dispatch_task, minute={0, 30}),
        # AC-007：残余队列对账（每分钟，幂等）
        cron(scheduled_upload_queue_reconcile_task, minute=set(range(0, 60))),
        cron(scheduled_source_health_task, hour={3}, minute={40}),
        cron(scheduled_db_retention_task, hour={4}, minute={0}),
        cron(scheduled_wal_checkpoint_task, hour={4}, minute={10}),
        cron(scheduled_eval_expiry_task, minute=set(range(0, 60))),
        cron(process_chat_side_effects_task, minute={0, 30}),
        cron(scheduled_worker_heartbeat_task, minute=set(range(0, 60, 5))),
    ]
