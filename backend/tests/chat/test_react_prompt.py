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

    def test_prompt_requires_chinese_reasoning_content(self):
        state = {
            "user_id": 1,
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "compressed_context": None,
            "memory_summaries": [],
        }
        prompt = build_react_system_prompt(state)
        assert "reasoning_content" in prompt
        assert "推理过程" in prompt
        assert "简体中文" in prompt

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
        assert len(prompt) < 10000

    def test_always_active_skill_body_injected_when_active_skills_empty(self):
        """interview-tool-use (always_active=true) body must appear even with no active_skills."""
        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": [],
        }
        prompt = build_react_system_prompt(state)
        assert "空结果时沉默不语" in prompt
        assert "<skill_instructions>" in prompt

    def test_always_active_body_plus_explicit_active_skills(self):
        """When active_skills=[interview-rhythm], output ALSO contains interview-tool-use body."""
        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": ["interview-rhythm"],
            "active_skill_instructions": [
                {
                    "skill_name": "interview-rhythm",
                    "instruction": "## Interview Rhythm\nKeep pacing.",
                }
            ],
        }
        prompt = build_react_system_prompt(state)
        assert "空结果时沉默不语" in prompt
        assert "Keep pacing" in prompt

    def test_non_tool_use_always_active_skill_body_not_auto_injected(self):
        """always_active means registry matching; only tool-use bodies are auto-injected."""
        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": [],
        }
        prompt = build_react_system_prompt(state)
        assert "空结果时沉默不语" in prompt
        assert "Candidates who feel overwhelmed stop talking" not in prompt

    def test_non_tool_use_always_active_skill_body_injected_when_explicitly_active(self):
        """Non-tool-use always_active skills still inject when active_skills names them."""
        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": ["adaptive-difficulty"],
        }
        prompt = build_react_system_prompt(state)
        assert "Candidates who feel overwhelmed stop talking" in prompt
