"""
TDD 测试 — LangGraph 最佳实践改进

基于研究结果，实现两个改进：
1. 条件路由显式化（route_after_classify 函数）
2. 最大轮次限制（防止无限对话）
"""
import pytest


class TestExplicitRouting:
    """条件路由显式化测试"""

    def test_interview_intent_complete_routes_to_rag(self):
        """面试问题意图 + 回答应完整 → 路由到 RAG 检索（为出新题提供参考）"""
        from app.agents.chat.nodes import route_after_classify

        state = {"intent": "interview_question", "answer_complete": True}
        assert route_after_classify(state) == "rag_retrieve"

    def test_interview_intent_incomplete_routes_to_direct(self):
        """面试问题意图 + 回答不完整 → 路由到直接回复（面试官会追问）"""
        from app.agents.chat.nodes import route_after_classify

        state = {"intent": "interview_question", "answer_complete": False}
        assert route_after_classify(state) == "direct_respond"

    def test_practice_request_routes_to_rag(self):
        """练习请求应路由到 RAG 检索"""
        from app.agents.chat.nodes import route_after_classify

        state = {"intent": "practice_request"}
        assert route_after_classify(state) == "rag_retrieve"

    def test_chat_intent_routes_to_direct(self):
        """闲聊应路由到直接回复"""
        from app.agents.chat.nodes import route_after_classify

        state = {"intent": "chat"}
        assert route_after_classify(state) == "direct_respond"

    def test_follow_up_routes_to_direct(self):
        """追问应路由到直接回复"""
        from app.agents.chat.nodes import route_after_classify

        state = {"intent": "follow_up"}
        assert route_after_classify(state) == "direct_respond"

    def test_unknown_intent_defaults_to_direct(self):
        """未知意图 + 回答不完整 → 默认路由到直接回复"""
        from app.agents.chat.nodes import route_after_classify

        state = {"intent": "unknown", "answer_complete": False}
        assert route_after_classify(state) == "direct_respond"

    def test_unknown_intent_complete_routes_to_rag(self):
        """未知意图 + 回答完整 → 默认路由到 RAG 检索"""
        from app.agents.chat.nodes import route_after_classify

        state = {"intent": "unknown", "answer_complete": True}
        assert route_after_classify(state) == "rag_retrieve"

    def test_missing_intent_defaults_to_direct(self):
        """缺失意图字段默认为 interview_question + answer_complete=False → 直接回复"""
        from app.agents.chat.nodes import route_after_classify

        state = {}
        assert route_after_classify(state) == "direct_respond"


class TestMaxRoundsLimit:
    """最大轮次限制测试"""

    def test_under_limit_allows_continuation(self):
        """消息数未超限时应允许继续"""
        from app.agents.chat.nodes import check_round_limit

        # 10 条消息（5 轮）< 100 条限制
        messages = [{"role": "user", "content": "test"}] * 10
        assert check_round_limit(messages) is True

    def test_at_limit_blocks_continuation(self):
        """消息数达到超限时应阻止继续"""
        from app.agents.chat.nodes import check_round_limit

        # 100 条消息（50 轮）= 100 条限制
        messages = [{"role": "user", "content": "test"}] * 100
        assert check_round_limit(messages) is False

    def test_over_limit_blocks_continuation(self):
        """消息数超过超限时应阻止继续"""
        from app.agents.chat.nodes import check_round_limit

        messages = [{"role": "user", "content": "test"}] * 150
        assert check_round_limit(messages) is False

    def test_empty_messages_allows_continuation(self):
        """空消息列表应允许继续"""
        from app.agents.chat.nodes import check_round_limit

        assert check_round_limit([]) is True
