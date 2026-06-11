"""
TDD 测试 — 结构化查询改写（Structured Query Rewrite）

替代简单关键词提取，用结构化 JSON 表达检索意图：
- retrieval_intent: 检索意图（find_similar / expand_knowledge / review_weakness）
- main_topic: 主题核心（2-4 字技术词）
- positive_terms: 必须包含的检索词
- negative_terms: 必须排除的检索词
"""

import pytest
import json
from unittest.mock import patch, AsyncMock


class TestParseStructuredRewrite:
    """_parse_structured_rewrite 解析 LLM JSON 输出"""

    def test_valid_rewrite(self):
        """SR-001: 正常 JSON 应完整解析"""
        from app.services.memory_recall_service import _parse_structured_rewrite

        llm_output = json.dumps(
            {
                "retrieval_intent": "find_similar",
                "main_topic": "Redis 缓存穿透",
                "positive_terms": ["Redis", "缓存穿透", "布隆过滤器"],
                "negative_terms": ["MySQL", "索引"],
            }
        )

        result = _parse_structured_rewrite(llm_output)

        assert result["retrieval_intent"] == "find_similar"
        assert result["main_topic"] == "Redis 缓存穿透"
        assert "Redis" in result["positive_terms"]
        assert "MySQL" in result["negative_terms"]

    def test_valid_minimal_fields(self):
        """SR-002: 只有 main_topic 和 retrieval_intent 也应有效"""
        from app.services.memory_recall_service import _parse_structured_rewrite

        llm_output = json.dumps(
            {
                "retrieval_intent": "expand_knowledge",
                "main_topic": "高并发限流",
                "positive_terms": [],
                "negative_terms": [],
            }
        )

        result = _parse_structured_rewrite(llm_output)

        assert result["retrieval_intent"] == "expand_knowledge"
        assert result["main_topic"] == "高并发限流"
        assert result["positive_terms"] == []
        assert result["negative_terms"] == []

    def test_invalid_json_falls_back(self):
        """SR-003: 非法 JSON 应返回 None（调用方用 fallback）"""
        from app.services.memory_recall_service import _parse_structured_rewrite

        result = _parse_structured_rewrite("这不是 JSON")

        assert result is None

    def test_missing_required_field_returns_none(self):
        """SR-004: 缺少 main_topic 字段应返回 None"""
        from app.services.memory_recall_service import _parse_structured_rewrite

        llm_output = json.dumps(
            {
                "retrieval_intent": "find_similar",
                "positive_terms": ["test"],
                "negative_terms": [],
            }
        )

        result = _parse_structured_rewrite(llm_output)

        assert result is None

    def test_invalid_intent_defaults_to_find_similar(self):
        """SR-005: 无效 retrieval_intent 应默认为 find_similar"""
        from app.services.memory_recall_service import _parse_structured_rewrite

        llm_output = json.dumps(
            {
                "retrieval_intent": "invalid_intent",
                "main_topic": "测试",
                "positive_terms": [],
                "negative_terms": [],
            }
        )

        result = _parse_structured_rewrite(llm_output)

        assert result["retrieval_intent"] == "find_similar"

    def test_positive_terms_max_limit(self):
        """SR-006: positive_terms 最多保留 5 个"""
        from app.services.memory_recall_service import _parse_structured_rewrite

        llm_output = json.dumps(
            {
                "retrieval_intent": "find_similar",
                "main_topic": "测试",
                "positive_terms": ["a", "b", "c", "d", "e", "f", "g"],
                "negative_terms": [],
            }
        )

        result = _parse_structured_rewrite(llm_output)

        assert len(result["positive_terms"]) <= 5

    def test_negative_terms_max_limit(self):
        """SR-007: negative_terms 最多保留 3 个"""
        from app.services.memory_recall_service import _parse_structured_rewrite

        llm_output = json.dumps(
            {
                "retrieval_intent": "find_similar",
                "main_topic": "测试",
                "positive_terms": [],
                "negative_terms": ["a", "b", "c", "d", "e"],
            }
        )

        result = _parse_structured_rewrite(llm_output)

        assert len(result["negative_terms"]) <= 3

    def test_empty_string_input(self):
        """SR-008: 空字符串应返回 None"""
        from app.services.memory_recall_service import _parse_structured_rewrite

        result = _parse_structured_rewrite("")

        assert result is None

    def test_none_input(self):
        """SR-009: None 输入应返回 None"""
        from app.services.memory_recall_service import _parse_structured_rewrite

        result = _parse_structured_rewrite(None)

        assert result is None


class TestBuildSearchParams:
    """_build_search_params 将 rewrite 转换为搜索参数"""

    def test_find_similar_uses_all_fields(self):
        """SP-001: find_similar 意图应使用全部正向+负向检索词"""
        from app.services.memory_recall_service import _build_search_params

        rewrite = {
            "retrieval_intent": "find_similar",
            "main_topic": "Redis 缓存穿透",
            "positive_terms": ["Redis", "缓存穿透", "布隆过滤器"],
            "negative_terms": ["MySQL"],
        }

        params = _build_search_params(rewrite)

        assert params["query"] is not None
        assert params["exclude_keywords"] == ["MySQL"]
        assert params["boost"] is None

    def test_expand_knowledge_broadens_search(self):
        """SP-002: expand_knowledge 应降低正向词权重，宽搜索"""
        from app.services.memory_recall_service import _build_search_params

        rewrite = {
            "retrieval_intent": "expand_knowledge",
            "main_topic": "高并发限流",
            "positive_terms": ["限流", "令牌桶"],
            "negative_terms": [],
        }

        params = _build_search_params(rewrite)

        assert params["query"] is not None
        assert params["exclude_keywords"] == []
        assert params["boost"] == "broad"

    def test_review_weakness_focuses_weakness(self):
        """SP-003: review_weakness 应优先匹配 weakness 记忆"""
        from app.services.memory_recall_service import _build_search_params

        rewrite = {
            "retrieval_intent": "review_weakness",
            "main_topic": "系统设计",
            "positive_terms": ["系统设计", "架构"],
            "negative_terms": [],
        }

        params = _build_search_params(rewrite)

        assert params["query"] is not None
        assert params["boost"] == "weakness"

    def test_empty_positive_terms_uses_main_topic(self):
        """SP-004: positive_terms 为空时，query 应退化为 main_topic"""
        from app.services.memory_recall_service import _build_search_params

        rewrite = {
            "retrieval_intent": "find_similar",
            "main_topic": "Redis",
            "positive_terms": [],
            "negative_terms": [],
        }

        params = _build_search_params(rewrite)

        assert params["query"] == "Redis"

    def test_query_combines_main_topic_and_positive_terms(self):
        """SP-005: query 应包含 main_topic 和 positive_terms"""
        from app.services.memory_recall_service import _build_search_params

        rewrite = {
            "retrieval_intent": "find_similar",
            "main_topic": "LRU 缓存",
            "positive_terms": ["LRU", "缓存淘汰"],
            "negative_terms": [],
        }

        params = _build_search_params(rewrite)

        assert "LRU" in params["query"] or "LRU 缓存" in params["query"]


class TestClassifyAndRecallIntegration:
    """classify_and_recall 集成结构化改写"""

    @pytest.mark.asyncio
    async def test_llm_returns_structured_rewrite(self):
        """INT-001: LLM 返回含 rewrite 的 JSON 时，应使用结构化改写"""
        from app.services.memory_recall_service import classify_and_recall

        summaries = [
            {"id": 5, "memory_type": "weakness", "summary": "Redis 缓存策略不熟悉"},
        ]

        mock_response = json.dumps(
            {
                "intent": "interview_question",
                "relevant_memory_ids": [5],
                "keywords": ["Redis", "缓存穿透"],
                "search_query": "Redis 缓存穿透 布隆过滤器",
                "answer_complete": True,
                "rewrite": {
                    "retrieval_intent": "find_similar",
                    "main_topic": "Redis 缓存穿透",
                    "positive_terms": ["Redis", "缓存穿透", "布隆过滤器"],
                    "negative_terms": ["MySQL"],
                },
            }
        )

        with patch(
            "app.services.memory_recall_service._call_llm_with_retry",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = mock_response

            (
                intent,
                memory_ids,
                keywords,
                search_query,
                answer_complete,
            ) = await classify_and_recall(
                user_message="面试官好，我来回答一下关于 Redis 缓存穿透和布隆过滤器的技术问题",
                recent_context="",
                memory_summaries=summaries,
                user_id=1,
            )

        assert intent == "interview_question"
        assert 5 in memory_ids
        assert isinstance(keywords, list)
        assert isinstance(search_query, str)

    @pytest.mark.asyncio
    async def test_llm_without_rewrite_falls_back(self):
        """INT-002: LLM 返回不含 rewrite 的 JSON 时，应降级到原关键词逻辑"""
        from app.services.memory_recall_service import classify_and_recall

        summaries = [
            {"id": 5, "memory_type": "weakness", "summary": "Redis 不熟"},
        ]

        mock_response = json.dumps(
            {
                "intent": "interview_question",
                "relevant_memory_ids": [5],
                "keywords": ["Redis"],
                "search_query": "Redis 数据结构",
                "answer_complete": True,
            }
        )

        with patch(
            "app.services.memory_recall_service._call_llm_with_retry",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = mock_response

            (
                intent,
                memory_ids,
                keywords,
                search_query,
                answer_complete,
            ) = await classify_and_recall(
                user_message="Redis 有哪些数据结构",
                recent_context="",
                memory_summaries=summaries,
                user_id=1,
            )

        assert intent == "interview_question"
        assert search_query  # 应有非空 search_query

    @pytest.mark.asyncio
    async def test_invalid_rewrite_still_returns_valid_result(self):
        """INT-003: LLM 返回无效 rewrite 时，不应崩溃，应降级"""
        from app.services.memory_recall_service import classify_and_recall

        summaries = [
            {"id": 5, "memory_type": "weakness", "summary": "测试"},
        ]

        mock_response = json.dumps(
            {
                "intent": "interview_question",
                "relevant_memory_ids": [5],
                "keywords": ["测试"],
                "search_query": "测试消息",
                "answer_complete": False,
                "rewrite": {"invalid": "structure"},
            }
        )

        with patch(
            "app.services.memory_recall_service._call_llm_with_retry",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = mock_response

            (
                intent,
                memory_ids,
                keywords,
                search_query,
                answer_complete,
            ) = await classify_and_recall(
                user_message="测试消息",
                recent_context="",
                memory_summaries=summaries,
                user_id=1,
            )

        assert intent in {"interview_question", "practice_request", "chat", "follow_up"}
        assert isinstance(search_query, str)
