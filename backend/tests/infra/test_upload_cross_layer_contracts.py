"""跨层契约对账：前端实际发送/读取的形状，必须被后端实际接受/提供。

为什么单独存在这一层测试：2026-09-29 spec 的多处缺陷不是"没人实现"，而是
**后端与前端各自自洽、两侧从未对账**——在各自的单测里全绿，在真实链路上功能死：

- 前端发 ``position_id = users.current_position_id``（整数 ID），后端拿它去比
  ``interview.job_position``（TEXT 岗位名称）；
- 前端读 ``task.interview_id``，后端快照只提供 ``result.interview_id``；
- worker 从 policy 取 ``write_scope``（private/public），JD 节点却判 ``target == "personal"``；
- 审批事务内即物化 ``status='approved' AND owner_id IS NULL`` 的公共面经，
  而公开读取谓词没有发布门槛。

这些用例只断言**跨层一致**，不复制任何一侧的当前实现假设。它们当前应为红；
修复后转绿。禁止为了让它们通过而放宽断言或改成单侧断言。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def as_user(client):
    """以指定认证主体发起请求（业务层不得 mock 为直接成功）。"""

    from app.asgi import app
    from app.core.auth import get_current_user

    def _install(uid: int, is_admin: int = 0):
        app.dependency_overrides[get_current_user] = lambda: {
            "id": int(uid),
            "username": f"u{uid}",
            "is_admin": int(is_admin),
        }

    try:
        yield _install
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ── CT-1：岗位筛选契约（AC-002 / F02 / R09）─────────────────────────────


def test_interview_list_accepts_the_position_id_the_frontend_sends(client, test_db, as_user):
    """前端契约：``position_id`` 传 ``current_position_id``。

    来源：``frontend/src/layouts/AuthenticatedLayout.vue`` 用
    ``currentUser.current_position_id`` 赋值，``useMasterBankData.fetchInterviewPage``
    以 ``position_id`` 发出。服务端必须把该值解析为岗位后返回该岗位记录；
    当前实现直接拿它比 ``interview.job_position``（名称列），正常用户的面经库为空。
    """

    # users.current_position_id 有 FK 到 job_positions(id)，岗位必须先建
    test_db.execute("INSERT INTO job_positions (id, name) VALUES (1, '后端开发')")
    test_db.execute(
        "INSERT INTO users (id, username, password_hash, is_admin, current_position_id) "
        "VALUES (101, 'u101', 'x', 0, 1)"
    )
    for i in range(3):
        test_db.execute(
            "INSERT INTO interview (id, url, company, round, questions_list, owner_id, "
            "status, job_position, season, created_at) "
            "VALUES (?, ?, '公司', '一面', '1.x', 101, 'approved', '后端开发', "
            "'2026春招', '2026-09-29 10:00:00')",
            (1000 + i, f"https://a.example.com/{1000 + i}"),
        )
    test_db.commit()

    as_user(101)
    resp = client.get(
        "/api/data/interview?file_type=interview&page=1&page_size=20"
        "&sort=created_at_desc&position_id=1"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3, (
        "前端按 current_position_id 过滤，服务端必须返回该岗位记录；"
        "否则真实用户的面经库会渲染 0 条"
    )


# ── CT-2：任务中心结果定位契约（AC-001 / F01 / D5）────────────────────


def _insert_completed_root(test_db, *, interview_id):
    test_db.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES (101, 'u101', 'x', 0)"
    )
    test_db.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, status, interview_id) "
        "VALUES ('imp-ct2', 101, 'key-ct2', 'hash-ct2', 'private', 'interview', "
        "'upload-pipeline-v1', '{}', 'completed', ?)",
        (interview_id,),
    )
    test_db.commit()
    return test_db.execute(
        "SELECT * FROM upload_imports WHERE id = 'imp-ct2'"
    ).fetchone()


def test_completed_root_snapshot_is_serializable(test_db):
    """已完成任务必须能构造快照。

    ``_snapshot`` 把 ``result`` 交给 ``UploadResultDTO``（``extra="forbid"``），
    多传字段会让列表/详情/by-key/SSE/retry **全部 500**——恰好是任务中心要展示的
    那些"已完成"任务。
    """

    from app.routers.upload_imports import _snapshot

    row = _insert_completed_root(test_db, interview_id=555)
    snapshot = _snapshot(row, conn=test_db)
    assert snapshot["result"]["interview_id"] == 555
    assert snapshot["status"] == "completed"


def test_task_center_reads_an_interview_id_field_the_snapshot_provides(
    client, test_db, as_user
):
    """前端 ``openResult`` 读取的字段必须真实存在于服务端快照。

    从 ``UploadTaskCenter.vue`` 源码提取实际读取路径，再用真实 HTTP 快照校验，
    避免测试自己编造顶层 ``interview_id`` 造成假绿。
    """

    source = (
        PROJECT_ROOT / "frontend/src/components/business/UploadTaskCenter.vue"
    ).read_text(encoding="utf-8")
    body = re.search(r"async function openResult\(task\)\s*\{(?P<body>.*?)\n\}", source, re.S)
    assert body, "openResult 结构变化，契约测试需要同步更新"
    read = re.search(r"task((?:\.[A-Za-z_]\w*)+)", body.group("body"))
    assert read, "openResult 未读取任务字段"
    keys = [part for part in read.group(1).split(".") if part]

    _insert_completed_root(test_db, interview_id=555)

    as_user(101)
    resp = client.get("/api/upload-imports/imp-ct2")
    assert resp.status_code == 200
    snapshot = resp.json()

    cursor = snapshot
    for key in keys:
        assert isinstance(cursor, dict) and key in cursor, (
            f"任务中心读取 task.{'.'.join(keys)}，但快照中没有该字段；"
            f"实际快照顶层字段：{sorted(snapshot)}"
        )
        cursor = cursor[key]
    assert cursor == 555, "结果定位必须指向真实 interview_id"


# ── CT-3：私人 JD 归属契约（AC-024 / E6）──────────────────────────────


async def test_private_jd_import_keeps_the_requester_as_owner(client, test_db):
    """worker 传 ``write_scope``（private/public），JD 节点必须按同一词表判定。

    当前 JD 节点判 ``target == "personal"``，v2 永远取不到该值，导致普通用户的
    私人 JD 落成 ``owner_id=NULL / status='pending'``（自己看不到自己的 JD）。
    """

    from app.agents.submit.persist_personal import jd_persist_node

    test_db.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES (101, 'u101', 'x', 0)"
    )
    test_db.commit()

    state = {
        "user_id": 101,
        "is_admin": False,
        # 与 worker 从 policy 派生的取值一致（upload_policy.write_scope）
        "target": "private",
        "saved_url": "https://jd.example.com/private-1",
        "season": "2026春招",
        "job_position": "后端开发",
        "extracted_data": {
            "公司": "某公司",
            "岗位名称": "后端开发",
            "薪资范围": "20k-30k",
            "核心技术要求": ["Python"],
            "加分项": "无",
        },
        "request_public_review": False,
    }

    await jd_persist_node(state)

    row = test_db.execute(
        "SELECT owner_id, status FROM jd ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "私人 JD 必须落库"
    assert row["owner_id"] == 101, (
        "私人 JD 必须归属提交者；owner_id 为空等于把用户私人 JD 当成公共待审数据"
    )
    assert row["status"] == "approved", "私人 JD 不需要公共审核状态"


# ── CT-4：发布门槛契约（AC-015 / E3 / E7）─────────────────────────────


def test_queued_public_contribution_is_not_readable_publicly(client, test_db, as_user):
    """审批通过 ≠ published：公共处理未完成的申请不得出现在公开读取接口。

    README §5.3：``public_interview/questions_detail`` 在处理完成前不能被普通
    用户的面经、搜索、统计、来源接口查询出来。
    """

    from app.models.upload_contracts import build_review_projection_request
    from app.services.public_contributions import (
        approve_public_contribution_v2,
        create_public_contribution_request,
    )

    for uid, is_admin in ((101, 0), (102, 0), (201, 1)):
        test_db.execute(
            "INSERT INTO users (id, username, password_hash, is_admin) "
            "VALUES (?, ?, 'x', ?)",
            (uid, f"u{uid}", is_admin),
        )
    test_db.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, "
        "status, job_position, season, created_at) "
        "VALUES (500, 'https://private.example.com/1', '私有公司', '一面', '1.a', 101, "
        "'approved', '后端开发', '2026春招', '2026-09-29 10:00:00')"
    )
    for ordinal, question in enumerate(["题目A", "题目B"], start=1):
        test_db.execute(
            "INSERT INTO questions_detail (interview_id, question, cat1, cat2, "
            "source_ordinal, job_position) VALUES (500, ?, '后端', '基础', ?, '后端开发')",
            (question, ordinal),
        )
    test_db.commit()

    request = create_public_contribution_request(test_db, "interview", 500, 101)
    # _serialize_request 不返回 revision，直接从落库行读取 CAS 前置条件
    request_revision = test_db.execute(
        "SELECT revision FROM public_contribution_requests WHERE id = ?",
        (request["id"],),
    ).fetchone()["revision"]
    review_request = build_review_projection_request(
        {
            "expected_revision": request_revision,
            "excluded_item_ids": [],
            "review_fields": {},
        },
        source_type="interview",
    )
    result = approve_public_contribution_v2(
        test_db, request_id=request["id"], admin_id=201, review_request=review_request
    )
    public_interview_id = result["public_interview_id"]
    assert public_interview_id, "批准后应产生公共面经实体"

    queued = test_db.execute(
        "SELECT COUNT(*) FROM public_contribution_items "
        "WHERE request_id = ? AND status = 'queued'",
        (request["id"],),
    ).fetchone()[0]
    assert queued > 0, "批准后子项应处于待处理状态，而不是已发布"

    as_user(102)
    body = client.get(
        "/api/data/interview?file_type=interview&page=1&page_size=50"
        "&scope=public&position_id=后端开发"
    ).json()
    visible_ids = [item["id"] for item in body["items"]]
    assert public_interview_id not in visible_ids, (
        "公共处理尚未完成的申请不得被普通用户读取（审批通过不等于已发布）"
    )
