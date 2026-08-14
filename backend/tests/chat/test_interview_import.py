import hashlib
import json

import pytest


def _create_user(conn, username: str) -> int:
    cursor = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, "test-hash"),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _chunk(stream_type: str, index: int, total: int, content: str) -> dict:
    return {
        "stream_type": stream_type,
        "chunk_index": index,
        "total_chunks": total,
        "content": content,
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


@pytest.fixture
def imported_transcript():
    return json.dumps(
        [
            {
                "sequence": 1,
                "speaker": "interviewer",
                "content": "模型参数量是多少？",
                "question_id": 1,
            },
            {
                "sequence": 2,
                "speaker": "candidate",
                "content": "我会先确认模型版本和参数口径。",
            },
        ],
        ensure_ascii=False,
    )


def test_import_is_resumable_and_idempotent(test_db, imported_transcript):
    from app.services.interview_import_service import (
        complete_import,
        get_import_status,
        start_import,
        upload_import_chunk,
    )

    user_id = _create_user(test_db, "import-owner")
    started = start_import(
        user_id,
        client_request_id="gpt-session-1",
        title="GPT 模拟面试",
        context={"job_position": "大模型应用开发", "company": "蚂蚁国际"},
    )
    repeated = start_import(
        user_id,
        client_request_id="gpt-session-1",
        title="should not replace",
        context={"job_position": "other"},
    )
    assert repeated["import_id"] == started["import_id"]

    first = imported_transcript[:20]
    second = imported_transcript[20:]
    one = upload_import_chunk(
        user_id, started["import_id"], **_chunk("turns", 0, 2, first)
    )
    duplicate = upload_import_chunk(
        user_id, started["import_id"], **_chunk("turns", 0, 2, first)
    )
    assert one["accepted"] is True
    assert duplicate["idempotent"] is True

    upload_import_chunk(
        user_id, started["import_id"], **_chunk("turns", 1, 2, second)
    )
    completed = complete_import(user_id, started["import_id"])
    assert completed["status"] == "queued"
    assert completed["job_id"] > 0

    status = get_import_status(user_id, started["import_id"])
    assert status["status"] == "queued"
    assert status["received_chunks"]["turns"] == [0, 1]


def test_conflicting_chunk_and_cross_user_access_are_rejected(test_db):
    from app.services.interview_import_service import (
        ImportAccessError,
        ImportChunkConflict,
        start_import,
        upload_import_chunk,
    )

    owner_id = _create_user(test_db, "owner")
    other_id = _create_user(test_db, "other")
    started = start_import(owner_id, client_request_id="conflict-1")
    upload_import_chunk(
        owner_id,
        started["import_id"],
        **_chunk("transcript", 0, 1, "original"),
    )

    with pytest.raises(ImportChunkConflict):
        upload_import_chunk(
            owner_id,
            started["import_id"],
            **_chunk("transcript", 0, 1, "tampered"),
        )
    with pytest.raises(ImportAccessError):
        upload_import_chunk(
            other_id,
            started["import_id"],
            **_chunk("transcript", 0, 1, "other-user"),
        )


def test_analysis_projects_native_conversation_without_practice_history(
    test_db, imported_transcript
):
    from app.services.chat_service import get_conversation, get_messages
    from app.services.interview_import_service import (
        analyze_import,
        complete_import,
        get_interview_record,
        get_interview_report,
        start_import,
        upload_import_chunk,
    )

    user_id = _create_user(test_db, "projection-owner")
    test_db.execute(
        "INSERT INTO question_bank (id, question, status, owner_id) VALUES (?, ?, 'approved', NULL)",
        (1, "模型参数量是多少？"),
    )
    test_db.commit()
    started = start_import(
        user_id,
        client_request_id="projection-1",
        title="原生兼容记录",
        context={"job_position": "大模型应用开发", "recruiting_season": "2026 春招"},
        external_analysis={"overall": "回答清晰", "score": 82},
    )
    upload_import_chunk(
        user_id,
        started["import_id"],
        **_chunk("turns", 0, 1, imported_transcript),
    )
    complete = complete_import(user_id, started["import_id"])
    result = analyze_import(started["import_id"], complete["job_id"])

    assert result["status"] == "completed"
    conversation = get_conversation(result["conversation_id"], user_id)
    messages = get_messages(result["conversation_id"])
    assert conversation["metadata"]["origin"] == "external_mcp"
    assert conversation["metadata"]["sealed"] is True
    assert [message["role"] for message in messages] == ["assistant", "user"]
    assert messages[0]["metadata"]["question_id"] == 1
    assert get_interview_report(user_id, started["import_id"])["external_analysis"]["score"] == 82
    assert get_interview_record(user_id, started["import_id"])["conversation_id"] == result[
        "conversation_id"
    ]
    assert test_db.execute(
        "SELECT COUNT(*) FROM user_practice_history WHERE user_id = ?", (user_id,)
    ).fetchone()[0] == 0


def test_failed_analysis_can_be_retried_without_reuploading(test_db):
    from app.services.interview_import_service import (
        ImportAnalysisError,
        complete_import,
        get_import_status,
        retry_import_analysis,
        start_import,
        upload_import_chunk,
    )

    user_id = _create_user(test_db, "retry-owner")
    started = start_import(user_id, client_request_id="retry-1")
    upload_import_chunk(
        user_id,
        started["import_id"],
        **_chunk("turns", 0, 1, "not-json"),
    )
    complete = complete_import(user_id, started["import_id"])
    with pytest.raises(ImportAnalysisError):
        from app.services.interview_import_service import analyze_import

        analyze_import(started["import_id"], complete["job_id"])
    assert get_import_status(user_id, started["import_id"])["status"] == "failed"

    retried = retry_import_analysis(user_id, started["import_id"])
    assert retried["status"] == "queued"
    assert retried["job_id"] != complete["job_id"]


@pytest.mark.asyncio
async def test_mcp_import_tools_use_authenticated_owner_and_return_retry_data(
    test_db, monkeypatch
):
    from app.mcp_server import app as mcp_app
    from app.mcp_server.principal import (
        MCPPrincipal,
        reset_mcp_principal,
        set_mcp_principal,
    )
    from app.services.interview_import_service import analyze_import

    user_id = _create_user(test_db, "mcp-owner")

    async def sync_run_db(fn):
        return fn()

    monkeypatch.setattr(mcp_app, "run_db", sync_run_db)
    token = set_mcp_principal(MCPPrincipal(user_id=user_id, bank_mode="all"))
    try:
        from app.mcp_server.app import mcp

        started = await mcp.call_tool(
            "start_interview_import",
            {"client_request_id": "mcp-1", "context": {"job_position": "Agent"}},
        )
        started_payload = json.loads(started[0].text)
        assert started_payload["ok"] is True
        import_id = started_payload["data"]["import_id"]

        bad = await mcp.call_tool(
            "upload_interview_import_chunk",
            {
                "import_id": import_id,
                "stream_type": "turns",
                "chunk_index": 0,
                "total_chunks": 1,
                "content": "[]",
                "content_hash": "bad",
            },
        )
        bad_payload = json.loads(bad[0].text)
        assert bad_payload["ok"] is False
        assert bad_payload["error"]["error_code"] == "CHUNK_HASH_MISMATCH"
        assert bad_payload["data"]["retryable"] is True
        assert bad_payload["data"]["failed_chunks"][0]["chunk_index"] == 0
    finally:
        reset_mcp_principal(token)


@pytest.mark.asyncio
async def test_mcp_read_tools_expose_published_record_only_to_owner(test_db):
    from app.mcp_server import app as mcp_app
    from app.mcp_server.principal import (
        MCPPrincipal,
        reset_mcp_principal,
        set_mcp_principal,
    )
    from app.services.interview_import_service import (
        analyze_import,
        complete_import,
        start_import,
        upload_import_chunk,
    )

    owner_id = _create_user(test_db, "mcp-read-owner")
    other_id = _create_user(test_db, "mcp-read-other")
    started = start_import(owner_id, client_request_id="mcp-read-1")
    content = json.dumps(
        [{"speaker": "interviewer", "content": "介绍一下你的项目"}],
        ensure_ascii=False,
    )
    upload_import_chunk(owner_id, started["import_id"], **_chunk("turns", 0, 1, content))
    complete = complete_import(owner_id, started["import_id"])
    analyze_import(started["import_id"], complete["job_id"])

    async def sync_run_db(fn):
        return fn()

    mcp_app.run_db = sync_run_db
    token = set_mcp_principal(MCPPrincipal(user_id=other_id, bank_mode="all"))
    try:
        from app.mcp_server.app import mcp

        response = await mcp.call_tool(
            "get_interview_record", {"import_id": started["import_id"]}
        )
        payload = json.loads(response[0].text)
        assert payload["ok"] is False
        assert payload["error"]["error_code"] == "IMPORT_NOT_FOUND"
    finally:
        reset_mcp_principal(token)


@pytest.mark.asyncio
async def test_async_worker_claims_import_job_and_publishes_record(test_db):
    from app import worker
    from app.services import interview_import_service
    from app.services.interview_import_service import (
        complete_import,
        get_import_status,
        start_import,
        upload_import_chunk,
    )

    user_id = _create_user(test_db, "worker-owner")
    started = start_import(user_id, client_request_id="worker-1")
    content = json.dumps(
        [{"speaker": "interviewer", "content": "请介绍你的系统设计思路"}],
        ensure_ascii=False,
    )
    upload_import_chunk(user_id, started["import_id"], **_chunk("turns", 0, 1, content))
    complete = complete_import(user_id, started["import_id"])

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.db.connection.get_db_connection", lambda: test_db)
    monkeypatch.setattr(worker, "get_db_connection", lambda: test_db, raising=False)
    monkeypatch.setattr(interview_import_service, "get_db_connection", lambda: test_db)
    try:
        result = await worker.interview_import_analysis_task({}, complete["job_id"])
    finally:
        monkeypatch.undo()

    assert result["status"] == "completed"
    status = get_import_status(user_id, started["import_id"])
    assert status["status"] == "completed"
    assert status["job"]["status"] == "completed"
