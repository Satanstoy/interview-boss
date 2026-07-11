"""Scoring logic: rule-based and LLM-as-judge."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from .types import Scenario, JudgeLLMConfig
from .http_client import _call_openai_compatible_chat


def _event_tool_name(event: dict) -> str | None:
    if event.get("type") == "tool_step":
        data = event.get("data") if isinstance(event.get("data"), dict) else event
        step = data.get("tool_name") or data.get("tool") or ""
    elif event.get("type") == "step":
        step = event.get("step", "")
    else:
        return None
    if step in ("search_questions", "draw_questions", "select_question", "load_skill"):
        return step
    return None


def _event_tools_for_turn(turn: dict) -> list[str]:
    return [tool for event in turn.get("events", []) if (tool := _event_tool_name(event))]


def _assistant_text_from_events(events: list[dict]) -> str:
    return "".join(e.get("content", "") for e in events if e.get("type") == "chunk")


def _preview(text: str, limit: int = 80) -> str:
    compact = " ".join(str(text).split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _build_conversation_transcript(turns: list[dict], max_chars: int = 8000) -> str:
    """Build a readable transcript from turns, truncating if needed."""
    lines = []
    for turn in turns:
        user = str(turn.get("user") or "")[:200]
        assistant = str(turn.get("assistant") or "")[:300]
        tools = _event_tools_for_turn(turn)
        tool_tag = f" [tools: {', '.join(tools)}]" if tools else ""
        lines.append(f"Turn {turn.get('turn', '?')}:")
        lines.append(f"  候选人: {user}")
        lines.append(f"  面试官{tool_tag}: {assistant}")
        lines.append("")

    transcript = "\n".join(lines)
    if len(transcript) <= max_chars:
        return transcript

    # Truncate from middle, keep head and tail
    head_end = int(max_chars * 0.4)
    tail_start = len(transcript) - int(max_chars * 0.5)
    head_end = transcript.rfind("\n", 0, head_end)
    tail_start = transcript.find("\n", tail_start)
    if head_end < 0:
        head_end = int(max_chars * 0.4)
    if tail_start < 0:
        tail_start = len(transcript) - int(max_chars * 0.5)
    return transcript[:head_end] + f"\n\n... [省略 {tail_start - head_end} 字符] ...\n\n" + transcript[tail_start:]


def _build_scoring_criteria_text(scenario: Scenario) -> str:
    """Format scenario scoring criteria as LLM-readable rubric."""
    lines: list[str] = []
    for key, config in scenario.scoring.items():
        desc = config.get("description", key)
        weight = config.get("weight", 1.0)
        rubric = config.get("rubric", {})
        lines.append(f"### {key} (weight={weight}, 权重={weight})")
        lines.append(f"说明: {desc}")
        if rubric:
            lines.append("评分标准:")
            for score, anchor in sorted(rubric.items()):
                lines.append(f"  {score}分: {anchor}")
        lines.append("")
    return "\n".join(lines)


def score_scenario(scenario: Scenario, metrics: dict[str, Any]) -> dict[str, Any]:
    """Rule-based scoring using code check functions."""
    items: dict[str, dict[str, Any]] = {}
    total_weight = 0.0
    passed_weight = 0.0

    for key, config in scenario.scoring.items():
        weight = float(config.get("weight", 1.0))
        total_weight += weight
        if "check" not in config:
            items[key] = {
                "passed": None,
                "weight": weight,
                "description": config.get("description", key),
                "error": None,
                "note": "requires LLM judge",
            }
            continue
        try:
            passed = bool(config["check"](metrics))
            error = None
        except Exception as exc:
            passed = False
            error = str(exc)
        if passed:
            passed_weight += weight
        items[key] = {
            "passed": passed,
            "weight": weight,
            "description": config.get("description", key),
            "error": error,
        }

    checked_weight = sum(
        float(config.get("weight", 1.0))
        for config in scenario.scoring.values()
        if "check" in config
    )
    return {
        "passed": passed_weight == checked_weight if checked_weight > 0 else None,
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "checked_weight": checked_weight,
        "ratio": passed_weight / checked_weight if checked_weight > 0 else 0.0,
        "items": items,
    }


def llm_score_scenario(
    scenario: Scenario,
    turns: list[dict[str, Any]],
    metrics: dict[str, Any],
    judge_config: JudgeLLMConfig,
) -> dict[str, Any]:
    """Use LLM judge to evaluate the interview against rubric criteria."""
    transcript = _build_conversation_transcript(turns)
    criteria_text = _build_scoring_criteria_text(scenario)

    hard_metrics = {
        "turn_count": metrics.get("turn_count", 0),
        "tool_count": metrics.get("tool_count", 0),
        "tool_names": metrics.get("tool_names", []),
        "selected_ids_count": len(metrics.get("selected_ids", [])),
        "cross_turn_duplicates": metrics.get("cross_turn_duplicate_candidates", []),
        "asked_questions_count": len(metrics.get("asked_questions", [])),
        "has_summary": metrics.get("has_summary", False),
        "thinking_turns": metrics.get("thinking_turns", 0),
        "error_count": len(metrics.get("errors", [])),
    }

    prompt = f"""你是一位资深技术面试质量评审专家。请根据以下面试对话记录，对面试质量进行逐项评估。

## 评测场景
- 场景: {scenario.scenario_id}
- 模式: {scenario.mode}
- 难度: {scenario.difficulty}
- 预期轮数: {scenario.max_turns}

## 评分维度与评分标准
{criteria_text}

## 硬指标数据
```json
{json.dumps(hard_metrics, ensure_ascii=False, indent=2)}
```

## 面试对话记录
{transcript}

## 评估要求

对每个维度：
1. 先写 reasoning（判断依据，引用对话中的具体轮次或内容）
2. 再写 score（1-5 整数，参照评分标准中的锚点描述）
3. 不要仅依赖硬指标 — 用对话内容验证

请严格按以下 JSON 格式返回（不要包含其他文本）：
```json
{{
  "dimensions": {{
    "dimension_key_1": {{
      "reasoning": "先写判断依据，引用对话内容",
      "score": 3
    }},
    "dimension_key_2": {{ ... }}
  }},
  "critical_issues": ["最严重的1-2个问题"],
  "highlights": ["1-2个亮点"]
}}
```

维度 key 列表: {', '.join(scenario.scoring.keys())}"""

    try:
        raw = _call_openai_compatible_chat(
            judge_config,
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4000,
        )
        json_match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
        json_str = json_match.group(1) if json_match else raw
        if not json_match:
            obj_match = re.search(r"\{.*\}", raw, re.DOTALL)
            json_str = obj_match.group(0) if obj_match else raw

        parsed = json.loads(json_str)
        dimensions = parsed.get("dimensions", {})

        items: dict[str, dict[str, Any]] = {}
        weighted_sum = 0.0
        total_weight = 0.0

        for key, config in scenario.scoring.items():
            weight = float(config.get("weight", 1.0))
            total_weight += weight
            dim = dimensions.get(key, {})
            raw_score = dim.get("score", 3)
            score = float(raw_score)
            if 0.0 <= score <= 1.0:
                score *= 5.0
            score = int(round(score))
            score = max(1, min(5, score))
            weighted_sum += score * weight
            passed = dim.get("passed")
            if not isinstance(passed, bool):
                passed = score >= 3
            items[key] = {
                "score": score,
                "passed": passed,
                "weight": weight,
                "description": config.get("description", key),
                "reasoning": str(dim.get("reasoning", "")),
                "error": None,
            }

        weighted_avg = weighted_sum / total_weight if total_weight else 3.0
        normalized_score = (weighted_avg - 1) / 4.0

        overall_passed = parsed.get("overall_passed")
        return {
            "passed": overall_passed if isinstance(overall_passed, bool) else weighted_avg >= 3.0,
            "overall_score": round(normalized_score, 3),
            "weighted_avg": round(weighted_avg, 2),
            "items": items,
            "critical_issues": parsed.get("critical_issues", []),
            "highlights": parsed.get("highlights", []),
            "judge_model": judge_config.model,
        }

    except Exception as exc:
        print(f"Warning: LLM judge scoring failed, falling back to rule-based: {exc}", file=sys.stderr)
        result = score_scenario(scenario, metrics)
        result["judge_error"] = str(exc)
        result["judge_model"] = judge_config.model
        result["fallback_notice"] = (
            f"⚠️ LLM 评分失败（{judge_config.model}: {exc}），已降级为规则评分。"
            "规则评分使用关键词匹配，可能不够准确。"
        )
        return result
