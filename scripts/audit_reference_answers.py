"""Audit and repair existing reference answers in batches of 30.

The audit uses the configured global LLM as a semantic quality gate. Failed
answers are regenerated through the production search -> generate -> critic /
revise pipeline with job position and category metadata included for
disambiguation. The script preserves an existing answer when regeneration
raises and writes a resumable JSON report after every audit batch.

Run inside the backend container:

    python /app/scripts/audit_reference_answers.py --batch-size 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import DB_PATH
from app.services.answer_enrichment import (
    prepare_answer_prompt,
    refine_answer,
    sources_json,
)
from app.services.llm import _call_llm_with_retry


AUDIT_PROMPT = """你是严格的技术面试参考答案质检员。请一次审查下面这一批答案。

每道题都提供目标岗位、一级分类、二级分类、题面、现有答案和已保存的联网来源。岗位与分类只用于消歧。例如 RAG 分类中的“重排序”应理解为检索 Rerank，而不是 CPU Reorder Buffer。

## 评分维度（每项 0–10）
- relevance：是否在正确技术领域内直接回答题目，而非答非所问。
- accuracy：关键事实、术语、版本和边界是否准确；不能因有链接就默认正确。
- completeness：是否覆盖题目明确要求和决定答案成立的核心考点。
- oral：是否层次清楚、可在面试现场复述，不过度冗长或模板化。
- evidence：有来源时，引用是否来自给定 URL 且与对应事实相关；无来源时不因缺链接扣分。

## 通过门槛
只有同时满足以下条件才能 PASS：relevance>=8、accuracy>=8、completeness>=7.5、oral>=7、evidence>=7、total>=8，且没有 critical_issue。
以下任一项都是 critical_issue：答错技术领域、关键事实错误、遗漏题目的主要子问、题目指定语言却使用其他语言、编造个人经历或精确业务数据、拒答/生成失败占位符。
如果题目要求个人经历、学校、到岗日期、项目指标等，而题面没有提供真实资料，公共参考答案必须避免编造。此时，给出可直接套用的回答结构、具体示例措辞和 `【按真实经历替换】` 占位符是正确做法，只要模板确实逐项回应题目，就不能据此判 FAIL。不能反过来要求模型虚构个人事实。
如果题目提到“当前代码”等缺失材料，答案应明确无法判断具体问题，并提供拿到代码后可执行的检查顺序；不能因为没有虚构代码细节而扣相关性。
篇幅只是辅助判断：复杂题可以超过 520 字，不能仅因略长判失败；但明显重复、难以口述应降低 oral。

## 待审查数据
<items_json>
{items_json}
</items_json>

必须返回每个输入 id，不能遗漏。只输出 JSON：
{{
  "results": [
    {{
      "id": 1,
      "relevance": 0,
      "accuracy": 0,
      "completeness": 0,
      "oral": 0,
      "evidence": 0,
      "total": 0,
      "critical_issue": false,
      "verdict": "PASS或FAIL",
      "reason": "若失败，指出最需要修复的一项；通过则简述优点"
    }}
  ]
}}"""


@dataclass
class QuestionRow:
    id: int
    question: str
    cat1: str
    cat2: str
    job_position: str
    owner_id: int | None
    answer: str
    sources: list[dict[str, Any]]


def _parse_json(raw: str) -> dict[str, Any]:
    text = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip(), flags=re.MULTILINE
    )
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"质检模型未返回 JSON：{text[:200]}")
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("质检结果不是 JSON 对象")
    return value


def _decode_sources(value: str | None) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _load_rows() -> list[QuestionRow]:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT id, question, cat1, cat2, job_position, owner_id,
               ai_answer, answer_sources
        FROM question_bank
        WHERE deleted_at IS NULL
          AND TRIM(COALESCE(ai_answer, '')) != ''
        ORDER BY id
        """
    ).fetchall()
    connection.close()
    return [
        QuestionRow(
            id=int(row["id"]),
            question=row["question"] or "",
            cat1=row["cat1"] or "",
            cat2=row["cat2"] or "",
            job_position=row["job_position"] or "",
            owner_id=row["owner_id"],
            answer=row["ai_answer"] or "",
            sources=_decode_sources(row["answer_sources"]),
        )
        for row in rows
    ]


def _audit_item(row: QuestionRow) -> dict[str, Any]:
    sources = [
        {
            "title": source.get("title") or "",
            "url": source.get("url") or "",
            "snippet": (source.get("snippet") or "")[:250],
        }
        for source in row.sources[:5]
    ]
    return {
        "id": row.id,
        "job_position": row.job_position,
        "cat1": row.cat1,
        "cat2": row.cat2,
        "question": row.question,
        "answer": row.answer,
        "sources": sources,
    }


def _passes(result: dict[str, Any]) -> bool:
    thresholds = {
        "relevance": 8.0,
        "accuracy": 8.0,
        "completeness": 7.5,
        "oral": 7.0,
        "evidence": 7.0,
        "total": 8.0,
    }
    score_keys = ("relevance", "accuracy", "completeness", "oral", "evidence")
    try:
        scores = {key: float(result.get(key, 0)) for key in score_keys}
        # Recompute total so malformed model output cannot pass the gate.
        result["total"] = round(sum(scores.values()) / len(scores), 1)
        scores_pass = all(
            float(result.get(key, 0)) >= value
            for key, value in thresholds.items()
        )
    except (TypeError, ValueError):
        return False
    return (
        scores_pass
        and not bool(result.get("critical_issue", False))
    )


async def _audit_batch(rows: list[QuestionRow]) -> dict[int, dict[str, Any]]:
    prompt = AUDIT_PROMPT.format(
        items_json=json.dumps([_audit_item(row) for row in rows], ensure_ascii=False)
    )
    raw = await _call_llm_with_retry(
        prompt,
        system_msg="你是严格、公正的技术面试答案质检员，只输出 JSON。",
        response_format={"type": "json_object"},
        llm_scope="global",
        thinking=True,
    )
    parsed = _parse_json(raw)
    results = parsed.get("results")
    if not isinstance(results, list):
        raise ValueError("质检结果缺少 results 数组")
    by_id: dict[int, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        try:
            result_id = int(result.get("id"))
        except (TypeError, ValueError):
            continue
        result["passed"] = _passes(result)
        by_id[result_id] = result
    missing = {row.id for row in rows} - set(by_id)
    if missing:
        raise ValueError(f"质检结果遗漏题目：{sorted(missing)}")
    return by_id


async def _audit_with_split_retry(
    rows: list[QuestionRow],
    batch_size: int,
    judge_chunk_size: int,
    concurrency: int,
) -> dict[int, dict[str, Any]]:
    all_results: dict[int, dict[str, Any]] = {}
    semaphore = asyncio.Semaphore(concurrency)

    async def audit_chunk(chunk: list[QuestionRow]) -> dict[int, dict[str, Any]]:
        try:
            async with semaphore:
                return await _audit_batch(chunk)
        except Exception as exc:
            print(
                f"质检子组（{len(chunk)} 题）失败，拆成单题重试：{exc}",
                flush=True,
            )
            results: dict[int, dict[str, Any]] = {}
            for row in chunk:
                async with semaphore:
                    results.update(await _audit_batch([row]))
            return results

    for offset in range(0, len(rows), batch_size):
        batch = rows[offset : offset + batch_size]
        batch_no = offset // batch_size + 1
        chunks = [
            batch[index : index + judge_chunk_size]
            for index in range(0, len(batch), judge_chunk_size)
        ]
        chunk_results = await asyncio.gather(*(audit_chunk(chunk) for chunk in chunks))
        results = {
            item_id: result
            for chunk_result in chunk_results
            for item_id, result in chunk_result.items()
        }
        # Batch judging is efficient but can be noisy. Confirm every failure
        # independently before allowing it to trigger a destructive overwrite.
        initially_failed = [row for row in batch if not results[row.id]["passed"]]
        if initially_failed:
            confirmations = await asyncio.gather(
                *(audit_chunk([row]) for row in initially_failed)
            )
            for confirmation in confirmations:
                for item_id, confirmed in confirmation.items():
                    if confirmed.get("passed"):
                        results[item_id] = confirmed
                    else:
                        first = results[item_id]
                        confirmed["initial_reason"] = first.get("reason", "")
                        results[item_id] = confirmed
        all_results.update(results)
        failed = [row.id for row in batch if not results[row.id]["passed"]]
        print(
            f"质检批次 {batch_no}: {len(batch) - len(failed)}/{len(batch)} 通过；"
            f"失败 ID={failed}",
            flush=True,
        )
    return all_results


async def _regenerate(row: QuestionRow, semaphore: asyncio.Semaphore) -> bool:
    async with semaphore:
        try:
            prompt, sources = await prepare_answer_prompt(
                row.question,
                user_id=None,
                search_scope="public",
                job_position=row.job_position,
                cat1=row.cat1,
                cat2=row.cat2,
            )
            draft = await _call_llm_with_retry(
                prompt,
                system_msg="你是一个技术面试指导专家。",
                llm_scope="global",
            )
            answer, _ = await refine_answer(
                prompt,
                draft,
                sources,
                max_rounds=2,
                llm_scope="global",
            )
            if not answer or answer.startswith("[生成失败"):
                raise ValueError("生成结果为空或为失败占位符")

            connection = sqlite3.connect(DB_PATH, timeout=30)
            connection.execute(
                """
                UPDATE question_bank
                SET ai_answer = ?, answer_sources = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (answer, sources_json(sources), row.id),
            )
            connection.commit()
            connection.close()
            print(f"已重生成 ID={row.id}：{row.question[:40]}", flush=True)
            return True
        except Exception as exc:
            print(f"重生成失败 ID={row.id}：{exc}", file=sys.stderr, flush=True)
            return False


def _write_report(
    path: Path,
    *,
    round_no: int,
    total: int,
    results: dict[int, dict[str, Any]],
    elapsed: float,
) -> None:
    failed = {
        str(item_id): result
        for item_id, result in results.items()
        if not result.get("passed")
    }
    payload = {
        "round": round_no,
        "total": total,
        "passed": total - len(failed),
        "failed": failed,
        "elapsed_seconds": round(elapsed, 1),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def _run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    all_initial_rows = _load_rows()
    if args.expected_count and len(all_initial_rows) != args.expected_count:
        raise RuntimeError(
            f"答案范围发生变化：预期 {args.expected_count}，实际 {len(all_initial_rows)}"
        )
    selected_ids = set(args.ids or [])
    initial_rows = [
        row for row in all_initial_rows if not selected_ids or row.id in selected_ids
    ]
    missing_ids = selected_ids - {row.id for row in initial_rows}
    if missing_ids:
        raise RuntimeError(f"指定 ID 不在现有答案范围：{sorted(missing_ids)}")
    target_ids = {row.id for row in initial_rows}
    print(f"加载 {len(initial_rows)} 份现有答案；每批 {args.batch_size} 题。", flush=True)

    for round_no in range(1, args.max_rounds + 1):
        current = [row for row in _load_rows() if row.id in target_ids]
        results = await _audit_with_split_retry(
            current,
            args.batch_size,
            args.judge_chunk_size,
            args.concurrency,
        )
        _write_report(
            args.report,
            round_no=round_no,
            total=len(current),
            results=results,
            elapsed=time.monotonic() - started,
        )
        failed_ids = [row.id for row in current if not results[row.id]["passed"]]
        if not failed_ids:
            print(
                f"全量通过：{len(current)}/{len(current)}；"
                f"总耗时 {time.monotonic() - started:.1f}s",
                flush=True,
            )
            return 0
        if args.audit_only:
            print(f"审计结束，{len(failed_ids)} 题未通过。", flush=True)
            return 2
        print(
            f"第 {round_no} 轮有 {len(failed_ids)} 题未通过，开始重生成。",
            flush=True,
        )
        row_by_id = {row.id: row for row in current}
        semaphore = asyncio.Semaphore(args.concurrency)
        await asyncio.gather(
            *(_regenerate(row_by_id[item_id], semaphore) for item_id in failed_ids)
        )

    print(f"达到最大轮次 {args.max_rounds}，仍有答案未通过。", file=sys.stderr)
    return 2


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--judge-chunk-size", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--expected-count", type=int, default=205)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--ids", type=int, nargs="*")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("/tmp/interview-boss-answer-quality-audit.json"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_args())))
