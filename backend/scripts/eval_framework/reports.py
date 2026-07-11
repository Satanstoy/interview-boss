"""Report generation: JSON, Markdown, and LLM-generated reports."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from .types import JudgeLLMConfig, DEFAULT_OUTPUT_DIR
from .http_client import _call_openai_compatible_chat
from .scoring import _build_conversation_transcript, _event_tools_for_turn, _event_tool_name, _preview


def llm_generate_report(result: dict, judge_config: JudgeLLMConfig) -> str | None:
    """Generate a Markdown report using LLM."""
    try:
        transcript = _build_conversation_transcript(result.get("turns", []), max_chars=6000)
        scores = result.get("scores", {})
        metrics = result.get("metrics", {})

        prompt = f"""请根据以下面试评测数据，生成一份结构化的中文评测报告。

## 场景: {result.get('scenario_id', 'unknown')}
## 评分结果
```json
{json.dumps(scores, ensure_ascii=False, indent=2)[:2000]}
```

## 硬指标
```json
{json.dumps({k: v for k, v in metrics.items() if not isinstance(v, (list, dict))}, ensure_ascii=False, indent=2)}
```

## 对话记录
{transcript}

请生成包含以下部分的 Markdown 报告：
1. 概述（1-2句总结）
2. 评分表格（维度、得分、说明）
3. 关键发现（亮点和问题）
4. 改进建议（具体可操作的建议）
5. 代表性对话片段（引用1-2个典型轮次）"""

        raw = _call_openai_compatible_chat(
            judge_config,
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=3000,
        )
        return raw
    except Exception as exc:
        print(f"Warning: LLM report generation failed: {exc}", file=sys.stderr)
        fallback = _render_markdown_report(result, time.strftime("%Y%m%d_%H%M%S"))
        return (
            "## 降级提醒\n\n"
            f"LLM 报告生成失败：{exc}。以下为规则模板报告。\n\n"
            f"{fallback}"
        )


def write_reports(
    result: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    timestamp: str | None = None,
    llm_report: str | None = None,
) -> tuple[Path, Path]:
    """Write JSON and Markdown reports."""
    timestamp = timestamp or time.strftime("%Y%m%d_%H%M%S")
    scenario_id = result["scenario_id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"eval_{scenario_id}_{timestamp}.json"
    md_path = output_dir / f"eval_{scenario_id}_{timestamp}.md"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_content = llm_report if llm_report else _render_markdown_report(result, timestamp)
    md_path.write_text(md_content, encoding="utf-8")
    return json_path, md_path


def _render_markdown_report(result: dict, timestamp: str) -> str:
    """Render a template-based Markdown report."""
    scenario_id = result.get("scenario_id", "unknown")
    scores = result.get("scores", {})
    metrics = result.get("metrics", {})
    turns = result.get("turns", [])

    lines = [
        f"# 评测报告：{scenario_id}",
        f"时间：{timestamp}",
        "",
        "## 评分",
        "| 维度 | 得分 | 说明 |",
        "|------|------|------|",
    ]
    for key, item in scores.get("items", {}).items():
        passed = item.get("passed")
        if passed is None:
            state = "N/A (LLM judge)"
        elif passed:
            state = "PASS"
        else:
            state = "FAIL"
        lines.append(f"| {key} | {state} | {item.get('description', '')} |")

    lines.extend([
        "",
        "## 面试流程",
        "| 轮次 | 候选人摘要 | 面试官摘要 | 工具 | 耗时 |",
        "|------|-----------|-----------|------|------|",
    ])
    for turn in turns:
        t = turn.get("turn", "?")
        user = _preview(turn.get("user", ""), 40)
        assistant = _preview(turn.get("assistant", ""), 40)
        tools = ", ".join(_event_tools_for_turn(turn)) or "-"
        latency = f"{turn.get('latency_sec', 0):.1f}s"
        lines.append(f"| {t} | {user} | {assistant} | {tools} | {latency} |")

    if scores.get("critical_issues"):
        lines.extend(["", "## ⚠️ 严重问题"])
        for issue in scores["critical_issues"]:
            lines.append(f"- {issue}")

    if scores.get("highlights"):
        lines.extend(["", "## ✨ 亮点"])
        for highlight in scores["highlights"]:
            lines.append(f"- {highlight}")

    return "\n".join(lines)


def write_unified_report(
    results: list[dict[str, Any]],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    judge_config: JudgeLLMConfig | None = None,
) -> Path:
    """Generate a unified report summarizing all scenario results."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    unified_path = output_dir / f"eval_unified_{timestamp}.md"

    scenario_summaries: list[str] = []
    for r in results:
        scores = r["scores"]
        metrics = r["metrics"]
        overall = scores.get("overall_score", scores.get("ratio", 0))
        passed = scores.get("passed", False)
        status = "✅ PASS" if passed else "❌ FAIL"
        fallback = " ⚠️降级" if scores.get("fallback_notice") else ""
        turn_count = metrics.get("turn_count", len(r.get("turns", [])))

        items = scores.get("items", {})
        passed_dims = sum(1 for v in items.values() if v.get("passed"))
        total_dims = len(items)

        scenario_summaries.append(
            f"| {r['scenario_id']} | {turn_count}轮 | {overall:.2f} | {status}{fallback} "
            f"| {passed_dims}/{total_dims} |"
        )

    lines = [
        "# 统一评测报告",
        f"时间: {timestamp}",
        f"场景数: {len(results)}",
        "",
        "## 总览",
        "| 场景 | 轮数 | 综合分 | 状态 | 通过维度 |",
        "|------|------|--------|------|----------|",
    ]
    lines.extend(scenario_summaries)

    # Per-scenario details
    for r in results:
        scores = r["scores"]
        lines.extend([
            "",
            f"### {r['scenario_id']}",
            "| 维度 | 分数 | 说明 |",
            "|------|------|------|",
        ])
        for key, item in scores.get("items", {}).items():
            score = item.get("score", item.get("passed", "?"))
            lines.append(f"| {key} | {score} | {item.get('description', '')} |")

    report_content = "\n".join(lines)
    unified_path.write_text(report_content, encoding="utf-8")
    return unified_path
