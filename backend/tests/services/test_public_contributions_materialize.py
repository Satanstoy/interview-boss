"""AC-014 / UR-014：最终公开内容必须等于审核投影。

契约（contracts.md §3.1、§3.3）：

- 公司/轮次/来源 URL 默认不公开；管理员显式确认才公开，null 表示删除公开字段，
  **不得**回落到原始 snapshot；
- 审核预览与物化共用同一构造函数；
- 物化只接受 reviewed_projection，禁止内部重新读取 source 原值补敏感字段；
- 未知字段、非本申请 item_id 一律拒绝。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.models.upload_contracts import build_review_projection_request
from app.services.public_contributions import (
    build_review_projection,
    materialize_public_interview_from_projection,
)


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (201, 'admin', 'x')")
    return conn


def _snapshot():
    return {
        "company": "PRIVATE公司",
        "round": "一面",
        "focus": "数据库",
        "source_url": "https://secret.example.com/post/1",
        "season": "2026春招",
        "difficulty": "中等",
    }


def _items():
    return [
        {
            "item_id": 11,
            "ordinal": 1,
            "question": "说明数据库索引的工作原理",
            "cat1": "数据库",
            "cat2": "索引",
            "tags": "mysql",
            "difficulty": "中等",
        },
        {
            "item_id": 12,
            "ordinal": 2,
            "question": "什么是事务隔离级别",
            "cat1": "数据库",
            "cat2": "事务",
            "tags": "",
            "difficulty": "中等",
        },
    ]


def _review_request(payload):
    return build_review_projection_request(payload, source_type="interview")


def test_public_fields_equal_review_projection_not_original_snapshot():
    request = _review_request(
        {
            "expected_revision": 1,
            "excluded_item_ids": [12],
            "review_fields": {
                "source": {
                    "company": None,
                    "round": "一面（技术）",
                    "source_url": None,
                },
                "items": [{"item_id": 11, "question": "数据库索引的工作原理是什么？"}],
            },
        }
    )
    projection = build_review_projection(
        snapshot=_snapshot(), items=_items(), request=request, reviewer_id=201
    )

    # 原快照不得被修改
    assert projection["source_snapshot_unchanged"] == _snapshot()
    # null = 删除公开字段，不回落原始值
    assert projection["source"]["company"] is None
    assert projection["source"]["source_url"] is None
    assert projection["source"]["round"] == "一面（技术）"
    item = projection["items"][0]
    assert item["item_id"] == 11
    assert item["question"] == "数据库索引的工作原理是什么？"
    assert [i["item_id"] for i in projection["items"]] == [11]
    assert projection["excluded_item_ids"] == [12]


def test_preview_and_materialization_share_one_constructor():
    request = _review_request(
        {
            "expected_revision": 3,
            "review_fields": {"source": {"company": "某公司"}},
        }
    )
    projection = build_review_projection(
        snapshot=_snapshot(), items=_items(), request=request, reviewer_id=201
    )
    conn = _db()
    public_interview_id, detail_ids = materialize_public_interview_from_projection(
        conn, projection, source_id=1, requester_id=101
    )
    row = conn.execute("SELECT * FROM interview WHERE id = ?", (public_interview_id,)).fetchone()
    # 物化字段与投影一致
    assert row["company"] == "某公司"
    # 未显式确认的可识别来源字段一律不公开（不继承 snapshot、不回读 source）
    assert (row["round"] or "") == "", "round 未确认公开时必须为空"
    assert (row["url"] or "") == "", "source_url 未确认公开时必须为空"
    conn.close()


def test_materialization_never_fills_from_source_snapshot():
    request = _review_request({"expected_revision": 1, "review_fields": {"source": {}}})
    projection = build_review_projection(
        snapshot=_snapshot(), items=_items(), request=request, reviewer_id=201
    )
    conn = _db()
    public_interview_id, detail_ids = materialize_public_interview_from_projection(
        conn, projection, source_id=1, requester_id=101
    )
    row = conn.execute("SELECT * FROM interview WHERE id = ?", (public_interview_id,)).fetchone()
    # 未确认的来源字段全部不得公开
    assert not row["company"]
    assert not row["round"]
    assert not row["url"]
    detail = conn.execute(
        "SELECT * FROM questions_detail WHERE id = ?", (detail_ids[0],)
    ).fetchone()
    assert detail["company"] in (None, "", "未提供")
    conn.close()


def test_blank_review_value_normalizes_to_deletion():
    request = _review_request(
        {
            "expected_revision": 1,
            "review_fields": {"source": {"company": "   ", "focus": "数据库"}},
        }
    )
    projection = build_review_projection(
        snapshot=_snapshot(), items=_items(), request=request, reviewer_id=201
    )
    assert projection["source"]["company"] is None
    assert projection["source"]["focus"] == "数据库"


def test_unknown_item_id_from_other_request_is_rejected():
    request = _review_request(
        {
            "expected_revision": 1,
            "review_fields": {"items": [{"item_id": 999, "question": "x"}]},
        }
    )
    with pytest.raises(ValueError):
        build_review_projection(
            snapshot=_snapshot(), items=_items(), request=request, reviewer_id=201
        )


def test_unreviewed_item_inherits_snapshot_but_still_excludes_sensitive_source():
    request = _review_request({"expected_revision": 1, "review_fields": {}})
    projection = build_review_projection(
        snapshot=_snapshot(), items=_items(), request=request, reviewer_id=201
    )
    item = projection["items"][0]
    assert item["question"] == "说明数据库索引的工作原理"
    # 来源字段不随题干继承
    assert "company" not in item


def test_projection_has_hash_and_reviewer():
    request = _review_request({"expected_revision": 1, "review_fields": {}})
    projection = build_review_projection(
        snapshot=_snapshot(), items=_items(), request=request, reviewer_id=201
    )
    assert projection["schema_version"] == 1
    assert projection["reviewer_id"] == 201
    assert projection["hash"]
    # 同输入 hash 稳定
    again = build_review_projection(
        snapshot=_snapshot(), items=_items(), request=request, reviewer_id=201
    )
    assert again["hash"] == projection["hash"]


def _nested_snapshot():
    """真实快照结构：{source: {...}, items: [...]}（R11）。"""

    return {
        "source": {
            "company": "PRIVATE公司",
            "round": "一面",
            "focus": "数据库",
            "source_url": "https://secret.example.com/post/1",
            "season": "2026春招",
            "difficulty": "中等",
            "job_position": "后端开发",
        },
        "items": _items(),
    }


def test_projection_inherits_non_sensitive_defaults_from_nested_source(R11_bug=None):
    """R11：真实嵌套快照下，非敏感来源字段从 source 层级继承（曾读错层级全变 None）。"""

    request = _review_request({"expected_revision": 1, "review_fields": {}})
    projection = build_review_projection(
        snapshot=_nested_snapshot(), items=_items(), request=request, reviewer_id=201
    )
    # 非敏感字段继承 source 层级
    assert projection["source"]["focus"] == "数据库"
    assert projection["source"]["season"] == "2026春招"
    assert projection["source"]["difficulty"] == "中等"
    # 敏感字段未显式确认默认不公开
    assert projection["source"]["company"] is None
    assert projection["source"]["round"] is None
    assert projection["source"]["source_url"] is None


def test_jd_approve_materializes_jd_not_interview():
    """R11：v2 批准 JD 只产生公共 jd，绝不走面经/题目分支；岗位信息保留。"""

    from app.models.upload_contracts import build_review_projection_request
    from app.services.public_contributions import (
        approve_public_contribution_v2,
        create_public_contribution_request,
    )

    conn = _db()
    conn.execute(
        "INSERT INTO jd (id, url, company, job_position, job_title, tech_stack, owner_id, status) "
        "VALUES (50, 'https://private.example.com/jd/1', 'PRIVATE公司', '后端开发', '资深后端', 'Go', 101, 'approved')"
    )
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    conn.commit()

    request = create_public_contribution_request(conn, "jd", 50, 101)
    request_id = request["id"]
    assert request["source_type"] == "jd"

    review_request = build_review_projection_request(
        {
            "expected_revision": 1,
            "review_fields": {
                "source": {
                    "company": "某公司",
                    "job_title": "资深后端工程师",
                    "tech_stack": "Go",
                    "bonus": "SQL 与分布式系统",
                    "position": "后端开发",
                    "source_url": "https://public.example.com/jd/1",
                }
            },
        },
        source_type="jd",
    )
    approval = approve_public_contribution_v2(
        conn,
        request_id=request_id,
        admin_id=201,
        review_request=review_request,
    )
    assert approval["public_jd_id"]
    assert approval["status"] == "published"

    # 只产生公共 JD，不产生面经/题目
    assert conn.execute("SELECT COUNT(*) FROM interview").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM questions_detail").fetchone()[0] == 0
    jd_row = conn.execute("SELECT * FROM jd WHERE id = ?", (approval["public_jd_id"],)).fetchone()
    assert jd_row["owner_id"] is None
    assert jd_row["company"] == "某公司"
    assert jd_row["job_title"] == "资深后端工程师"
    assert jd_row["bonus"] == "SQL 与分布式系统"
    assert jd_row["url"] == "https://public.example.com/jd/1"
    # 岗位信息保留（R11）
    assert (jd_row["job_position"] or "") == "后端开发"

    # 申请 item 标记 published
    item = conn.execute(
        "SELECT status FROM public_contribution_items WHERE request_id = ?", (request_id,)
    ).fetchone()
    assert item["status"] == "published"
    request_row = conn.execute(
        "SELECT * FROM public_contribution_requests WHERE id = ?", (request_id,)
    ).fetchone()
    assert request_row["public_jd_id"] == approval["public_jd_id"]
    assert request_row["status"] == "published"

    event_count = conn.execute(
        "SELECT COUNT(*) FROM public_contribution_events WHERE request_id = ?", (request_id,)
    ).fetchone()[0]
    jd_count = conn.execute("SELECT COUNT(*) FROM jd WHERE owner_id IS NULL").fetchone()[0]
    repeated_approval = approve_public_contribution_v2(
        conn,
        request_id=request_id,
        admin_id=201,
        review_request=review_request,
        expected_revision=approval["revision"],
    )
    assert repeated_approval["status"] == "published"
    assert repeated_approval["public_jd_id"] == approval["public_jd_id"]
    assert repeated_approval["revision"] == approval["revision"]
    assert conn.execute(
        "SELECT COUNT(*) FROM public_contribution_events WHERE request_id = ?", (request_id,)
    ).fetchone()[0] == event_count
    assert conn.execute("SELECT COUNT(*) FROM jd WHERE owner_id IS NULL").fetchone()[0] == jd_count

    conflicting_review = build_review_projection_request(
        {
            "expected_revision": approval["revision"],
            "review_fields": {"source": {"company": "某公司", "bonus": "changed projection"}},
        },
        source_type="jd",
    )
    from app.services.public_contributions import StateConflict
    import pytest

    with pytest.raises(StateConflict):
        approve_public_contribution_v2(
            conn,
            request_id=request_id,
            admin_id=201,
            review_request=conflicting_review,
            expected_revision=approval["revision"],
        )
    conn.close()


def test_interview_approve_keeps_snapshot_job_position():
    """R11：面经批准物化时岗位从源冻结，不因审查丢失。"""

    from app.models.upload_contracts import build_review_projection_request
    from app.services.public_contributions import (
        approve_public_contribution_v2,
        create_public_contribution_request,
    )

    conn = _db()
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, company, job_position, owner_id, status) "
        "VALUES (60, 'https://private.example.com/i/1', 'PRIVATE公司', '后端开发', 101, 'approved')"
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2, owner_id) "
        "VALUES (61, 60, '说明数据库索引的工作原理', '数据库', '索引', 101)"
    )
    conn.commit()

    request = create_public_contribution_request(conn, "interview", 60, 101)
    request_id = request["id"]
    approval = approve_public_contribution_v2(
        conn,
        request_id=request_id,
        admin_id=201,
        review_request=build_review_projection_request(
            {"expected_revision": 1, "review_fields": {"source": {"company": "某公司"}}},
            source_type="interview",
        ),
    )
    row = conn.execute(
        "SELECT * FROM interview WHERE id = ?", (approval["public_interview_id"],)
    ).fetchone()
    # 岗位从源快照冻结
    assert (row["job_position"] or "") == "后端开发"
    # 未确认敏感字段不公开
    assert (row["company"] or "") == "某公司"
    assert (row["round"] or "") == ""
    assert (row["url"] or "") == ""
    conn.close()


def test_v2_materialize_reuses_same_url_public_interview():
    """R10/AC-016：同 URL 已有公共面经时复用不重复建（追加贡献一致）。"""

    from app.models.upload_contracts import build_review_projection_request
    from app.services.public_contributions import (
        approve_public_contribution_v2,
        create_public_contribution_request,
    )

    conn = _db()
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    # 已存在的公共面经（同 URL）
    conn.execute(
        "INSERT INTO interview (id, url, company, job_position, owner_id, status) "
        "VALUES (900, 'https://shared.example.com/i/1', '旧公司', '后端开发', NULL, 'approved')"
    )
    # 私人申请（同 URL 追加）
    conn.execute(
        "INSERT INTO interview (id, url, company, job_position, owner_id, status) "
        "VALUES (70, 'https://shared.example.com/i/1', 'PRIVATE公司', '后端开发', 101, 'approved')"
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2, owner_id) "
        "VALUES (71, 70, 'Redis 持久化机制', '数据库', 'Redis', 101)"
    )
    conn.commit()

    request = create_public_contribution_request(conn, "interview", 70, 101)
    approval = approve_public_contribution_v2(
        conn,
        request_id=request["id"],
        admin_id=201,
        review_request=build_review_projection_request(
            {
                "expected_revision": 1,
                "review_fields": {
                    "source": {"company": "某公司", "source_url": "https://shared.example.com/i/1"}
                },
            },
            source_type="interview",
        ),
    )
    # 复用公共面经 900，不新建
    assert approval["public_interview_id"] == 900
    # 追加的明细挂到公共面经下
    detail = conn.execute(
        "SELECT id, interview_id, company FROM questions_detail "
        "WHERE interview_id = 900 AND question = 'Redis 持久化机制'"
    ).fetchone()
    assert detail is not None
    assert detail["company"] == "某公司"
    conn.close()


def test_second_contribution_from_same_source_only_snapshots_new_questions():
    """AC-016: a later contribution must add new source items without re-publishing old ones."""

    from app.services.public_contributions import create_public_contribution_request

    conn = _db()
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status) "
        "VALUES (80, 'https://shared.example.com/i/2', 101, 'approved')"
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, owner_id, status) "
        "VALUES (81, 80, 'AC016 question A', 101, 'approved')"
    )
    conn.commit()

    first = create_public_contribution_request(conn, "interview", 80, 101)
    first_item = conn.execute(
        "SELECT id FROM public_contribution_items WHERE request_id = ?",
        (first["id"],),
    ).fetchone()
    conn.execute(
        "UPDATE public_contribution_items SET status = 'published' WHERE id = ?",
        (first_item["id"],),
    )
    conn.execute(
        "UPDATE public_contribution_requests SET status = 'published' WHERE id = ?",
        (first["id"],),
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, owner_id, status) "
        "VALUES (82, 80, 'AC016 question B', 101, 'approved')"
    )
    conn.commit()

    second = create_public_contribution_request(conn, "interview", 80, 101)
    second_items = conn.execute(
        "SELECT id, source_item_id, snapshot_json FROM public_contribution_items "
        "WHERE request_id = ? ORDER BY ordinal",
        (second["id"],),
    ).fetchall()

    assert second["id"] != first["id"]
    assert second["summary"]["item_count"] == 1
    assert len(second_items) == 1
    assert int(second_items[0]["id"]) != int(first_item["id"])
    assert int(second_items[0]["source_item_id"]) == 82
    assert "AC016 question B" in second_items[0]["snapshot_json"]
    conn.close()


def test_partially_published_items_are_not_resubmitted_as_new_contribution():
    """A failed item with an existing public detail must use admin retry, not a duplicate request."""

    from app.services.public_contributions import create_public_contribution_request

    conn = _db()
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status) "
        "VALUES (80, 'https://shared.example.com/i/3', 101, 'approved')"
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, owner_id, status) "
        "VALUES (81, 80, 'AC016 published A', 101, 'approved'), "
        "(82, 80, 'AC016 failed B', 101, 'approved')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status) "
        "VALUES (90, 'https://shared.example.com/i/3', NULL, 'approved')"
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, owner_id, status) "
        "VALUES (91, 90, 'AC016 published A', NULL, 'approved'), "
        "(92, 90, 'AC016 failed B', NULL, 'approved')"
    )
    conn.commit()

    previous = create_public_contribution_request(conn, "interview", 80, 101)
    item_a, item_b = conn.execute(
        "SELECT id, source_item_id FROM public_contribution_items "
        "WHERE request_id = ? ORDER BY ordinal",
        (previous["id"],),
    ).fetchall()
    conn.execute(
        "UPDATE public_contribution_items SET status = 'published', public_detail_id = 91 "
        "WHERE id = ?",
        (item_a["id"],),
    )
    conn.execute(
        "UPDATE public_contribution_items SET status = 'failed', public_detail_id = 92 "
        "WHERE id = ?",
        (item_b["id"],),
    )
    conn.execute(
        "UPDATE public_contribution_requests SET status = 'partially_published' WHERE id = ?",
        (previous["id"],),
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, owner_id, status) "
        "VALUES (83, 80, 'AC016 new C', 101, 'approved')"
    )
    conn.commit()

    next_request = create_public_contribution_request(conn, "interview", 80, 101)
    next_items = conn.execute(
        "SELECT source_item_id FROM public_contribution_items WHERE request_id = ?",
        (next_request["id"],),
    ).fetchall()

    assert next_request["id"] != previous["id"]
    assert [int(row["source_item_id"]) for row in next_items] == [83]
    assert int(item_b["source_item_id"]) == 82
    conn.close()


def test_withdrawn_rejected_item_can_be_shared_again():
    """AC-016: withdrawal releases unpublished source items for a later request."""

    from app.services.public_contributions import create_public_contribution_request

    conn = _db()
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status) "
        "VALUES (80, 'https://shared.example.com/i/withdrawn', 101, 'approved')"
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, owner_id, status) "
        "VALUES (81, 80, 'AC016 withdrawn question', 101, 'approved')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status) "
        "VALUES (90, 'https://shared.example.com/i/withdrawn', NULL, 'approved')"
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, owner_id, status) "
        "VALUES (91, 90, 'AC016 withdrawn question', NULL, 'approved')"
    )
    conn.commit()

    withdrawn = create_public_contribution_request(conn, "interview", 80, 101)
    conn.execute(
        "UPDATE public_contribution_items SET status = 'rejected', public_detail_id = 91 "
        "WHERE request_id = ?",
        (withdrawn["id"],),
    )
    conn.execute(
        "UPDATE public_contribution_requests SET status = 'withdrawn' WHERE id = ?",
        (withdrawn["id"],),
    )
    conn.commit()

    next_request = create_public_contribution_request(conn, "interview", 80, 101)
    next_items = conn.execute(
        "SELECT source_item_id FROM public_contribution_items WHERE request_id = ?",
        (next_request["id"],),
    ).fetchall()

    assert next_request["id"] != withdrawn["id"]
    assert [int(row["source_item_id"]) for row in next_items] == [81]
    conn.close()
