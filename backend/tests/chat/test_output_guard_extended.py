from app.agents.chat.output_guardrails import check_context_grounding


def test_context_grounding_blocks_unknown_project():
    """引入候选人未提及的项目应被拦截。"""
    candidate_context = "211 硕士，2年 RAG 开发经验，用 LangGraph 搭建 Agent"
    output = "在你做过的 OpenClaw 项目中，你是怎么处理多智能体循环的？"

    result = check_context_grounding(output, candidate_context)
    assert result["passed"] is False
    assert "OpenClaw" in result["reason"]


def test_context_grounding_passes_known_project():
    """提及候选人已知项目应通过。"""
    candidate_context = "211 硕士，2年 RAG 开发经验，用 LangGraph 搭建 Agent"
    output = "你刚才提到用 LangGraph 搭建过 Agent，那遇到过输出不稳定的情况吗？"

    result = check_context_grounding(output, candidate_context)
    assert result["passed"] is True
