"""R05/AC-005：真实 persist 节点写入 import_id/source_ordinal + resolution。

覆盖：
- 私人逐题明细写 import_id/source_ordinal（不会重复写，重试幂等）；
- 命中公共/个人规范题 → record_resolution(matched)，且不改公共 sources；
- 未命中 → 新题写入后 resolution(created)；
- 匹配异常不得造新题（failed 持久化可恢复失败，见 R05 测试）。
"""

from __future__ import annotations

import sqlite3

from app.db.migrations import run_migrations
from app.services.upload_resolution_link import link_details_to_import


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version) "
        "VALUES ('imp-1', 101, 'k-1', 'h-1', 'private', 'interview', 'upload-pipeline-v1')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status, job_position) "
        "VALUES (1, 'internal://a', 101, 'approved', '后端开发')"
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2, owner_id) "
        "VALUES (11, 1, '解释 TCP 三次握手', '网络', 'tcp', 101), "
        "       (12, 1, 'Redis 持久化机制', '数据库', 'Redis', 101)"
    )
    conn.commit()
    return conn


def test_link_writes_import_id_and_source_ordinal():
    conn = _db()
    link_details_to_import(
        conn,
        import_id="imp-1",
        detail_ids=[11, 12],
        ordinals={11: 1, 12: 2},
        actor_id=101,
        stage="persist",
    )
    conn.commit()
    row1 = conn.execute(
        "SELECT import_id, source_ordinal FROM questions_detail WHERE id = 11"
    ).fetchone()
    assert row1["import_id"] == "imp-1"
    assert row1["source_ordinal"] == 1
    row2 = conn.execute(
        "SELECT import_id, source_ordinal FROM questions_detail WHERE id = 12"
    ).fetchone()
    assert row2["import_id"] == "imp-1"
    assert row2["source_ordinal"] == 2
    # 幂等：重复写入不报错
    link_details_to_import(
        conn,
        import_id="imp-1",
        detail_ids=[11, 12],
        ordinals={11: 1, 12: 2},
        actor_id=101,
        stage="persist",
    )
    conn.commit()
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM questions_detail WHERE import_id = 'imp-1'"
    ).fetchone()["c"]
    assert count == 2
    conn.close()


def test_link_records_matched_resolution_without_touching_public_source():
    """R05：命中公共规范题 → resolution(matched)；公共 sources 不变。"""

    conn = _db()
    # 公共规范题 + 来源
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, owner_id, status) "
        "VALUES (900, '解释 TCP 三次握手', '网络', 'tcp', NULL, 'approved')"
    )
    conn.execute(
        "INSERT INTO question_sources (question_bank_id, url) "
        "VALUES (900, 'https://example.com/public')"
    )
    conn.commit()

    link_details_to_import(
        conn,
        import_id="imp-1",
        detail_ids=[11],
        ordinals={11: 1},
        actor_id=101,
        stage="persist",
        matches={11: {"canonical_id": 900, "canonical_scope": "public", "status": "matched"}},
    )
    conn.commit()

    res = conn.execute(
        "SELECT * FROM question_resolutions WHERE detail_id = 11 AND invalidated_at IS NULL"
    ).fetchone()
    assert res is not None
    assert res["status"] == "matched"
    assert res["canonical_id"] == 900
    assert res["canonical_scope"] == "public"
    checkpoint = conn.execute(
        "SELECT status, result_json FROM upload_stage_results "
        "WHERE import_id = 'imp-1' AND stage = 'resolve' AND unit_key = 'detail:11'"
    ).fetchone()
    assert checkpoint["status"] == "succeeded"
    assert '"canonical_id": 900' in checkpoint["result_json"]
    # 公共 sources 不被私人命中改动
    sources = conn.execute(
        "SELECT COUNT(*) AS c FROM question_sources WHERE question_bank_id = 900"
    ).fetchone()["c"]
    assert sources == 1
    conn.close()


def test_link_records_created_for_unmatched_new_question():
    conn = _db()
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, owner_id, status) "
        "VALUES (901, 'Redis 持久化机制', '数据库', 'Redis', 101, 'approved')"
    )
    conn.commit()
    link_details_to_import(
        conn,
        import_id="imp-1",
        detail_ids=[12],
        ordinals={12: 2},
        actor_id=101,
        stage="persist",
        matches={12: {"canonical_id": 901, "canonical_scope": "private", "status": "created"}},
    )
    conn.commit()
    res = conn.execute(
        "SELECT * FROM question_resolutions WHERE detail_id = 12 AND invalidated_at IS NULL"
    ).fetchone()
    assert res["status"] == "created"
    assert res["canonical_scope"] == "private"
    conn.close()


def test_link_without_match_persists_failed_not_new_question():
    """R05：一笔匹配失败持久化为 failed，不生成 phantom canonical。"""

    conn = _db()
    link_details_to_import(
        conn,
        import_id="imp-1",
        detail_ids=[12],
        ordinals={12: 2},
        actor_id=101,
        stage="persist",
        matches={12: None},
        write_unmatched=False,
    )
    conn.commit()
    res = conn.execute(
        "SELECT * FROM question_resolutions WHERE detail_id = 12 AND invalidated_at IS NULL"
    ).fetchone()
    assert res is not None
    assert res["status"] == "failed"
    phantom = conn.execute(
        "SELECT COUNT(*) AS c FROM question_bank WHERE owner_id = 101 "
        "AND question = 'Redis 持久化机制'"
    ).fetchone()["c"]
    assert phantom == 0, "匹配失败不得造新题"

def test_link_explicit_failed_match_records_error_code_and_no_canonical():
    """AC-006：显式 failed（status=failed + error_code）→ resolution 记
    failed 且 reason 携带错误码；绝不创建规范题。"""

    conn = _db()
    link_details_to_import(
        conn,
        import_id="imp-1",
        detail_ids=[12],
        ordinals={12: 2},
        actor_id=101,
        stage="persist",
        matches={12: {"status": "failed", "error_code": "UPSTREAM_TIMEOUT"}},
        write_unmatched=False,
    )
    conn.commit()
    res = conn.execute(
        "SELECT * FROM question_resolutions WHERE detail_id = 12 AND invalidated_at IS NULL"
    ).fetchone()
    assert res is not None
    assert res["status"] == "failed"
    assert "UPSTREAM_TIMEOUT" in (res["reason"] or ""), (
        "失败理由必须携带错误码便于运维定位"
    )
    assert res["canonical_id"] is None, "模型失败绝对不产生 canonical 关联"
    conn.close()


def test_root_gets_contribution_request_id_bound():
    """F-PUBLIC：private share 完成后 root.contribution_request_id 回写，
    使 review_status 可计算（此前该列全库零写入）。"""

    from app.services.public_contributions import (
        bind_contribution_request_to_root,
        create_public_contribution_request,
    )

    conn = _db()
    root_row = conn.execute(
        "SELECT * FROM upload_imports WHERE id = 'imp-1'"
    ).fetchone()
    assert root_row is not None

    request = create_public_contribution_request(
        conn, "interview", 1, 101
    )
    bind_contribution_request_to_root(
        conn, import_id="imp-1", contribution_request_id=int(request["id"])
    )
    conn.commit()

    bound = conn.execute(
        "SELECT contribution_request_id FROM upload_imports WHERE id = 'imp-1'"
    ).fetchone()
    assert int(bound["contribution_request_id"]) == int(request["id"]), (
        "root 必须回写 contribution_request_id 供 review_status 计算"
    )
    conn.close()
