"""Cluster and interview-processing ARQ task handlers."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from app.services.worker_observability import record_worker_heartbeat_async

logger = logging.getLogger("interview-boss")


async def maybe_inject_e2e_public_failure(ctx, batch, *, root_import_id):
    """Fail one marked public item in the disposable AC-029 stack.

    The Redis NX marker survives an ARQ worker restart. Failed contribution
    queue rows are held out of reconciliation until the explicit retry API
    moves their item back to ``queued``.
    """
    if os.environ.get("E2E_STUB_PROVIDER") != "1" or not root_import_id:
        return
    redis = ctx.get("redis") if isinstance(ctx, dict) else None
    if redis is None:
        return
    for item in batch or []:
        if (
            item.get("owner_id") is not None
            or not item.get("contribution_request_id")
            or "AC029_FAIL_PUBLIC_ORDINAL_" not in str(item.get("question") or "")
        ):
            continue
        detail_id = item.get("qd_id")
        if detail_id is None:
            continue
        key = f"e2e:ac029:public-failure:{root_import_id}:{int(detail_id)}"
        armed = await redis.set(key, "injected", ex=86400, nx=True)
        if armed:
            raise RuntimeError(f"AC029_PUBLIC_ITEM_FAILURE detail_id={int(detail_id)}")


async def _schedule_cluster_continuation(root_import_id, actor_id):
    from app.services.pipeline import _run_cluster_batch_in_background

    if root_import_id:
        await _run_cluster_batch_in_background(
            user_id=actor_id,
            root_import_id=str(root_import_id),
        )
        return
    def _rootless_continuation_scope():
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            has_contribution = conn.execute(
                "SELECT 1 FROM analysis_queue aq "
                "JOIN interview i ON i.id = aq.interview_id "
                "JOIN questions_detail qd ON qd.id = aq.question_detail_id "
                "JOIN public_contribution_items pci "
                "ON pci.request_id = aq.contribution_request_id "
                "AND pci.public_detail_id = aq.question_detail_id "
                "WHERE aq.status = 'pending' AND aq.root_import_id IS NULL "
                "AND aq.owner_id IS NULL AND aq.contribution_request_id IS NOT NULL "
                "AND pci.status IN ('queued', 'approved_for_processing', 'processing') "
                "AND i.status = 'approved' AND i.deleted_at IS NULL "
                "AND qd.deleted_at IS NULL LIMIT 1"
            ).fetchone()
            if has_contribution:
                return "public_contribution"

            # Rebuilds also consume ordinary public queue rows which do not
            # carry a contribution_request_id. Keep those moving through the
            # generic rootless batch path after a rebuild releases the queue.
            has_regular_public_row = conn.execute(
                "SELECT 1 FROM analysis_queue aq "
                "JOIN interview i ON i.id = aq.interview_id "
                "JOIN questions_detail qd ON qd.id = aq.question_detail_id "
                "WHERE aq.status = 'pending' AND aq.root_import_id IS NULL "
                "AND aq.owner_id IS NULL AND aq.contribution_request_id IS NULL "
                "AND i.owner_id IS NULL AND i.status = 'approved' "
                "AND i.deleted_at IS NULL AND qd.deleted_at IS NULL LIMIT 1"
            ).fetchone()
            if has_regular_public_row:
                return "generic"

            # Legacy personal rows can also be rootless. Rebuild only drains
            # the public owner bucket, so release eligible private rows through
            # the generic worker once the rebuild no longer blocks dispatch.
            has_personal_row = conn.execute(
                "SELECT 1 FROM analysis_queue aq "
                "JOIN interview i ON i.id = aq.interview_id "
                "JOIN questions_detail qd ON qd.id = aq.question_detail_id "
                "WHERE aq.status = 'pending' AND aq.root_import_id IS NULL "
                "AND aq.owner_id IS NOT NULL AND i.owner_id = aq.owner_id "
                "AND i.status = 'approved' AND i.deleted_at IS NULL "
                "AND qd.deleted_at IS NULL LIMIT 1"
            ).fetchone()
            return "generic" if has_personal_row else None

    continuation_scope = await asyncio.to_thread(_rootless_continuation_scope)
    if continuation_scope == "public_contribution":
        await _run_cluster_batch_in_background(
            user_id=actor_id,
            queue_scope="public_contribution",
        )
    elif continuation_scope == "generic":
        await _run_cluster_batch_in_background(user_id=actor_id)

async def recompute_embedding_task(ctx, job_id: int):
    """ARQ: 全量 embedding 重算（模型更换后自动触发）。"""
    from app.services.embedding_recompute import run_recompute

    await run_recompute(job_id)


async def cluster_review_task(ctx, task_id: str):
    """ARQ worker：执行一个带 cluster_version 校验的 AI 质量评估。"""
    from app.services.cluster_review_lifecycle import run_cluster_review_task

    return await run_cluster_review_task(task_id)


async def quality_review_scan_task(ctx, job_id: int):
    """ARQ worker：执行管理员触发的误合并 + 漏合并全量扫描。"""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        QUALITY_REVIEW_SCAN_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
        touch_job,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=QUALITY_REVIEW_SCAN_JOB_TYPE,
            )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            conn.commit()
            return dict(task), json.loads(payload_row["payload"]) if payload_row else {}

    claimed = await asyncio.to_thread(_claim_and_load)
    if claimed is None:
        logger.info("聚合质量扫描已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    task, payload = claimed

    def _progress(current: int, message: str):
        with get_db_connection() as conn:
            touch_job(
                conn,
                job_id,
                worker_id,
                progress_current=current,
                progress_message=message,
            )
            conn.commit()

    def _complete(result):
        with get_db_connection() as conn:
            complete_job(
                conn,
                job_id,
                worker_id,
                result=json.dumps(result, ensure_ascii=False),
            )
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    try:
        from app.services.clustering_maintenance import generate_quality_issues
        from app.services.unmerged_quality import generate_unmerged_quality_issues

        await asyncio.to_thread(_progress, 0, "正在分析聚类内误合并")
        mismerge = await generate_quality_issues(
            user_id=payload.get("user_id"),
            limit=payload.get("mismerge_limit", 1000),
            review_task_id=str(job_id),
            trigger_reason="manual_full_scan",
        )
        await asyncio.to_thread(_progress, 1, "正在分析孤岛题漏合并")
        unmerged = await generate_unmerged_quality_issues(
            user_id=payload.get("user_id"),
            limit=payload.get("singleton_limit", 1000),
            candidate_limit=payload.get("candidate_limit", 3),
            similarity_threshold=payload.get("similarity_threshold", 0.30),
            review_task_id=str(job_id),
            trigger_reason="manual_full_scan",
        )
        from app.services.cluster_review_lifecycle import sync_review_state_after_scan

        def _sync_review_state():
            with get_db_connection() as conn:
                state = sync_review_state_after_scan(
                    conn,
                    (mismerge.get("scanned_cluster_ids") or [])
                    + (unmerged.get("scanned_singleton_ids") or []),
                    trigger_reason="manual_full_scan",
                )
                conn.commit()
                return state

        state = await asyncio.to_thread(_sync_review_state)
        result = {
            "status": "completed",
            "mismerge": mismerge,
            "unmerged": unmerged,
            "review_state": state,
        }
        _complete(result)
        return {"job_id": job_id, **result}
    except Exception as exc:
        outcome = _fail(str(exc)[:500])
        logger.exception("聚合质量扫描失败: job_id=%s", job_id)
        return {"status": outcome["status"], "job_id": job_id}


async def startup(ctx):
    """Worker 启动时初始化"""
    from app.db.connection import init_db
    from app.core.config import _reload_from_db
    from app.services.embedding_service import reload_embedding_config

    init_db()
    await record_worker_heartbeat_async(
        "arq-worker",
        status="online",
        queue_name=os.environ.get("ARQ_QUEUE_NAME", "arq:default"),
        metadata={"pid": os.getpid()},
    )
    _reload_from_db()
    reload_embedding_config()
    try:
        from redis.asyncio import from_url
        from app.core.cache import set_cache_client
        from app.core.config import REDIS_CACHE_URL

        cache = from_url(REDIS_CACHE_URL, decode_responses=True)
        await cache.ping()
        set_cache_client(cache)
        ctx["redis_cache"] = cache
    except Exception as exc:
        logger.warning("ARQ Worker Redis cache 初始化失败: %s", exc)
    logger.info("ARQ Worker 已启动")


async def shutdown(ctx):
    """Worker 关闭时清理"""
    await record_worker_heartbeat_async(
        "arq-worker",
        status="offline",
        queue_name=os.environ.get("ARQ_QUEUE_NAME", "arq:default"),
        metadata={"pid": os.getpid()},
    )
    from app.core.cache import close_cache_client

    await close_cache_client()
    logger.info("ARQ Worker 已关闭")


async def _schedule_cluster_answer_jobs(
    parent_job_id: int,
    question_bank_ids: list[int],
    *,
    owner_id: int | None,
    actor_id: int | None,
    job_fence: tuple[int, int] | None = None,
) -> list[int]:
    """Create durable answer jobs with the final question-bank scope.

    The clustering worker may be invoked by an admin on behalf of a user.
    ``owner_id`` is therefore the only source of truth for model/search scope:
    public rows use the global/public configuration, personal rows use the
    owning user's configuration.
    """
    ids = sorted({int(item) for item in (question_bank_ids or [])})
    if not ids:
        return []
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import create_answer_generation_jobs

    llm_scope = "global" if owner_id is None else "user"
    search_scope = "public" if owner_id is None else "user"
    answer_user_id = owner_id if owner_id is not None else actor_id

    def _create():
        placeholders = ",".join("?" * len(ids))
        with get_db_connection() as conn:
            owns_transaction = not conn.in_transaction
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            if job_fence is not None:
                from app.services.job_lifecycle import assert_job_fence

                assert_job_fence(conn, int(job_fence[0]), int(job_fence[1]))
            rows = conn.execute(
                "SELECT id, question FROM question_bank "
                f"WHERE id IN ({placeholders}) AND deleted_at IS NULL "
                "AND question IS NOT NULL AND question != '' "
                "AND owner_id IS ? AND (ai_answer IS NULL OR ai_answer = '')",
                [*ids, owner_id],
            ).fetchall()
            tasks = [(int(row["id"]), row["question"]) for row in rows]
            job_ids = create_answer_generation_jobs(
                conn,
                parent_job_id,
                tasks,
                answer_user_id,
                llm_scope=llm_scope,
                search_scope=search_scope,
            )
            if owns_transaction:
                conn.commit()
            return job_ids

    try:
        return await asyncio.to_thread(_create)
    except Exception:
        # Answer enrichment is secondary to the durable clustering result.
        # The answer job dispatcher can be retried independently; never roll
        # back a successfully written public/personal cluster here.
        logger.exception(
            "聚类完成但答案任务创建失败: parent_job_id=%s, owner_id=%s",
            parent_job_id,
            owner_id,
        )
        return []


async def _cluster_preflight_ready(job_id: int) -> bool:
    """Do not claim root-bound clustering until its exact model config is probed."""

    from app.db.connection import get_db_connection

    def _check():
        import json

        from app.services.credential_preflight import create_credential_preflight_job
        from app.services.job_lifecycle import (
            defer_job_for_upload_preflight,
            get_successful_upload_preflight,
        )
        from app.services.upload_credentials import resolve_upload_credentials

        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT j.root_import_id, j.upload_attempt_id, r.requester_id, "
                "r.status AS root_status, r.policy_json, p.payload AS job_payload "
                "FROM jobs j LEFT JOIN upload_imports r ON r.id = j.root_import_id "
                "LEFT JOIN job_payloads p ON p.job_id = j.id WHERE j.id = ?",
                (job_id,),
            ).fetchone()
            if row is None or not row["root_import_id"]:
                return True
            try:
                payload = json.loads(row["job_payload"] or "{}")
            except (json.JSONDecodeError, TypeError):
                payload = {}
            try:
                policy = json.loads(row["policy_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                policy = {}
            credential_scope = payload.get("credential_scope")
            user_id = payload.get("user_id")
            if credential_scope not in ("user", "global"):
                queue_row = conn.execute(
                    "SELECT owner_id, contribution_request_id FROM analysis_queue "
                    "WHERE root_import_id = ? AND status = 'pending' ORDER BY id LIMIT 1",
                    (row["root_import_id"],),
                ).fetchone()
                if queue_row and queue_row["owner_id"] is not None:
                    credential_scope = "user"
                    user_id = int(queue_row["owner_id"])
                elif queue_row and queue_row["contribution_request_id"] is not None:
                    credential_scope = policy.get("post_approval_credential_scope") or "global"
                    user_id = int(row["requester_id"]) if credential_scope == "user" else None
                else:
                    credential_scope = policy.get("credential_scope") or "global"
                    user_id = int(row["requester_id"]) if credential_scope == "user" else None

            preflight = get_successful_upload_preflight(
                conn,
                root_import_id=str(row["root_import_id"]),
                attempt_id=row["upload_attempt_id"],
                credential_scope=credential_scope,
            )
            if preflight:
                try:
                    current = resolve_upload_credentials(
                        credential_scope=credential_scope,
                        user_id=int(user_id) if user_id is not None and credential_scope == "user" else None,
                        stage="resolve",
                    )
                    result = json.loads(preflight["result_json"] or "{}")
                except Exception:
                    current = None
                    result = {}
                if current and result.get("config_fingerprint") == current.config_fingerprint:
                    return True

            create_credential_preflight_job(
                conn,
                root_import_id=str(row["root_import_id"]),
                requester_id=int(row["requester_id"]),
                credential_scope=credential_scope,
                user_id=int(user_id) if user_id is not None and credential_scope == "user" else None,
                attempt_id=row["upload_attempt_id"],
            )
            defer_job_for_upload_preflight(conn, job_id)
            conn.commit()
            return False

    return await asyncio.to_thread(_check)


async def cluster_batch_task(ctx, job_id: int):
    """ARQ task: claim and process one database-owned clustering batch."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        CLUSTER_BATCH_JOB_TYPE,
        MAX_JOB_ATTEMPTS,
        JobFenceError,
        claim_job,
        claim_job_with_generation,
        complete_job,
        default_worker_id,
        fail_job,
        heartbeat_job,
    )
    from app.services.upload_scope_leases import (
        UploadScopeLeaseError,
        acquire_upload_scope_lease,
        heartbeat_upload_scope_lease,
        release_upload_scope_lease,
    )
    from app.services.pipeline import (
        BATCH_SIZE,
        cluster_batch,
        dequeue_batch,
        mark_batch_done,
        mark_batch_failed,
    )

    worker_id = default_worker_id()

    if not await _cluster_preflight_ready(job_id):
        logger.info("聚类任务等待匹配 scope 的模型预检: job_id=%s", job_id)
        return {"status": "waiting_preflight", "job_id": job_id}

    def _claim_and_load():
        with get_db_connection() as conn:
            candidate = conn.execute(
                "SELECT root_import_id FROM jobs WHERE id = ? AND job_type = ?",
                (job_id, CLUSTER_BATCH_JOB_TYPE),
            ).fetchone()
            if candidate and candidate["root_import_id"]:
                task = claim_job_with_generation(
                    conn,
                    job_id,
                    worker_id=worker_id,
                    job_type=CLUSTER_BATCH_JOB_TYPE,
                    lease_seconds=120,
                )
            else:
                task = claim_job(
                    conn,
                    job_id,
                    worker_id,
                    job_type=CLUSTER_BATCH_JOB_TYPE,
                )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            conn.commit()
            payload = json.loads(payload_row["payload"]) if payload_row else {}
            return dict(task), payload

    claimed = await asyncio.to_thread(_claim_and_load)
    if claimed is None:
        logger.info("聚类攒批任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}
    task, payload = claimed
    root_import_id = task.get("root_import_id")
    job_fence = (job_id, int(task["lease_generation"])) if root_import_id else None

    def _complete(result):
        with get_db_connection() as conn:
            completed = complete_job(
                conn,
                job_id,
                worker_id,
                result=json.dumps(result, ensure_ascii=False),
                lease_generation=job_fence[1] if job_fence else None,
            )
            conn.commit()
            return completed

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(
                conn,
                job_id,
                worker_id,
                error,
                lease_generation=job_fence[1] if job_fence else None,
            )
            conn.commit()
            return outcome

    scope_lease = None
    scope_fence = None
    heartbeat_stop = asyncio.Event()
    heartbeat_lost = asyncio.Event()
    lease_heartbeat_task = None
    batch = []
    try:
        if root_import_id:
            def _load_scope_key():
                with get_db_connection() as conn:
                    row = conn.execute(
                        "SELECT r.position_id, r.position_name, aq.owner_id, i.job_position "
                        "FROM upload_imports r LEFT JOIN analysis_queue aq "
                        "ON aq.root_import_id = r.id AND aq.status = 'pending' "
                        "LEFT JOIN interview i ON i.id = aq.interview_id "
                        "WHERE r.id = ? ORDER BY aq.id LIMIT 1",
                        (root_import_id,),
                    ).fetchone()
                    if row is None or (
                        row["owner_id"] is None
                        and row["position_id"] is None
                        and not row["job_position"]
                        and not row["position_name"]
                    ):
                        return None
                    position_id = row["position_id"]
                    position_name = row["job_position"] or row["position_name"] or "unknown"
                    if position_id is None:
                        position = conn.execute(
                            "SELECT id FROM job_positions WHERE name = ? LIMIT 1",
                            (position_name,),
                        ).fetchone()
                        position_id = position["id"] if position else None
                    position_key = (
                        str(position_id)
                        if position_id is not None
                        else f"name:{position_name}"
                    )
                    suffix = (
                        "public"
                        if row["owner_id"] is None
                        else f"user:{int(row['owner_id'])}"
                    )
                    return f"{position_key}:{suffix}"

            scope_key = await asyncio.to_thread(_load_scope_key)
            if scope_key:
                holder_token = f"{worker_id}:job:{job_id}:generation:{job_fence[1]}"

                def _try_acquire_scope():
                    with get_db_connection() as conn:
                        lease = acquire_upload_scope_lease(
                            conn,
                            scope_key,
                            holder_token=holder_token,
                            lease_seconds=120,
                        )
                        conn.commit()
                        return lease

                while scope_lease is None:
                    scope_lease = await asyncio.to_thread(_try_acquire_scope)
                    if scope_lease is None:
                        def _keep_job_alive():
                            with get_db_connection() as conn:
                                alive = heartbeat_job(
                                    conn, job_id, job_fence[1], lease_seconds=120
                                )
                                conn.commit()
                                return alive

                        if not await asyncio.to_thread(_keep_job_alive):
                            raise JobFenceError(
                                "聚类任务等待scope lease期间租约失效",
                                job_id=job_id,
                                generation=job_fence[1],
                            )
                        await asyncio.sleep(1)

                scope_fence = (
                    scope_key,
                    holder_token,
                    int(scope_lease["generation"]),
                )

                def _heartbeat_owned():
                    with get_db_connection() as conn:
                        job_ok = heartbeat_job(
                            conn, job_id, job_fence[1], lease_seconds=120
                        )
                        scope_ok = heartbeat_upload_scope_lease(
                            conn,
                            scope_key,
                            holder_token=holder_token,
                            generation=scope_fence[2],
                            lease_seconds=120,
                        )
                        conn.commit()
                        return bool(job_ok and scope_ok)

                async def _renew_leases():
                    while not heartbeat_stop.is_set():
                        try:
                            await asyncio.wait_for(heartbeat_stop.wait(), timeout=30)
                            continue
                        except asyncio.TimeoutError:
                            pass
                        if not await asyncio.to_thread(_heartbeat_owned):
                            heartbeat_lost.set()
                            return

                lease_heartbeat_task = asyncio.create_task(_renew_leases())

        if root_import_id:
            batch = dequeue_batch(
                BATCH_SIZE,
                owner_id=payload.get("owner_id"),
                root_import_id=root_import_id,
                job_fence=job_fence,
                scope_fence=scope_fence,
            )
        else:
            if payload.get("queue_scope") == "public_contribution":
                batch = dequeue_batch(
                    BATCH_SIZE,
                    owner_id=None,
                    contribution_only=True,
                )
            else:
                batch = dequeue_batch(BATCH_SIZE)
        if not batch:
            result = {"status": "empty", "new_count": 0}
            if not _complete(result) and job_fence:
                raise JobFenceError(
                    "聚类任务租约已失效，不能完成任务",
                    job_id=job_id,
                    generation=job_fence[1],
                )
            await _schedule_cluster_continuation(
                root_import_id,
                payload.get("actor_id") or payload.get("user_id"),
            )
            return {"job_id": job_id, **result}

        await maybe_inject_e2e_public_failure(
            ctx, batch, root_import_id=root_import_id
        )

        batch_root_import_id = batch[0].get("root_import_id")
        if batch_root_import_id:
            from app.services.upload_llm_accounting import upload_llm_context

            owner_id = batch[0].get("owner_id")

            def _load_upload_scope():
                with get_db_connection() as conn:
                    root = conn.execute(
                        "SELECT requester_id, target_intent, policy_json "
                        "FROM upload_imports WHERE id = ?",
                        (batch_root_import_id,),
                    ).fetchone()
                    if not root:
                        raise ValueError("聚类队列引用的上传根任务不存在")
                    try:
                        policy = json.loads(root["policy_json"] or "{}")
                    except (json.JSONDecodeError, TypeError):
                        policy = {}
                    if owner_id is not None:
                        return "user", int(owner_id)
                    scope = policy.get("post_approval_credential_scope")
                    if not scope:
                        scope = (
                            policy.get("credential_scope")
                            if root["target_intent"] == "share"
                            else "global"
                        )
                    return scope or "global", int(root["requester_id"])

            credential_scope, scope_user_id = await asyncio.to_thread(
                _load_upload_scope
            )
            with upload_llm_context(
                root_import_id=str(batch_root_import_id),
                stage="resolve",
                unit_key="queue-batch",
                credential_scope=credential_scope,
                user_id=scope_user_id,
            ):
                cluster_result = await cluster_batch(
                    batch,
                    user_id=payload.get("user_id"),
                    return_new_ids=True,
                    job_fence=job_fence,
                    scope_fence=scope_fence,
                )
        else:
            cluster_result = await cluster_batch(
                batch,
                user_id=payload.get("user_id"),
                return_new_ids=True,
                job_fence=job_fence,
                scope_fence=scope_fence,
            )
        if heartbeat_lost.is_set():
            raise JobFenceError(
                "聚类期间任务或scope lease心跳失败",
                job_id=job_id,
                generation=job_fence[1] if job_fence else None,
            )
        if isinstance(cluster_result, dict):
            new_count = int(cluster_result.get("count", 0))
            new_qb_ids = cluster_result.get("ids", [])
        else:  # compatibility with lightweight test/legacy implementations
            new_count = int(cluster_result or 0)
            new_qb_ids = []
        queue_ids = [item["queue_id"] for item in batch]
        mark_batch_done(
            queue_ids, job_fence=job_fence, scope_fence=scope_fence
        )
        from app.services.public_contributions import mark_public_contribution_queue_done

        with get_db_connection() as connection:
            mark_public_contribution_queue_done(
                connection,
                queue_ids,
                job_fence=job_fence,
                scope_fence=scope_fence,
            )
        await _schedule_cluster_answer_jobs(
            job_id,
            new_qb_ids,
            owner_id=batch[0].get("owner_id"),
            actor_id=payload.get("user_id"),
            job_fence=job_fence,
        )
        result = {"status": "done", "new_count": new_count, "processed": len(batch)}
        if not _complete(result) and job_fence:
            raise JobFenceError(
                "聚类任务租约已失效，不能完成任务",
                job_id=job_id,
                generation=job_fence[1],
            )
        await _schedule_cluster_continuation(
            root_import_id,
            payload.get("actor_id") or payload.get("user_id"),
        )
        return {"job_id": job_id, **result}
    except Exception as exc:
        if isinstance(exc, (JobFenceError, UploadScopeLeaseError)):
            logger.info("聚类任务失去generation/scope fence: job_id=%s", job_id)
            return {"status": "stale", "job_id": job_id}
        queue_ids = [item["queue_id"] for item in batch]
        try:
            mark_batch_failed(
                queue_ids,
                job_fence=job_fence,
                scope_fence=scope_fence,
                terminal=(
                    root_import_id is None
                    and int(task.get("attempts") or 0) >= MAX_JOB_ATTEMPTS
                ),
            )
            from app.services.public_contributions import mark_public_contribution_queue_failed

            with get_db_connection() as connection:
                mark_public_contribution_queue_failed(
                    connection,
                    queue_ids,
                    str(exc),
                    job_fence=job_fence,
                    scope_fence=scope_fence,
                )
        except (JobFenceError, UploadScopeLeaseError):
            logger.info("聚类失败处理时generation/scope fence已失效: job_id=%s", job_id)
            return {"status": "stale", "job_id": job_id}
        outcome = _fail(str(exc)[:500])
        logger.exception("聚类攒批任务失败: job_id=%s", job_id)
        if root_import_id:
            should_continue = any(
                item.get("contribution_request_id") for item in batch
            )
        else:
            # Retryable failures stay on this durable job and honor its backoff.
            # Only a terminal failure releases the rootless queue; its failed
            # rows have already been marked failed, so continue other work only.
            should_continue = outcome.get("status") == "failed"
        if should_continue:
            await _schedule_cluster_continuation(
                root_import_id,
                payload.get("actor_id") or payload.get("user_id"),
            )
        return {"status": outcome["status"], "job_id": job_id}
    finally:
        heartbeat_stop.set()
        if lease_heartbeat_task is not None:
            lease_heartbeat_task.cancel()
            await asyncio.gather(lease_heartbeat_task, return_exceptions=True)
        if scope_fence:
            def _release_scope():
                with get_db_connection() as conn:
                    released = release_upload_scope_lease(
                        conn,
                        scope_fence[0],
                        holder_token=scope_fence[1],
                        generation=scope_fence[2],
                    )
                    conn.commit()
                    return released

            await asyncio.to_thread(_release_scope)


async def cluster_rebuild_task(ctx, job_id: int):
    """ARQ task: durably process every queued question for a full rebuild."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        CLUSTER_REBUILD_JOB_TYPE,
        MAX_JOB_ATTEMPTS,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
        touch_job,
    )
    from app.services.pipeline import (
        BATCH_SIZE,
        cluster_batch,
        dequeue_batch,
        mark_batch_done,
        mark_batch_failed,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=CLUSTER_REBUILD_JOB_TYPE,
            )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            conn.commit()
            payload = json.loads(payload_row["payload"]) if payload_row else {}
            return (
                payload,
                int(task["progress_total"] or 1),
                int(task["attempts"] or 0),
            )

    claimed = await asyncio.to_thread(_claim_and_load)
    if claimed is None:
        logger.info("全量聚类重建任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    payload, progress_total, attempts = claimed
    processed = 0
    total_new = 0
    total_batches = 0
    batch = []

    def _touch(message: str):
        with get_db_connection() as conn:
            touch_job(
                conn,
                job_id,
                worker_id,
                progress_current=processed,
                progress_total=max(progress_total, processed, 1),
                progress_message=message,
            )
            conn.commit()

    def _complete(result):
        with get_db_connection() as conn:
            completed = complete_job(
                conn,
                job_id,
                worker_id,
                result=json.dumps(result, ensure_ascii=False),
            )
            conn.commit()
            return completed

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    try:
        while True:
            batch = dequeue_batch(BATCH_SIZE, owner_id=None)
            if not batch:
                result = {
                    "status": "done",
                    "batches": total_batches,
                    "new_qb_count": total_new,
                    "processed": processed,
                }
                completed = _complete(result)
                if completed:
                    # Approval/retry can commit a contribution after the last
                    # empty dequeue but before this job completes. Its inline
                    # scheduler sees this rebuild as active and defers. Recheck
                    # after completion so that deferred public work gets a job.
                    await _schedule_cluster_continuation(
                        None, payload.get("user_id")
                    )
                return {"job_id": job_id, **result}

            total_batches += 1
            cluster_result = await cluster_batch(
                batch,
                user_id=payload.get("user_id"),
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
                actor_id=payload.get("user_id"),
            )
            processed += len(batch)
            total_new += new_count
            _touch(f"已完成 {processed} 道题，处理 {total_batches} 个批次")
            await asyncio.sleep(0.5)
    except Exception as exc:
        if batch:
            mark_batch_failed(
                [item["queue_id"] for item in batch],
                terminal=attempts >= MAX_JOB_ATTEMPTS,
            )
            from app.services.public_contributions import mark_public_contribution_queue_failed

            with get_db_connection() as connection:
                mark_public_contribution_queue_failed(
                    connection, [item["queue_id"] for item in batch], str(exc)
                )
        outcome = _fail(str(exc)[:500])
        if outcome.get("status") == "failed":
            # A terminal failure releases the rootless queue. Approval/retry
            # may have deferred its batch while this rebuild was active.
            await _schedule_cluster_continuation(
                None, payload.get("user_id")
            )
        logger.exception("全量聚类重建任务失败: job_id=%s", job_id)
        return {"status": outcome["status"], "job_id": job_id}


async def interview_reprocess_task(ctx, job_id: int):
    """ARQ task: tag one interview, enqueue its questions and open clustering."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        INTERVIEW_REPROCESS_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
        touch_job,
    )
    from app.services.pipeline import (
        _run_cluster_batch_in_background,
        enqueue_questions,
        tag_interview,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=INTERVIEW_REPROCESS_JOB_TYPE,
            )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            payload = json.loads(payload_row["payload"]) if payload_row else {}
            interview = conn.execute(
                "SELECT id, url, company, round, questions_list, job_position "
                "FROM interview WHERE id = ?",
                (payload.get("interview_id"),),
            ).fetchone()
            conn.commit()
            return payload, dict(interview) if interview else None

    claimed = await asyncio.to_thread(_claim_and_load)
    if claimed is None:
        logger.info("面经重分析任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    payload, interview = claimed

    def _set_analysis_status(status: str):
        with get_db_connection() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(interview)").fetchall()}
            if "analysis_status" in columns:
                conn.execute(
                    "UPDATE interview SET analysis_status = ?, "
                    "analysis_updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status, payload.get("interview_id")),
                )
                conn.commit()

    def _touch(message: str):
        with get_db_connection() as conn:
            touch_job(
                conn,
                job_id,
                worker_id,
                progress_current=0,
                progress_total=1,
                progress_message=message,
            )
            conn.commit()

    def _complete(result):
        with get_db_connection() as conn:
            complete_job(
                conn,
                job_id,
                worker_id,
                result=json.dumps(result, ensure_ascii=False),
            )
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    try:
        if not interview:
            raise ValueError("未找到待重分析的面经")
        questions_list = str(interview.get("questions_list") or "")
        if not questions_list.strip():
            raise ValueError("该面经没有可分析的题目清单")

        _set_analysis_status("processing")
        _touch("正在调用 AI 标注题目")
        user_id = payload.get("user_id")
        tagged_rows = await tag_interview(
            interview.get("url") or f"internal://{interview['id']}",
            interview.get("company") or "未提供",
            interview.get("round") or "未提供",
            questions_list,
            job_position=interview.get("job_position") or "",
            user_id=user_id,
            interview_id=interview["id"],
        )
        enqueue_questions(interview["id"])
        scheduled = await _run_cluster_batch_in_background(user_id=user_id)

        details = [
            {
                "question": row[3],
                "cat1": row[4],
                "cat2": row[5],
                "tags": row[6],
                "difficulty": row[7],
            }
            for row in tagged_rows
        ]
        result = {
            "interview_id": interview["id"],
            "tagged_count": len(tagged_rows),
            "details": details,
            "cluster_pending": True,
            "cluster_scheduled": scheduled,
        }
        _set_analysis_status("completed")
        _complete(result)
        return {"job_id": job_id, "status": "completed", **result}
    except Exception as exc:
        _set_analysis_status("failed")
        outcome = _fail(str(exc)[:500])
        logger.exception("面经重分析任务失败: job_id=%s", job_id)
        return {"job_id": job_id, "status": outcome["status"]}


async def refresh_interview_distribution_task(ctx, scope: str, job_position: str):
    """Recompute one distribution hierarchy after its facts were marked stale."""
    from app.db.connection import get_db_connection
    from app.services.interview_distribution import refresh_distribution_scope

    conn = get_db_connection()
    try:
        result = refresh_distribution_scope(conn, scope, job_position)
        conn.commit()
        return {"status": "completed", **result}
    except Exception:
        conn.rollback()
        raise
