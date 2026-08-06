"""向量 top-20 + LLM rerank 评估：与生产混合检索（hybrid_search）同查询集对比。

链路：bge-m3 向量检索 top-20 → 生产 _llm_rerank_in_tool（LLM 评分过滤）→ top-5
对比：生产混合检索 rerank 后 3.5 分（hybrid_search_eval.md）

运行：docker compose run --rm -v $PWD/backend:/app/backend backend python -m app.services.clustering.experiments.vector_rerank_eval
输出：backend/experiment_reports/vector_rerank_eval.md
"""

import asyncio
import json
import os
import time
import urllib.request

from app.db.connection import get_db_connection

REPORT_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", "experiment_reports"
    )
)
EMB_CACHE = os.path.join(REPORT_DIR, "draw_eval_embeddings.json")
EMB_URL = "https://api.siliconflow.cn/v1/embeddings"
EMB_KEY = "sk-hkaopkqmnstcesslqwxifjiqdffgbpljrixgyssagvgtclym"
EMB_MODEL = "BAAI/bge-m3"

QUERIES = [
    {
        "name": "缓存设计",
        "query_text": "缓存穿透、击穿、雪崩怎么解决",
        "qtype": "knowledge_probe",
    },
    {
        "name": "线程池",
        "query_text": "Java 线程池的核心参数和工作原理",
        "qtype": "knowledge_probe",
    },
    {
        "name": "MySQL索引",
        "query_text": "MySQL 索引为什么用 B+树",
        "qtype": "knowledge_probe",
    },
    {
        "name": "Redis锁",
        "query_text": "Redis 分布式锁怎么实现，有什么问题",
        "qtype": "knowledge_probe",
    },
    {"name": "JVM", "query_text": "JVM 内存模型和 GC 机制", "qtype": "knowledge_probe"},
    {
        "name": "秒杀系统",
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


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb + 1e-9)


def embed_bgem3(texts):
    req = urllib.request.Request(
        EMB_URL,
        data=json.dumps(
            {"model": EMB_MODEL, "input": texts, "encoding_format": "float"}
        ).encode(),
        headers={
            "Authorization": f"Bearer {EMB_KEY}",
            "Content-Type": "application/json",
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
            out = [None] * len(texts)
            for d in data["data"]:
                out[d["index"]] = d["embedding"]
            return out
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


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

    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, question, cat1, cat2, tags FROM question_bank WHERE deleted_at IS NULL ORDER BY id"
    ).fetchall()
    qs = [
        {
            "id": r["id"],
            "question": r["question"],
            "cat1": r["cat1"] or "",
            "cat2": r["cat2"] or "",
            "tags": r["tags"] or "",
        }
        for r in rows
    ]
    print(f"[eval] 题库 {len(qs)} 题")

    # bge-m3 向量（复用缓存）
    cache = json.load(open(EMB_CACHE)) if os.path.exists(EMB_CACHE) else {}
    qvec = {}
    for q in qs:
        v = cache.get(f"q{q['id']}")
        if v:
            qvec[q["id"]] = v
    missing = [q for q in qs if q["id"] not in qvec]
    if missing:
        vecs = embed_bgem3(
            [f"{q['question']} {q['cat2']} {q['tags']}" for q in missing]
        )
        for q, v in zip(missing, vecs):
            qvec[q["id"]] = v
        print(f"[eval] 补充编码 {len(missing)} 题")
    query_vecs = {
        q["query_text"]: v
        for q, v in zip(QUERIES, embed_bgem3([q["query_text"] for q in QUERIES]))
    }

    lines = [
        f"# 向量 top-20 + LLM rerank 评估（对照生产混合检索 3.5）",
        "",
        f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "- 链路: bge-m3 向量检索 top-20 → 生产 `_llm_rerank_in_tool` → top-5",
        "- 对照: 生产混合检索（FTS+向量+RRF+rerank）平均 3.5（hybrid_search_eval.md）",
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
            f"{x['id']}. {x['question']}（cat2={x['cat2']}）" for x in items
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
        qv = query_vecs[query]
        # 向量 top-20
        scored = sorted(
            ((x, cosine(qv, qvec[x["id"]])) for x in qs),
            key=lambda t: t[1],
            reverse=True,
        )[:20]
        top20 = [dict(x) for x, _ in scored]
        for x in top20:
            x["_query"] = query
        top5_raw = top20[:5]
        # 生产 LLM rerank
        reranked = await _llm_rerank_in_tool([dict(x) for x in top20], query, user_id=1)
        reranked = reranked[:5] if reranked else []

        s_raw, s_rr = await asyncio.gather(
            score("top20前5", top5_raw, query),
            score("rerank后", reranked, query),
        )
        summary.append((name, s_raw, s_rr))
        print(f"[eval] {name}: 向量前5={s_raw[1]:.1f} rerank后={s_rr[1]:.1f}")

        lines += [
            f"## {name}",
            "",
            f"- 意图: {query}",
            "",
            "| 阶段 | top-5 | 平均分 |",
            "|------|-------|--------|",
        ]
        for tag, avg, sc, items in (
            (s_raw[0], s_raw[1], s_raw[2], top5_raw),
            (s_rr[0], s_rr[1], s_rr[2], reranked),
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
        "| 查询 | 向量前5 | 向量top20+rerank | 生产混合检索rerank后 |",
        "|------|---------|-------------------|---------------------|",
    ]
    for name, s_raw, s_rr in summary:
        lines.append(
            f"| {name} | {s_raw[1]:.1f} | {s_rr[1]:.1f} | （见 hybrid_search_eval） |"
        )
    avg_raw = sum(s[1] for _, s, _ in summary) / len(summary)
    avg_rr = sum(s[1] for _, _, s in summary) / len(summary)
    lines += [f"| **平均** | **{avg_raw:.1f}** | **{avg_rr:.1f}** | **3.5** |", ""]

    path = os.path.join(REPORT_DIR, "vector_rerank_eval.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[eval] 报告已写入 {path}，耗时 {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
