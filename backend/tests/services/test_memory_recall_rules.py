"""
TDD 测试 — Memory Recall 规则路径

测试 _rule_based_intent 和 _extract_keywords_fallback 的各种场景。
这些是纯规则函数，零 LLM 成本。
"""
import pytest


class TestRuleBasedIntent:
    """_rule_based_intent 规则意图分类测试"""

    def test_chat_keywords_return_chat(self):
        """聊天关键词应返回 chat 意图"""
        from app.services.memory_recall_service import _rule_based_intent

        chat_messages = ["你好", "hello", "hi", "谢谢", "感谢", "再见", "拜拜", "ok", "好的", "嗯"]
        for msg in chat_messages:
            result = _rule_based_intent(msg)
            assert result == "chat", f"'{msg}' 应返回 chat，实际返回 {result}"

    def test_chat_keyword_case_insensitive(self):
        """聊天关键词应不区分大小写"""
        from app.services.memory_recall_service import _rule_based_intent

        assert _rule_based_intent("Hello") == "chat"
        assert _rule_based_intent("OK") == "chat"
        assert _rule_based_intent("HI") == "chat"

    def test_practice_keywords_return_practice_request(self):
        """练习关键词应返回 practice_request 意图"""
        from app.services.memory_recall_service import _rule_based_intent

        practice_messages = [
            "出题",
            "来一道算法题",
            "换一个话题",
            "换个题目",
            "开始练习",
            "出个设计题",
            "出题吧",
        ]
        for msg in practice_messages:
            result = _rule_based_intent(msg)
            assert result == "practice_request", f"'{msg}' 应返回 practice_request，实际返回 {result}"

    def test_follow_up_keywords_return_follow_up(self):
        """追问关键词（短消息）应返回 follow_up 意图"""
        from app.services.memory_recall_service import _rule_based_intent

        follow_up_messages = [
            "能解释一下吗",
            "详细说说",
            "具体怎么做",
            "为什么这样",
            "怎么实现",
            "能再说一遍吗",
            "不太明白",
            "什么意思",
        ]
        for msg in follow_up_messages:
            result = _rule_based_intent(msg)
            assert result == "follow_up", f"'{msg}' 应返回 follow_up，实际返回 {result}"

    def test_follow_up_keyword_in_long_message_not_triggered(self):
        """长消息中的追问关键词不应触发 follow_up"""
        from app.services.memory_recall_service import _rule_based_intent

        # 超过 50 字的消息不应被 follow_up 关键词匹配
        long_msg = "这个问题的解释涉及到多个方面，首先我们需要理解底层原理，然后才能给出具体的实现方案，整体来说需要考虑性能和可维护性"
        result = _rule_based_intent(long_msg)
        # 应该返回 None（需要 LLM 判断）而不是 follow_up
        assert result is None

    def test_interview_message_returns_none(self):
        """面试回答消息应返回 None（需要 LLM 判断）"""
        from app.services.memory_recall_service import _rule_based_intent

        interview_messages = [
            "Redis 的五种数据结构包括 String、List、Hash、Set 和 ZSet",
            "分布式锁可以通过 Redis 的 SETNX 命令实现",
            "我觉得这个方案的优缺点如下",
        ]
        for msg in interview_messages:
            result = _rule_based_intent(msg)
            assert result is None, f"'{msg}' 应返回 None，实际返回 {result}"

    def test_empty_message_returns_none(self):
        """空消息应返回 None"""
        from app.services.memory_recall_service import _rule_based_intent

        assert _rule_based_intent("") is None
        assert _rule_based_intent("   ") is None


class TestExtractKeywordsFallback:
    """_extract_keywords_fallback 关键词提取测试"""

    def test_chinese_keywords_extracted(self):
        """应提取 2-4 字的中文技术词"""
        from app.services.memory_recall_service import _extract_keywords_fallback

        keywords = _extract_keywords_fallback("Redis 的缓存策略有哪些")
        assert len(keywords) > 0
        keyword_text = " ".join(keywords)
        assert "缓存" in keyword_text or "策略" in keyword_text

    def test_english_keywords_extracted(self):
        """应提取英文技术术语"""
        from app.services.memory_recall_service import _extract_keywords_fallback

        keywords = _extract_keywords_fallback("How to use Docker container")
        assert len(keywords) > 0
        keyword_text = " ".join(keywords).lower()
        assert "docker" in keyword_text or "container" in keyword_text

    def test_mixed_keywords(self):
        """中英文混合消息应提取两种关键词"""
        from app.services.memory_recall_service import _extract_keywords_fallback

        keywords = _extract_keywords_fallback("Redis 的分布式锁怎么实现")
        assert len(keywords) > 0
        keyword_text = " ".join(keywords).lower()
        assert "redis" in keyword_text
        # 应包含中文关键词
        cjk_keywords = [k for k in keywords if any('一' <= c <= '鿿' for c in k)]
        assert len(cjk_keywords) > 0

    def test_stop_words_filtered(self):
        """停用词应被过滤"""
        from app.services.memory_recall_service import _extract_keywords_fallback

        keywords = _extract_keywords_fallback("你好我是目前在读方向是可以")
        # 停用词不应出现在结果中
        stop_words = {"你好", "我是", "目前", "在读", "方向是", "的是", "可以"}
        for kw in keywords:
            assert kw not in stop_words, f"停用词 '{kw}' 不应出现在结果中"

    def test_short_cjk_words_filtered(self):
        """单字中文词应被过滤"""
        from app.services.memory_recall_service import _extract_keywords_fallback

        keywords = _extract_keywords_fallback("我你他她它的了是在")
        # 单字词不应出现
        for kw in keywords:
            assert len(kw) >= 2, f"单字词 '{kw}' 不应出现在结果中"

    def test_max_keywords_limit(self):
        """返回关键词数量应不超过 5 个"""
        from app.services.memory_recall_service import _extract_keywords_fallback

        keywords = _extract_keywords_fallback("Redis 缓存穿透布隆过滤器高并发限流方案分布式锁实现")
        assert len(keywords) <= 5

    def test_empty_message_returns_empty(self):
        """空消息应返回空列表"""
        from app.services.memory_recall_service import _extract_keywords_fallback

        assert _extract_keywords_fallback("") == []
        assert _extract_keywords_fallback("   ") == []

    def test_technical_terms_priority(self):
        """技术术语应优先提取"""
        from app.services.memory_recall_service import _extract_keywords_fallback

        keywords = _extract_keywords_fallback("Redis 的五种数据结构有哪些")
        # Redis 是英文技术词，应被提取
        assert any("redis" in k.lower() for k in keywords)

    def test_short_english_words_filtered(self):
        """过短的英文单词（<2字符）应被过滤"""
        from app.services.memory_recall_service import _extract_keywords_fallback

        keywords = _extract_keywords_fallback("I am a developer using Go")
        # "I", "am", "a" 不应出现（太短）
        for kw in keywords:
            if kw.isascii():
                assert len(kw) >= 2, f"短英文词 '{kw}' 不应出现在结果中"
