import pytest


@pytest.mark.asyncio
async def test_insufficient_evidence_no_unknown_project():
    """追问时不应引入候选人未提及的项目。"""
    from app.agents.chat.output_guardrails import check_context_grounding

    candidate_context = "211 硕士，2年 RAG 开发经验，用 LangGraph 搭建 Agent"
    interviewer_output = "在你做过的 OpenClaw 项目中，你是怎么处理多智能体循环的？"

    result = check_context_grounding(interviewer_output, candidate_context)
    assert result["passed"] is False
    assert "OpenClaw" in result["unknown_entities"]
