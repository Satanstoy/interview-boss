"""SSE 事件构建工具 — 兼容现有协议，支持增强 data 字段"""
import json
import time
import contextvars
from typing import Optional

# 通过 contextvars 传递 event_queue，避免放入 LangGraph state（不可序列化）
_event_queue_var: contextvars.ContextVar = contextvars.ContextVar('_event_queue', default=None)


def make_progress_event(step: str, message: str, data: Optional[dict] = None) -> dict:
    """构建 progress 事件（兼容旧前端，可选 data 字段）"""
    event = {"type": "progress", "step": step, "message": message}
    if data:
        event["data"] = data
    return event


def make_done_event(doc_type: str, target: str, saved_data: dict) -> dict:
    """构建 done 事件"""
    return {"type": "done", "doc_type": doc_type, "target": target, "saved_data": saved_data}


def make_error_event(message: str) -> dict:
    """构建 error 事件"""
    return {"type": "error", "message": message}


def format_sse(event: dict) -> str:
    """将事件 dict 格式化为 SSE data 行"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def emit_progress(state, step: str, message: str, data: Optional[dict] = None):
    """实时推送 progress 事件（通过 contextvars 获取队列）"""
    queue = _event_queue_var.get()
    if queue:
        queue.put_nowait(make_progress_event(step, message, data))


def emit_error(state, message: str):
    """实时推送 error 事件（通过 contextvars 获取队列）"""
    queue = _event_queue_var.get()
    if queue:
        queue.put_nowait(make_error_event(message))


def build_extraction_data(data: dict, quality_score: float, elapsed: float, retry_count: int = 0) -> dict:
    """为 extract 步骤构建增强 data"""
    questions = data.get("具体题目清单", [])
    return {
        "doc_type": data.get("_doc_type", ""),
        "company": data.get("公司", "未提供"),
        "question_count": len(questions),
        "quality_score": round(quality_score, 1),
        "elapsed_seconds": round(elapsed, 1),
        "retry_count": retry_count,
    }


def build_tagging_data(tagged_rows: list, quality_score: float, elapsed: float, retry_count: int = 0) -> dict:
    """为 tag 步骤构建增强 data"""
    categories = {}
    for row in tagged_rows:
        cat1 = row[4] if len(row) > 4 else "未分类"
        categories[cat1] = categories.get(cat1, 0) + 1
    return {
        "question_count": len(tagged_rows),
        "categories": categories,
        "quality_score": round(quality_score, 1),
        "elapsed_seconds": round(elapsed, 1),
        "retry_count": retry_count,
    }


def build_matching_data(match_result: dict, elapsed: float) -> dict:
    """为 match 步骤构建增强 data"""
    matched = match_result.get("matched", [])
    unmatched = match_result.get("unmatched", [])
    return {
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "elapsed_seconds": round(elapsed, 1),
    }


class NodeTimer:
    """节点计时器上下文管理器"""
    def __init__(self):
        self.elapsed = 0.0
        self._start = 0.0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, *_):
        self.elapsed = time.monotonic() - self._start
