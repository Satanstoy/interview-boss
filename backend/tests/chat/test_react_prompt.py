"""Tests for build_react_system_prompt — ReAct loop system prompt builder."""

from app.agents.chat.nodes import build_react_system_prompt


class TestBuildReactSystemPrompt:
    def test_prompt_contains_base_info(self):
        state = {
            "user_id": 1,
            "mode": "free_practice",
            "interview_context": "目标岗位：后端开发",
            "session_notes": "",
            "compressed_context": None,
            "memory_summaries": [],
        }
        prompt = build_react_system_prompt(state)
        assert "面试" in prompt  # should contain interview-related content

    def test_prompt_contains_tool_guidance(self):
        state = {
            "user_id": 1,
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "compressed_context": None,
            "memory_summaries": [],
        }
        prompt = build_react_system_prompt(state)
        assert "load_skill" in prompt
        assert "search_questions" in prompt

    def test_prompt_not_excessively_long(self):
        state = {
            "user_id": 1,
            "mode": "free_practice",
            "interview_context": "测试" * 100,
            "session_notes": "",
            "compressed_context": None,
            "memory_summaries": [],
        }
        prompt = build_react_system_prompt(state)
        assert len(prompt) < 8000
