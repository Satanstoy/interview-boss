"""Tests for build_skill_catalog — lightweight skill catalog for system prompt."""


class TestBuildSkillCatalog:
    def test_catalog_contains_all_skills(self):
        """catalog should contain all registered skill names"""
        from app.agents.shared.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()
        assert "interview-rhythm" in catalog
        assert "algorithm-coding" in catalog

    def test_catalog_does_not_contain_full_instructions(self):
        """catalog should NOT contain full instructions (only names+descriptions)"""
        from app.agents.shared.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()
        assert len(catalog) < 2500
        assert "<skill_instruction" not in catalog

    def test_catalog_has_tool_guidance(self):
        """catalog should include tool usage guidance"""
        from app.agents.shared.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()
        assert "load_skill" in catalog
        assert "search_questions" in catalog
        assert "draw_questions" in catalog

    def test_catalog_forbids_internal_names_as_final_answer(self):
        """catalog should tell the model not to output skill/tool names directly."""
        from app.agents.shared.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()
        assert "内部控制信号" in catalog
        assert "不得把" in catalog
        assert "最终回复正文" in catalog

    def test_catalog_has_scene_based_tool_guidance(self):
        """catalog should provide scene-based tool usage suggestions."""
        from app.agents.shared.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()
        assert "面试追问" in catalog or "追问题" in catalog
        assert "新话题" in catalog or "练习请求" in catalog
