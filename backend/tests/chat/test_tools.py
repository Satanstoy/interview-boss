"""TDD tests for chat ReAct agent tool schemas and executor."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def sample_state():
    """Minimal ChatState for testing."""
    return {
        "user_id": 1,
        "user_message": "Tell me about Java",
        "retrieved_questions": [],
    }


@pytest.fixture
def sample_skill():
    """A mock Skill object."""
    skill = MagicMock()
    skill.name = "theory-qa"
    skill.description = "理论问答策略"
    skill.get_instruction.return_value = "## Theory QA Instruction\n\nAsk theory questions."
    return skill


# ── TestToolSchemas ────────────────────────────────────────

class TestToolSchemas:
    def test_search_questions_schema_has_when_to_use(self):
        """search_questions description should contain usage guidance."""
        from app.agents.chat.tools import SEARCH_QUESTIONS_SCHEMA

        desc = SEARCH_QUESTIONS_SCHEMA["function"]["description"]
        assert "何时使用" in desc or "WHEN TO USE" in desc
        assert "何时不用" in desc or "WHEN NOT TO USE" in desc

    def test_search_questions_keywords_description_is_specific(self):
        """keywords parameter description should guide against generic terms."""
        from app.agents.chat.tools import SEARCH_QUESTIONS_SCHEMA

        kw_desc = SEARCH_QUESTIONS_SCHEMA["function"]["parameters"]["properties"]["keywords"]["description"]
        assert "2-5" in kw_desc or "具体" in kw_desc

    def test_search_questions_question_type_has_enum_descriptions(self):
        """question_type description should explain each enum value."""
        from app.agents.chat.tools import SEARCH_QUESTIONS_SCHEMA

        qt_desc = SEARCH_QUESTIONS_SCHEMA["function"]["parameters"]["properties"]["question_type"]["description"]
        assert "project_followup" in qt_desc
        assert "knowledge_probe" in qt_desc

    def test_search_questions_schema_explains_result_usage(self):
        """search_questions description should tell the model how to use returned questions."""
        from app.agents.chat.tools import SEARCH_QUESTIONS_SCHEMA

        desc = SEARCH_QUESTIONS_SCHEMA["function"]["description"]
        assert "如何使用返回结果" in desc
        assert "top 3" in desc
        assert "不要机械复述" in desc

    def test_draw_questions_schema_has_when_to_use(self):
        """draw_questions description should contain usage guidance."""
        from app.agents.chat.tools import DRAW_QUESTIONS_SCHEMA

        desc = DRAW_QUESTIONS_SCHEMA["function"]["description"]
        assert "何时使用" in desc or "WHEN TO USE" in desc
        assert "何时不用" in desc or "WHEN NOT TO USE" in desc

    def test_draw_questions_count_has_default_description(self):
        """count parameter should mention default value in Chinese."""
        from app.agents.chat.tools import DRAW_QUESTIONS_SCHEMA

        count_desc = DRAW_QUESTIONS_SCHEMA["function"]["parameters"]["properties"]["count"]["description"]
        assert "默认" in count_desc

    def test_load_skill_schema_has_usage_guidance(self):
        """load_skill description should explain when to use and when not to."""
        from app.agents.chat.tools import LOAD_SKILL_SCHEMA

        desc = LOAD_SKILL_SCHEMA["function"]["description"]
        assert "何时使用" in desc or "WHEN TO USE" in desc
        assert "何时不用" in desc or "WHEN NOT TO USE" in desc

    def test_load_skill_enum_descriptions(self):
        """skill_name description should list all skills with their purposes."""
        from app.agents.chat.tools import LOAD_SKILL_SCHEMA

        skill_desc = LOAD_SKILL_SCHEMA["function"]["parameters"]["properties"]["skill_name"]["description"]
        assert "project-deep-dive" in skill_desc
        assert "algorithm-coding" in skill_desc


class TestToolGatewayModels:
    def test_normalize_search_question_item_prefers_combined_score(self):
        from app.agents.chat.tool_gateway import normalize_question_item

        item = normalize_question_item(
            {
                "id": 42,
                "question": "介绍一下 RAG 的检索和重排流程",
                "cat1": "B.Agent与LLM应用",
                "cat2": "B2.RAG系统设计",
                "tags": "rag,检索,重排",
                "_combined_rank_score": 0.123456,
                "_rrf_score": 0.05,
                "sources": "[{\"company\": \"测试公司\", \"round\": \"一面\"}]",
            },
            source="search",
            reason="rrf_ranked",
        )

        assert item["id"] == 42
        assert item["question"] == "介绍一下 RAG 的检索和重排流程"
        assert item["cat1"] == "B.Agent与LLM应用"
        assert item["cat2"] == "B2.RAG系统设计"
        assert item["source"] == "search"
        assert item["score"] == 0.123456
        assert item["reason"] == "rrf_ranked"
        assert item["sources"] == [{"company": "测试公司", "round": "一面"}]

    def test_build_tool_success_envelope_has_stable_shape(self):
        from app.agents.chat.tool_gateway import build_success_envelope

        envelope = build_success_envelope(
            tool="search_questions",
            items=[
                {
                    "id": 1,
                    "question": "What is JVM?",
                    "cat1": "Java",
                    "cat2": "Basics",
                    "source": "search",
                    "score": 0.1,
                    "reason": "rrf_ranked",
                    "tags": "jvm",
                    "difficulty": "medium",
                    "sources": [],
                }
            ],
            total_ms=7,
            debug_reason="hybrid_search_ok",
        )

        assert envelope["ok"] is True
        assert envelope["tool"] == "search_questions"
        assert envelope["items"][0]["id"] == 1
        assert envelope["metadata"]["result_count"] == 1
        assert envelope["metadata"]["fallback_used"] is False
        assert envelope["metadata"]["metrics"]["total_ms"] == 7
        assert envelope["metadata"]["debug_reason"] == "hybrid_search_ok"
        assert envelope["error"] is None

    def test_build_tool_error_envelope_has_error_code(self):
        from app.agents.chat.tool_gateway import build_error_envelope

        envelope = build_error_envelope(
            tool="draw_questions",
            error_code="USER_REQUIRED",
            message="user_id is required for draw_questions",
            total_ms=2,
            debug_reason="missing_user_id",
        )

        assert envelope["ok"] is False
        assert envelope["tool"] == "draw_questions"
        assert envelope["items"] == []
        assert envelope["metadata"]["result_count"] == 0
        assert envelope["metadata"]["metrics"]["total_ms"] == 2
        assert envelope["metadata"]["debug_reason"] == "missing_user_id"
        assert envelope["error"] == {
            "error_code": "USER_REQUIRED",
            "message": "user_id is required for draw_questions",
        }


# ── TestExecuteToolLoadSkill ─────────────────────────────

class TestExecuteToolLoadSkill:

    async def test_load_skill_returns_confirmation(self, sample_state, sample_skill):
        """load_skill should return confirmation with status, not full instruction."""
        from app.agents.chat.tools import execute_tool

        tool_call = {
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "theory-qa"}),
            }
        }

        mock_registry = MagicMock()
        mock_registry.get.return_value = sample_skill

        with patch("app.agents.chat.tools._get_skill_registry", return_value=mock_registry):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["status"] == "loaded"
        assert parsed["skill"] == "theory-qa"
        assert "summary" in parsed
        assert "instruction" not in parsed

    async def test_load_skill_unknown_name(self, sample_state):
        """load_skill should return error when skill is not found."""
        from app.agents.chat.tools import execute_tool

        tool_call = {
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "nonexistent"}),
            }
        }

        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        with patch("app.agents.chat.tools._get_skill_registry", return_value=mock_registry):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert "error" in parsed
        assert "nonexistent" in parsed["error"]


class TestLoadSkillStateInjection:
    async def test_load_skill_stores_instruction_in_state(self, sample_state):
        """load_skill should store instruction in state for system prompt injection."""
        from app.agents.chat.tools import execute_tool

        sample_skill_obj = MagicMock()
        sample_skill_obj.name = "theory-qa"
        sample_skill_obj.description = "理论问答策略"
        sample_skill_obj.get_instruction.return_value = "## Theory QA full instruction"

        tool_call = {
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "theory-qa"}),
            }
        }

        mock_registry = MagicMock()
        mock_registry.get.return_value = sample_skill_obj

        with patch("app.agents.chat.tools._get_skill_registry", return_value=mock_registry):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["status"] == "loaded"
        assert parsed["skill"] == "theory-qa"
        assert "instruction" not in parsed

        assert "active_skill_instructions" in sample_state
        assert len(sample_state["active_skill_instructions"]) == 1
        assert sample_state["active_skill_instructions"][0]["skill_name"] == "theory-qa"
        assert sample_state["active_skill_instructions"][0]["instruction"] == "## Theory QA full instruction"

    async def test_load_skill_already_active_returns_already_active(self, sample_state):
        """load_skill should return already_active if skill is already loaded."""
        from app.agents.chat.tools import execute_tool

        sample_state["active_skills"] = ["theory-qa"]

        tool_call = {
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "theory-qa"}),
            }
        }

        mock_registry = MagicMock()
        mock_skill_obj = MagicMock()
        mock_skill_obj.get_instruction.return_value = "instruction"
        mock_registry.get.return_value = mock_skill_obj

        with patch("app.agents.chat.tools._get_skill_registry", return_value=mock_registry):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["status"] == "already_active"
        assert "active_skill_instructions" not in sample_state or sample_state.get("active_skill_instructions") == []


# ── TestExecuteToolSearchQuestions ────────────────────────

class TestExecuteToolSearchQuestions:

    async def test_search_returns_json_results(self, sample_state):
        """search_questions should return JSON results and update state."""
        from app.agents.chat.tools import execute_tool

        mock_results = [
            {"id": 1, "question": "What is JVM?", "cat1": "Java", "cat2": "Basics", "difficulty": "easy"},
            {"id": 2, "question": "Explain GC", "cat1": "Java", "cat2": "Basics", "difficulty": "medium"},
            {"id": 3, "question": "Thread safety", "cat1": "Java", "cat2": "Concurrency", "difficulty": "hard"},
            {"id": 4, "question": "Too many", "cat1": "Java", "cat2": "Other", "difficulty": "hard"},
        ]

        tool_call = {
            "function": {
                "name": "search_questions",
                "arguments": json.dumps({"keywords": ["Java", "JVM"]}),
            }
        }

        with patch(
            "app.mcp_server.interview_tools._hybrid_search_for_tool",
            new=AsyncMock(return_value=mock_results),
        ):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["tool"] == "search_questions"
        assert len(parsed["items"]) == 4
        assert parsed["items"][0]["id"] == 1
        assert parsed["items"][0]["source"] == "search"
        assert parsed["metadata"]["result_count"] == 4
        assert parsed["metadata"]["metrics"]["total_ms"] >= 0
        assert parsed["error"] is None
        assert sample_state["retrieved_questions"] == mock_results
        assert sample_state["candidate_questions"] == mock_results
        assert sample_state["question_source"] == "search"

    async def test_search_with_question_type(self, sample_state):
        """search_questions should pass question_type through to hybrid_search."""
        from app.agents.chat.tools import execute_tool

        tool_call = {
            "function": {
                "name": "search_questions",
                "arguments": json.dumps({
                    "keywords": ["Java"],
                    "question_type": "knowledge_probe",
                }),
            }
        }

        with patch(
            "app.mcp_server.interview_tools._hybrid_search_for_tool",
            new=AsyncMock(return_value=[]),
        ) as mock_search:
            await execute_tool(tool_call, sample_state)

        mock_search.assert_awaited_once_with(
            keywords=["Java"],
            question_type="knowledge_probe",
        )

    async def test_search_empty_keywords_returns_no_query_envelope(self, sample_state):
        from app.agents.chat.tools import execute_tool

        tool_call = {
            "function": {
                "name": "search_questions",
                "arguments": json.dumps({"keywords": []}),
            }
        }

        result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["tool"] == "search_questions"
        assert parsed["items"] == []
        assert parsed["error"]["error_code"] == "NO_QUERY"
        assert parsed["metadata"]["empty_reason"] == "no_query"
        assert sample_state.get("retrieved_questions") == []

    async def test_search_service_error_returns_service_error_envelope(self, sample_state):
        from app.agents.chat.tools import execute_tool

        tool_call = {
            "function": {
                "name": "search_questions",
                "arguments": json.dumps({"keywords": ["RAG"]}),
            }
        }

        with patch(
            "app.mcp_server.interview_tools._hybrid_search_for_tool",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["tool"] == "search_questions"
        assert parsed["error"]["error_code"] == "SERVICE_ERROR"
        assert parsed["metadata"]["empty_reason"] == "service_unavailable"
        assert "db down" not in parsed["error"]["message"]


# ── TestExecuteToolDrawQuestions ──────────────────────────

class TestExecuteToolDrawQuestions:

    async def test_draw_returns_json_results(self, sample_state):
        """draw_questions should return JSON results and update state."""
        from app.agents.chat.tools import execute_tool

        mock_results = [
            {"id": 10, "question": "Design a cache", "difficulty": "medium"},
            {"id": 11, "question": "Implement LRU", "difficulty": "hard"},
        ]

        tool_call = {
            "function": {
                "name": "draw_questions",
                "arguments": json.dumps({"count": 2, "difficulty": "medium"}),
            }
        }

        with patch(
            "app.mcp_server.interview_tools._draw_questions_for_tool",
            new=AsyncMock(return_value=mock_results),
        ):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["tool"] == "draw_questions"
        assert len(parsed["items"]) == 2
        assert parsed["items"][0]["id"] == 10
        assert parsed["items"][0]["source"] == "draw"
        assert parsed["metadata"]["result_count"] == 2
        assert parsed["metadata"]["metrics"]["total_ms"] >= 0
        assert parsed["error"] is None
        assert sample_state["retrieved_questions"] == mock_results
        assert sample_state["candidate_questions"] == mock_results
        assert sample_state["question_source"] == "draw"

    async def test_draw_passes_topic_and_question_type(self, sample_state):
        """draw_questions should support directed question drawing."""
        from app.agents.chat.tools import execute_tool

        tool_call = {
            "function": {
                "name": "draw_questions",
                "arguments": json.dumps({
                    "count": 1,
                    "cat1": "E.算法与数据结构",
                    "cat2": "E2.算法手撕",
                    "topic": "LRU",
                    "question_type": "algorithm_coding",
                }),
            }
        }

        with patch(
            "app.mcp_server.interview_tools._draw_questions_for_tool",
            new=AsyncMock(return_value=[]),
        ) as mock_draw:
            await execute_tool(tool_call, sample_state)

        mock_draw.assert_awaited_once()
        assert mock_draw.await_args.kwargs["cat1"] == "E.算法与数据结构"
        assert mock_draw.await_args.kwargs["cat2"] == "E2.算法手撕"
        assert mock_draw.await_args.kwargs["topic"] == "LRU"
        assert mock_draw.await_args.kwargs["question_type"] == "algorithm_coding"

    async def test_draw_missing_user_returns_user_required_envelope(self):
        from app.agents.chat.tools import execute_tool

        state = {"retrieved_questions": []}
        tool_call = {
            "function": {
                "name": "draw_questions",
                "arguments": json.dumps({"count": 1}),
            }
        }

        result = await execute_tool(tool_call, state)

        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["tool"] == "draw_questions"
        assert parsed["error"]["error_code"] == "USER_REQUIRED"
        assert parsed["metadata"]["debug_reason"] == "missing_user_id"

    async def test_draw_invalid_count_returns_validation_error_envelope(self, sample_state):
        from app.agents.chat.tools import execute_tool

        tool_call = {
            "function": {
                "name": "draw_questions",
                "arguments": json.dumps({"count": 99}),
            }
        }

        result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["tool"] == "draw_questions"
        assert parsed["error"]["error_code"] == "VALIDATION_ERROR"
        assert parsed["metadata"]["debug_reason"] == "validation_failed"

    async def test_unknown_tool_returns_error(self, sample_state):
        """execute_tool should return error for unknown tool names."""
        from app.agents.chat.tools import execute_tool

        tool_call = {
            "function": {
                "name": "unknown_tool",
                "arguments": json.dumps({"foo": "bar"}),
            }
        }

        result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert "error" in parsed
        assert "unknown_tool" in parsed["error"]


class TestToolProgressMessage:
    def test_progress_messages_are_user_friendly_chinese(self):
        from app.agents.chat.tools import tool_progress_message

        assert tool_progress_message({
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "project-deep-dive"}),
            }
        }) == "正在加载项目深挖策略..."
        assert tool_progress_message({
            "function": {
                "name": "search_questions",
                "arguments": json.dumps({"keywords": ["Redis"]}),
            }
        }) == "正在检索相关面试题..."
        assert tool_progress_message({
            "function": {
                "name": "draw_questions",
                "arguments": json.dumps({"count": 2}),
            }
        }) == "正在从题库抽题..."
