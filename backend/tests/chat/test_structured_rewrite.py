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

    def test_polluted_field_names_are_rejected(self):
        """SR-005b: LLM 把字段名当 query 时应拒绝结构化改写"""
        from app.services.memory_recall_service import _parse_structured_rewrite

        llm_output = json.dumps(
            {
                "retrieval_intent": "find_similar",
                "main_topic": "intent answer complete search query",
                "positive_terms": ["intent", "answer", "search_query"],
                "negative_terms": ["用户在讲 RAG 项目"],
            }
        )

        result = _parse_structured_rewrite(llm_output)

        assert result is None

    def test_polluted_negative_terms_are_filtered(self):
        """SR-005c: negative_terms 只能保留真实技术词"""
        from app.services.memory_recall_service import _parse_structured_rewrite

        llm_output = json.dumps(
            {
                "retrieval_intent": "find_similar",
                "main_topic": "RRF 融合",
                "positive_terms": ["RRF", "reciprocal rank fusion"],
                "negative_terms": ["用户在讲 RAG 项目", "一个题在 FTS 里排第 1", "Redis"],
            }
        )

        result = _parse_structured_rewrite(llm_output)

        assert result["negative_terms"] == ["Redis"]

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
                _structured_rewrite,
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
                _structured_rewrite,
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
                _structured_rewrite,
            ) = await classify_and_recall(
                user_message="测试消息",
                recent_context="",
                memory_summaries=summaries,
                user_id=1,
            )

        assert intent in {"interview_question", "practice_request", "chat", "follow_up"}
        assert isinstance(search_query, str)


class TestNegativeTermsFiltering:
    """_filter_negative_terms 过滤负向排除词"""

    def test_filter_excludes_matching_results(self):
        from app.services.fts_service import _filter_negative_terms

        results = [
            {
                "id": 1,
                "question": "Redis 缓存穿透怎么解决",
                "tags": "Redis",
                "cat1": "数据库",
                "cat2": "",
            },
            {
                "id": 2,
                "question": "MySQL 索引优化",
                "tags": "MySQL",
                "cat1": "数据库",
                "cat2": "",
            },
            {
                "id": 3,
                "question": "Redis 持久化机制",
                "tags": "Redis",
                "cat1": "数据库",
                "cat2": "",
            },
        ]
        filtered = _filter_negative_terms(results, ["MySQL"])
        assert len(filtered) == 2
        assert all(r["id"] != 2 for r in filtered)

    def test_filter_no_match_keeps_all(self):
        from app.services.fts_service import _filter_negative_terms

        results = [
            {"id": 1, "question": "Redis 缓存穿透", "tags": "", "cat1": "", "cat2": ""},
            {"id": 2, "question": "LRU 缓存设计", "tags": "", "cat1": "", "cat2": ""},
        ]
        filtered = _filter_negative_terms(results, ["MySQL"])
        assert len(filtered) == 2

    def test_filter_empty_negative_terms(self):
        from app.services.fts_service import _filter_negative_terms

        results = [{"id": 1, "question": "测试", "tags": "", "cat1": "", "cat2": ""}]
        filtered = _filter_negative_terms(results, [])
        assert len(filtered) == 1

    def test_filter_checks_all_fields(self):
        from app.services.fts_service import _filter_negative_terms

        results = [
            {"id": 1, "question": "问题", "tags": "MySQL优化", "cat1": "", "cat2": ""},
            {"id": 2, "question": "问题", "tags": "", "cat1": "MySQL相关", "cat2": ""},
            {"id": 3, "question": "问题", "tags": "", "cat1": "", "cat2": "MySQL专题"},
        ]
        filtered = _filter_negative_terms(results, ["MySQL"])
        assert len(filtered) == 0


class TestInferRuleBasedRewrite:
    """_infer_rule_based_rewrite 轻量规则推断"""

    def test_project_keywords_infer_project_followup(self):
        from app.services.memory_recall_service import _infer_rule_based_rewrite

        result = _infer_rule_based_rewrite(
            "说说你的项目架构是怎么设计的",
            ["架构", "设计"],
            "interview_question",
        )
        assert result["question_type"] == "project_followup"
        assert result["retrieval_intent"] == "find_similar"

    def test_knowledge_keywords_infer_knowledge_probe(self):
        from app.services.memory_recall_service import _infer_rule_based_rewrite

        result = _infer_rule_based_rewrite(
            "Redis 缓存穿透怎么解决",
            ["Redis", "缓存穿透"],
            "interview_question",
        )
        assert result["question_type"] == "knowledge_probe"

    def test_practice_request_infer_find_similar(self):
        from app.services.memory_recall_service import _infer_rule_based_rewrite

        result = _infer_rule_based_rewrite(
            "出一道算法题",
            ["算法"],
            "practice_request",
        )
        assert result["retrieval_intent"] == "find_similar"

    def test_follow_up_infer_expand_knowledge(self):
        from app.services.memory_recall_service import _infer_rule_based_rewrite

        result = _infer_rule_based_rewrite(
            "能再详细说说吗",
            [],
            "follow_up",
        )
        assert result["retrieval_intent"] == "expand_knowledge"

    def test_negative_pattern_extracts_example_words(self):
        from app.services.memory_recall_service import _infer_rule_based_rewrite

        result = _infer_rule_based_rewrite(
            '这个参考题不对，"AI Coding" 是例子',
            ["参考题"],
            "interview_question",
        )
        assert "AI Coding" in result["negative_terms"]

    def test_short_message_infer_review_weakness(self):
        from app.services.memory_recall_service import _infer_rule_based_rewrite

        result = _infer_rule_based_rewrite(
            "不太清楚",
            [],
            "interview_question",
        )
        assert result["retrieval_intent"] == "review_weakness"

    def test_no_project_or_knowledge_defaults_to_new_question(self):
        from app.services.memory_recall_service import _infer_rule_based_rewrite

        result = _infer_rule_based_rewrite(
            "介绍一下你自己",
            ["自我介绍"],
            "interview_question",
        )
        assert result["question_type"] == "new_question"

    def test_state_fields_not_in_positive_terms(self):
        """状态字段不能作为核心关键词"""
        from app.services.memory_recall_service import _infer_rule_based_rewrite

        result = _infer_rule_based_rewrite(
            "conversation_id 和 retrieved_questions 不是关键词",
            ["conversation_id", "retrieved_questions", "id"],
            "interview_question",
        )
        # 状态字段应该被过滤掉
        for term in result["positive_terms"]:
            assert term.lower() not in {
                "conversation_id",
                "retrieved_questions",
                "id",
                "selected_basis_questions",
                "basis_type",
                "metadata",
            }

    def test_noise_example_extracts_negative_terms(self):
        """噪声示例应该进入 negative_terms"""
        from app.services.memory_recall_service import _infer_rule_based_rewrite

        result = _infer_rule_based_rewrite(
            "比如 LRU、Redis、AI Coding 工具使用这种噪声不该被召回",
            ["RAG", "混合检索"],
            "interview_question",
        )
        assert "LRU" in result["negative_terms"]
        assert "Redis" in result["negative_terms"]

    def test_noise_example_with_quotes(self):
        """引号中的噪声示例应该进入 negative_terms"""
        from app.services.memory_recall_service import _infer_rule_based_rewrite

        result = _infer_rule_based_rewrite(
            '这个参考题不对，"AI Coding" 是例子',
            ["参考题"],
            "interview_question",
        )
        assert "AI Coding" in result["negative_terms"]

    def test_negative_terms_do_not_affect_question_type(self):
        """negative_terms 不应该影响 question_type 判断"""
        from app.services.memory_recall_service import _infer_rule_based_rewrite

        result = _infer_rule_based_rewrite(
            "比如 LRU、Redis 这种噪声不该被召回，我想问的是 RAG 混合检索",
            ["RAG", "混合检索", "检索"],
            "interview_question",
        )
        # question_type 应该基于 positive_terms，不是 negative_terms
        assert result["question_type"] in {
            "project_followup",
            "knowledge_probe",
            "new_question",
        }
        # negative_terms 应该包含噪声词
        assert len(result["negative_terms"]) > 0
