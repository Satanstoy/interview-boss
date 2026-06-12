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
        assert len(catalog) < 2000
        assert "<skill_instruction" not in catalog

    def test_catalog_has_tool_guidance(self):
        """catalog should include tool usage guidance"""
        from app.agents.shared.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()
        assert "load_skill" in catalog
        assert "search_questions" in catalog
        assert "draw_questions" in catalog
