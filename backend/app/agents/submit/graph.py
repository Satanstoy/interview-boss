"""Submit 流程的 LangGraph StateGraph 定义"""
import asyncio
import json
import logging
from langgraph.graph import StateGraph, START, END

from app.agents.shared.state import SubmitState
from app.agents.shared.quality import should_retry
from app.agents.shared.events import format_sse, make_error_event, make_done_event, _event_queue_var
from app.agents.submit.extract import recognize_node, extract_node, retry_extract_node
from app.agents.submit.classify import complete_node, classify_node, retry_classify_node
from app.agents.submit.persist_personal import match_and_persist_personal_node, jd_persist_node, error_empty_node
from app.agents.submit.persist_public import persist_public_node, cluster_public_node

logger = logging.getLogger("interview-boss")

_FRIENDLY_ERROR = "AI 服务配置错误，请在系统设置中配置有效的 API Key"


def _sanitize_error(e: Exception) -> str:
    err_str = str(e).lower()
    if "401" in err_str or "invalid api key" in err_str or "unauthorized" in err_str:
        return _FRIENDLY_ERROR
    return f"处理失败: {str(e)[:200]}"


# ── 条件路由函数 ──

def after_extract(state: SubmitState) -> str:
    """提取后路由: JD 直接保存 / 空题报错 / 质量达标继续 / 否则重试"""
    doc_type = state.get("doc_type", "")
    quality = state.get("extraction_quality", 0)
    retries = state.get("extraction_retries", 0)

    # JD 路径：提取后直接保存，不走 classify
    if doc_type == "jd":
        return "jd"

    # 空题检查：重试后仍无题目
    data = state.get("extracted_data", {})
    questions = data.get("具体题目清单", [])
    if not questions and retries >= 2:
        return "error_empty"

    if quality <= 0 or should_retry(quality, retries):
        if retries < 2:
            return "retry"
    return "continue"


def after_classify(state: SubmitState) -> str:
    """分类后路由: 质量不足则重试，否则按 target 路由到对应路径"""
    quality = state.get("tagging_quality", 0)
    retries = state.get("tagging_retries", 0)
    if quality <= 0 or should_retry(quality, retries):
        if retries < 2:
            return "retry"
    target = state.get("target", "personal")
    if target == "public":
        return "public"
    return "personal"


# ── Graph 构建 ──

def _build_submit_graph() -> StateGraph:
    """构建 Submit 流程的 StateGraph"""
    workflow = StateGraph(SubmitState)

    # 添加节点（直接使用原函数，错误通过 state["error"] 传递）
    workflow.add_node("recognize", recognize_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("retry_extract", retry_extract_node)
    workflow.add_node("complete", complete_node)
    workflow.add_node("classify", classify_node)
    workflow.add_node("retry_classify", retry_classify_node)
    workflow.add_node("match_persist_personal", match_and_persist_personal_node)
    workflow.add_node("persist_public", persist_public_node)
    workflow.add_node("cluster_public", cluster_public_node)
    workflow.add_node("jd_persist", jd_persist_node)
    workflow.add_node("error_empty", error_empty_node)

    # 边: START → recognize → extract
    workflow.add_edge(START, "recognize")
    workflow.add_edge("recognize", "extract")

    # 条件边: extract → (JD / empty error / quality check) → jd/error/continue/retry
    workflow.add_conditional_edges(
        "extract",
        after_extract,
        {"jd": "jd_persist", "error_empty": "error_empty", "continue": "complete", "retry": "retry_extract"},
    )
    workflow.add_edge("retry_extract", "extract")

    # JD 路径结束
    workflow.add_edge("jd_persist", END)

    # 空题错误结束
    workflow.add_edge("error_empty", END)

    # 边: complete → classify
    workflow.add_edge("complete", "classify")

    # 条件边: classify → (quality check + target route) → retry/personal/public
    workflow.add_conditional_edges(
        "classify",
        after_classify,
        {"retry": "retry_classify", "personal": "match_persist_personal", "public": "persist_public"},
    )
    workflow.add_edge("retry_classify", "classify")

    # 个人路径结束
    workflow.add_edge("match_persist_personal", END)

    # 公共路径: persist → cluster → END
    workflow.add_edge("persist_public", "cluster_public")
    workflow.add_edge("cluster_public", END)

    return workflow


# ── 编译后的图实例 ──

from langgraph.checkpoint.memory import MemorySaver
submit_graph = _build_submit_graph().compile(checkpointer=MemorySaver())


# ── SSE 流式桥接 ──

_SENTINEL = object()  # 队列终止信号


async def stream_submit_graph(input_state: dict, result_collector: dict = None):
    """将 LangGraph 执行映射为前端 SSE 事件流。

    使用 event_queue 实现实时推送：每个节点在执行过程中立即将事件写入队列，
    本函数从队列读取并 yield SSE 字符串，不等待节点执行完毕。
    """
    queue = asyncio.Queue()
    token = _event_queue_var.set(queue)
    config = {"configurable": {"thread_id": f"submit-{input_state.get('user_id', 0)}-{__import__('time').time():.0f}"}}

    async def _run_graph():
        """在后台运行图，完成后向队列发送终止信号"""
        import time as _t
        _t0 = _t.monotonic()
        try:
            logger.info("[SSE] graph task started")
            await submit_graph.ainvoke(input_state, config=config)
            logger.info(f"[SSE] graph task completed in {_t.monotonic()-_t0:.1f}s")
        except Exception as e:
            logger.exception(f"[SSE] graph task failed in {_t.monotonic()-_t0:.1f}s")
            queue.put_nowait(make_error_event(_sanitize_error(e)))
        finally:
            queue.put_nowait(_SENTINEL)

    import asyncio as _aio
    graph_task = _aio.create_task(_run_graph())

    try:
        import time as _t
        _sse_t0 = _t.monotonic()
        _evt_count = 0
        # 实时从队列读取事件并 yield SSE
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            _evt_count += 1
            logger.info(f"[SSE] yielding event #{_evt_count} at +{_t.monotonic()-_sse_t0:.1f}s: {item.get('type')}/{item.get('step','')}")
            yield format_sse(item)
            await _aio.sleep(0)  # 让出事件循环，确保网络层刷新

        logger.info(f"[SSE] all {_evt_count} events yielded in {_t.monotonic()-_sse_t0:.1f}s")

        # 图执行完毕，发送 done 事件
        final_state = await submit_graph.aget_state(config)
        state_values = final_state.values if hasattr(final_state, 'values') else {}
        if not state_values.get("error"):
            doc_type = state_values.get("doc_type", "Interview")
            doc_type = {"jd": "JD", "interview": "Interview"}.get(doc_type, doc_type)
            target = state_values.get("target", "personal")
            extracted_data = state_values.get("extracted_data", {})
            yield format_sse(make_done_event(doc_type, target, extracted_data))

        # 收集 answer_tasks 供调用方派发后台任务
        if result_collector is not None:
            result_collector["answer_tasks"] = state_values.get("answer_tasks", [])
            result_collector["user_id"] = input_state.get("user_id")
            # 保存 config 供调用方后续读取 final state
            result_collector["_graph_config"] = config
            # 直接保存完整 state_values 供非 SSE 调用方使用
            result_collector["final_state"] = state_values

    except Exception as e:
        logger.exception("LangGraph 流式执行失败")
        yield format_sse(make_error_event(_sanitize_error(e)))
    finally:
        # 恢复 contextvar，避免泄漏
        _event_queue_var.reset(token)
        if not graph_task.done():
            graph_task.cancel()
