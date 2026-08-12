"""用同一 MiMo 模型对公共参考答案 Prompt 做成对盲评。

实验只比较 Prompt 本身：不联网、不写数据库、不运行生成后 refine loop。
运行：
    docker compose run --rm \
      -v "$PWD/backend:/app/backend" \
      -v "$PWD/scripts:/app/scripts" \
      -v "$PWD/docs:/app/docs" \
      backend python /app/scripts/eval_reference_answer_prompt.py

默认输出：docs/evaluations/reference-answer-prompt-mimo-eval.md
可用 ANSWER_PROMPT_EVAL_OUTPUT 指定报告文件名。
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.prompts import ANSWER_PROMPT, ANSWER_PROMPT_CANDIDATE
from app.services.llm import _call_llm_with_retry, get_llm_client_for_user


QUESTIONS = [
    {
        "id": "Q1",
        "type": "基础原理",
        "question": "Redis 为什么快？回答时不要只罗列技术名词，还要说明这些因素分别解决了什么瓶颈。",
    },
    {
        "id": "Q2",
        "type": "原理对比",
        "question": "进程和线程有什么区别？实际开发中应该怎么选？",
    },
    {
        "id": "Q3",
        "type": "数据库",
        "question": "MySQL 的 MVCC 是怎么实现的？它能解决什么问题，又不能解决什么问题？",
    },
    {
        "id": "Q4",
        "type": "网络",
        "question": "TCP 为什么需要三次握手，而不是两次或四次？",
    },
    {
        "id": "Q5",
        "type": "系统设计",
        "question": "设计一个秒杀系统，要求支持十万级瞬时并发，并说明如何防止超卖、保护下游和处理失败恢复。",
    },
    {
        "id": "Q6",
        "type": "LLM应用",
        "question": "RAG 系统出现‘检索结果相关，但最终答案仍然错’时，你会怎么定位和优化？",
    },
    {
        "id": "Q7",
        "type": "Agent设计",
        "question": "ReAct Agent 在生产环境中为什么容易陷入无效循环？你会如何设置停止条件和兜底？",
    },
    {
        "id": "Q8",
        "type": "项目经历",
        "question": "请介绍一次你把接口 P99 延迟从 800ms 优化到 200ms 的经历，并说明定位过程和取舍。题目没有提供候选人的真实项目背景。",
    },
    {
        "id": "Q9",
        "type": "算法代码",
        "question": "用 Java 实现 LRU Cache，要求 get 和 put 的平均时间复杂度都是 O(1)。",
    },
    {
        "id": "Q10",
        "type": "混合选型",
        "question": "消息队列如何保证消息不丢失？如果业务还要求尽量不重复消费，生产者、Broker 和消费者分别要做什么？",
    },
]


JUDGE_PROMPT = """你是一名严格的技术面试答案评审员。下面有同一道题的两份匿名答案。请独立评分，不要猜测哪份是新版。

## 评分维度（每项 0–10）
- accuracy：事实与技术细节准确，边界表述不过度绝对。
- completeness：覆盖本题决定答案是否成立的核心考点。
- oral：像面试现场能自然说出口，不像报告或教材摘抄。
- memorability：有清晰因果链和记忆锚点，复习后容易复述。
- structure：层次服务于内容，扫读清楚且不过度模板化。
- specificity：回答紧扣本题，能解释“为什么”和取舍，不堆术语。
- integrity：不虚构经历，遵守题目指定语言等约束。

总分 total 为七项的算术平均值，保留一位小数。winner 只能是 "A"、"B" 或 "tie"；两份总分差小于 0.3 时判 tie。

## 面试题
{question}

## 答案 A
<answer_a>
{answer_a}
</answer_a>

## 答案 B
<answer_b>
{answer_b}
</answer_b>

只输出 JSON：
{{
  "A": {{"accuracy": 0, "completeness": 0, "oral": 0, "memorability": 0, "structure": 0, "specificity": 0, "integrity": 0, "total": 0, "comment": "一句话评价"}},
  "B": {{"accuracy": 0, "completeness": 0, "oral": 0, "memorability": 0, "structure": 0, "specificity": 0, "integrity": 0, "total": 0, "comment": "一句话评价"}},
  "winner": "A或B或tie",
  "deciding_reason": "决定胜负的主要原因"
}}"""


DIMENSIONS = (
    "accuracy",
    "completeness",
    "oral",
    "memorability",
    "structure",
    "specificity",
    "integrity",
)


@dataclass
class CaseResult:
    item: dict
    baseline: str
    candidate: str
    judgments: list[dict]


def _extract_json(raw: str) -> dict:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"judge did not return JSON: {text[:200]}")
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("judge JSON is not an object")
    return value


def _prompt(template: str, question: str) -> str:
    return template.replace("{question}", question)


async def _llm(prompt: str, *, system_msg: str) -> str:
    return await _call_llm_with_retry(
        prompt,
        system_msg=system_msg,
        llm_scope="global",
        thinking=False,
    )


async def _generate_pair(item: dict, sem: asyncio.Semaphore) -> tuple[str, str]:
    async def generate(template: str) -> str:
        async with sem:
            return await _llm(
                _prompt(template, item["question"]),
                system_msg="你是一个后端和算法面试指导专家。",
            )

    return tuple(await asyncio.gather(generate(ANSWER_PROMPT), generate(ANSWER_PROMPT_CANDIDATE)))


async def _judge_pair(
    item: dict,
    baseline: str,
    candidate: str,
    sem: asyncio.Semaphore,
) -> list[dict]:
    # 第二轮交换 A/B，降低同一评审模型的位置偏差。
    orders = [
        ("baseline", baseline, "candidate", candidate),
        ("candidate", candidate, "baseline", baseline),
    ]

    async def judge(order: tuple[str, str, str, str]) -> dict:
        a_name, answer_a, b_name, answer_b = order
        prompt = JUDGE_PROMPT.format(
            question=item["question"], answer_a=answer_a, answer_b=answer_b
        )
        async with sem:
            raw = await _llm(prompt, system_msg="你是严格、公正的技术面试答案评审员，只输出 JSON。")
        parsed = _extract_json(raw)
        return {"mapping": {"A": a_name, "B": b_name}, "result": parsed}

    return list(await asyncio.gather(*(judge(order) for order in orders)))


def _variant_scores(case: CaseResult, variant: str) -> dict[str, float]:
    values = {dimension: [] for dimension in (*DIMENSIONS, "total")}
    for judgment in case.judgments:
        label = next(k for k, v in judgment["mapping"].items() if v == variant)
        score = judgment["result"].get(label, {})
        for dimension in values:
            try:
                values[dimension].append(float(score.get(dimension, 0)))
            except (TypeError, ValueError):
                values[dimension].append(0.0)
    return {
        dimension: sum(scores) / len(scores) if scores else 0.0
        for dimension, scores in values.items()
    }


def _sign_test_p_value(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    smaller = min(wins, losses)
    tail = sum(math.comb(n, k) for k in range(smaller + 1)) / (2**n)
    return min(1.0, 2 * tail)


def _winner(baseline_total: float, candidate_total: float) -> str:
    delta = candidate_total - baseline_total
    if abs(delta) < 0.3:
        return "平"
    return "新版" if delta > 0 else "旧版"


def _render_report(cases: list[CaseResult], model: str, elapsed: float) -> str:
    scored = []
    for case in cases:
        old = _variant_scores(case, "baseline")
        new = _variant_scores(case, "candidate")
        scored.append((case, old, new))

    old_avg = {
        dimension: sum(old[dimension] for _, old, _ in scored) / len(scored)
        for dimension in (*DIMENSIONS, "total")
    }
    new_avg = {
        dimension: sum(new[dimension] for _, _, new in scored) / len(scored)
        for dimension in (*DIMENSIONS, "total")
    }
    wins = sum(_winner(old["total"], new["total"]) == "新版" for _, old, new in scored)
    losses = sum(_winner(old["total"], new["total"]) == "旧版" for _, old, new in scored)
    ties = len(scored) - wins - losses
    p_value = _sign_test_p_value(wins, losses)
    relative = (
        (new_avg["total"] - old_avg["total"]) / old_avg["total"] * 100
        if old_avg["total"]
        else 0.0
    )
    significance = "达到" if p_value < 0.05 else "未达到"

    lines = [
        "# 公共参考答案 Prompt：MiMo 10 题成对评估",
        "",
        f"- 模型：`{model}`",
        "- 方法：旧版/候选版各生成一次；同一模型两轮盲评，第二轮交换 A/B；无联网、无数据库写入、无 refine loop。",
        f"- 样本：{len(cases)} 题；总调用数约 {len(cases) * 4}；耗时 {elapsed:.0f} 秒。",
        "- 说明：这是小样本模型评审，只能判断方向；不能替代真人面试官评审和多次随机种子复验。",
        "",
        "## 结论",
        "",
        f"- 旧版平均：**{old_avg['total']:.2f}/10**；新版平均：**{new_avg['total']:.2f}/10**；变化 **{new_avg['total'] - old_avg['total']:+.2f}**（{relative:+.1f}%）。",
        f"- 成对结果：新版胜 {wins}、旧版胜 {losses}、平 {ties}。双侧符号检验 `p={p_value:.4f}`，{significance} 0.05 显著性阈值。",
        "",
        "## 分维度汇总",
        "",
        "| 维度 | 旧版 | 新版 | 差值 |",
        "|---|---:|---:|---:|",
    ]
    labels = {
        "accuracy": "准确性",
        "completeness": "完整性",
        "oral": "口述性",
        "memorability": "易背性",
        "structure": "结构",
        "specificity": "针对性",
        "integrity": "约束与真实性",
        "total": "总分",
    }
    for dimension in (*DIMENSIONS, "total"):
        lines.append(
            f"| {labels[dimension]} | {old_avg[dimension]:.2f} | {new_avg[dimension]:.2f} | {new_avg[dimension] - old_avg[dimension]:+.2f} |"
        )

    lines += [
        "",
        "## 逐题结果",
        "",
        "| 题号 | 题型 | 旧版 | 新版 | 差值 | 胜者 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for case, old, new in scored:
        lines.append(
            f"| {case.item['id']} | {case.item['type']} | {old['total']:.2f} | {new['total']:.2f} | {new['total'] - old['total']:+.2f} | {_winner(old['total'], new['total'])} |"
        )

    lines += ["", "## 修改前后完整对比", ""]
    for case, old, new in scored:
        reasons = []
        for index, judgment in enumerate(case.judgments, 1):
            reason = str(judgment["result"].get("deciding_reason", "")).strip()
            mapping = judgment["mapping"]
            if reason:
                reasons.append(
                    f"评审{index}（A={mapping['A']}，B={mapping['B']}）：{reason}"
                )
        lines += [
            f"### {case.item['id']} · {case.item['type']}",
            "",
            f"**问题：** {case.item['question']}",
            "",
            f"**评分：** 旧版 {old['total']:.2f}，新版 {new['total']:.2f}，差值 {new['total'] - old['total']:+.2f}。",
            "",
            f"**盲评关键理由：** {'；'.join(reasons) or '无'}",
            "",
            "#### 修改前",
            "",
            case.baseline.strip(),
            "",
            "#### 修改后",
            "",
            case.candidate.strip(),
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


async def main() -> None:
    _, model, _, _, _ = get_llm_client_for_user(None, llm_scope="global")
    started = time.monotonic()
    sem = asyncio.Semaphore(int(os.environ.get("ANSWER_PROMPT_EVAL_CONCURRENCY", "2")))

    print(f"[eval] model={model}; questions={len(QUESTIONS)}")
    generated = await asyncio.gather(*(_generate_pair(item, sem) for item in QUESTIONS))
    print("[eval] generation complete; starting swapped-order blind judging")
    judged = await asyncio.gather(
        *(
            _judge_pair(item, pair[0], pair[1], sem)
            for item, pair in zip(QUESTIONS, generated, strict=True)
        )
    )
    cases = [
        CaseResult(item=item, baseline=pair[0], candidate=pair[1], judgments=judgments)
        for item, pair, judgments in zip(QUESTIONS, generated, judged, strict=True)
    ]
    elapsed = time.monotonic() - started
    report = _render_report(cases, model, elapsed)
    repo_root = Path(__file__).resolve().parents[1]
    output_name = os.environ.get(
        "ANSWER_PROMPT_EVAL_OUTPUT", "reference-answer-prompt-mimo-eval.md"
    )
    output = repo_root / "docs" / "evaluations" / Path(output_name).name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"[eval] report={output}; elapsed={elapsed:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
