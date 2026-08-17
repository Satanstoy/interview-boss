"""Tests for build_react_system_prompt — ReAct loop system prompt builder."""

from app.agents.chat.nodes import build_react_prompt_parts, build_react_system_prompt
from app.agents.chat.prompt_cache import build_prompt_cache_fingerprint


class TestBuildReactSystemPrompt:
    def test_prompt_cache_fingerprint_is_stable_for_equivalent_tools(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        equivalent_tools = [{"function": dict(tools[0]["function"]), "type": "function"}]

        assert build_prompt_cache_fingerprint("stable", tools, "m") == build_prompt_cache_fingerprint(
            "stable", equivalent_tools, "m"
        )
        assert build_prompt_cache_fingerprint("changed", tools, "m") != build_prompt_cache_fingerprint(
            "stable", tools, "m"
        )

    def test_dynamic_state_is_outside_stable_prefix(self):
        base_state = {
            "user_id": 1,
            "mode": "free_practice",
            "interview_context": "项目 A",
            "session_notes": "第一轮笔记",
            "compressed_context": "历史摘要 A",
            "memory_summaries": [],
            "interview_state": {"current_phase": "project_followup"},
            "answer_quality": "complete",
            "active_skills": [],
            "message_history": [],
        }
        next_state = {
            **base_state,
            "interview_context": "项目 B",
            "session_notes": "第二轮笔记",
            "compressed_context": "历史摘要 B",
            "interview_state": {"current_phase": "knowledge_probe"},
            "answer_quality": "incomplete",
        }

        first = build_react_prompt_parts(base_state)
        second = build_react_prompt_parts(next_state)

        assert first["stable_system_prompt"] == second["stable_system_prompt"]
        assert "项目 A" not in first["stable_system_prompt"]
        assert "第一轮笔记" not in first["stable_system_prompt"]
        assert "项目 A" in first["dynamic_context"]
        assert "项目 B" in second["dynamic_context"]

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
        # The compatibility single-string form includes the cache envelope;
        # the live ReAct path sends the same data as two messages.
        assert len(prompt) < 12000

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
