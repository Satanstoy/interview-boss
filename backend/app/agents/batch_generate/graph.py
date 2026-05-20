"""Batch-Generate-Answers 流程的 LangGraph StateGraph 定义"""
from langgraph.graph import StateGraph, START, END

from app.agents.shared.state import BatchGenerateState
from app.agents.batch_generate.nodes import (
    load_questions_node,
    generate_answer_node,
    should_continue_generate,
    summarize_node,
)


def _build_batch_generate_graph() -> StateGraph:
    """构建批量生成答案的 StateGraph"""
    workflow = StateGraph(BatchGenerateState)

    workflow.add_node("load_questions", load_questions_node)
    workflow.add_node("generate_answer", generate_answer_node)
    workflow.add_node("summarize", summarize_node)

    workflow.add_edge(START, "load_questions")
    workflow.add_edge("load_questions", "generate_answer")

    # 条件路由: 继续生成下一题 或 结束
    workflow.add_conditional_edges(
        "generate_answer",
        should_continue_generate,
        {"continue": "generate_answer", "done": "summarize"},
    )
    workflow.add_edge("summarize", END)

    return workflow


batch_generate_graph = _build_batch_generate_graph().compile()


async def stream_batch_generate(input_state: dict):
    """将 batch_generate astream_events 映射为 SSE 事件流"""
    import json
    from app.agents.shared.events import format_sse, make_error_event

    config = {"configurable": {"thread_id": f"generate-{input_state.get('user_id', 0)}-{__import__('time').time():.0f}"}}

    try:
        async for event in batch_generate_graph.astream_events(input_state, config=config, version="v2"):
            if event.get("event") == "on_chain_end":
                node_name = event.get("name", "")
                if node_name.startswith("__"):
                    continue
                output = event.get("data", {}).get("output", {})
                if not isinstance(output, dict):
                    continue
                for evt in output.get("events", []):
                    yield format_sse(evt)
    except Exception as e:
        import logging
        logging.getLogger("interview-boss").exception("Batch generate graph 执行失败")
        yield format_sse(make_error_event(f"答案生成失败: {str(e)[:200]}"))
