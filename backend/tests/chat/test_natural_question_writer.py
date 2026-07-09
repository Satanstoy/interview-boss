import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_natural_question_writer_returns_error_on_empty():
    """LLM 输出为空时应返回 error。"""
    from app.agents.chat.natural_question_writer import generate_natural_question

    mock_llm = AsyncMock(return_value="")

    result = await generate_natural_question(
        question_intent={"question": "如何设计高并发消息队列？", "question_type": "system_design"},
        selected_question={"id": 123, "question": "如何设计高并发消息队列？"},
        context_anchor="候选人提到过消息队列",
        llm_call=mock_llm,
    )

    assert result["status"] == "error"
    assert result["error_code"] == "natural_question_generation_failed"


@pytest.mark.asyncio
async def test_natural_question_writer_rejects_mechanical():
    """机械复述题干应返回 error。"""
    from app.agents.chat.natural_question_writer import generate_natural_question

    mock_llm = AsyncMock(return_value="好，如何设计高并发消息队列？")

    result = await generate_natural_question(
        question_intent={"question": "如何设计高并发消息队列？", "question_type": "system_design"},
        selected_question={"id": 123, "question": "如何设计高并发消息队列？"},
        context_anchor="候选人提到过消息队列",
        llm_call=mock_llm,
    )

    assert result["status"] == "error"
    assert result["error_code"] == "natural_question_generation_failed"
    assert result["guard"] == "naturalness"


@pytest.mark.asyncio
async def test_natural_question_writer_success():
    """正常自然化问题应返回 success。"""
    from app.agents.chat.natural_question_writer import generate_natural_question

    mock_llm = AsyncMock(
        return_value="你刚才提到在项目里用过消息队列处理异步任务。那我想深入问一下——如果让你设计一个支撑每秒10万消息的队列系统，你会怎么考虑架构？"
    )

    result = await generate_natural_question(
        question_intent={"question": "如何设计高并发消息队列？", "question_type": "system_design"},
        selected_question={"id": 123, "question": "如何设计高并发消息队列？"},
        context_anchor="候选人提到过消息队列",
        llm_call=mock_llm,
    )

    assert result["status"] == "success"
    assert "消息队列" in result["text"]
    assert len(result["text"]) > 20  # 不是机械复述
