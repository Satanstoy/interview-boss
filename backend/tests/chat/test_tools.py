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


# ── TestExecuteToolLoadSkill ─────────────────────────────

class TestExecuteToolLoadSkill:

    async def test_load_skill_returns_instruction(self, sample_state, sample_skill):
        """load_skill should return the skill instruction text from registry."""
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
        assert "instruction" in parsed
        assert parsed["instruction"] == "## Theory QA Instruction\n\nAsk theory questions."
        mock_registry.get.assert_called_once_with("theory-qa")

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

        with patch("app.agents.chat.tools._hybrid_search", return_value=mock_results):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 3  # top 3 only
        assert sample_state["retrieved_questions"] == mock_results

    async def test_search_with_question_type(self, sample_state):
        """search_questions should pass question_type through to hybrid_search."""
        from app.agents.chat.tools import execute_tool, _hybrid_search

        tool_call = {
            "function": {
                "name": "search_questions",
                "arguments": json.dumps({
                    "keywords": ["Java"],
                    "question_type": "knowledge_probe",
                }),
            }
        }

        with patch("app.agents.chat.tools._hybrid_search", return_value=[]) as mock_search:
            await execute_tool(tool_call, sample_state)

        mock_search.assert_called_once_with(
            keywords=["Java"],
            question_type="knowledge_probe",
        )


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

        with patch("app.agents.chat.tools._draw_questions", return_value=mock_results):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert sample_state["retrieved_questions"] == mock_results

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
