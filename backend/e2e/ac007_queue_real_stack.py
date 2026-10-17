"""Drive AC-007 fairness and post-commit dispatch recovery in disposable E2E."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time

from app.core.auth import hash_password
from app.db.connection import get_db_connection


OWNER_USERNAME = "ac007_queue_owner"
TEST_PASSWORD = "Ac007-queue-real-stack-123!"
PUBLIC_URL = "https://ac007-queue.example/public"
PRIVATE_URL = "https://ac007-queue.example/private"
POSITION = "后端"
FAIRNESS_MARKER = "AC007_QUEUE_FAIRNESS"


def _user_id(conn, username: str, *, is_admin: bool = False) -> int:
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if row:
        return int(row["id"])
    cursor = conn.execute(
        "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
        "VALUES (?, ?, ?, ?, 'private')",
        (username, hash_password(TEST_PASSWORD), f"{username}@example.test", int(is_admin)),
    )
    return int(cursor.lastrowid)


def _add_public_items(conn, *, request_id: int, source_interview_id: int,
                      public_interview_id: int, wave: int, count: int) -> list[int]:
    queue_ids = []
    for index in range(count):
        ordinal = wave * 100 + index + 1
        question = f"{FAIRNESS_MARKER} public wave {wave} question {index}"
        source_detail_id = int(
            conn.execute(
                "INSERT INTO questions_detail "
                "(interview_id, question, cat1, cat2, owner_id, status, source_ordinal) "
                "VALUES (?, ?, '后端', '调度', ?, 'approved', ?)",
                (source_interview_id, question, _user_id(conn, OWNER_USERNAME), ordinal),
            ).lastrowid
        )
        public_detail_id = int(
            conn.execute(
                "INSERT INTO questions_detail "
                "(interview_id, question, cat1, cat2, owner_id, status, source_ordinal) "
                "VALUES (?, ?, '后端', '调度', NULL, 'approved', ?)",
                (public_interview_id, question, ordinal),
            ).lastrowid
        )
        conn.execute(
            "INSERT INTO public_contribution_items "
            "(request_id, source_item_type, source_item_id, ordinal, status, "
            "snapshot_json, public_detail_id) "
            "VALUES (?, 'question', ?, ?, 'queued', ?, ?)",
            (
                request_id,
                source_detail_id,
                ordinal,
                json.dumps({"question": question}, ensure_ascii=False),
                public_detail_id,
            ),
        )
        queue_ids.append(
            int(
                conn.execute(
                    "INSERT INTO analysis_queue "
                    "(interview_id, question_detail_id, owner_id, status, contribution_request_id) "
                    "VALUES (?, ?, NULL, 'pending', ?) RETURNING id",
                    (public_interview_id, public_detail_id, request_id),
                ).fetchone()["id"]
            )
        )
    return queue_ids


def _insert_private_rows(conn, *, owner_id: int, interview_id: int, count: int, wave: int):
    for index in range(count):
        question = f"{FAIRNESS_MARKER} private question {wave}-{index}"
        detail_id = int(
            conn.execute(
                "INSERT INTO questions_detail "
                "(interview_id, question, cat1, cat2, owner_id, status, source_ordinal) "
                "VALUES (?, ?, '后端', '调度', ?, 'approved', ?)",
                (interview_id, question, owner_id, wave * 100 + index + 1),
            ).lastrowid
        )
        conn.execute(
            "INSERT INTO analysis_queue "
            "(interview_id, question_detail_id, owner_id, status) "
            "VALUES (?, ?, ?, 'pending')",
            (interview_id, detail_id, owner_id),
        )


def seed_fairness() -> None:
    from app.services.pipeline import _run_cluster_batch_in_background

    with get_db_connection() as conn:
        active = conn.execute(
            "SELECT id FROM jobs WHERE job_type = 'cluster_batch' "
            "AND root_import_id IS NULL AND status IN ('pending','queued','running')"
        ).fetchall()
        if active:
            raise RuntimeError(f"unexpected active rootless cluster jobs: {[r['id'] for r in active]}")
        owner_id = _user_id(conn, OWNER_USERNAME)
        admin = conn.execute(
            "SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if admin is None:
            raise RuntimeError("disposable stack is missing its administrator")
        admin_id = int(admin["id"])
        conn.execute(
            "INSERT OR REPLACE INTO user_llm_config "
            "(user_id, api_key, base_url, model, timeout) "
            "VALUES (?, 'real-stack-e2e-provider-key', 'http://llm-stub:8080/v1', "
            "'real-stack-stub', '10')",
            (owner_id,),
        )
        source_interview_id = int(
            conn.execute(
                "INSERT INTO interview "
                "(url, company, round, questions_list, owner_id, status, job_position) "
                "VALUES (?, 'AC007 private source', '一面', 'private', ?, 'approved', ?)",
                (PRIVATE_URL, owner_id, POSITION),
            ).lastrowid
        )
        public_interview_id = int(
            conn.execute(
                "INSERT INTO interview "
                "(url, company, round, questions_list, owner_id, status, job_position) "
                "VALUES (?, 'AC007 public target', '一面', 'public', NULL, 'approved', ?)",
                (PUBLIC_URL, POSITION),
            ).lastrowid
        )
        request_id = int(
            conn.execute(
                "INSERT INTO public_contribution_requests "
                "(source_type, source_id, requester_id, public_interview_id, status, "
                "snapshot_json, revision) "
                "VALUES ('interview', ?, ?, ?, 'partially_published', '{}', 1) RETURNING id",
                (source_interview_id, owner_id, public_interview_id),
            ).fetchone()["id"]
        )
        _add_public_items(
            conn,
            request_id=request_id,
            source_interview_id=source_interview_id,
            public_interview_id=public_interview_id,
            wave=0,
            count=11,
        )
        _insert_private_rows(conn, owner_id=owner_id, interview_id=source_interview_id, count=7, wave=1)
        conn.commit()

    created = asyncio.run(
        _run_cluster_batch_in_background(
            user_id=admin_id,
            queue_scope="public_contribution",
        )
    )
    if not created:
        raise AssertionError("failed to create the initial public contribution job")
    with get_db_connection() as conn:
        job = conn.execute(
            "SELECT id, status, root_import_id FROM jobs "
            "WHERE job_type = 'cluster_batch' AND root_import_id IS NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if job is None or job["status"] not in ("pending", "queued"):
            raise AssertionError(f"the durable public queue job is missing: {job}")
    print(json.dumps({
        "owner_id": owner_id,
        "admin_id": admin_id,
        "request_id": request_id,
        "source_interview_id": source_interview_id,
        "public_interview_id": public_interview_id,
        "private_interview_id": source_interview_id,
        "initial_private_pending": 7,
        "initial_public_pending": 11,
        "initial_job_id": int(job["id"]),
        "initial_job_status": job["status"],
    }, sort_keys=True))


def watch_fairness(request_id: int, private_interview_id: int, source_interview_id: int,
                   public_interview_id: int, timeout: float) -> None:
    started = time.monotonic()
    next_wave_at = started
    wave = 1
    total_arrivals = 0
    trace = None
    while time.monotonic() - started < timeout:
        with get_db_connection() as conn:
            private = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done, "
                "SUM(CASE WHEN status IN ('processing','failed') THEN 1 ELSE 0 END) AS started "
                "FROM analysis_queue WHERE interview_id = ? AND owner_id IS NOT NULL "
                "AND root_import_id IS NULL",
                (private_interview_id,),
            ).fetchone()
            public_pending = int(
                conn.execute(
                    "SELECT COUNT(*) FROM analysis_queue WHERE contribution_request_id = ? "
                    "AND owner_id IS NULL AND status = 'pending'",
                    (request_id,),
                ).fetchone()[0]
            )
            if int(private["done"] or 0) >= 5 and public_pending > 0:
                trace = {
                    "private_total": int(private["total"]),
                    "private_done_when_public_pending": int(private["done"]),
                    "private_started_when_public_pending": int(private["started"] or 0),
                    "public_pending_when_private_served": public_pending,
                    "public_arrival_waves": wave - 1,
                    "public_arrivals_added": total_arrivals,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "fairness_passed": True,
                }
                break
            now = time.monotonic()
            if now >= next_wave_at:
                _add_public_items(
                    conn,
                    request_id=request_id,
                    source_interview_id=source_interview_id,
                    public_interview_id=public_interview_id,
                    wave=wave,
                    count=5,
                )
                conn.commit()
                wave += 1
                total_arrivals += 5
                next_wave_at = now + 0.75
        time.sleep(0.2)
    if trace is None:
        with get_db_connection() as conn:
            private_pending = conn.execute(
                "SELECT COUNT(*) FROM analysis_queue WHERE interview_id = ? "
                "AND owner_id IS NOT NULL AND root_import_id IS NULL AND status = 'pending'",
                (private_interview_id,),
            ).fetchone()[0]
            public_pending = conn.execute(
                "SELECT COUNT(*) FROM analysis_queue WHERE contribution_request_id = ? "
                "AND owner_id IS NULL AND status = 'pending'",
                (request_id,),
            ).fetchone()[0]
        raise AssertionError(
            f"private queue starved: private_pending={private_pending}, "
            f"public_pending={public_pending}, waves={wave - 1}"
        )
    print(json.dumps(trace, sort_keys=True))


def wait_fairness_idle(request_id: int, private_interview_id: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with get_db_connection() as conn:
            queue_pending = conn.execute(
                "SELECT COUNT(*) FROM analysis_queue WHERE root_import_id IS NULL "
                "AND status IN ('pending','processing') "
                "AND (interview_id = ? OR contribution_request_id = ?)",
                (private_interview_id, request_id),
            ).fetchone()[0]
            active_jobs = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE job_type = 'cluster_batch' "
                "AND root_import_id IS NULL AND status IN ('pending','queued','running')"
            ).fetchone()[0]
        if int(queue_pending) == 0 and int(active_jobs) == 0:
            print(json.dumps({"queue_pending": 0, "active_rootless_jobs": 0}))
            return
        time.sleep(0.5)
    raise TimeoutError("AC-007 fairness queues did not drain in the disposable worker stack")


def seed_lost_dispatch(owner_id: int) -> None:
    with get_db_connection() as conn:
        interview_id = int(
            conn.execute(
                "INSERT INTO interview "
                "(url, company, round, questions_list, owner_id, status, job_position) "
                "VALUES ('https://ac007-queue.example/lost-dispatch', 'AC007 dispatch recovery', "
                "'一面', 'private pending', ?, 'approved', ?) RETURNING id",
                (owner_id, POSITION),
            ).fetchone()["id"]
        )
        _insert_private_rows(conn, owner_id=owner_id, interview_id=interview_id, count=5, wave=9)
        conn.commit()
        print(json.dumps({"owner_id": owner_id, "interview_id": interview_id}, sort_keys=True))


def create_lost_dispatch(owner_id: int) -> None:
    from app.services.pipeline import _run_cluster_batch_in_background

    if os.environ.get("AC007_EXPECT_QUEUE_OUTAGE") != "1":
        raise RuntimeError("stop the disposable queue Redis before this scenario")

    failure_messages = []

    class DispatchFailureCapture(logging.Handler):
        def emit(self, record):
            message = record.getMessage()
            if "ARQ 调度失败" in message and "保留 pending 等待 dispatcher" in message:
                failure_messages.append(message)

    logger = logging.getLogger("interview-boss")
    capture = DispatchFailureCapture(level=logging.WARNING)
    logger.addHandler(capture)
    try:
        result = asyncio.run(_run_cluster_batch_in_background(user_id=owner_id))
    finally:
        logger.removeHandler(capture)

    with get_db_connection() as conn:
        job = conn.execute(
            "SELECT id, status, created_by, idempotency_key FROM jobs "
            "WHERE job_type = 'cluster_batch' AND root_import_id IS NULL "
            "AND created_by = ? ORDER BY id DESC LIMIT 1",
            (owner_id,),
        ).fetchone()
        if (
            not result
            or job is None
            or job["status"] != "pending"
            or len(failure_messages) != 1
        ):
            raise AssertionError(f"post-commit ARQ loss did not preserve one pending job: {job}")
        active_count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE job_type = 'cluster_batch' "
            "AND root_import_id IS NULL AND status IN ('pending','queued','running')"
        ).fetchone()[0]
        if int(active_count) != 1:
            raise AssertionError(f"expected one outbox job after lost notification, got {active_count}")
    print(json.dumps({
        "job_id": int(job["id"]),
        "status_after_lost_notification": job["status"],
        "idempotency_key": job["idempotency_key"],
        "active_rootless_job_count": int(active_count),
        "enqueue_attempt_returned": bool(result),
        "queue_redis_container_stopped": True,
        "post_commit_enqueue_failure_observed": True,
        "failure_log_count": len(failure_messages),
    }, sort_keys=True))


def assert_dispatched(job_id: int) -> None:
    with get_db_connection() as conn:
        job = conn.execute(
            "SELECT id, status, arq_job_id, idempotency_key FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if job is None or job["status"] != "queued" or not job["arq_job_id"]:
            raise AssertionError(f"the durable job was not dispatched to real Redis: {job}")
        same_key = int(
            conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE idempotency_key = ?",
                (job["idempotency_key"],),
            ).fetchone()[0]
        )
        if same_key != 1:
            raise AssertionError(f"dispatch recovery duplicated the durable job: {same_key}")
    print(json.dumps({
        "job_id": int(job["id"]),
        "status": job["status"],
        "arq_job_id": job["arq_job_id"],
        "same_idempotency_key_job_count": same_key,
        "dispatch_recovered_once": True,
    }, sort_keys=True))


def wait_lost_dispatch(job_id: int, interview_id: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with get_db_connection() as conn:
            job = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            pending = conn.execute(
                "SELECT COUNT(*) FROM analysis_queue WHERE interview_id = ? "
                "AND root_import_id IS NULL AND status != 'done'",
                (interview_id,),
            ).fetchone()[0]
        if job and job["status"] == "completed" and int(pending) == 0:
            print(json.dumps({"job_id": job_id, "status": "completed", "unfinished_queue_rows": 0}))
            return
        time.sleep(0.5)
    raise TimeoutError(f"recovered rootless job {job_id} did not complete")


def recover_rootless_retry_gap(owner_id: int, timeout: float) -> None:
    """Simulate a process exit after the queue-row commit but before dispatch."""
    from app.services.personal_analysis_recovery import retry_personal_analysis_failure

    question = "AC007 rootless reconciler recovery after committed retry"
    with get_db_connection() as conn:
        before_attempts = int(conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0])
        before_jobs = int(
            conn.execute(
                "SELECT COALESCE(MAX(id), 0) FROM jobs WHERE job_type = 'cluster_batch' "
                "AND root_import_id IS NULL AND created_by = ?",
                (owner_id,),
            ).fetchone()[0]
        )
        interview_id = int(
            conn.execute(
                "INSERT INTO interview "
                "(url, company, round, questions_list, owner_id, status, job_position) "
                "VALUES ('https://ac007-queue.example/reconcile-gap', 'AC007 reconcile gap', "
                "'一面', ?, ?, 'approved', ?) RETURNING id",
                (question, owner_id, POSITION),
            ).fetchone()["id"]
        )
        detail_id = int(
            conn.execute(
                "INSERT INTO questions_detail "
                "(interview_id, question, cat1, cat2, owner_id, status) "
                "VALUES (?, ?, '后端', '调度', ?, 'approved') RETURNING id",
                (interview_id, question, owner_id),
            ).fetchone()["id"]
        )
        queue_id = int(
            conn.execute(
                "INSERT INTO analysis_queue "
                "(interview_id, question_detail_id, owner_id, status, root_import_id) "
                "VALUES (?, ?, ?, 'failed', NULL) RETURNING id",
                (interview_id, detail_id, owner_id),
            ).fetchone()["id"]
        )
        conn.commit()

        retry = retry_personal_analysis_failure(
            conn, queue_id=queue_id, owner_id=owner_id
        )
        if retry != {"queue_id": queue_id, "status": "pending", "created": True}:
            raise AssertionError(f"owner retry did not commit the original row: {retry}")
        pending = conn.execute(
            "SELECT status FROM analysis_queue WHERE id = ?", (queue_id,)
        ).fetchone()
        jobs_after_retry = int(
            conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE job_type = 'cluster_batch' "
                "AND root_import_id IS NULL AND created_by = ? AND id > ?",
                (owner_id, before_jobs),
            ).fetchone()[0]
        )
        if not pending or pending["status"] != "pending" or jobs_after_retry != 0:
            raise AssertionError("simulated crash gap was not established after row commit")

    import app.services.pipeline.queue as cluster_queue
    from app.worker_scheduled import scheduled_upload_queue_reconcile_task

    original_delay = cluster_queue.CLUSTER_DELAY_SECONDS
    cluster_queue.CLUSTER_DELAY_SECONDS = 0
    try:
        reconcile = asyncio.run(scheduled_upload_queue_reconcile_task({}))
    finally:
        cluster_queue.CLUSTER_DELAY_SECONDS = original_delay

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with get_db_connection() as conn:
            queue_row = conn.execute(
                "SELECT aq.status, aq.owner_id, aq.root_import_id, aq.interview_id, "
                "i.owner_id AS interview_owner_id, qd.question, qd.import_id "
                "FROM analysis_queue aq JOIN interview i ON i.id = aq.interview_id "
                "JOIN questions_detail qd ON qd.id = aq.question_detail_id "
                "WHERE aq.id = ?",
                (queue_id,),
            ).fetchone()
            recovered_jobs = conn.execute(
                "SELECT id, status, root_import_id, upload_attempt_id FROM jobs "
                "WHERE job_type = 'cluster_batch' AND root_import_id IS NULL "
                "AND created_by = ? AND id > ? ORDER BY id",
                (owner_id, before_jobs),
            ).fetchall()
            private_result = conn.execute(
                "SELECT id FROM question_bank WHERE owner_id = ? AND question = ?",
                (owner_id, question),
            ).fetchone()
        if queue_row and queue_row["status"] == "done" and private_result:
            break
        time.sleep(0.5)

    if not queue_row or queue_row["status"] != "done" or not private_result:
        raise TimeoutError("periodic reconciliation did not recover the rootless retry")
    if (
        int(queue_row["owner_id"]) != owner_id
        or int(queue_row["interview_owner_id"]) != owner_id
        or queue_row["root_import_id"] is not None
        or queue_row["import_id"] is not None
        or len(recovered_jobs) != 1
        or recovered_jobs[0]["status"] != "completed"
        or recovered_jobs[0]["root_import_id"] is not None
        or recovered_jobs[0]["upload_attempt_id"] is not None
    ):
        raise AssertionError(
            f"reconciled rootless scope/job changed unexpectedly: "
            f"queue={dict(queue_row)}, jobs={[dict(row) for row in recovered_jobs]}"
        )

    with get_db_connection() as conn:
        linked_roots = int(
            conn.execute(
                "SELECT COUNT(*) FROM upload_imports WHERE interview_id = ?",
                (interview_id,),
            ).fetchone()[0]
        )
        attempts_after = int(conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0])
    if linked_roots or attempts_after != before_attempts:
        raise AssertionError("periodic recovery created an upload root or attempt")

    print(json.dumps({
        "queue_id": queue_id,
        "interview_id": interview_id,
        "retry_committed_without_job": True,
        "reconcile_report": reconcile,
        "recovered_job": dict(recovered_jobs[0]),
        "queue_row": dict(queue_row),
        "private_question_bank_id": int(private_result["id"]),
        "upload_roots_linked": linked_roots,
        "upload_attempts_before": before_attempts,
        "upload_attempts_after": attempts_after,
    }, ensure_ascii=False, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-fairness")
    watch = sub.add_parser("watch-fairness")
    watch.add_argument("request_id", type=int)
    watch.add_argument("private_interview_id", type=int)
    watch.add_argument("source_interview_id", type=int)
    watch.add_argument("public_interview_id", type=int)
    watch.add_argument("--timeout", type=float, default=90)
    idle = sub.add_parser("wait-fairness-idle")
    idle.add_argument("request_id", type=int)
    idle.add_argument("private_interview_id", type=int)
    idle.add_argument("--timeout", type=float, default=180)
    lost_seed = sub.add_parser("seed-lost-dispatch")
    lost_seed.add_argument("owner_id", type=int)
    create_lost = sub.add_parser("create-lost-dispatch")
    create_lost.add_argument("owner_id", type=int)
    dispatched = sub.add_parser("assert-dispatched")
    dispatched.add_argument("job_id", type=int)
    wait_job = sub.add_parser("wait-lost-dispatch")
    wait_job.add_argument("job_id", type=int)
    wait_job.add_argument("interview_id", type=int)
    wait_job.add_argument("--timeout", type=float, default=90)
    gap = sub.add_parser("recover-rootless-retry-gap")
    gap.add_argument("owner_id", type=int)
    gap.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    if args.command == "seed-fairness":
        seed_fairness()
    elif args.command == "watch-fairness":
        watch_fairness(
            args.request_id,
            args.private_interview_id,
            args.source_interview_id,
            args.public_interview_id,
            args.timeout,
        )
    elif args.command == "wait-fairness-idle":
        wait_fairness_idle(args.request_id, args.private_interview_id, args.timeout)
    elif args.command == "seed-lost-dispatch":
        seed_lost_dispatch(args.owner_id)
    elif args.command == "create-lost-dispatch":
        create_lost_dispatch(args.owner_id)
    elif args.command == "assert-dispatched":
        assert_dispatched(args.job_id)
    elif args.command == "wait-lost-dispatch":
        wait_lost_dispatch(args.job_id, args.interview_id, args.timeout)
    elif args.command == "recover-rootless-retry-gap":
        recover_rootless_retry_gap(args.owner_id, args.timeout)


if __name__ == "__main__":
    main()
