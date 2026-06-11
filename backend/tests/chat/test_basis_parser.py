"""Tests for _parse_basis_from_response() — [BASIS] block parsing"""

import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestParseBasisFromResponse:
    """Test suite for _parse_basis_from_response() function"""

    def test_valid_json_basis_block(self):
        """Test parsing a valid [BASIS] block with complete JSON"""
        from app.agents.chat.nodes import _parse_basis_from_response

        response = 'Here is my analysis.\n[BASIS]{"type":"technical","question_ids":[1,2,3],"confidence":0.85,"show_refs":true}[/BASIS]\nPlease review.'

        result = _parse_basis_from_response(response)

        assert result["basis_type"] == "technical"
        assert result["basis_question_ids"] == [1, 2, 3]
        assert result["basis_confidence"] == 0.85
        assert result["should_show_references"] is True
        assert "Here is my analysis." in result["clean_response"]
        assert "Please review." in result["clean_response"]
        assert "[BASIS]" not in result["clean_response"]
        assert "[/BASIS]" not in result["clean_response"]

    def test_invalid_json_in_basis_block(self):
        """Test handling of invalid JSON inside [BASIS] block"""
        from app.agents.chat.nodes import _parse_basis_from_response

        response = "Some text.\n[BASIS]{invalid json}[/BASIS]\nMore text."

        result = _parse_basis_from_response(response)

        # Should return defaults when JSON is invalid
        assert result["basis_type"] == ""
        assert result["basis_question_ids"] == []
        assert result["basis_confidence"] == 0.0
        assert result["should_show_references"] is False
        # Clean response should still strip the [BASIS] block
        assert "[BASIS]" not in result["clean_response"]
        assert "Some text." in result["clean_response"]
        assert "More text." in result["clean_response"]

    def test_missing_basis_block(self):
        """Test response with no [BASIS] block at all"""
        from app.agents.chat.nodes import _parse_basis_from_response

        response = "This is a normal response without any basis block."

        result = _parse_basis_from_response(response)

        assert result["basis_type"] == ""
        assert result["basis_question_ids"] == []
        assert result["basis_confidence"] == 0.0
        assert result["should_show_references"] is False
        assert result["clean_response"] == response

    def test_question_ids_clamped_to_valid_range(self):
        """Test that question_ids are clamped to 1-999999 range"""
        from app.agents.chat.nodes import _parse_basis_from_response

        # IDs below 1 should be clamped to 1, above 999999 should be clamped
        response = '[BASIS]{"type":"mixed","question_ids":[0, -5, 1000000, 999999, 42],"confidence":0.7,"show_refs":false}[/BASIS]'

        result = _parse_basis_from_response(response)

        assert result["basis_type"] == "mixed"
        # 0 → 1, -5 → 1, 1000000 → 999999, 999999 stays, 42 stays
        assert result["basis_question_ids"] == [1, 1, 999999, 999999, 42]
        assert result["basis_confidence"] == 0.7
        assert result["should_show_references"] is False

    def test_missing_optional_fields(self):
        """Test handling when optional fields are missing from JSON"""
        from app.agents.chat.nodes import _parse_basis_from_response

        # Only type is provided, others are optional
        response = '[BASIS]{"type":"behavioral"}[/BASIS]'

        result = _parse_basis_from_response(response)

        assert result["basis_type"] == "behavioral"
        assert result["basis_question_ids"] == []
        assert result["basis_confidence"] == 0.0
        assert result["should_show_references"] is False
        assert result["clean_response"] == ""

    def test_response_with_thinking_tags(self):
        """Test parsing [BASIS] block when thinking tags are present"""
        from app.agents.chat.nodes import _parse_basis_from_response

        response = '<thinking>Analyzing the answer...</thinking>\n[BASIS]{"type":"technical","question_ids":[5],"confidence":0.9,"show_refs":true}[/BASIS]\nBased on my analysis, your answer is solid.'

        result = _parse_basis_from_response(response)

        assert result["basis_type"] == "technical"
        assert result["basis_question_ids"] == [5]
        assert result["basis_confidence"] == 0.9
        assert result["should_show_references"] is True
        # Thinking tags should remain in clean_response (they're separate from BASIS)
        assert "<thinking>" in result["clean_response"]
        assert "[BASIS]" not in result["clean_response"]

    def test_empty_question_ids_list(self):
        """Test handling when question_ids is an empty list"""
        from app.agents.chat.nodes import _parse_basis_from_response

        response = '[BASIS]{"type":"general","question_ids":[],"confidence":0.5,"show_refs":true}[/BASIS]\nResponse text.'

        result = _parse_basis_from_response(response)

        assert result["basis_type"] == "general"
        assert result["basis_question_ids"] == []
        assert result["basis_confidence"] == 0.5
        assert result["should_show_references"] is True
        assert "Response text." in result["clean_response"]
