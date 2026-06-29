import json
import logging
import time

from app.agents.shared.state import SubmitState
from app.agents.shared.quality import evaluate_tagging_quality, should_retry
from app.agents.shared.events import emit_progress, build_tagging_data, NodeTimer

logger = logging.getLogger("interview-boss")


async def complete_node(state: SubmitState) -> dict:
    """字段补全节点 -- 补全公司/轮次/难度等缺失字段"""
    from app.services.llm import raw_llm_call, _extract_json, get_llm_client_for_user, _should_use_response_format

    with NodeTimer() as timer:
        data = state.get("extracted_data", {})
        missing_fields = []
        if data.get("公司") == "未提供":
            missing_fields.append("公司")
        if data.get("面试轮次") == "未提供":
            missing_fields.append("面试轮次")
        if data.get("难易程度") == "未提供":
            missing_fields.append("难易程度")

        if not missing_fields or len(missing_fields) > 2:
            emit_progress(state, "fill", "信息完整，跳过补全")
            return {
                "completion_attempted": False,
                "node_timings": {**state.get("node_timings", {}), "complete": timer.elapsed},
            }

        missing_label = "、".join(missing_fields)
        retry_prompt = f"""以下是从一份面经中提取的信息，但有几个字段缺失（返回了"未提供"）。
请根据已有内容推断这些缺失字段的值。

已提取的信息：
- 公司：{data.get('公司', '未提供')}
- 面试轮次：{data.get('面试轮次', '未提供')}
- 考察重点：{data.get('考察重点', '未提供')}
- 题目清单：{json.dumps(data.get('具体题目清单', []), ensure_ascii=False)}
- 难易程度：{data.get('难易程度', '未提供')}

需要补全的字段：{', '.join(missing_fields)}

请返回一个JSON对象，只包含需要补全的字段。对于难易程度，请根据题目难度判断为"简单"、"中等"或"困难"。
对于公司，请从内容中推断。对于面试轮次，请从内容中推断。"""

        try:
            _rc, _rm, _rt, _rbu, _rprovider = get_llm_client_for_user(state["user_id"])
            retry_kwargs = dict(
                model=_rm,
                messages=[
                    {"role": "system", "content": "你是一个信息补全助手。根据已有信息推断缺失字段，返回JSON。"},
                    {"role": "user", "content": retry_prompt}
                ],
                temperature=0.2,
            )
            if _should_use_response_format(_rbu):
                retry_kwargs["response_format"] = {"type": "json_object"}
            retry_text = await raw_llm_call(state["user_id"], **retry_kwargs)
            retry_data = _extract_json(retry_text)
            for field in missing_fields:
                val = retry_data.get(field, "未提供")
                if val and val != "未提供":
                    data[field] = val
                    logger.info(f"字段补全成功: {field} = {val}")
            message = f"缺失信息已推断（{missing_label}）"
        except Exception as e:
            logger.warning(f"字段补全重试失败: {e}")
            message = "信息补全失败，继续处理"

    emit_progress(state, "fill", message)
    return {
        "extracted_data": data,
        "completion_attempted": True,
        "node_timings": {**state.get("node_timings", {}), "complete": timer.elapsed},
        "llm_call_count": state.get("llm_call_count", 0) + 1,
    }


async def classify_node(state: SubmitState) -> dict:
    """分类标注节点 -- 调用现有 tag_questions_batch + 质量检查"""
    from app.services.submit_service import tag_questions_batch
    from app.db.connection import run_db, get_taxonomy_for_position

    with NodeTimer() as timer:
        data = state.get("extracted_data", {})
        q_list = data.get("具体题目清单", [])

        # 加载分类体系
        taxonomy_config = state.get("taxonomy_config")
        if not taxonomy_config:
            taxonomy_config = await run_db(lambda: get_taxonomy_for_position(user_id=state.get("user_id")))

        tagged_rows = await tag_questions_batch(
            url=state.get("saved_url", ""),
            company=data.get("公司", "未提供"),
            round_=data.get("面试轮次", "未提供"),
            questions=q_list,
            taxonomy_config=taxonomy_config,
            user_id=state["user_id"],
        )

    # 从 taxonomy 提取合法分类用于质量检查
    valid_cat1 = None
    valid_cat2_by_cat1 = None
    if taxonomy_config and taxonomy_config.get("categories"):
        valid_cat1 = set()
        valid_cat2_by_cat1 = {}
        for cat in taxonomy_config["categories"]:
            cname = cat.get("cat1", "")
            if cname:
                valid_cat1.add(cname)
                children = cat.get("children", [])
                valid_cat2_by_cat1[cname] = set(
                    c if isinstance(c, str) else c.get("name", "")
                    for c in children
                )

    quality = evaluate_tagging_quality(tagged_rows, valid_cat1=valid_cat1, valid_cat2_by_cat1=valid_cat2_by_cat1)
    retry_count = state.get("tagging_retries", 0)

    emit_progress(state, "tag", f"标注完成，共 {len(tagged_rows)} 道题",
                  build_tagging_data(tagged_rows, quality, timer.elapsed, retry_count))

    return {
        "tagged_rows": tagged_rows,
        "tagging_quality": quality,
        "tagging_retries": retry_count,
        "taxonomy_config": taxonomy_config,
        "node_timings": {**state.get("node_timings", {}), "classify": timer.elapsed},
        "llm_call_count": state.get("llm_call_count", 0) + 1,
    }


async def retry_classify_node(state: SubmitState) -> dict:
    """重试分类 -- 增加重试计数"""
    emit_progress(state, "tag",
        f"分类质量不足（{state.get('tagging_quality', 0):.1f}/10），正在重试...（{state.get('tagging_retries', 0) + 1}/2）")
    return {
        "tagging_retries": state.get("tagging_retries", 0) + 1,
    }
