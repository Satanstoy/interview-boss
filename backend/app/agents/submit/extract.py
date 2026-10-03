import logging
import secrets

from app.agents.shared.state import SubmitState
from app.agents.shared.quality import evaluate_extraction_quality
from app.agents.shared.events import emit_progress, build_extraction_data, NodeTimer

logger = logging.getLogger("interview-boss")
from app.services.upload_llm_accounting import upload_llm_stage


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


@upload_llm_stage("extract", unit_key="document", checkpoint_result=True)
async def extract_node(state: SubmitState) -> dict:
    """LLM 提取结构化数据节点（F08：支持从阶段检查点复用已成功结果）。"""
    from app.services.llm import _call_llm_with_retry_messages, _extract_json, get_llm_client_for_user, _should_use_response_format
    from app.core.prompts import SYSTEM_PROMPT, JD_PROMPT, INTERVIEW_PROMPT
    from app.services.utils import encode_image

    with NodeTimer() as timer:
        doc_type = state.get("doc_type", "")
        user_id = state["user_id"]

        # F08：恢复时 worker 注入已成功的 extract 检查点 → 不重跑 LLM
        resume = state.get("_resume_extracted")
        if isinstance(resume, dict) and resume.get("data"):
            data = resume["data"]
            doc_type = resume.get("doc_type") or doc_type
            url = resume.get("url") or state.get("url", "")
            emit_progress(
                state,
                "extract",
                f"复用已保存的提取结果（{len(data.get('具体题目清单', []))} 道题）",
            )
        else:
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

            credential_scope = state.get("credential_scope", "user")
            _c, _m, _t, _bu, _provider = get_llm_client_for_user(
                user_id, llm_scope=credential_scope
            )
            llm_kwargs = dict(
                model=state.get("_eval_model") or _m,
                temperature=float(state.get("_eval_temperature", 0.1)),
                # R01：global 公共导入必须用系统凭据（worker 注入的
                # credential_scope），禁止静默回退到提交者本人 Key。
                llm_scope=credential_scope,
            )
            if _should_use_response_format(_bu):
                llm_kwargs["response_format"] = {"type": "json_object"}
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]

            from app.services.extraction_integrity import (
                ExtractionSchemaError,
                normalize_extracted_questions,
            )
            from app.services.upload_llm_accounting import upload_retry_budget_scope

            def parse_output(raw_output):
                try:
                    parsed = _extract_json(raw_output)
                except Exception as exc:
                    raise ExtractionSchemaError("模型输出不是合法 JSON") from exc
                if not isinstance(parsed, dict):
                    raise ExtractionSchemaError("模型输出必须是 JSON 对象")

                parsed_type = str(parsed.get("type") or doc_type or "").lower()
                parsed_data = parsed.get("data", {})
                if not isinstance(parsed_data, dict):
                    raise ExtractionSchemaError("模型输出的 data 必须是 JSON 对象")

                if parsed_type == "interview":
                    raw_list = parsed_data.get("具体题目清单", [])
                    normalized = normalize_extracted_questions(raw_list)
                    parsed_data["具体题目清单"] = [
                        item["question"] for item in normalized["questions"]
                    ]
                    parsed_data["题目 ordinal"] = [
                        item["ordinal"] for item in normalized["questions"]
                    ]
                    parsed_data["题目标记"] = {
                        str(item["ordinal"]): item["review_reason"]
                        for item in normalized["questions"]
                        if item["needs_review"]
                    }
                    parsed_data["提取计数"] = {
                        "extracted": normalized["counts"]["extracted"],
                        "retained": normalized["counts"]["retained"],
                        "excluded": normalized["counts"]["excluded"],
                        "needs_review": normalized["counts"]["needs_review"],
                    }
                return parsed_type, parsed_data

            async def call_and_parse_with_repairs(retry_budget):
                response_text = await _call_llm_with_retry_messages(
                    messages, user_id=user_id, **llm_kwargs
                )
                try:
                    return parse_output(response_text)
                except ExtractionSchemaError as schema_error:
                    # Repairs are upload-only and capped at two. Every request,
                    # including Tenacity retries, shares this same budget.
                    if retry_budget is None:
                        raise
                    for _repair_no in range(2):
                        if retry_budget.exhausted:
                            raise schema_error
                        repair_messages = [
                            *messages,
                            {"role": "assistant", "content": response_text},
                            {
                                "role": "user",
                                "content": (
                                    "上一条输出未通过 JSON 结构校验："
                                    f"{schema_error}。请只返回修正后的 JSON 对象，"
                                    "保持原有数据和全部题目，不要丢题或添加解释文字。"
                                ),
                            },
                        ]
                        response_text = await _call_llm_with_retry_messages(
                            repair_messages, user_id=user_id, **llm_kwargs
                        )
                        try:
                            return parse_output(response_text)
                        except ExtractionSchemaError as repair_error:
                            schema_error = repair_error
                    raise schema_error

            with upload_retry_budget_scope() as retry_budget:
                doc_type, data = await call_and_parse_with_repairs(retry_budget)

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
