import logging
import secrets

from app.agents.shared.state import SubmitState
from app.agents.shared.quality import evaluate_extraction_quality
from app.agents.shared.events import emit_progress, build_extraction_data, NodeTimer

logger = logging.getLogger("interview-boss")

# 提取黑名单（LLM误提取的非面试题）
_EXTRACT_BLACKLIST = ["自我介绍", "反问", "想问我", "职业规划", "加班", "薪资", "为什么离职", "优缺点"]


async def recognize_node(state: SubmitState) -> dict:
    """识别内容类型节点（JD/Interview）"""
    # 如果用户已指定类型，直接使用
    hint = state.get("content_type_hint", "auto")
    if hint in ("jd", "interview"):
        emit_progress(state, "extract", f"类型已指定: {hint.upper()}")
        return {
            "doc_type": hint,
        }
    # 否则在 extract 节点中由 LLM 判断，这里不做额外调用
    return {"doc_type": ""}


async def extract_node(state: SubmitState) -> dict:
    """LLM 提取结构化数据节点"""
    from app.services.llm import _call_llm_with_retry_messages, _extract_json, get_llm_client_for_user, _should_use_response_format
    from app.core.prompts import SYSTEM_PROMPT, JD_PROMPT, INTERVIEW_PROMPT
    from app.services.utils import encode_image

    with NodeTimer() as timer:
        doc_type = state.get("doc_type", "")
        user_id = state["user_id"]

        # 选择 prompt
        if doc_type == "jd":
            system_prompt = JD_PROMPT
        elif doc_type == "interview":
            system_prompt = INTERVIEW_PROMPT
        else:
            system_prompt = SYSTEM_PROMPT

        # 构建 messages
        user_content = [{"type": "text", "text": "请分析以下联合内容，保持信息连贯性，并综合整理后严格按照 JSON Schema 返回："}]
        raw_text = state.get("raw_text", "")
        if raw_text.strip():
            user_content.append({"type": "text", "text": f"\n【文本内容】:\n{raw_text}\n"})
        for img in state.get("image_data", []):
            base64_img = encode_image(img["content"])
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img['mime']};base64,{base64_img}"}
            })

        _c, _m, _t, _bu, _provider = get_llm_client_for_user(user_id)
        llm_kwargs = dict(
            model=state.get("_eval_model") or _m,
            temperature=float(state.get("_eval_temperature", 0.1)),
        )
        if _should_use_response_format(_bu):
            llm_kwargs["response_format"] = {"type": "json_object"}
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]

        response_text = await _call_llm_with_retry_messages(messages, user_id=user_id, **llm_kwargs)
        parsed = _extract_json(response_text)

        # 解析结果
        if not doc_type:
            doc_type = (parsed.get("type") or "").lower()
        data = parsed.get("data", {})

        # 过滤黑名单
        if doc_type == "interview":
            q_list = data.get("具体题目清单", [])
            q_list = [q for q in q_list if q.strip() and not any(b in q for b in _EXTRACT_BLACKLIST)]
            data["具体题目清单"] = q_list

    # 质量评估
    quality = evaluate_extraction_quality(data)
    retry_count = state.get("extraction_retries", 0)

    # 生成 URL
    url = state.get("url", "")
    if not url:
        url = f"internal://{secrets.token_urlsafe(16)}"

    emit_progress(state, "extract", f"提取完成: {len(data.get('具体题目清单', []))} 道题",
                  build_extraction_data(data, quality, timer.elapsed, retry_count))

    return {
        "doc_type": doc_type,
        "extracted_data": data,
        "extraction_quality": quality,
        "extraction_retries": retry_count,
        "saved_url": url,
        "node_timings": {**state.get("node_timings", {}), "extract": timer.elapsed},
        "llm_call_count": state.get("llm_call_count", 0) + 1,
    }


async def retry_extract_node(state: SubmitState) -> dict:
    """重试提取 -- 增加重试计数，降低 temperature"""
    emit_progress(state, "extract",
        f"提取质量不足（{state.get('extraction_quality', 0):.1f}/10），正在重试...（{state.get('extraction_retries', 0) + 1}/2）")
    return {
        "extraction_retries": state.get("extraction_retries", 0) + 1,
    }
