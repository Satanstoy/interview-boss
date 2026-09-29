"""AC-020 / UR-020：审批与撤回互斥（CAS + 同事务副作用）。

契约（contracts.md §3.2）：

- approve/withdraw 在读取当前状态前持写事务，并校验 ``expected_revision``；
  ``UPDATE ... WHERE revision=?`` 行数不为 1 → ``STATE_CONFLICT``；
- withdraw 成功后不得留下该申请新建的可执行公共工作；
- 重复请求不追加重复事件或公开实体；事务失败必须回滚状态、事件与工作。
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from app.db.migrations import run_migrations
from app.models.upload_contracts import build_review_projection_request
from app.services.public_contributions import (
    StateConflict,
    approve_public_contribution_v2,
    withdraw_public_contribution_v2,
)


def _connect(path, migrate=True):
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if migrate:
        run_migrations(conn)
    return conn


def _seed(conn):
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')")
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (201, 'admin', 'x')")
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (1, 'https://a.example.com/1', 'A', '一面', '1.x', 101, 'approved', '后端')"
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2) "
        "VALUES (11, 1, 'TCP 三次握手', '网络', 'TCP')"
    )
    conn.execute(
        "INSERT INTO public_contribution_requests "
        "(id, source_type, source_id, requester_id, status, snapshot_json, revision) "
        "VALUES (1, 'interview', 1, 101, 'pending_review', ?, 1)",
        (
            '{"company": "PRIVATE", "round": "一面", "source_url": "https://a.example.com/1", "items": [{"item_id": 11, "ordinal": 1, "question": "TCP 三次握手", "cat1": "网络", "cat2": "TCP"}]}',
        ),
    )
    conn.execute(
        "INSERT INTO public_contribution_items "
        "(id, request_id, source_item_type, source_item_id, ordinal, status, snapshot_json) "
        "VALUES (11, 1, 'question', 11, 1, 'pending_review', "
        '\'{"item_id": 11, "ordinal": 1, "question": "TCP 三次握手", "cat1": "网络", "cat2": "TCP"}\')'
    )
    conn.commit()
    return conn


def _request(payload=None):
    return build_review_projection_request(
        payload or {"expected_revision": 1, "review_fields": {}}, source_type="interview"
    )


def test_approve_requires_matching_expected_revision(tmp_path):
    conn = _connect(str(tmp_path / "cas.db"))
    _seed(conn)
    with pytest.raises(StateConflict):
        approve_public_contribution_v2(
            conn,
            request_id=1,
            admin_id=201,
            review_request=_request({"expected_revision": 99}),
        )
    assert (
        conn.execute("SELECT status FROM public_contribution_requests WHERE id = 1").fetchone()[
            "status"
        ]
        == "pending_review"
    )
    conn.close()


def test_withdraw_removes_public_work_created_by_request(tmp_path):
    conn = _connect(str(tmp_path / "w.db"))
    _seed(conn)
    # 模拟该申请已排入的可执行公共工作（上一次尝试留下的队列）
    conn.execute(
        "INSERT INTO analysis_queue (interview_id, question_detail_id, owner_id, status, "
        "contribution_request_id) VALUES (1, 11, NULL, 'pending', 1)"
    )
    conn.commit()

    withdrawn = withdraw_public_contribution_v2(
        conn, request_id=1, requester_id=101, expected_revision=1
    )
    assert withdrawn["status"] == "withdrawn"
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM analysis_queue WHERE contribution_request_id = 1 AND status = 'pending'"
        ).fetchone()[0]
        == 0
    ), "撤回成功后不得留下可执行公共工作"
    conn.close()


def test_withdraw_after_approve_conflicts(tmp_path):
    conn = _connect(str(tmp_path / "wa.db"))
    _seed(conn)
    approved = approve_public_contribution_v2(
        conn, request_id=1, admin_id=201, review_request=_request()
    )
    with pytest.raises(StateConflict):
        withdraw_public_contribution_v2(
            conn,
            request_id=1,
            requester_id=101,
            expected_revision=approved["revision"],
        )
    assert (
        conn.execute("SELECT status FROM public_contribution_requests WHERE id = 1").fetchone()[
            "status"
        ]
        == "approved_for_processing"
    )
    conn.close()


def test_repeated_approve_does_not_duplicate_events(tmp_path):
    conn = _connect(str(tmp_path / "dup.db"))
    _seed(conn)
    first = approve_public_contribution_v2(
        conn, request_id=1, admin_id=201, review_request=_request()
    )
    events_after_first = conn.execute(
        "SELECT COUNT(*) FROM public_contribution_events WHERE request_id = 1"
    ).fetchone()[0]
    # 同 revision 重复批准：不新增事件，不新建公开实体
    again = approve_public_contribution_v2(
        conn,
        request_id=1,
        admin_id=201,
        review_request=_request(),
        expected_revision=first["revision"],
    )
    assert again["status"] == "approved_for_processing"
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM public_contribution_events WHERE request_id = 1"
        ).fetchone()[0]
        == events_after_first
    )
    conn.close()


def test_concurrent_approve_and_withdraw_only_one_wins(tmp_path):
    db_path = str(tmp_path / "race.db")
    setup = _connect(db_path)
    _seed(setup)
    setup.close()

    results: dict[str, str] = {}
    errors: dict[str, Exception] = {}

    def _approve():
        conn = _connect(db_path, migrate=False)
        try:
            row = approve_public_contribution_v2(
                conn, request_id=1, admin_id=201, review_request=_request()
            )
            results["approve"] = row["status"]
        except Exception as exc:
            errors["approve"] = exc
            results["approve"] = "failed"
        finally:
            conn.close()

    def _withdraw():
        conn = _connect(db_path, migrate=False)
        try:
            row = withdraw_public_contribution_v2(
                conn, request_id=1, requester_id=101, expected_revision=1
            )
            results["withdraw"] = row["status"]
        except Exception as exc:
            errors["withdraw"] = exc
            results["withdraw"] = "failed"
        finally:
            conn.close()

    threads = [threading.Thread(target=_approve), threading.Thread(target=_withdraw)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    succeeded = [key for key, value in results.items() if value != "failed"]
    assert len(succeeded) == 1, f"只能有一个成功: {results}"
    conn = _connect(db_path, migrate=False)
    final = conn.execute("SELECT status FROM public_contribution_requests WHERE id = 1").fetchone()[
        "status"
    ]
    if results["withdraw"] == "withdrawn":
        assert final == "withdrawn"
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM analysis_queue WHERE contribution_request_id = 1 AND status = 'pending'"
            ).fetchone()[0]
            == 0
        )
    else:
        assert final == "approved_for_processing"
    conn.close()


def test_failed_transaction_rolls_back_state_event_and_work(tmp_path):
    """物化失败：状态、事件、公共工作全部回滚。"""

    conn = _connect(str(tmp_path / "fail.db"))
    _seed(conn)
    original = None
    import app.services.public_contributions as pc

    original = pc.materialize_public_interview_from_projection

    def boom(*args, **kwargs):
        raise RuntimeError("materialize failed")

    pc.materialize_public_interview_from_projection = boom
    try:
        with pytest.raises(RuntimeError):
            approve_public_contribution_v2(
                conn, request_id=1, admin_id=201, review_request=_request()
            )
    finally:
        pc.materialize_public_interview_from_projection = original

    assert (
        conn.execute(
            "SELECT status, revision FROM public_contribution_requests WHERE id = 1"
        ).fetchone()["status"]
        == "pending_review"
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM public_contribution_events WHERE request_id = 1"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM analysis_queue WHERE contribution_request_id = 1"
        ).fetchone()[0]
        == 0
    )
    conn.close()
