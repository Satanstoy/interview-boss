import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_summary_writer_requires_sections():
    """总结必须包含必备段落。"""
    from app.agents.chat.summary_writer import generate_summary

    mock_llm = AsyncMock(return_value="""{
        "overall_comment": "候选人技术扎实，对 RAG 和 Agent 有深入理解",
        "strongest_topic": "RAG 系统设计",
        "weakest_topic": "算法编码",
        "key_suggestions": ["加强算法练习", "深入学习分布式系统", "准备系统设计题"],
        "score_estimate": 7,
        "hiring_signal": "建议进入下一轮",
        "risk_points": "算法能力需要验证",
        "next_round_questions": ["设计一个分布式限流系统"]
    }""")

    result = await generate_summary(
        session_notes="讨论了 RAG、Agent、Redis、MySQL",
        asked_questions=["RAG 召回率", "Agent 稳定性", "Redis 分布式锁"],
        message_count=16,
        llm_call=mock_llm,
    )

    assert result["status"] == "success"
    assert "overall_comment" in result["summary"]
    assert "hiring_signal" in result["summary"]
