"""Fixed-model LLM Judge for official evaluation items.

The Judge is deliberately separate from the Target Adapter. The adapter produces
evidence; this module turns that evidence into a versioned, inspectable score.
Failures are retained as ``judge_status=failed`` instead of silently falling
back to a different scoring method.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.llm import _call_llm_with_retry


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def build_judge_prompt(
    *,
    case_key: str,
    contract: dict[str, Any],
    observation: dict[str, Any],
    judge_model: str,
) -> str:
    """Build the immutable rubric prompt used by the fixed Judge model."""
    return f"""你是 InterviewBoss 的官方评测 Judge，模型标识为 {judge_model}。
请只根据给定的 Benchmark Contract 和 Target Observation 评分，不补写不存在的证据。
这是离线质量评测，不是给候选人的建议。

## Benchmark Case
case_key: {case_key}

## Contract
{_json_dumps(contract)}

## Target Observation
{_json_dumps(observation)}

## 评分规则
1. 逐个 rubric dimension 评分，score 必须是 1-5 的整数。
2. reasoning 必须引用 observation 中的具体事实、轮次或工具事件；证据缺失时明确写“证据不足”。
3. overall_score 是 0-1 的小数，按 rubric 权重聚合；不要因为硬断言失败而隐藏维度分数。
4. 对 observation.payload.metrics、tool_metrics、intent_metrics 等系统提供的确定性统计优先使用；不要凭文本猜测字段覆盖、分类准确率、工具次数或意图结果。
5. 对结构化抽取，重点判断字段是否忠实于输入、是否遗漏关键信息、是否把未知事实编造成确定事实。
6. 对简历分析，重点判断事实边界、岗位匹配、建议可执行性；禁止把优化文本中的新增内容当成候选人的真实经历。
7. 对题目分类，重点判断分类层级、标签和难度是否与题意及冻结 taxonomy 一致。
8. 对模拟面试，tool_effectiveness 必须同时考虑工具是否必要、工具结果是否被后续动作使用、调用是否失败或冗余；intent 还必须驱动正确策略。
9. critical_issues 和 highlights 只写 observation 能支持的内容。
10. 只输出 JSON，不要 markdown，不要额外解释。

## 输出格式
{{
  "dimensions": {{
    "dimension_key": {{"score": 1, "reasoning": "..."}}
  }},
  "overall_score": 0.0,
  "critical_issues": [],
  "highlights": []
}}"""


def _extract_json(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("Judge 没有返回 JSON object")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Judge 返回值不是 JSON object")
    return value


def parse_judge_response(
    raw: str,
    *,
    rubric: dict[str, Any],
    judge_model: str,
) -> dict[str, Any]:
    """Normalize a Judge response into the durable evaluation result shape."""
    parsed = _extract_json(raw)
    dimensions: dict[str, dict[str, Any]] = {}
    weighted_sum = 0.0
    total_weight = 0.0
    raw_dimensions = parsed.get("dimensions")
    if not isinstance(raw_dimensions, dict):
        raw_dimensions = {}

    for key, config in rubric.items():
        config = config if isinstance(config, dict) else {}
        weight = float(config.get("weight", 1.0))
        source = raw_dimensions.get(key)
        if not isinstance(source, dict):
            raise ValueError(f"Judge 缺少维度: {key}")
        if "score" not in source:
            raise ValueError(f"Judge 维度缺少 score: {key}")
        try:
            score = int(round(float(source["score"])))
        except (TypeError, ValueError):
            raise ValueError(f"Judge 维度 score 无效: {key}") from None
        score = max(1, min(5, score))
        dimensions[key] = {
            "score": score,
            "reasoning": str(source.get("reasoning", "证据不足")),
            "weight": weight,
        }
        weighted_sum += score * weight
        total_weight += weight

    derived_score = (weighted_sum / total_weight - 1) / 4 if total_weight else 0.0
    reported_score = parsed.get("overall_score")
    try:
        reported_score = float(reported_score) if reported_score is not None else None
    except (TypeError, ValueError):
        reported_score = None
    if reported_score is not None and reported_score > 1:
        reported_score = (reported_score - 1) / 4
    if reported_score is not None:
        reported_score = max(0.0, min(1.0, reported_score))
    overall_score = max(0.0, min(1.0, derived_score))

    return {
        "judge_status": "succeeded",
        "judge_model": judge_model,
        "score": round(overall_score, 4),
        "overall_score": round(overall_score, 4),
        "judge_reported_score": round(reported_score, 4) if reported_score is not None else None,
        "weighted_avg": round(weighted_sum / total_weight, 3) if total_weight else None,
        "dimensions": dimensions,
        "critical_issues": parsed.get("critical_issues", []),
        "highlights": parsed.get("highlights", []),
    }


async def judge_observation(
    *,
    case_key: str,
    contract: dict[str, Any],
    observation: dict[str, Any],
    judge_model: str,
) -> dict[str, Any]:
    """Call the fixed Judge and return an explicit success/failure result."""
    rubric = contract.get("rubric") or {}
    prompt = build_judge_prompt(
        case_key=case_key,
        contract=contract,
        observation=observation,
        judge_model=judge_model,
    )
    try:
        raw = await _call_llm_with_retry(
            prompt,
            system_msg="你是一个严格、稳定、只输出 JSON 的 AI 评测 Judge。",
            response_format={"type": "json_object"},
            model=judge_model,
            thinking=False,
            llm_scope="global",
            temperature=0,
        )
        return parse_judge_response(raw, rubric=rubric, judge_model=judge_model)
    except Exception as exc:
        return {
            "judge_status": "failed",
            "judge_model": judge_model,
            "score": None,
            "dimensions": {},
            "critical_issues": [],
            "highlights": [],
            "error": str(exc)[:500],
        }
