"""Worker 定时/保留侧 - 从 worker.py 机械抽取。

职责:Cron 调度任务(compaction/quality audit/source health/db retention/job dispatch)
与数据库保留清理(run_db_retention)。WorkerSettings 仍引用这些函数(经 worker.py re-export)。
"""
import time
import json
import asyncio
import logging
from datetime import datetime
from app.worker_enqueue import (
    enqueue_build_job,
    enqueue_cluster_batch_job,
    enqueue_cluster_rebuild_job,
    enqueue_cluster_review_task,
    enqueue_generate_answer_job,
    enqueue_generate_recitation_job,
    enqueue_interview_import_analysis_job,
    enqueue_interview_reprocess_job,
    enqueue_quality_review_scan_job,
    enqueue_recompute_embedding_job,
    enqueue_submit_import_job,
)

logger = logging.getLogger("interview-boss")


def _mark_job_complete(job_id: int, status: str, result: str = None, error: str = None):
    """标记任务完成/失败（jobs.error 列已废弃，错误只写 last_error）"""
    from app.db.connection import get_db_connection
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, result = ?, last_error = ?, completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, result, error, job_id)
        )
        conn.commit()


async def scheduled_compaction_task(ctx):
    """定时 compaction 任务：每天凌晨 3 点自动运行"""
    from app.services.pipeline import compact_singletons_in_db

    logger.info("[定时任务] 开始 compaction...")
    start_time = time.time()

    try:
        result = await compact_singletons_in_db()
        elapsed = time.time() - start_time

        # 记录统计日志
        log_entry = {
            "task": "scheduled_compaction",
            "timestamp": datetime.now().isoformat(),
            "result": result,
            "elapsed_seconds": round(elapsed, 2)
        }
        logger.info(f"[定时任务] Compaction 完成: {result}")

        # 写入数据库记录
        def _save_log():
            from app.db.connection import get_db_connection
            conn = get_db_connection()
            try:
                conn.execute(
                    "INSERT INTO task_logs (task_type, result, elapsed_seconds, created_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    ("compaction", json.dumps(result, ensure_ascii=False), elapsed)
                )
                conn.commit()
            except Exception as e:
                logger.warning(f"[定时任务] 保存日志失败: {e}")
                conn.rollback()

        await asyncio.to_thread(_save_log)

        return result
    except Exception as e:
        logger.exception(f"[定时任务] Compaction 失败: {e}")
        raise


async def scheduled_quality_audit_task(ctx):
    """定时聚类质量审查：抽查公共题库并生成管理员待审清单。

    误合并率超阈值（10%）时 triggered_cleanup=1，提示清洗（不自动执行）。
    清单生成与代表题检查都只处理公共题库，避免把个人题暴露给管理员。
    """
    from app.services.clustering_maintenance import (
        generate_quality_issues,
        generate_weak_representative_issues,
        run_quality_audit,
    )

    logger.info("[定时任务] 开始聚类质量审查...")
    try:
        audit_result = await run_quality_audit(user_id=None)
        issue_result = await generate_quality_issues(user_id=None, limit=20)
        weak_issue_result = await generate_weak_representative_issues(
            user_id=None, limit=20
        )
        result = {
            "audit": audit_result,
            "quality_issues": issue_result,
            "weak_representative_issues": weak_issue_result,
        }
        logger.info("[定时任务] 质量审查完成: %s", result)
        return result
    except Exception as e:
        logger.exception(f"[定时任务] 质量审查失败: {e}")
        raise


async def scheduled_submit_job_dispatch_task(ctx):
    """Recover and dispatch durable application jobs that were not delivered."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        ANSWER_GENERATION_JOB_TYPE,
        BUILD_MASTER_BANK_JOB_TYPE,
        CLUSTER_BATCH_JOB_TYPE,
        CLUSTER_REBUILD_JOB_TYPE,
        INTERVIEW_REPROCESS_JOB_TYPE,
        INTERVIEW_IMPORT_ANALYSIS_JOB_TYPE,
        DISPATCHABLE_JOB_TYPES,
        RECITATION_GENERATION_JOB_TYPE,
        RECOMPUTE_EMBEDDING_JOB_TYPE,
        SUBMIT_IMPORT_JOB_TYPE,
        QUALITY_REVIEW_SCAN_JOB_TYPE,
        claim_dispatch_batch,
        mark_dispatch_failed,
        mark_job_dispatched,
    )

    def _reserve(job_type):
        with get_db_connection() as conn:
            jobs = claim_dispatch_batch(
                conn, job_type=job_type, limit=10
            )
            conn.commit()
            return jobs

    enqueuers = {
        SUBMIT_IMPORT_JOB_TYPE: enqueue_submit_import_job,
        ANSWER_GENERATION_JOB_TYPE: enqueue_generate_answer_job,
        CLUSTER_BATCH_JOB_TYPE: enqueue_cluster_batch_job,
        CLUSTER_REBUILD_JOB_TYPE: enqueue_cluster_rebuild_job,
        INTERVIEW_REPROCESS_JOB_TYPE: enqueue_interview_reprocess_job,
        INTERVIEW_IMPORT_ANALYSIS_JOB_TYPE: enqueue_interview_import_analysis_job,
        BUILD_MASTER_BANK_JOB_TYPE: enqueue_build_job,
        RECOMPUTE_EMBEDDING_JOB_TYPE: enqueue_recompute_embedding_job,
        RECITATION_GENERATION_JOB_TYPE: enqueue_generate_recitation_job,
        QUALITY_REVIEW_SCAN_JOB_TYPE: enqueue_quality_review_scan_job,
    }
    dispatched = 0
    failed = 0
    reserved = 0
    per_type = {}
    for job_type in DISPATCHABLE_JOB_TYPES:
        jobs = await asyncio.to_thread(_reserve, job_type)
        type_dispatched = 0
        type_failed = 0
        reserved += len(jobs)
        for job_row in jobs:
            job_id = job_row["id"]
            try:
                arq_job = await enqueuers[job_type](job_id)
                arq_job_id = getattr(arq_job, "job_id", None)
                if not arq_job_id:
                    raise RuntimeError("ARQ 未返回 job_id")

                def _mark(job_id=job_id, arq_id=str(arq_job_id)):
                    with get_db_connection() as conn:
                        if not mark_job_dispatched(conn, job_id, arq_id):
                            raise RuntimeError(f"任务不可再投递: job_id={job_id}")
                        conn.commit()

                await asyncio.to_thread(_mark)
                dispatched += 1
                type_dispatched += 1
            except Exception as exc:
                failed += 1
                type_failed += 1
                logger.warning("[任务] ARQ 投递失败 type=%s job=%s: %s", job_type, job_id, exc)

                def _reset(job_id=job_id, error=str(exc)):
                    with get_db_connection() as conn:
                        mark_dispatch_failed(conn, job_id, error)
                        conn.commit()

                await asyncio.to_thread(_reset)
        per_type[job_type] = {
            "reserved": len(jobs),
            "dispatched": type_dispatched,
            "failed": type_failed,
        }

    result = {
        "reserved": reserved,
        "dispatched": dispatched,
        "failed": failed,
        "by_type": per_type,
    }
    logger.info("[上传任务] dispatcher 完成: %s", result)
    return result


async def scheduled_cluster_review_dispatch_task(ctx):
    """定时补偿：回填活跃聚类状态，并将持久 outbox 投递到 ARQ。

    回填是幂等的，因此进程长期停止后重新启动也能恢复遗漏的聚类；
    ARQ 只是执行器，任务是否存在、是否过期和是否完成都以 SQLite 为准。
    """
    from app.db.connection import get_db_connection
    from app.services.cluster_review_lifecycle import (
        backfill_cluster_review_state,
        claim_review_dispatch_batch,
        mark_review_task_dispatched,
    )

    def _prepare():
        conn = get_db_connection()
        report = backfill_cluster_review_state(conn, dry_run=False)
        tasks = claim_review_dispatch_batch(conn, limit=10)
        conn.commit()
        return report, tasks

    report, tasks = await asyncio.to_thread(_prepare)
    dispatched = 0
    failed = 0
    for task in tasks:
        try:
            job = await enqueue_cluster_review_task(task["id"])
            arq_job_id = getattr(job, "job_id", None)

            def _mark(task_id=task["id"], job_id=arq_job_id):
                conn = get_db_connection()
                mark_review_task_dispatched(conn, task_id, job_id)
                conn.commit()

            await asyncio.to_thread(_mark)
            if arq_job_id:
                dispatched += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            logger.warning("[聚类质量] ARQ 投递失败 task=%s: %s", task["id"], exc)

            def _reset(task_id=task["id"], error=str(exc)):
                conn = get_db_connection()
                mark_review_task_dispatched(conn, task_id, None)
                conn.execute(
                    "UPDATE cluster_review_tasks SET last_error = ? WHERE id = ?",
                    (error[:500], task_id),
                )
                conn.commit()

            await asyncio.to_thread(_reset)

    result = {
        "backfill": report,
        "reserved": len(tasks),
        "dispatched": dispatched,
        "failed": failed,
    }
    logger.info("[聚类质量] dispatcher 完成: %s", result)
    return result


async def scheduled_source_health_task(ctx):
    """定时来源健康检查：每周日凌晨 3:40 扫同签名重复面经 / internal:// 增长 / JSON 双写不一致。

    只读检查 + 更新 internal 基线文件，发现问题只记日志告警，
    不自动修改数据（修复走 backend/scripts/fix_source_consistency.py）。
    """
    import os

    from app.services.source_health import run_source_health_checks

    baseline = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "data",
        "source_health_baseline.json",
    )
    logger.info("[定时任务] 开始来源健康检查...")
    try:
        report = await asyncio.to_thread(
            run_source_health_checks, None, os.path.normpath(baseline)
        )
        if report["ok"]:
            logger.info("[定时任务] 来源健康检查通过")
        else:
            logger.warning(
                "[定时任务] 来源健康检查发现问题: 同签名重复 "
                "interview=%d 组/jd=%d 组, internal 新增=%d, "
                "JSON 双写不一致=%d 处",
                len(report["duplicate_signature_groups"]["interview"]),
                len(report["duplicate_signature_groups"]["jd"]),
                len(report["internal"]["new_urls"]),
                len(report["dual_write_mismatches"]),
            )
        return report
    except Exception as e:
        logger.exception(f"[定时任务] 来源健康检查失败: {e}")
        raise


def run_db_retention(conn) -> dict:
    """按龄清理过期/完成数据（保守保留期，保护仍被引用的行）。

    - email_verification_codes：已过期或 used 超 30 天（expires_at 为 ISO 文本，
      需 datetime() 归一后再与 SQLite 时间比较）
    - analysis_queue：done/failed 超 30 天
    - login_failures：未锁定且 30 天无更新
    - jobs：completed/failed 超 90 天且无子任务（parent_job_id 保护父子血缘）
    """
    deleted = {}
    cur = conn.execute(
        "DELETE FROM email_verification_codes "
        "WHERE datetime(expires_at) < datetime('now') "
        "OR (used = 1 AND created_at < datetime('now', '-30 days'))"
    )
    deleted["email_verification_codes"] = cur.rowcount
    cur = conn.execute(
        "DELETE FROM analysis_queue WHERE status IN ('done', 'failed') "
        "AND created_at < datetime('now', '-30 days')"
    )
    deleted["analysis_queue"] = cur.rowcount
    cur = conn.execute(
        "DELETE FROM login_failures WHERE locked_until = '' "
        "AND updated_at < datetime('now', '-30 days')"
    )
    deleted["login_failures"] = cur.rowcount
    cur = conn.execute(
        "DELETE FROM jobs WHERE status IN ('completed', 'failed') "
        "AND completed_at < datetime('now', '-90 days') "
        "AND NOT EXISTS (SELECT 1 FROM jobs c WHERE c.parent_job_id = jobs.id)"
    )
    deleted["jobs"] = cur.rowcount
    conn.commit()
    logger.info("[DB 保留期清理] %s", deleted)
    return deleted


async def scheduled_db_retention_task(ctx):
    """每日凌晨 4:00 清理过期验证码 / 完成队列 / 失败登录记录 / 陈旧任务。"""
    from app.db.connection import get_db_connection

    logger.info("[定时任务] 开始 DB 保留期清理...")
    try:
        return await asyncio.to_thread(run_db_retention, get_db_connection())
    except Exception as e:
        logger.exception(f"[定时任务] DB 保留期清理失败: {e}")
        raise


