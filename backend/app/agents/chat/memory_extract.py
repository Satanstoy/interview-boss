"""记忆提取与 basis 解析 - 从 nodes.py 机械抽取。

职责:面试后的用户记忆提取(_extract_company/_get_resume_name/_parse_basis/extract_memory)。
纯内部辅助,被 nodes.pipeline 等调用。
"""
import logging
from app.services import chat_service
from app.services import load_visible_jd
from app.services.llm import _call_llm_with_retry, _extract_json
from app.agents.chat.state import ChatState
from app.agents.chat.prompts import MEMORY_EXTRACT_PROMPT

logger = logging.getLogger("interview-boss")


def _extract_company_from_sources(question: dict) -> str:
    import json

    sources = question.get("sources", [])
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except:
            return ""
    if sources and isinstance(sources, list):
        return sources[0].get("company", "")
    return ""


def _extract_round_from_sources(question: dict) -> str:
    import json

    sources = question.get("sources", [])
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except:
            return ""
    if sources and isinstance(sources, list):
        return sources[0].get("round", "")
    return ""


def _response_references_resume(response: str, resume_summary: str) -> bool:
    if not resume_summary or len(resume_summary) < 20:
        return False
    import re

    resume_cues = (
        "简历",
        "履历",
        "背景",
        "项目经历",
        "工作经历",
        "你的经历",
        "你在",
        "你曾",
        "你负责",
        "你做过",
    )
    if not any(cue in response for cue in resume_cues):
        return False

    cjk_words = re.findall(r"[\u4e00-\u9fff]{2,6}", resume_summary[:500])
    en_words = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", resume_summary[:500])
    stopwords = {
        "主要做",
        "负责",
        "包含",
        "项目",
        "经验",
        "应用",
        "方向",
        "系统",
        "能力",
    }
    keywords: list[str] = []
    seen: set[str] = set()
    for word in cjk_words + en_words:
        normalized = word.strip()
        lookup = normalized.lower()
        if len(normalized) < 3 or normalized in stopwords or lookup in seen:
            continue
        seen.add(lookup)
        keywords.append(normalized)

    hits = 0
    response_lower = response.lower()
    for keyword in keywords[:30]:
        if keyword.lower() in response_lower:
            hits += 1
        if hits >= 2:
            return True
    return False


def _response_references_jd(response: str, jd_text: str) -> bool:
    if not jd_text or len(jd_text) < 20:
        return False
    import re

    cjk_words = re.findall(r"[\u4e00-\u9fff]{2,6}", jd_text[:500])
    en_words = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", jd_text[:500])
    keywords = list(set(cjk_words + en_words))[:15]
    return any(kw in response for kw in keywords)


def _get_resume_name(user_id: int) -> str:
    try:
        from app.services import resume_service
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            resume = resume_service.get_resume_text(user_id)
            if resume:
                return "我的简历"
    except:
        pass
    return ""


def _get_jd_title(jd_id: int, user_id: int | None = None) -> str:
    if not jd_id:
        return ""
    try:
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            row = load_visible_jd(conn, jd_id, user_id)
            if row and row[0]:
                return row["job_title"]
    except:
        pass
    return ""


def _parse_basis_from_response(response: str) -> dict:
    """从 LLM 回复中提取 [BASIS]...[/BASIS] 块并解析为结构化数据。

    优先解析最后一个 [BASIS] 块（prompt 要求 basis 在最后一行）。
    如果存在多个 [BASIS] 块，记录 warning 并使用最后一个。
    clean_response 删除所有 basis 块。

    Returns:
        dict with keys:
            - basis_type: str (题型分类)
            - basis_question_ids: list[int] (关联题目ID，clamped 1-999999)
            - basis_confidence: float (置信度 0-1)
            - should_show_references: bool (是否展示参考资料)
            - clean_response: str (去除所有 [BASIS] 块后的回复文本)
    """
    import re as _re
    import json as _json

    defaults = {
        "basis_type": "",
        "basis_question_ids": [],
        "basis_confidence": 0.0,
        "should_show_references": False,
        "clean_response": response,
    }

    # Find all [BASIS]...[/BASIS] blocks
    full_matches = list(_re.finditer(r"\[BASIS\](.*?)\[/BASIS\]", response, _re.DOTALL))
    # Also find [BASIS]{...} without closing tag (LLM may omit closing)
    partial_matches = list(_re.finditer(r"\[BASIS\](\{[^}]*\})", response, _re.DOTALL))

    # Combine and deduplicate (full matches take priority).
    # A partial match starting at the same position as a full match is a duplicate.
    all_matches = []
    full_start_positions = {m.start() for m in full_matches}
    for m in full_matches:
        all_matches.append(m)
    for m in partial_matches:
        if m.start() not in full_start_positions:
            all_matches.append(m)
    all_matches.sort(key=lambda x: x.start())

    if not all_matches:
        return defaults

    # Log warning if multiple blocks found
    if len(all_matches) > 1:
        logger.warning(
            f"BASIS parser: 发现 {len(all_matches)} 个 [BASIS] 块，使用最后一个"
        )

    # Use the LAST match (prompt requires basis at end of response)
    match = all_matches[-1]
    basis_block = match.group(1).strip()

    # Strip markdown code fences if present
    basis_block = _re.sub(r"^```(?:json)?\s*", "", basis_block)
    basis_block = _re.sub(r"\s*```$", "", basis_block)

    # Clean response: remove ALL [BASIS] blocks (both full and partial)
    clean_response = response
    for m in sorted(all_matches, key=lambda x: x.start(), reverse=True):
        clean_response = clean_response[: m.start()] + clean_response[m.end() :]
    clean_response = clean_response.strip()
    # Remove trailing markdown code fences from clean response
    clean_response = _re.sub(r"\s*```\s*$", "", clean_response)

    try:
        data = _json.loads(basis_block)
    except (ValueError, _json.JSONDecodeError):
        return {**defaults, "clean_response": clean_response}

    basis_type = str(data.get("type", "") or "").strip()
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError, OverflowError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    show_refs = bool(data.get("show_refs", False))

    raw_ids = data.get("question_ids", [])
    if isinstance(raw_ids, list):
        question_ids = []
        for qid in raw_ids:
            try:
                val = int(float(qid))
                question_ids.append(max(1, min(999999, val)))
            except (ValueError, TypeError, OverflowError):
                continue
    else:
        question_ids = []

    return {
        "basis_type": basis_type,
        "basis_question_ids": question_ids,
        "basis_confidence": confidence,
        "should_show_references": show_refs,
        "clean_response": clean_response,
    }


async def extract_memory(state: ChatState) -> dict:
    """从对话中自动提取用户记忆（弱点、强项等），并更新 session notes"""
    user_id = state["user_id"]
    user_message = state["user_message"]
    response = state.get("response", "")

    if not response or len(user_message) < 10:
        if state.get("_side_effect_job_id"):
            chat_service.complete_side_effect_job(state["_side_effect_job_id"])
        return {}

    # 构建对话片段（包含面试官提问上下文，提高记忆提取准确性）
    recent = state.get("recent_messages", [])
    prior_question = ""
    if recent:
        for msg in reversed(recent):
            if msg["role"] == "assistant":
                prior_question = msg["content"][:200]
                break

    history_text = f"面试官提问: {prior_question}\n候选人回答: {user_message}\n面试官追问: {response[:500]}"

    try:
        prompt = MEMORY_EXTRACT_PROMPT.format(message_history=history_text)
        result = await _call_llm_with_retry(
            prompt,
            user_id=user_id,
            response_format={"type": "json_object"},
        )
        parsed = _extract_json(result)

        if isinstance(parsed, list):
            memories = parsed
        elif isinstance(parsed, dict):
            memories = parsed.get("memories", parsed.get("items", []))
        else:
            memories = []

        durable_job_id = state.get("_side_effect_job_id")
        if not durable_job_id:
            for mem in memories:
                if isinstance(mem, dict) and mem.get("type") in (
                    "weakness",
                    "strength",
                    "preference",
                ):
                    chat_service.save_memory(
                        user_id=user_id,
                        memory_type=mem["type"],
                        content=mem["content"],
                        source="auto_extract",
                    )

        # 累积 session notes（增强增量记忆）
        note_parts = []
        for mem in memories:
            if isinstance(mem, dict) and mem.get("type") in (
                "weakness",
                "strength",
                "preference",
            ):
                note_parts.append(f"[{mem['type']}] {mem['content']}")

        # 捕获当前话题（从 keywords）
        keywords = state.get("keywords", [])
        if keywords:
            note_parts.append(f"[topics] {', '.join(keywords[:3])}")

        # 记录被问到的题目（优先使用最终 selected_question / question_plan）
        intent = state.get("intent", "")
        selected_question = state.get("selected_question")
        if not selected_question and state.get("next_question_plan"):
            plan = state.get("next_question_plan") or {}
            selected_question = {
                "id": plan.get("question_id"),
                "question": plan.get("question_text"),
                "cat1": "",
                "cat2": "",
                "tags": plan.get("strategy", ""),
            }
        if (
            intent == "interview_question"
            and not selected_question
            and state.get("retrieved_questions")
        ):
            selected_question = state["retrieved_questions"][0]
        if intent == "interview_question" and isinstance(selected_question, dict):
            qid = selected_question.get("id") or ""
            cat1 = str(selected_question.get("cat1") or "").strip()
            cat2 = str(selected_question.get("cat2") or "").strip()
            qtype = str(
                state.get("question_type") or selected_question.get("tags") or "general"
            ).strip()
            question = str(selected_question.get("question") or "")[:80]
            category = f"{cat1}/{cat2}".strip("/")
            note_parts.append(
                f"[asked] {category} #{qid} [{qtype}]: {question}".strip()
            )

        if durable_job_id:
            chat_service.commit_memory_extraction_job(
                durable_job_id,
                memories if isinstance(memories, list) else [],
                note_parts,
            )
        elif note_parts:
            current_notes = state.get("session_notes", "")
            new_notes = "\n".join(note_parts)
            updated_notes = (
                f"{current_notes}\n{new_notes}" if current_notes else new_notes
            )
            if len(updated_notes) > 2000:
                # 在行边界处截断，避免切断 [tag] 标签
                all_lines = updated_notes.split("\n")
                truncated = ""
                for ln in reversed(all_lines):
                    candidate = ln + "\n" + truncated if truncated else ln
                    if len(candidate) > 2000:
                        break
                    truncated = candidate
                updated_notes = truncated
            chat_service.update_session_notes(state["conversation_id"], updated_notes)
            state["session_notes"] = updated_notes

    except Exception as e:
        durable_job_id = state.get("_side_effect_job_id")
        if durable_job_id:
            try:
                chat_service.fail_side_effect_job(durable_job_id, str(e), retry=True)
            except Exception:
                logger.exception("无法更新 memory side-effect job 状态: %s", durable_job_id)
        logger.debug(f"记忆提取跳过: {e}")

    return {}

