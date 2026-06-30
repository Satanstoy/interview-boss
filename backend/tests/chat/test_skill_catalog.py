"""Tests for build_skill_catalog — lightweight skill catalog for system prompt."""


class TestBuildSkillCatalog:
    def test_shared_catalog_requires_explicit_registry(self):
        """shared catalog builder must not know any agent-specific registry."""
        import pytest

        from app.agents.shared.skills.builder import build_skill_catalog

        with pytest.raises(TypeError):
            build_skill_catalog()

    def test_shared_catalog_contains_only_skill_metadata(self):
        """shared catalog renders names/descriptions, not chat tool policy."""
        from app.agents.shared.skills.base import Skill, SkillRegistry
        from app.agents.shared.skills.builder import build_skill_catalog

        registry = SkillRegistry(agent_name="unit")
        registry.register(
            Skill(
                name="unit-skill",
                description="Use when unit testing generic skill catalogs",
                priority=10,
            )
        )

        catalog = build_skill_catalog(registry)
        assert "unit-skill" in catalog
        assert "Use when unit testing generic skill catalogs" in catalog
        assert "search_questions" not in catalog
        assert "draw_questions" not in catalog
        assert "load_skill" not in catalog
        assert "内部控制信号" not in catalog

    def test_chat_catalog_contains_all_skills(self):
        """chat catalog should contain all registered chat skill names"""
        from app.agents.chat.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()
        assert "interview-rhythm" in catalog
        assert "algorithm-coding" in catalog

    def test_catalog_does_not_contain_full_instructions(self):
        """catalog should NOT contain full instructions (only names+descriptions)"""
        from app.agents.chat.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()
        assert len(catalog) < 2500
        assert "<skill_instruction" not in catalog

    def test_chat_catalog_routes_tool_guidance_to_tool_use_skill(self):
        """chat catalog should advertise the tool-use skill, not inline policy."""
        from app.agents.chat.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()
        assert "interview-tool-use" in catalog
        assert "search_questions" not in catalog
        assert "draw_questions" not in catalog

    def test_internal_name_boundary_lives_in_tool_use_skill_body(self):
        """runtime internal-name policy belongs to the always-injected skill body."""
        from app.agents.chat.nodes import build_react_system_prompt

        prompt = build_react_system_prompt(
            {
                "mode": "free_practice",
                "interview_context": "",
                "session_notes": "",
                "memory_summaries": [],
                "compressed_context": None,
                "active_skills": [],
            }
        )
        assert "内部控制信号" in prompt
        assert "最终回复必须是面试官直接对候选人说的话" in prompt

    def test_dynamic_tool_strategy_has_scene_based_tool_guidance(self):
        """state-specific hard guidance belongs to _build_tool_strategy."""
        from app.agents.chat.nodes import _build_tool_strategy

        strategy = _build_tool_strategy(
            {
                "intent": "interview_question",
                "answer_complete": True,
                "retrieved_questions": [],
                "active_skills": ["project-deep-dive"],
            }
        )
        assert "项目深挖模式" in strategy
        assert "search_questions" in strategy
