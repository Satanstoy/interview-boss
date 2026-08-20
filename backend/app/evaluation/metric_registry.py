"""Business-facing metric definitions shared by the evaluation API and UI."""

from __future__ import annotations

from typing import Any


# This is part of the progress-colour contract. Keep it stable so historical
# runs remain comparable even when their old manifest omitted thresholds.
DEFAULT_POOR_SCORE_THRESHOLD = 0.6


def _metric(
    key: str,
    label: str,
    unit: str,
    *,
    direction: str = "higher",
    source: str,
    formatter: str = "ratio",
    threshold: float,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "direction": direction,
        "source": source,
        "formatter": formatter,
        "threshold": threshold,
    }


TARGET_METRIC_DICTIONARY: dict[str, dict[str, Any]] = {
    "interview": {
        "label": "模拟面试",
        "core_metrics": [
            "tool_success_rate",
            "tool_result_used_rate",
            "intent_coverage",
            "intent_accuracy",
        ],
        "metrics": {
            "tool_success_rate": _metric(
                "tool_success_rate",
                "工具调用成功率",
                "%",
                source="tool",
                threshold=0.8,
            ),
            "tool_result_used_rate": _metric(
                "tool_result_used_rate",
                "工具结果采用率",
                "%",
                source="tool",
                threshold=0.8,
            ),
            "intent_coverage": _metric(
                "intent_coverage",
                "用户意图理解覆盖率",
                "%",
                source="intent",
                threshold=0.8,
            ),
            "intent_accuracy": _metric(
                "intent_accuracy",
                "用户意图判断准确度",
                "%",
                source="intent",
                threshold=0.8,
            ),
        },
    },
    "experience_extraction": {
        "label": "面经提取",
        "core_metrics": [
            "field_coverage",
            "field_match_rate",
            "question_recall",
            "question_precision",
        ],
        "metrics": {
            "field_coverage": _metric(
                "field_coverage",
                "关键信息识别完整度",
                "%",
                source="content",
                threshold=0.8,
            ),
            "field_match_rate": _metric(
                "field_match_rate",
                "关键内容匹配度",
                "%",
                source="content",
                threshold=0.8,
            ),
            "question_recall": _metric(
                "question_recall",
                "题目找全程度",
                "%",
                source="content",
                threshold=0.8,
            ),
            "question_precision": _metric(
                "question_precision",
                "题目准确度",
                "%",
                source="content",
                threshold=0.8,
            ),
        },
    },
    "jd_extraction": {
        "label": "JD 提取",
        "core_metrics": [
            "field_coverage",
            "field_match_rate",
            "question_recall",
            "question_precision",
        ],
        "metrics": {
            "field_coverage": _metric(
                "field_coverage",
                "岗位信息识别完整度",
                "%",
                source="content",
                threshold=0.8,
            ),
            "field_match_rate": _metric(
                "field_match_rate",
                "岗位内容匹配度",
                "%",
                source="content",
                threshold=0.8,
            ),
            "question_recall": _metric(
                "question_recall",
                "技术要求找全程度",
                "%",
                source="content",
                threshold=0.8,
            ),
            "question_precision": _metric(
                "question_precision",
                "技术要求准确度",
                "%",
                source="content",
                threshold=0.8,
            ),
        },
    },
    "resume_analysis": {
        "label": "简历分析与优化",
        "core_metrics": [
            "source_fact_coverage",
            "target_alignment",
            "improvement_point_count",
            "forbidden_claim_count",
        ],
        "metrics": {
            "source_fact_coverage": _metric(
                "source_fact_coverage",
                "简历事实保留率",
                "%",
                source="resume",
                threshold=0.95,
            ),
            "target_alignment": _metric(
                "target_alignment",
                "岗位匹配度",
                "%",
                source="resume",
                threshold=0.75,
            ),
            "improvement_point_count": _metric(
                "improvement_point_count",
                "优化建议条数",
                "条",
                source="resume",
                formatter="number",
                threshold=1,
            ),
            "forbidden_claim_count": _metric(
                "forbidden_claim_count",
                "虚构内容",
                "条",
                direction="lower",
                source="resume",
                formatter="number",
                threshold=0,
            ),
        },
    },
    "question_tagging": {
        "label": "面试题分类",
        "core_metrics": [
            "taxonomy_validity",
            "classification_accuracy",
            "row_count",
        ],
        "metrics": {
            "taxonomy_validity": _metric(
                "taxonomy_validity",
                "分类规则符合度",
                "%",
                source="tagging",
                threshold=0.95,
            ),
            "classification_accuracy": _metric(
                "classification_accuracy",
                "题目分类准确度",
                "%",
                source="tagging",
                threshold=0.8,
            ),
            "row_count": _metric(
                "row_count",
                "已分类题目",
                "题",
                source="tagging",
                formatter="number",
                threshold=1,
            ),
        },
    },
}


def get_target_metric_definition(target_type: str) -> dict[str, Any]:
    try:
        return TARGET_METRIC_DICTIONARY[target_type]
    except KeyError as exc:
        raise ValueError(f"未知评测目标: {target_type}") from exc


def quality_threshold_from_manifest(manifest: dict[str, Any] | None) -> float | None:
    manifest = manifest if isinstance(manifest, dict) else {}
    protocol = manifest.get("protocol") if isinstance(manifest.get("protocol"), dict) else {}
    thresholds = protocol.get("quality_thresholds")
    if not isinstance(thresholds, dict):
        thresholds = manifest.get("quality_thresholds")
    if not isinstance(thresholds, dict):
        return DEFAULT_POOR_SCORE_THRESHOLD
    value = thresholds.get("poor_score_below")
    try:
        return float(value) if value is not None else DEFAULT_POOR_SCORE_THRESHOLD
    except (TypeError, ValueError):
        return DEFAULT_POOR_SCORE_THRESHOLD


def _source_value(summary: dict[str, Any], metric: dict[str, Any]) -> Any:
    source = summary.get(metric["source"]) or {}
    key = metric["key"]
    if key == "tool_success_rate":
        calls = int(source.get("call_count") or 0)
        failed = int(source.get("failed_call_count") or 0)
        return round((calls - failed) / calls, 4) if calls else None
    return source.get(key)


def _status(value: Any, direction: str, threshold: float | None) -> str:
    if value is None:
        return "unavailable"
    if threshold is None:
        return "available"
    passed = value >= threshold if direction == "higher" else value <= threshold
    return "passed" if passed else "poor"


def build_metric_cards(
    target_type: str,
    summary: dict[str, Any] | None,
    *,
    thresholds: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    definition = get_target_metric_definition(target_type)
    summary = summary if isinstance(summary, dict) else {}
    thresholds = thresholds or {}
    cards = []
    for key in definition["core_metrics"]:
        metric = definition["metrics"][key]
        value = _source_value(summary, metric)
        cards.append(
            {
                **metric,
                "value": value,
                "threshold": thresholds.get(key, metric.get("threshold")),
                "status": _status(
                    value,
                    metric["direction"],
                    thresholds.get(key, metric.get("threshold")),
                ),
            }
        )
    return cards


def classify_progress_outcome(item: dict[str, Any], poor_score_below: float | None) -> str:
    """Classify one Item without collapsing execution and quality states."""
    status = item.get("status")
    if status in {"pending", "running", "queued", "created"}:
        return "pending"
    if (
        status in {"failed", "cancelled"}
        or item.get("contract_status") in {"invalid", "failed"}
        or item.get("hard_gate_status") in {"invalid", "failed"}
    ):
        return "failed"
    if item.get("judge_status") in {"pending", "running"}:
        return "pending"
    score = item.get("score")
    if score is None:
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        score_data = result.get("score") if isinstance(result.get("score"), dict) else {}
        score = score_data.get("score", score_data.get("final"))
    if score is None:
        return "pending"
    if poor_score_below is not None and float(score) < float(poor_score_below):
        return "poor"
    return "passed" if item.get("hard_gate_status") in {"passed", "valid"} else "failed"


def build_progress_distribution(
    items: list[dict[str, Any]],
    *,
    total: int | None = None,
    poor_score_below: float | None,
) -> dict[str, int]:
    """Return mutually-exclusive red/yellow/green/gray Case counts."""
    counts = {"passed": 0, "poor": 0, "failed": 0, "pending": 0}
    for item in items:
        outcome = classify_progress_outcome(item, poor_score_below)
        counts[outcome] += 1
    counts["total"] = max(int(total or 0), sum(counts.values()))
    counts["pending"] += max(0, counts["total"] - sum(counts.values()))
    return {
        "total": counts["total"],
        "passed": counts["passed"],
        "poor": counts["poor"],
        "failed": counts["failed"],
        "pending": counts["pending"],
    }
