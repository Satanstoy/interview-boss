"""Security and lifecycle tests for account-level MCP tokens."""

import pytest
from starlette.requests import Request


def _request(path="/mcp", authorization="", host="interview.test"):
    headers = [(b"host", host.encode()), (b"x-forwarded-proto", b"http")]
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "scheme": "http",
            "server": (host, 80),
            "client": ("127.0.0.1", 12345),
        }
    )


def _insert_user(conn, user_id=7):
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
        (user_id, f"mcp-user-{user_id}", "TEST_PASSWORD_HASH"),
    )
    conn.commit()


def test_mcp_token_is_hashed_and_rotation_is_one_per_user(test_db):
    from app.services.mcp_token_service import (
        authenticate_mcp_token,
        get_mcp_token_connection,
        get_mcp_token_metadata,
        hash_mcp_token,
        issue_mcp_token,
    )

    _insert_user(test_db)
    first = issue_mcp_token(7)
    assert first["token"].startswith("ib_mcp_")
    assert authenticate_mcp_token(first["token"]) == {"user_id": 7, "bank_mode": "all"}

    stored = test_db.execute(
        "SELECT token_hash, token_seed FROM mcp_tokens WHERE user_id = 7"
    ).fetchone()
    assert stored["token_hash"] == hash_mcp_token(first["token"])
    assert stored["token_seed"]
    assert first["token"] not in stored["token_hash"]
    assert first["token"] not in stored["token_seed"]

    second = issue_mcp_token(7)
    assert authenticate_mcp_token(first["token"]) is None
    assert authenticate_mcp_token(second["token"]) == {"user_id": 7, "bank_mode": "all"}
    assert test_db.execute(
        "SELECT COUNT(*) FROM mcp_tokens WHERE user_id = 7"
    ).fetchone()[0] == 1

    metadata = get_mcp_token_metadata(7)
    assert metadata["token_hint"] == second["token_hint"]
    assert "token" not in metadata
    assert metadata["last_used_at"] is not None

    connection = get_mcp_token_connection(7)
    assert connection["token_available"] is True
    assert connection["token"] == second["token"]


def test_legacy_mcp_token_requires_one_rotation_before_copy(test_db):
    from app.services.mcp_token_service import (
        generate_mcp_token,
        get_mcp_token_connection,
        hash_mcp_token,
    )

    _insert_user(test_db, user_id=17)
    legacy_token, _ = generate_mcp_token(17)
    test_db.execute(
        """
        INSERT INTO mcp_tokens (user_id, token_hash, token_hint, token_seed)
        VALUES (?, ?, ?, NULL)
        """,
        (17, hash_mcp_token(legacy_token), f"…{legacy_token[-8:]}"),
    )
    test_db.commit()

    connection = get_mcp_token_connection(17)
    assert connection["token_available"] is False
    assert "token" not in connection


def test_mcp_token_revoke_invalidates_access(test_db):
    from app.services.mcp_token_service import (
        authenticate_mcp_token,
        issue_mcp_token,
        revoke_mcp_token,
    )

    _insert_user(test_db, user_id=8)
    issued = issue_mcp_token(8)
    assert revoke_mcp_token(8) is True
    assert revoke_mcp_token(8) is False
    assert authenticate_mcp_token(issued["token"]) is None


def test_mcp_profile_config_returns_copyable_active_token(test_db, client):
    from app.routers.profile_pkg.mcp import (
        get_my_mcp_config,
        rotate_my_mcp_token,
    )

    _insert_user(test_db, user_id=9)
    request = _request()

    before = __import__("asyncio").run(get_my_mcp_config(request, {"id": 9}))
    assert before["configured"] is False
    assert before["token_available"] is False
    assert "token" not in before

    issued = __import__("asyncio").run(rotate_my_mcp_token(request, {"id": 9}))
    assert issued["configured"] is True
    assert issued["token"].startswith("ib_mcp_")
    canonical_endpoint = "https://www.interviewboss.online/mcp"
    assert issued["config"]["mcpServers"]["interview-boss"]["url"] == canonical_endpoint
    assert (
        issued["config"]["mcpServers"]["interview-boss"]["headers"]["Authorization"]
        == f"Bearer {issued['token']}"
    )
    stdio = issued["stdio_config"]["mcpServers"]["interview-boss"]
    assert stdio["command"] == "npx"
    assert stdio["args"][:5] == [
        "-y",
        "mcp-remote",
        canonical_endpoint,
        "--transport",
        "http-only",
    ]
    assert "--allow-http" not in stdio["args"]
    assert stdio["env"]["INTERVIEW_BOSS_MCP_AUTH"] == f"Bearer {issued['token']}"
    assert "mcp-remote" in issued["stdio_config_json"]

    after = __import__("asyncio").run(get_my_mcp_config(request, {"id": 9}))
    assert after["configured"] is True
    assert after["token_available"] is True
    assert after["token"] == issued["token"]
    assert (
        after["config"]["mcpServers"]["interview-boss"]["headers"]["Authorization"]
        == f"Bearer {issued['token']}"
    )


def test_mcp_principal_comes_from_account_token(test_db, client):
    import asyncio

    from app.mcp_server.app import _load_account_mcp_principal
    from app.services.mcp_token_service import issue_mcp_token

    _insert_user(test_db, user_id=10)
    token = issue_mcp_token(10)["token"]
    principal = asyncio.run(_load_account_mcp_principal(_request(authorization=f"Bearer {token}")))
    assert principal.user_id == 10
    assert principal.bank_mode == "all"


def test_mcp_middleware_accepts_account_token_without_global_key(test_db, client, monkeypatch):
    import asyncio

    from app.mcp_server import app as mcp_app_module
    from app.mcp_server.principal import get_mcp_principal
    from app.services.mcp_token_service import issue_mcp_token

    _insert_user(test_db, user_id=11)
    token = issue_mcp_token(11)["token"]
    monkeypatch.setattr(mcp_app_module, "MCP_API_KEY", "")
    monkeypatch.setattr(mcp_app_module, "MCP_ALLOW_ANONYMOUS", False)
    observed = []

    async def downstream(scope, receive, send):
        observed.append(get_mcp_principal())

    async def send(message):
        pass

    asyncio.run(
        mcp_app_module.MCPAuthMiddleware(downstream)(
            _request(authorization=f"Bearer {token}").scope,
            None,
            send,
        )
    )

    assert observed[0].user_id == 11


@pytest.mark.asyncio
async def test_mcp_draw_passes_explicit_job_position_to_service(test_db, monkeypatch):
    from app.mcp_server import interview_tools

    test_db.execute(
        "INSERT INTO job_positions (id, name, description) VALUES (?, ?, ?)",
        (902, "后端开发", "后端服务开发岗位"),
    )
    test_db.commit()

    captured = {}

    async def fake_draw(**kwargs):
        captured.update(kwargs)
        return [{"id": 1, "question": "岗位题", "cat1": "A", "cat2": "A1"}]

    monkeypatch.setattr(interview_tools, "_draw_questions_for_tool", fake_draw)
    result = await interview_tools.draw_questions_tool(
        {"count": 1},
        {"user_id": 7, "bank_mode": "all", "job_position": "后端开发"},
    )

    assert result["ok"] is True
    assert captured["job_position"] == "后端开发"


@pytest.mark.asyncio
async def test_mcp_auto_loads_tool_use_skill_for_authenticated_session(client):
    from app.mcp_server import app as mcp_app_module
    from app.mcp_server.principal import (
        reset_mcp_principal,
        set_mcp_principal,
    )
    from app.mcp_server.principal import MCPPrincipal

    usage_instructions = mcp_app_module._load_mcp_usage_skill_instructions()
    assert "何时调用哪个工具" in usage_instructions
    assert "search_questions" in mcp_app_module.mcp.instructions
    assert "select_question" in mcp_app_module.mcp.instructions
    assert len(mcp_app_module.mcp.instructions) < 1800

    token = set_mcp_principal(MCPPrincipal(user_id=17, bank_mode="all"))
    try:
        session_id, state = await mcp_app_module._init_tool_state_async(
            "auto-tool-skill-test",
            {},
        )
    finally:
        reset_mcp_principal(token)

    assert session_id == "auto-tool-skill-test"
    assert "interview-tool-use" in state["active_skills"]
    assert any(
        item["skill_name"] == "interview-tool-use"
        for item in state["active_skill_instructions"]
    )
