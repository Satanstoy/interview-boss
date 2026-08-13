"""cross-encoder rerank（SiliconFlow bge-reranker-v2-m3）评估：对照生产 LLM rerank。

链路：生产 hybrid_search（FTS5 + bge-m3 向量 + RRF）→ SiliconFlow rerank API → top-5
对照：生产 LLM rerank 平均 3.5（hybrid_search_eval.md）

运行：docker compose run --rm -v $PWD/backend:/app/backend backend python -m app.services.clustering.experiments.reranker_cross_encoder_eval
输出：backend/experiment_reports/reranker_cross_encoder_eval.md
"""

import asyncio
import json
import os
import time
import urllib.request

from app.services.fts_service import hybrid_search

REPORT_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", "experiment_reports"
    )
)
RERANK_URL = "https://api.siliconflow.cn/v1/rerank"
# API key 从环境变量读取，禁止硬编码（tech-audit-2026-08-13 D4-1）
RERANK_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
if not RERANK_KEY:
    raise SystemExit("请设置环境变量 SILICONFLOW_API_KEY（SiliconFlow 平台密钥）后再运行本实验脚本")
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"

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


def rerank_cross_encoder(
    query: str, candidates: list[dict], top_n: int = 5
) -> list[dict]:
    """SiliconFlow bge-reranker-v2-m3 cross-encoder rerank"""
    if not candidates:
        return []
    docs = [
        f"{x['question']} [{x.get('cat1', '')}/{x.get('cat2', '')}]" for x in candidates
    ]
    req = urllib.request.Request(
        RERANK_URL,
        data=json.dumps(
            {
                "model": RERANK_MODEL,
                "query": query,
                "documents": docs,
                "top_n": top_n,
            }
        ).encode(),
        headers={
            "Authorization": f"Bearer {RERANK_KEY}",
            "Content-Type": "application/json",
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
            results = sorted(
                d.get("results", []),
                key=lambda x: x.get("relevance_score", 0),
                reverse=True,
            )
            out = []
            for item in results:
                idx = item.get("index")
                if idx is not None and 0 <= idx < len(candidates):
                    c = dict(candidates[idx])
                    c["_rerank_score"] = item.get("relevance_score", 0)
                    out.append(c)
            return out[:top_n]
        except Exception as e:
            if attempt == 2:
                print(f"  rerank 失败: {e}")
                return []
            time.sleep(2)


async def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    t0 = time.monotonic()

    lines = [
        f"# Cross-Encoder Rerank 评估（bge-reranker-v2-m3 via SiliconFlow）",
        "",
        f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "- 链路: 生产 hybrid_search（FTS5 + bge-m3 + RRF）→ bge-reranker-v2-m3 cross-encoder → top-5",
        "- 对照: 生产 LLM rerank 平均 3.5（hybrid_search_eval.md）；向量top20+LLM rerank 2.9",
        "",
    ]
    summary = []
    sem = asyncio.Semaphore(4)

    async def limited(prompt):
        async with sem:
            return await llm_call(prompt)

    async def score(tag, items, query):
        if not items:
            return tag, 0.0, {}
        fmt = "\n".join(
            f"{x['id']}. {x['question']}（cat2={x.get('cat2')}）" for x in items
        )
        raw = await limited(SCORE_PROMPT.format(query=query, items=fmt))
        sc = {}
        for x in norm_score_list(raw):
            try:
                sc[int(x.get("id"))] = x.get("score", 0)
            except (TypeError, ValueError):
                continue
        avg = sum(sc.get(x["id"], 0) for x in items) / len(items) if items else 0.0
        return tag, avg, sc

    for q in QUERIES:
        name = q["name"]
        query = q["query_text"]
        # 生产混合检索候选
        candidates = hybrid_search(
            keywords=q["keywords"],
            query_text=query,
            limit=15,
            user_id=1,
            bank_mode="public",
            question_type=q["qtype"],
        )
        if not candidates:
            print(f"[eval] {name}: 无候选")
            continue
        # 1) cross-encoder rerank（top-15 → top-5）
        ce_reranked = rerank_cross_encoder(query, candidates, top_n=5)
        # 2) 对照：不 rerank 直接取混合检索前 5
        raw_top5 = candidates[:5]
        for x in raw_top5:
            x["_query"] = query
        for x in ce_reranked:
            x["_query"] = query

        s_raw, s_ce = await asyncio.gather(
            score("混合检索前5", raw_top5, query),
            score("cross-encoder后", ce_reranked, query),
        )
        summary.append((name, len(candidates), s_raw, s_ce))
        print(
            f"[eval] {name}: 候选{len(candidates)} | 混合前5={s_raw[1]:.1f} cross-encoder={s_ce[1]:.1f}"
        )

        lines += [
            f"## {name}",
            "",
            f"- 意图: {query} | 候选: {len(candidates)} 题",
            "",
            "| 阶段 | top-5 | 平均分 |",
            "|------|-------|--------|",
        ]
        for tag, avg, sc, items in (
            (s_raw[0], s_raw[1], s_raw[2], raw_top5),
            (s_ce[0], s_ce[1], s_ce[2], ce_reranked),
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
        "| 查询 | 候选数 | 混合前5 | cross-encoder后 | LLM rerank(对照) |",
        "|------|--------|---------|----------------|------------------|",
    ]
    for name, n, s_raw, s_ce in summary:
        lines.append(
            f"| {name} | {n} | {s_raw[1]:.1f} | {s_ce[1]:.1f} | （hybrid_search_eval） |"
        )
    avg_raw = sum(s[1] for _, _, s, _ in summary) / len(summary)
    avg_ce = sum(s[1] for _, _, _, s in summary) / len(summary)
    lines += [f"| **平均** | | **{avg_raw:.1f}** | **{avg_ce:.1f}** | **3.5** |", ""]

    path = os.path.join(REPORT_DIR, "reranker_cross_encoder_eval.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[eval] 报告已写入 {path}，耗时 {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
