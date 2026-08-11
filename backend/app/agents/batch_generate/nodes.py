"""Batch-Generate-Answers 流程的 LangGraph 节点函数"""
import time
import logging
import asyncio

from app.agents.shared.state import BatchGenerateState
from app.agents.shared.quality import evaluate_answer_quality, should_retry
from app.agents.shared.events import make_progress_event

logger = logging.getLogger("interview-boss")

# 每批并发生成的题目数（与 answers.py 批量端点的 Semaphore(3) 对齐）
_BATCH_CONCURRENCY = 3


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
    """为当前批次题目并发生成答案（一批 _BATCH_CONCURRENCY 题）"""
    from app.services.llm import _call_llm_with_retry
    from app.services.answer_enrichment import prepare_answer_prompt, refine_answer, sources_json
    from app.db.connection import get_db_connection, run_db

    idx = state.get("current_index", 0)
    question_ids = state.get("question_ids", [])
    if idx >= len(question_ids):
        return {"error": "所有题目已处理完毕"}

    batch_ids = question_ids[idx : idx + _BATCH_CONCURRENCY]

    # 批量加载题面（一次 DB 查询）
    def _load_batch():
        conn = get_db_connection()
        placeholders = ",".join("?" * len(batch_ids))
        rows = conn.execute(
            f"SELECT id, question FROM question_bank WHERE id IN ({placeholders})",
            batch_ids,
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    questions_map = await run_db(_load_batch)

    async def _process_one(qid: int) -> dict:
        question = questions_map.get(qid)
        if not question:
            return {
                "qid": qid, "question": "", "answer": "", "quality": 0.0,
                "elapsed": 0.0, "success": False, "error": "题目不存在",
            }
        start = time.monotonic()
        try:
            prompt, search_sources = await prepare_answer_prompt(
                question, user_id=state.get("user_id")
            )
            answer = await _call_llm_with_retry(prompt, user_id=state.get("user_id"))
            answer, _ = await refine_answer(
                prompt,
                answer,
                search_sources,
                user_id=state.get("user_id"),
                max_rounds=2,
            )
            elapsed = time.monotonic() - start
            quality = evaluate_answer_quality(answer, question)

            # 保存答案
            def _save():
                conn = get_db_connection()
                conn.execute(
                    "UPDATE question_bank SET ai_answer = ?, answer_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (answer, sources_json(search_sources), qid),
                )
                conn.commit()
            await run_db(_save)
            return {
                "qid": qid, "question": question, "answer": answer,
                "quality": quality, "elapsed": elapsed, "success": True,
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
                "qid": qid, "question": question, "answer": "",
                "quality": 0.0, "elapsed": elapsed, "success": False,
                "error": str(e)[:100],
            }

    results = await asyncio.gather(*(_process_one(qid) for qid in batch_ids))

    success_count = state.get("success_count", 0)
    fail_count = state.get("fail_count", 0)
    summary_results = []
    events = []
    last_question = ""
    last_answer = ""
    last_quality = 0.0
    for offset, res in enumerate(results):
        seq = idx + offset + 1
        total = len(question_ids)
        if res["success"]:
            success_count += 1
            last_question = res["question"]
            last_answer = res["answer"]
            last_quality = res["quality"]
            summary_results.append(
                {"id": res["qid"], "quality": res["quality"], "elapsed": round(res["elapsed"], 1), "success": True}
            )
            events.append(make_progress_event("tag",
                f"[{seq}/{total}] 生成完成",
                {"question_id": res["qid"], "quality": round(res["quality"], 1), "elapsed": round(res["elapsed"], 1)}))
        else:
            fail_count += 1
            summary_results.append(
                {"id": res["qid"], "quality": 0, "elapsed": round(res["elapsed"], 1), "success": False, "error": res.get("error", "")[:100]}
            )
            events.append(make_progress_event("tag", f"[{seq}/{total}] 生成失败: {res.get('error', '')[:50]}"))

    return {
        "current_index": idx + len(batch_ids),
        "current_question": last_question,
        "current_answer": last_answer,
        "answer_quality": last_quality,
        "success_count": success_count,
        "fail_count": fail_count,
        "results": summary_results,
        "events": events,
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
