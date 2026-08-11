"""
Submit 业务逻辑：题目标签化、答案生成、增量更新题库。

从 routers/submit.py 中抽取，消除 router → service 的反向依赖。
"""
import json
import logging
from uuid import uuid4

from typing import List

from app.core.config import LLM_MODEL
from app.core.prompts import TAGGING_PROMPT, build_tagging_prompt
from app.db.connection import get_db_connection, run_db, get_current_job_position, get_user_job_position
from app.db.operations import insert_personal_questions_txn
from app.services.llm import client, _should_use_response_format, _extract_json, _call_llm_with_retry_messages, get_llm_client_for_user, raw_llm_call
from app.services.utils import normalize_category

logger = logging.getLogger("interview-boss")


async def persist_answer_generation_jobs(
    answer_tasks: list[tuple[int, str]],
    user_id: int,
    source: str = "submit",
) -> tuple[int, list[int]]:
    """Persist answer child jobs for legacy and current upload paths."""
    from app.services.job_lifecycle import create_answer_generation_jobs

    def _persist():
        with get_db_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO jobs "
                "(job_type, status, progress_total, created_by, idempotency_key) "
                "VALUES ('generate_answer_batch', 'pending', ?, ?, ?)",
                (len(answer_tasks), user_id, f"{source}:{user_id}:{uuid4().hex}"),
            )
            parent_id = int(cursor.lastrowid)
            child_ids = create_answer_generation_jobs(
                conn, parent_id, answer_tasks, user_id
            )
            conn.commit()
            return parent_id, child_ids

    return await run_db(_persist)


def _get_current_position_for_user(user_id: int) -> str:
    """Resolve the user's active position for import/write paths."""
    _, current_pos = get_user_job_position(user_id)
    return current_pos or get_current_job_position()


async def background_generate_answer(
    question_id: int,
    question_text: str,
    user_id: int = None,
    raise_on_error: bool = False,
):
    """后台任务：为新入库的题目生成 AI 参考答案。"""
    from app.services.answer_enrichment import prepare_answer_prompt, refine_answer, sources_json
    from app.services.llm import _call_llm_with_retry
    try:
        prompt, search_sources = await prepare_answer_prompt(
            question_text, user_id=user_id
        )
        answer = await _call_llm_with_retry(prompt, user_id=user_id)
        answer, _ = await refine_answer(
            prompt, answer, search_sources, user_id=user_id, max_rounds=2
        )

        def _update():
            with get_db_connection() as conn:
                conn.execute(
                    "UPDATE question_bank SET ai_answer = ?, answer_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (answer, sources_json(search_sources), question_id),
                )
                conn.commit()

        await run_db(_update)
        logger.info(f"自动解答生成完毕: [ID:{question_id}] {question_text[:30]}...")
        return {
            "answer": answer,
            "search_sources": search_sources,
        }
    except Exception as e:
        logger.error(f"自动解答生成失败: [ID:{question_id}]: {e}")

        def _mark_failed():
            with get_db_connection() as conn:
                conn.execute("UPDATE question_bank SET ai_answer = '[生成失败，请手动重试]', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (question_id,))
                conn.commit()
        try:
            await run_db(_mark_failed)
        except Exception:
            pass
        if raise_on_error:
            raise


async def tag_questions_batch(url: str, company: str, round_: str, questions: List[str], taxonomy_config: dict = None, user_id: int = None) -> List[List[str]]:
    input_data = [{"id": idx, "题目": q} for idx, q in enumerate(questions)]
    q_json = json.dumps(input_data, ensure_ascii=False)
    prompt = build_tagging_prompt(taxonomy_config) if taxonomy_config else TAGGING_PROMPT
    user_msg = prompt.replace("{questions}", q_json)

    _c, _m, _t, _bu, _provider = get_llm_client_for_user(user_id) if user_id else (client, LLM_MODEL, None, None, "openai")
    kwargs = dict(
        model=_m,
        messages=[
            {"role": "system", "content": "你是一个严格输出 JSON 对象的助手，格式必须为 {\"questions\": [...]}。必须输出输入数据中每一项对应的 \"id\" 字段，以便于与原输入一一对应。"},
            {"role": "user", "content": user_msg}
        ],
        temperature=0.0,
    )
    if _should_use_response_format(_bu):
        kwargs["response_format"] = {"type": "json_object"}
    from app.services.llm import _call_llm_with_retry
    raw_content = await _call_llm_with_retry(
        prompt=user_msg,
        system_msg="你是一个严格输出 JSON 对象的助手，格式必须为 {\"questions\": [...]}。必须输出输入数据中每一项对应的 \"id\" 字段，以便于与原输入一一对应。",
        response_format=kwargs.get("response_format"),
        user_id=user_id,
    )
    try:
        raw_items = _extract_json(raw_content).get("questions", [])
        result_map = {}
        for item in raw_items:
            if isinstance(item, dict) and "id" in item:
                try:
                    item_id = int(item["id"])
                    result_map[item_id] = {
                        "题目": item.get("题目", ""),
                        "一级大类": item.get("一级大类", ""),
                        "二级子类": item.get("二级子类", ""),
                        "考点标签": item.get("考点标签", ""),
                        "难度标签": item.get("难度标签", "")
                    }
                except (ValueError, TypeError):
                    pass
    except Exception:
        raw_items = []
        result_map = {}

    standardized = []
    for idx, q in enumerate(questions):
        if idx in result_map:
            it = result_map[idx]
            standardized.append([url, company, round_, q, normalize_category(it["一级大类"]), normalize_category(it["二级子类"]), it["考点标签"], it["难度标签"]])
        else:
            standardized.append([url, company, round_, q, "未分类(API漏标)", "未分类", "", "未知"])
    return standardized


async def incremental_update_master_bank(new_tagged_rows: list, bg_tasks=None, submitter_is_admin: bool = True, user_id: int = None, is_personal: bool = False, interview_id: int = None, job_position: str = None):
    """对一批已打标题目做处理。

    个人题库：直接插入 question_bank。
    公共题库：写入 questions_detail + 入队，由流水线阶段2负责聚类。
    """
    if not new_tagged_rows:
        return

    valid_rows = [row for row in new_tagged_rows if row[3].strip()]
    if not valid_rows:
        return

    current_pos = job_position or _get_current_position_for_user(user_id)

    # ── 个人题库：直接插入，不做聚类 ──
    if is_personal:
        answer_tasks = await run_db(lambda: insert_personal_questions_txn(valid_rows, user_id, current_pos))
        if answer_tasks:
            await persist_answer_generation_jobs(
                answer_tasks, user_id, source="incremental-personal"
            )
        logger.info(f"个人题库新增 {len(valid_rows)} 题")
        return

    # ── 公共题库：入队等待聚类 ──
    if interview_id:
        from app.services.pipeline import enqueue_questions
        from app.services.pipeline.queue import _run_cluster_batch_in_background

        enqueue_questions(interview_id)
        scheduled = await _run_cluster_batch_in_background(user_id=user_id)
        logger.info(f"面经 {interview_id} 已入队等待聚类攒批: scheduled={scheduled}")
    else:
        logger.warning("公共题库提交但无 interview_id，跳过入队")
