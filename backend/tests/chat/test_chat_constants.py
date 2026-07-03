"""Tests for chat_constants — keyword lists, signals, fallback texts."""

from __future__ import annotations

from app.agents.chat.chat_constants import (
    CANDIDATE_QUESTION_MARKER,
    CANDIDATE_QUESTION_PROMPT,
    CHAT_KEYWORDS,
    END_KEYWORDS,
    FALLBACK_ALGORITHM_CODING,
    FALLBACK_EMPTY_QUESTION,
    FALLBACK_GENERIC,
    FALLBACK_PROJECT_DEEP_DIVE,
    FOLLOW_UP_KEYWORDS,
    FOLLOW_UP_MAX_LENGTH,
    PRACTICE_KEYWORDS,
)


class TestIntentKeywords:
    """Keyword lists must be non-empty and contain expected entries."""

    def test_chat_keywords_non_empty(self):
        assert len(CHAT_KEYWORDS) > 0

    def test_chat_keywords_contains_你好(self):
        assert "你好" in CHAT_KEYWORDS

    def test_chat_keywords_contains_hello(self):
        assert "hello" in CHAT_KEYWORDS

    def test_chat_keywords_is_frozenset(self):
        assert isinstance(CHAT_KEYWORDS, frozenset)

    def test_practice_keywords_non_empty(self):
        assert len(PRACTICE_KEYWORDS) > 0

    def test_practice_keywords_contains_出题(self):
        assert "出题" in PRACTICE_KEYWORDS

    def test_practice_keywords_is_tuple(self):
        assert isinstance(PRACTICE_KEYWORDS, tuple)

    def test_end_keywords_non_empty(self):
        assert len(END_KEYWORDS) > 0

    def test_end_keywords_contains_结束面试(self):
        assert "结束面试" in END_KEYWORDS

    def test_follow_up_keywords_non_empty(self):
        assert len(FOLLOW_UP_KEYWORDS) > 0

    def test_follow_up_keywords_contains_解释(self):
        assert "解释" in FOLLOW_UP_KEYWORDS

    def test_follow_up_max_length(self):
        assert FOLLOW_UP_MAX_LENGTH == 50


class TestStopPolicyConstants:
    """Stop policy prompts and markers."""

    def test_candidate_question_prompt_contains_marker(self):
        assert CANDIDATE_QUESTION_MARKER in CANDIDATE_QUESTION_PROMPT

    def test_candidate_question_marker(self):
        assert CANDIDATE_QUESTION_MARKER == "你有什么想问"


class TestFallbackTexts:
    """Fallback text templates must be non-empty strings."""

    def test_project_deep_dive(self):
        assert len(FALLBACK_PROJECT_DEEP_DIVE) > 10

    def test_algorithm_coding(self):
        assert len(FALLBACK_ALGORITHM_CODING) > 10

    def test_generic(self):
        assert len(FALLBACK_GENERIC) > 10

    def test_empty_question(self):
        assert len(FALLBACK_EMPTY_QUESTION) > 10
