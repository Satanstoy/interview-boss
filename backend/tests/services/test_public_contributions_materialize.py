"""公共化申请物化的隐私边界与调度归属回归测试（audit 2026-08-24 D5/D4）。"""

from unittest.mock import AsyncMock, patch

import pytest


def _seed_user(conn, user_id: int, username: str):
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (?, ?, 'hash')",
        (user_id, username),
    )


def test_public_jd_materialization_uses_field_allowlist(test_db):
    """JD 公开物化必须走字段白名单：快照里的非白名单列不得被连带公开。"""
    # 模拟未来 schema 演进：jd 表新增私有列
    test_db.execute("ALTER TABLE jd ADD COLUMN internal_notes TEXT")
    _seed_user(test_db, 7, "jd-owner")
    _seed_user(test_db, 9, "jd-admin")
    test_db.execute(
        "INSERT INTO jd (id, url, company, season, owner_id, status, job_position,"
        " tech_stack, source, position, salary, job_title, internal_notes)"
        " VALUES (1, 'https://example.com/jd1', '示例公司', '2026秋招', 7, 'approved',"
        " '后端', 'Python/Go', '原始JD全文', '高级工程师', '30k', '后端开发',"
        " '私密备注：内推联系人 138xxxx')",
    )
    test_db.commit()

    from app.services.public_contributions import (
        approve_public_contribution,
        create_public_contribution_request,
    )

    request = create_public_contribution_request(test_db, "jd", 1, 7)
    result = approve_public_contribution(test_db, request["id"], 9)

    assert result["status"] == "published"
    public_id = result["public_jd_id"]
    assert public_id and public_id != 1
    row = test_db.execute("SELECT * FROM jd WHERE id = ?", (public_id,)).fetchone()
    assert row["owner_id"] is None
    assert row["status"] == "approved"
    assert row["deleted_at"] is None
    # 白名单字段照常公开
    assert row["url"] == "https://example.com/jd1"
    assert row["company"] == "示例公司"
    assert row["tech_stack"] == "Python/Go"
    assert row["source"] == "原始JD全文"
    assert row["position"] == "高级工程师"
    assert row["salary"] == "30k"
    assert row["job_title"] == "后端开发"
    assert row["season"] == "2026秋招"
    # 非白名单字段绝不外泄
    assert row["internal_notes"] is None


@pytest.mark.asyncio
async def test_finalize_approval_schedules_cluster_batch_in_service(test_db):
    """聚类调度属于服务层职责：finalize 包装器负责触发，路由层不再触碰 pipeline。"""
    _seed_user(test_db, 7, "iv-owner")
    _seed_user(test_db, 9, "iv-admin")
    test_db.execute(
        "INSERT INTO interview (id, url, company, owner_id, status)"
        " VALUES (1, 'https://example.com/iv1', '示例公司', 7, 'approved')"
    )
    test_db.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, cat1, cat2,"
        " owner_id, status) VALUES (11, 1, 'https://example.com/iv1',"
        " '讲讲 MySQL 索引原理', '技术考察', '数据库', 7, 'approved')"
    )
    test_db.commit()

    from app.services import public_contributions as svc

    request = svc.create_public_contribution_request(test_db, "interview", 1, 7)

    scheduler = AsyncMock(return_value=True)
    with (
        patch(
            "app.core.outbound_url.assert_safe_outbound_url_sync",
            side_effect=lambda url, **_: url,
        ),
        patch.object(svc, "_run_cluster_batch_in_background", scheduler),
    ):
        result = await svc.finalize_public_contribution_approval(request["id"], 9)

    assert result["status"] == "queued"
    assert result["public_interview_id"]
    assert result.get("cluster_scheduled") is True
    scheduler.assert_awaited_once_with(user_id=9)
