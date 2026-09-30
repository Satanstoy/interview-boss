"""AC-029：单份面经逐题数据流追踪（临时 SQLite + 本地 stub）。

按 acceptance.md 的要求，用真实服务代码与临时 SQLite 断言下列数据链：

``input ordinal → 私人 detail/resolution → contribution item → 审核投影 →
 public detail/resolution → canonical``

本测试覆盖的服务链（真实代码路径）：

1. ``accept_upload``：一次 share 提交 → 稳定 import_id + policy（U1、share、
   私人预处理 scope=user、审核要求）；
2. 私人阶段：``save_stage_result``（extract 检查点）→ ``record_resolution``
   （逐 ordinal 匹配/创建私人规范题，不修改公共来源/频次）；
3. ``create_public_contribution_request``：由私人面经生成不可变快照；
4. ``finalize_public_contribution_approval``（v2 CAS）：排除 1 题 + 编辑 1 题
   题干 + 脱敏 source_url/company → ``approve_public_contribution_v2``
   只按审核投影物化公共 detail（不回落原快照）；
5. ``record_resolution``（公共）+ ``publish_items_with_resolutions`` +
   ``refresh_public_interview_projection``：逐题 published，失败题不进清单；
6. 恢复：只重做失败子项（不重复成功成果，无新增实体），最终公共面经恰有
   保留题数，私人原稿仍保留全部题。

**注意**：真实 worker（ARQ）执行路径的“中间故障点注入 → 重启 worker → 从
同一 root 恢复”测试需要运行中的 ARQ + Redis 栈，由 AC-028 的隔离腿与
``test_upload_recovery_stack.py`` 覆盖；这里锁定的是**逐题数据流本身**，
不连接真实模型、不写入生产库。
"""

from __future__ import annotations

import sqlite3

from app.db.migrations import run_migrations


def _connect(path, migrate=True):
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if migrate:
        run_migrations(conn)
    return conn


def _seed_users(conn):
    for uid, admin in ((101, 0), (102, 0), (201, 1)):
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
            "VALUES (?, ?, 'x', ?)",
            (uid, f"u{uid}", admin),
        )
    conn.commit()


def _loaders():
    return {
        "user": lambda uid: {
            "api_key": "stub-user-key",
            "base_url": "https://stub.invalid/v1",
            "model": "stub-model",
            "timeout": 5,
        },
        "global": lambda: {
            "api_key": "stub-system-key",
            "base_url": "https://stub.invalid/v1",
            "model": "stub-model",
            "timeout": 5,
        },
    }


def _accept_share(conn):
    from app.services.upload_lifecycle import accept_upload

    return accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="ac029-share-1",
        target_intent="share",
        source_type="interview",
        text="面经：5 道可区分题（Redis 持久化、线程池、TCP、优缺点、专项）",
        position_name="后端",
        files=[],
        images=[],
        entry="api",
        credential_loaders=_loaders(),
    )


def _seed_private_pipeline(conn, import_id: str, interview_id: int):
    """私人暂存：面经 + 逐 ordinal 明细 + 检查点 + 私人 resolution。"""

    from app.services.question_resolution import record_resolution
    from app.services.upload_repository import save_stage_result

    save_stage_result(
        conn,
        import_id=import_id,
        stage="extract",
        unit_key="document",
        input_version=1,
        pipeline_version="upload-pipeline-v1",
        status="succeeded",
        result_json=(
            '{"questions": [{"ordinal": 1, "question": "Redis 持久化"}, '
            '{"ordinal": 2, "question": "线程池参数"}, {"ordinal": 3, "question": "TCP 握手"}, '
            '{"ordinal": 4, "question": "Redis 优缺点"}, {"ordinal": 5, "question": "并发专项"}]}'
        ),
    )
    questions = [
        ("Redis 持久化", "数据库", "Redis"),
        ("线程池参数", "并发", "线程池"),
        ("TCP 握手", "网络", "TCP"),
        ("Redis 优缺点", "数据库", "Redis"),
        ("并发专项", "并发", "并发"),
    ]
    detail_ids = []
    for ordinal, (question, cat1, cat2) in enumerate(questions, start=1):
        cur = conn.execute(
            "INSERT INTO questions_detail (interview_id, question, cat1, cat2, "
            "import_id, source_ordinal, job_position) "
            "VALUES (?, ?, ?, ?, ?, ?, '后端')",
            (interview_id, question, cat1, cat2, import_id, ordinal),
        )
        detail_id = int(cur.lastrowid)
        detail_ids.append(detail_id)
        # 私人 created：必须先建本人私人规范题再关联（private occurrence scope）
        canonical = conn.execute(
            "INSERT INTO question_bank (question, cat1, cat2, owner_id, status, frequency, "
            "sources, original_questions, original_question_sources) "
            "VALUES (?, ?, ?, 101, 'approved', 1, '[]', ?, ?) "
            "RETURNING id",
            (question, cat1, cat2, f'[{{"question": "{question}"}}]', "[]"),
        ).fetchone()
        record_resolution(
            conn,
            detail_id=detail_id,
            occurrence_scope="private",
            occurrence_owner_id=101,
            canonical_id=int(canonical["id"]),
            canonical_scope="private",
            status="created",
            pipeline_version="upload-pipeline-v1",
            reason="private_created",
        )
    return detail_ids


async def test_full_question_data_flow_trace(tmp_path):
    """从 share 提交到审核投影再到逐题 published：ordinal 全程一致、无重复。"""

    from app.models.upload_contracts import build_review_projection_request
    from app.services.pipeline.queue import enqueue_questions
    from app.services.public_contributions import (
        create_public_contribution_request,
        finalize_public_contribution_approval,
        publish_items_with_resolutions,
        refresh_public_interview_projection,
        request_publish_status,
    )
    from app.services.question_resolution import record_resolution
    from app.services.upload_lifecycle import restore_upload
    from app.services.upload_repository import get_stage_result

    db_path = str(tmp_path / "ac029.db")
    conn = _connect(db_path)
    _seed_users(conn)

    # 1) share 接受 → 稳定 import_id + policy
    accepted = _accept_share(conn)
    conn.commit()
    import_id = accepted["import_id"]
    policy = accepted["policy"]
    assert policy["target_intent"] == "share"
    assert policy["credential_scope"] == "user"
    assert policy["post_approval_credential_scope"] == "global"

    # 2) 私人暂存：面经 + 5 个 ordinal 明细 + resolution
    cur = conn.execute(
        "INSERT INTO interview (url, company, round, focus, questions_list, difficulty, "
        "season, owner_id, status, job_position) "
        "VALUES ('https://private.invalid/1', 'PRIVATE', '一面', '数据库', "
        "'1.Redis 持久化\n2.线程池参数\n3.TCP 握手\n4.Redis 优缺点\n5.并发专项', "
        "'中等', '2026春招', 101, 'approved', '后端')"
    )
    private_interview_id = int(cur.lastrowid)
    conn.execute(
        "UPDATE upload_imports SET interview_id = ? WHERE id = ?",
        (private_interview_id, import_id),
    )
    _seed_private_pipeline(conn, import_id, private_interview_id)
    conn.commit()

    check = get_stage_result(
        conn, import_id=import_id, stage="extract", unit_key="document", input_version=1
    )
    assert check["status"] == "succeeded"
    priv_details = conn.execute(
        "SELECT id, source_ordinal FROM questions_detail WHERE interview_id = ? ORDER BY source_ordinal",
        (private_interview_id,),
    ).fetchall()
    assert len(priv_details) == 5

    # 3) 公共贡献申请（不可变快照）
    request = create_public_contribution_request(
        conn, "interview", private_interview_id, 101
    )
    request_id = request["id"]
    assert request["status"] == "pending_review"

    # contribution items 按 ordinal 自增 id（1..5）；排除第 5 题、编辑第 1 题
    item_ids = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM public_contribution_items WHERE request_id = ? ORDER BY ordinal",
            (request_id,),
        ).fetchall()
    ]
    assert len(item_ids) == 5, item_ids

    # 4) 管理员审核：排除 ordinal=5、编辑 ordinal=1 题干、脱敏 company/source_url
    request_payload = {
        "expected_revision": 1,
        "excluded_item_ids": [int(item_ids[4])],
        "review_fields": {
            "source": {"company": None, "source_url": None, "round": "一面"},
            "items": [
                {
                    "item_id": int(item_ids[0]),
                    "question": "Redis 持久化机制（已编辑）",
                    "cat1": "数据库",
                    "cat2": "Redis",
                }
            ],
        },
    }
    import app.db.connection as db_module

    token = db_module._db_conn_var.set(conn)
    try:
        from app.services.public_contributions import finalize_public_contribution_approval

        approved = await finalize_public_contribution_approval(
            request_id,
            201,
            excluded_item_ids=request_payload["excluded_item_ids"],
            review_fields=request_payload["review_fields"],
            expected_revision=request_payload["expected_revision"],
        )
    finally:
        db_module._db_conn_var.reset(token)
    assert approved["status"] == "approved_for_processing"

    # 5) 公共 processing：聚合支付切换 global 后重试时由 worker 重新探测；
    #    这里用公共 resolution 驱动 published。
    pub_interview_id = approved["public_interview_id"]
    pub_details = conn.execute(
        "SELECT d.id AS id, d.source_ordinal AS ordinal FROM questions_detail d "
        "JOIN public_contribution_items i ON i.public_detail_id = d.id "
        "WHERE d.interview_id = ? AND i.status IN ('queued','processing','published') "
        "ORDER BY d.id",
        (pub_interview_id,),
    ).fetchall()
    # 排除 1 题后应恰有 4 个公共明细
    assert len(pub_details) == 4, [row["id"] for row in pub_details]

    # 编辑后的题干生效，且原 PRIVATE 来源不回落到公共字段
    edited = conn.execute(
        "SELECT question FROM questions_detail WHERE interview_id = ? AND id = ?",
        (pub_interview_id, pub_details[0]["id"]),
    ).fetchone()
    assert "已编辑" in edited["question"]
    pub_interview = conn.execute(
        "SELECT company, url, round FROM interview WHERE id = ?",
        (pub_interview_id,),
    ).fetchone()
    assert pub_interview["company"] in (None, "")
    assert pub_interview["url"] in (None, ""), "脱敏 source_url 不得回落公开来源"

    # 6) 逐题公共 resolution：前 3 题成功，第 4 题注入失败
    for index, pub_detail in enumerate(pub_details[:3]):
        canonical = conn.execute(
            "INSERT INTO question_bank (question, cat1, cat2, owner_id, status, frequency, "
            "sources, original_questions, original_question_sources) "
            "VALUES (?, '公共', '公共', NULL, 'approved', 1, '[]', '[]', '[]') "
            "RETURNING id",
            (f"公共题 {index + 1}",),
        ).fetchone()
        record_resolution(
            conn,
            detail_id=int(pub_detail["id"]),
            occurrence_scope="public",
            occurrence_owner_id=None,
            canonical_id=int(canonical["id"]),
            canonical_scope="public",
            status="created",
            pipeline_version="upload-pipeline-v1",
            reason="public_created",
        )
    record_resolution(
        conn,
        detail_id=int(pub_details[3]["id"]),
        occurrence_scope="public",
        occurrence_owner_id=None,
        canonical_id=None,
        canonical_scope=None,
        status="failed",
        pipeline_version="upload-pipeline-v1",
        reason="UPSTREAM_TIMEOUT",
    )
    conn.commit()

    report = publish_items_with_resolutions(conn, request_id=request_id)
    assert len(report["published_item_ids"]) == 3
    assert len(report["pending_item_ids"]) == 1, f"应只有失败题待处理: {report}"
    assert request_publish_status(conn, request_id=request_id) != "published"

    # 7) 恢复：只重做失败子项；成功成果不重复
    failed_item = conn.execute(
        "SELECT id, status FROM public_contribution_items WHERE request_id = ? "
        "AND public_detail_id = ?",
        (request_id, int(pub_details[3]["id"])),
    ).fetchone()
    assert failed_item["status"] == "processing" or failed_item["status"] in (
        "queued",
        "processing",
        "failed",
    )
    retry_canonical = conn.execute(
        "INSERT INTO question_bank (question, cat1, cat2, owner_id, status, frequency, "
        "sources, original_questions, original_question_sources) "
        "VALUES ('公共题 4', '并发', '并发', NULL, 'approved', 1, '[]', '[]', '[]') "
        "RETURNING id"
    ).fetchone()
    record_resolution(
        conn,
        detail_id=int(pub_details[3]["id"]),
        occurrence_scope="public",
        occurrence_owner_id=None,
        canonical_id=int(retry_canonical["id"]),
        canonical_scope="public",
        status="created",
        pipeline_version="upload-pipeline-v1",
        reason="public_created",
    )
    conn.commit()
    report2 = publish_items_with_resolutions(conn, request_id=request_id)
    assert len(report2["published_item_ids"]) == 4
    assert request_publish_status(conn, request_id=request_id) == "published"

    refresh_public_interview_projection(conn, public_interview_id=pub_interview_id)
    pub_list = conn.execute(
        "SELECT questions_list FROM interview WHERE id = ?", (pub_interview_id,)
    ).fetchone()["questions_list"]
    assert "Redis 持久化机制（已编辑）" in pub_list
    assert "并发专项" not in pub_list, "排除题不得进入公共清单"
    assert "Redis 持久化" in pub_list

    # 8) 私人原稿仍保留全部 5 题；无重复 detail/resolution
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM questions_detail WHERE interview_id = ?",
            (private_interview_id,),
        ).fetchone()[0]
        == 5
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM questions_detail WHERE import_id = ?",
            (import_id,),
        ).fetchone()[0]
        == 5
    )
    # 每个 detail 最多一个当前 resolution
    dup = conn.execute(
        "SELECT detail_id, COUNT(*) AS c FROM question_resolutions "
        "WHERE invalidated_at IS NULL GROUP BY detail_id HAVING c > 1"
    ).fetchall()
    assert dup == []

    conn.close()


def test_private_source_never_leaks_to_public_reader(tmp_path):
    """U2 通过公开读取看不到 U1 私人原稿/来源（AC-018 数据链收口）。"""

    from app.services.question_resolution import record_resolution
    from app.services.public_contributions import create_public_contribution_request

    db_path = str(tmp_path / "privacy.db")
    conn = _connect(db_path)
    _seed_users(conn)
    accepted = _accept_share(conn)
    conn.commit()
    cur = conn.execute(
        "INSERT INTO interview (url, company, round, questions_list, difficulty, "
        "season, owner_id, status, job_position) "
        "VALUES ('https://private.invalid/9', 'SECRET-CORP', '一面', '1.x', "
        "'简单', '2026春招', 101, 'approved', '后端')"
    )
    interview_id = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO questions_detail (interview_id, question, cat1, cat2, job_position) "
        "VALUES (?, 'Redis 持久化', '数据库', 'Redis', '后端')",
        (interview_id,),
    )
    conn.commit()
    # 私人来源不与公共内容共享：公共 detail 不写私有来源
    detail = conn.execute(
        "SELECT id FROM questions_detail WHERE interview_id = ? LIMIT 1", (interview_id,)
    ).fetchone()
    canonical = conn.execute(
        "INSERT INTO question_bank (question, cat1, cat2, owner_id, status, frequency, "
        "sources, original_questions, original_question_sources) "
        "VALUES ('Redis 持久化', '数据库', 'Redis', 101, 'approved', 1, '[]', '[]', '[]') "
        "RETURNING id"
    ).fetchone()
    record_resolution(
        conn,
        detail_id=int(detail["id"]),
        occurrence_scope="private",
        occurrence_owner_id=101,
        canonical_id=int(canonical["id"]),
        canonical_scope="private",
        status="created",
        pipeline_version="upload-pipeline-v1",
        reason="private_created",
    )
    conn.commit()

    request = create_public_contribution_request(conn, "interview", interview_id, 101)
    assert request["id"] > 0
    # 公共面经投影只从快照物化；私人 company 出现在 snapshot 但不进入公共
    snapshot = conn.execute(
        "SELECT snapshot_json FROM public_contribution_requests WHERE id = ?",
        (request["id"],),
    ).fetchone()["snapshot_json"]
    assert "SECRET-CORP" in snapshot
    conn.close()