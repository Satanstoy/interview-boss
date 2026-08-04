"""Compile the private Agent interview Markdown into a compact runtime catalog.

Usage:
    uv run python backend/scripts/import_agent_private_catalog.py \
      /path/to/Agent面试题库合集_完整版.md

The importer intentionally keeps question text and evaluation scaffolding, but
does not copy long sample answers into the runtime catalog.  The source file is
not read by the application at runtime.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


QUESTION_RE = re.compile(r"^(#{2,3})\s+(\d+)[.、）)]\s*(.+?)\s*$")
DIFFICULTY_RE = re.compile(r"(?:简单|中等|偏难|复杂)")
FENCE_RE = re.compile(r"```(?:\w+)?\s*\n(.*?)```", re.DOTALL)


def _clean_markdown(text: str) -> str:
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _difficulty(title: str, body: str) -> str:
    match = DIFFICULTY_RE.search(title)
    value = match.group(0) if match else DIFFICULTY_RE.search(body[:500])
    value = value.group(0) if hasattr(value, "group") else value
    return {"简单": "easy", "中等": "medium", "偏难": "hard", "复杂": "hard"}.get(
        value or "", "medium"
    )


def _section_extract(body: str, labels: tuple[str, ...], limit: int = 900) -> str:
    lines = body.splitlines()
    start = None
    for index, line in enumerate(lines):
        normalized = re.sub(r"[#：: ]", "", line)
        if any(label in normalized for label in labels):
            start = index + 1
            break
    if start is None:
        return ""
    collected: list[str] = []
    for line in lines[start:]:
        if re.match(r"^#{2,4}\s+", line):
            break
        if line.strip() and line.strip() != "---":
            collected.append(line.strip())
        if len("\n".join(collected)) >= limit:
            break
    return _clean_markdown("\n".join(collected))[:limit]


def _bullets(value: str, limit: int = 8) -> list[str]:
    if not value:
        return []
    values: list[str] = []
    for line in value.splitlines():
        line = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)", "", line).strip()
        if line.endswith((":", "：")):
            continue
        if line and line not in values:
            values.append(line[:240])
        if len(values) >= limit:
            break
    return values


def _classify(section: str, title: str, body: str) -> tuple[str, str, list[str]]:
    text = f"{section} {title} {body[:1500]}".casefold()
    code = any(token in text for token in ("js / typescript", "java", "python", "代码考察", "tool call 数据", "流式事件数据"))
    protocol = any(token in text for token in ("数据协议", "tool call 数据", "流式事件", "模型输入数据"))
    if code:
        fmt = "protocol_review" if protocol else "code_review"
        qtype = "knowledge_probe"
    elif any(token in text for token in ("设计", "架构", "平台", "系统", "多智能体")):
        fmt, qtype = "system_design", "system_design"
    else:
        fmt, qtype = "concept", "knowledge_probe"

    capability_map = (
        ("agent_orchestration", ("多智能体", "multi-agent", "sub-agent", "orchestrator")),
        ("agent_loop_tool_use", ("agent loop", "react", "tool calling", "工具调用", "tool registry")),
        ("memory_state", ("memory", "记忆", "state", "状态", "checkpoint", "resume")),
        ("rag_retrieval", ("rag", "embedding", "向量", "检索")),
        ("llm_fundamentals", ("transformer", "self-attention", "q / k / v", "kv cache")),
        ("agent_platform_engineering", ("监控", "日志", "限流", "缓存", "延迟", "prompt 管理", "大规模")),
        ("agent_safety_governance", ("安全", "治理", "审计", "副作用", "权限", "hallucination")),
        ("agent_code_understanding", ("ast", "symbol", "引用关系", "coding agent", "代码")),
        ("agent_protocols", ("sse", "websocket", "协议", "流式", "xml", "json")),
    )
    capabilities = [name for name, terms in capability_map if any(term in text for term in terms)]
    if not capabilities:
        capabilities = ["agent_engineering_general"]
    return fmt, qtype, capabilities


def parse_catalog(source: Path) -> list[dict]:
    lines = source.read_text(encoding="utf-8").splitlines()
    starts: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = QUESTION_RE.match(line)
        if match:
            starts.append((index, match))

    records: list[dict] = []
    for sequence, (start, match) in enumerate(starts, start=1):
        end = starts[sequence][0] if sequence < len(starts) else len(lines)
        title = _clean_markdown(match.group(3))
        title = re.sub(r"^[（(](?:简单|中等|偏难|复杂)[^）)]*[）)]\s*", "", title)
        top_sections = [
            line.removeprefix("# ").strip()
            for line in lines[:start]
            if line.startswith("# ") and line.removeprefix("# ").strip()
        ]
        section = top_sections[-1] if top_sections else "Agent interview"
        body = "\n".join(lines[start + 1 : end])
        fmt, qtype, capabilities = _classify(section, title, body)
        focus = _bullets(_section_extract(body, ("你想考什么", "这题主要考", "这题考的是", "这题真正想考什么")))
        must_have = _bullets(_section_extract(body, ("候选人至少答到", "一个比较好的回答要点", "好的回答通常会覆盖", "面试官说明")))
        bonus = _bullets(_section_extract(body, ("答到这些算加分", "加分点")))
        red_flags = _bullets(_section_extract(body, ("比较弱的回答", "弱回答通常", "改坏点", "这在业务里为什么常见")))
        followups = _bullets(_section_extract(body, ("可以继续追问", "追问方向", "面试官可以怎么判断")), limit=6)
        fixture = "\n".join(
            "\n".join(_clean_markdown(match.group(1)).splitlines()[:18])
            for match in FENCE_RE.finditer(body)
        )[:1600]
        records.append(
            {
                "id": 900000 + sequence,
                "question": title,
                "difficulty": _difficulty(title, body),
                "question_type": qtype,
                "format": fmt,
                "capability": capabilities[0],
                "tags": capabilities,
                "evaluation_focus": focus,
                "must_have": must_have,
                "bonus": bonus,
                "red_flags": red_flags,
                "followups": followups,
                "fixture_summary": fixture,
                "source_section": section,
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/app/mcp_server/data/agent_interview_catalog.json"),
    )
    args = parser.parse_args()
    records = parse_catalog(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"schema_version": 1, "source_kind": "private_agent_interview_material", "questions": records},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"compiled {len(records)} private Agent interview questions -> {args.output}")


if __name__ == "__main__":
    main()
