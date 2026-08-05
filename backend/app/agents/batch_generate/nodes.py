"""Batch-Generate-Answers 流程的 LangGraph 节点函数"""
import time
import logging

from app.agents.shared.state import BatchGenerateState
from app.agents.shared.quality import evaluate_answer_quality, should_retry
from app.agents.shared.events import make_progress_event

logger = logging.getLogger("interview-boss")


async def load_questions_node(state: BatchGenerateState) -> dict:
    """加载需要生成答案的题目列表"""
    from app.db.connection import get_db_connection, run_db

    def _load():
        conn = get_db_connection()
        question_ids = state.get("question_ids", [])
        if question_ids:
            placeholders = ','.join('?' * len(question_ids))
            rows = conn.execute(
                f"SELECT id, question FROM question_bank WHERE id IN ({placeholders}) AND (ai_answer IS NULL OR ai_answer = '')",
                question_ids
            ).fetchall()
        else:
            # 如果没有指定 ID，加载所有无答案的题目
            rows = conn.execute(
                "SELECT id, question FROM question_bank WHERE (ai_answer IS NULL OR ai_answer = '') AND deleted_at IS NULL ORDER BY id"
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    questions = await run_db(_load)
    return {
        "question_ids": [q[0] for q in questions],
        "current_index": 0,
        "success_count": 0,
        "fail_count": 0,
        "events": [make_progress_event("tag", f"已加载 {len(questions)} 道待生成答案的题目")],
    }


async def generate_answer_node(state: BatchGenerateState) -> dict:
    """为当前题目生成答案"""
    from app.services.llm import _call_llm_with_retry
    from app.services.answer_enrichment import prepare_answer_prompt, _sources_json
    from app.db.connection import get_db_connection, run_db

    idx = state.get("current_index", 0)
    question_ids = state.get("question_ids", [])
    if idx >= len(question_ids):
        return {"error": "所有题目已处理完毕"}

    qid = question_ids[idx]

    # 获取题目文本
    def _get_question():
        conn = get_db_connection()
        row = conn.execute("SELECT question FROM question_bank WHERE id = ?", (qid,)).fetchone()
        return row[0] if row else ""

    question = await run_db(_get_question)
    if not question:
        return {
            "current_index": idx + 1,
            "current_question": "",
            "fail_count": state.get("fail_count", 0) + 1,
            "results": [{"id": qid, "quality": 0, "elapsed": 0, "success": False, "reason": "题目不存在"}],
        }

    start = time.monotonic()
    try:
        prompt, search_sources = await prepare_answer_prompt(
            question, user_id=state.get("user_id")
        )
        answer = await _call_llm_with_retry(prompt, user_id=state.get("user_id"))
        elapsed = time.monotonic() - start
        quality = evaluate_answer_quality(answer, question)

        # 保存答案
        def _save():
            conn = get_db_connection()
            conn.execute(
                "UPDATE question_bank SET ai_answer = ?, answer_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (answer, _sources_json(search_sources), qid),
            )
            conn.commit()
        await run_db(_save)

        return {
            "current_index": idx + 1,
            "current_question": question,
            "current_answer": answer,
            "answer_quality": quality,
            "success_count": state.get("success_count", 0) + 1,
            "results": [{"id": qid, "quality": quality, "elapsed": round(elapsed, 1), "success": True}],
            "events": [make_progress_event("tag",
                f"[{idx + 1}/{len(question_ids)}] 生成完成",
                {"question_id": qid, "quality": round(quality, 1), "elapsed": round(elapsed, 1)})],
        }
    except Exception as e:
        elapsed = time.monotonic() - start
        logger.error(f"答案生成失败 [ID:{qid}]: {e}")

        def _mark_failed():
            conn = get_db_connection()
            conn.execute("UPDATE question_bank SET ai_answer = '[生成失败，请手动重试]', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (qid,))
            conn.commit()
        try:
            await run_db(_mark_failed)
        except Exception:
            pass

        return {
            "current_index": idx + 1,
            "current_question": question,
            "fail_count": state.get("fail_count", 0) + 1,
            "results": [{"id": qid, "quality": 0, "elapsed": round(elapsed, 1), "success": False, "error": str(e)[:100]}],
            "events": [make_progress_event("tag", f"[{idx + 1}/{len(question_ids)}] 生成失败: {str(e)[:50]}")],
        }


def should_continue_generate(state: BatchGenerateState) -> str:
    """条件路由: 是否继续生成下一题"""
    idx = state.get("current_index", 0)
    question_ids = state.get("question_ids", [])
    if idx >= len(question_ids):
        return "done"
    return "continue"


async def summarize_node(state: BatchGenerateState) -> dict:
    """总结生成结果"""
    success = state.get("success_count", 0)
    fail = state.get("fail_count", 0)
    total = success + fail
    return {
        "events": [make_progress_event("save",
            f"答案生成完毕: 成功 {success}/{total}",
            {"success": success, "fail": fail, "total": total})],
    }
