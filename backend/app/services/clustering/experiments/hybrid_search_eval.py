"""生产混合检索链路评估：hybrid_search（FTS5 + bge-m3 向量 + RRF）→ LLM rerank。

直接复用生产函数（fts_service.hybrid_search + agents.chat.tools._llm_rerank_in_tool），
验证切换 bge-m3 后生产 search_questions 的真实效果。
mimo 对"rerank 前 top-5" vs "rerank 后 top-5"打分对比（0-5）。

运行：docker compose run --rm -v $PWD/backend:/app/backend backend python -m app.services.clustering.experiments.hybrid_search_eval
输出：backend/experiment_reports/hybrid_search_eval.md
"""

import asyncio
import json
import os
import time

from app.services.fts_service import hybrid_search

REPORT_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", "experiment_reports"
    )
)

# agent 风格查询（keywords + query_text + question_type，模拟 search_questions 工具调用）
QUERIES = [
    {
        "name": "缓存设计",
        "keywords": ["缓存", "穿透", "雪崩"],
        "query_text": "缓存穿透、击穿、雪崩怎么解决",
        "qtype": "knowledge_probe",
    },
    {
        "name": "线程池",
        "keywords": ["线程池", "Java"],
        "query_text": "Java 线程池的核心参数和工作原理",
        "qtype": "knowledge_probe",
    },
    {
        "name": "MySQL索引",
        "keywords": ["MySQL", "索引", "B+树"],
        "query_text": "MySQL 索引为什么用 B+树",
        "qtype": "knowledge_probe",
    },
    {
        "name": "Redis锁",
        "keywords": ["Redis", "分布式锁"],
        "query_text": "Redis 分布式锁怎么实现，有什么问题",
        "qtype": "knowledge_probe",
    },
    {
        "name": "JVM",
        "keywords": ["JVM", "内存", "GC"],
        "query_text": "JVM 内存模型和 GC 机制",
        "qtype": "knowledge_probe",
    },
    {
        "name": "秒杀系统",
        "keywords": ["秒杀", "超卖", "库存"],
        "query_text": "秒杀系统的架构设计，如何防止超卖",
        "qtype": "system_design",
    },
]

SCORE_PROMPT = """你是面试官。面试查询意图：{query}

检索系统根据意图召回了以下 5 道题。请为每道题与意图的相关性打分（0-5）：
- 5 = 完全对应意图的考察点
- 3 = 相关但考察点有偏差
- 1 = 勉强相关
- 0 = 完全无关

{items}

输出格式（严格 JSON 数组）：
[{{"id": 题号, "score": 分数, "reason": "一句话原因"}}]"""


def parse_json(raw):
    import re

    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\[.*\]|\{.*\})", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def norm_score_list(raw):
    import re as _re

    data = parse_json(raw)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict) and "score" in x]
    if isinstance(data, dict):
        for k in ("scores", "results", "result", "items"):
            v = data.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict) and "score" in x]
        if "score" in data:
            return [data]
    out = []
    for m in _re.finditer(r"\{[^{}]*\}", raw or ""):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and "score" in obj:
                out.append(obj)
        except (json.JSONDecodeError, TypeError):
            continue
    return out


async def llm_call(prompt):
    from app.services.llm import _call_llm_with_retry

    return await _call_llm_with_retry(
        prompt,
        system_msg="你是一个资深面试官。",
        response_format=None,
        user_id=1,
        model=None,
    )


async def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    t0 = time.monotonic()
    from app.agents.chat.tools import _llm_rerank_in_tool

    lines = [
        f"# 生产混合检索链路评估（hybrid_search → LLM rerank，bge-m3）",
        "",
        f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "- 链路: FTS5 + bge-m3 向量 + CJK LIKE → RRF 融合 → heuristic → MMR → LLM rerank",
        "- 模型: bge-m3（SiliconFlow）+ mimo-v2.5（LLM）",
        "",
    ]
    summary = []
    sem = asyncio.Semaphore(4)

    async def limited(prompt):
        async with sem:
            return await llm_call(prompt)

    async def score(tag, items):
        if not items:
            return tag, 0.0, {}
        fmt = "\n".join(
            f"{x['id']}. {x['question']}（cat2={x.get('cat2')}）" for x in items
        )
        raw = await limited(SCORE_PROMPT.format(query=items[0]["_query"], items=fmt))
        sc_list = norm_score_list(raw)
        sc = {}
        for x in sc_list:
            try:
                sc[int(x.get("id"))] = x.get("score", 0)
            except (TypeError, ValueError):
                continue
        avg = sum(sc.get(x["id"], 0) for x in items) / len(items) if items else 0.0
        return tag, avg, sc

    for q in QUERIES:
        name = q["name"]
        # 生产混合检索（rerank 前）
        try:
            candidates = hybrid_search(
                keywords=q["keywords"],
                query_text=q["query_text"],
                limit=15,
                user_id=1,
                bank_mode="public",
                question_type=q["qtype"],
            )
        except Exception as e:
            print(f"[eval] {name} hybrid_search 失败: {e}")
            candidates = []
        for x in candidates:
            x["_query"] = q["query_text"]
        pre_rerank = candidates[:5]

        # 生产 LLM rerank（对话上下文用意图文本模拟）
        reranked = await _llm_rerank_in_tool(
            [dict(x) for x in candidates],
            q["query_text"],
            user_id=1,
        )
        if reranked:
            reranked = reranked[:5]
        else:
            reranked = []
        for x in reranked:
            x["_query"] = q["query_text"]

        # mimo 打分（rerank 前 vs 后）
        s_pre, s_post = await asyncio.gather(
            score("rerank前", pre_rerank),
            score("rerank后", reranked),
        )
        summary.append((name, len(candidates), s_pre, s_post))
        print(
            f"[eval] {name}: 候选{len(candidates)} | rerank前={s_pre[1]:.1f} rerank后={s_post[1]:.1f}"
        )

        lines += [
            f"## {name}",
            "",
            f"- 意图: {q['query_text']} | 混合检索候选: {len(candidates)} 题",
            "",
            "| 阶段 | top-5 | 平均分 |",
            "|------|-------|--------|",
        ]
        for tag, avg, sc, items in (
            (s_pre[0], s_pre[1], s_pre[2], pre_rerank),
            (s_post[0], s_post[1], s_post[2], reranked),
        ):
            detail = (
                "；".join(f"{x['id']}({sc.get(x['id'], '?')}分)" for x in items)
                if items
                else "（空）"
            )
            lines.append(f"| {tag} | {detail} | {avg:.1f} |")
        lines.append("")

    lines += [
        "## 汇总",
        "",
        "| 查询 | 候选数 | rerank前 | rerank后 |",
        "|------|--------|---------|---------|",
    ]
    for name, n, s_pre, s_post in summary:
        lines.append(f"| {name} | {n} | {s_pre[1]:.1f} | {s_post[1]:.1f} |")
    avg_pre = sum(s[1] for _, _, s, _ in summary) / len(summary)
    avg_post = sum(s[1] for _, _, _, s in summary) / len(summary)
    lines += [f"| **平均** | | **{avg_pre:.1f}** | **{avg_post:.1f}** |", ""]

    path = os.path.join(REPORT_DIR, "hybrid_search_eval.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[eval] 报告已写入 {path}，耗时 {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
