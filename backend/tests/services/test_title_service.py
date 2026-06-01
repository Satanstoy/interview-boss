"""
TDD 测试 — Chat 对话标题自动生成

模仿 DeepSeek/ChatGPT 的做法：在用户发送第一条消息时，
用轻量 LLM 调用从消息中提取/生成一个简短的对话标题。
"""
import pytest
from unittest.mock import patch, AsyncMock


class TestGenerateTitle:
    """generate_title 核心功能测试"""

    @pytest.mark.asyncio
    async def test_chinese_interview_question_generates_title(self):
        """T-001: 中文面试问题应生成有意义的标题"""
        from app.services.title_service import generate_title

        with patch("app.services.title_service._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "Redis 数据结构介绍"

            title = await generate_title("请介绍一下 Redis 的五种数据结构", user_id=1)

        assert len(title) <= 20
        assert "Redis" in title
        assert title != "请介绍一下 Redis 的五种数据结构"  # 不是原样返回

    @pytest.mark.asyncio
    async def test_english_message_generates_chinese_title(self):
        """T-002: 英文消息应生成中文标题"""
        from app.services.title_service import generate_title

        with patch("app.services.title_service._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "CAP 定理解析"

            title = await generate_title("Explain the CAP theorem in distributed systems", user_id=1)

        assert len(title) <= 20
        # 中文标题应包含中文字符
        assert any('一' <= c <= '鿿' for c in title)

    @pytest.mark.asyncio
    async def test_short_message_uses_directly(self):
        """T-003: 短消息（<10 字符）直接用作标题，不调用 LLM"""
        from app.services.title_service import generate_title

        with patch("app.services.title_service._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            title = await generate_title("你好", user_id=1)

        assert title == "你好"
        mock_llm.assert_not_called()  # 不应调用 LLM

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_truncation(self):
        """T-004: LLM 失败时应降级为截断标题"""
        from app.services.title_service import generate_title

        with patch("app.services.title_service._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("API 超时")

            title = await generate_title("请介绍一下 Redis 的五种数据结构和它们的使用场景", user_id=1)

        assert len(title) <= 20
        assert len(title) > 0

    @pytest.mark.asyncio
    async def test_empty_message_returns_default(self):
        """T-005: 空消息应返回默认标题"""
        from app.services.title_service import generate_title

        title = await generate_title("", user_id=1)
        assert title == "新对话"

    @pytest.mark.asyncio
    async def test_title_length_within_limit(self):
        """T-006: 任何情况下标题长度 ≤ 20 字符"""
        from app.services.title_service import generate_title

        with patch("app.services.title_service._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "这是一个非常非常非常非常非常非常非常长的标题应该被截断"

            title = await generate_title("很长的消息" * 50, user_id=1)

        assert len(title) <= 20


class TestTitleIntegration:
    """标题生成集成测试"""

    def test_should_generate_title_for_default_titles(self):
        """T-007: 仅在 title 为默认值时触发生成"""
        from app.services.title_service import should_generate_title

        assert should_generate_title("新对话") is True
        assert should_generate_title("JD定制面试") is True
        assert should_generate_title("Redis 缓存策略讨论") is False
        assert should_generate_title("") is True  # 空标题也算默认
