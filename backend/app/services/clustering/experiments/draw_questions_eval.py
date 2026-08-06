"""抽题工具评估：SQL 现状 vs embedding 语义 vs RAG+LLM。

场景：8 个典型面试抽题请求（题型 × 主题）。
方案 A：现状 draw_questions（SQL LIKE 过滤 + 加权随机）
方案 B：bge-m3 embedding 检索 top-20
方案 C：embedding top-20 + LLM 挑选 3 题（RAG+LLM）
评估：LLM 对每个方案抽出的 3 题按"与面试意图相关性"打分（0-5）。

运行：docker compose run --rm -v $PWD/backend:/app/backend backend python -m app.services.clustering.experiments.draw_questions_eval
输出：backend/experiment_reports/draw_questions_eval.md
"""
import asyncio
import json
import os
import random
import re
import sqlite3
import time
import urllib.request

from app.db.connection import get_db_connection

REPORT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "experiment_reports"))
EMB_CACHE = "/tmp/draw_eval_embeddings.json"
EMB_URL = "https://api.siliconflow.cn/v1/embeddings"
EMB_KEY = "sk-hkaopkqmnstcesslqwxifjiqdffgbpljrixgyssagvgtclym"
EMB_MODEL = "BAAI/bge-m3"
EMB_BATCH = 32
SEED = 42

SCENARIOS = [
    {"name": "缓存设计", "query": "Redis缓存设计与优化：缓存穿透、击穿、雪崩怎么解决，缓存与数据库一致性", "args": {"cat2": "D1.缓存设计与优化", "question_type": "knowledge_probe"}},
    {"name": "数据库基础", "query": "MySQL数据库基础：索引结构、B+树、事务、锁机制", "args": {"cat2": "C3.数据库基础", "question_type": "knowledge_probe"}},
    {"name": "高并发限流", "query": "高并发场景下的限流方案：怎么做限流、限流算法", "args": {"cat2": "D2.高并发与限流", "question_type": "knowledge_probe"}},
    {"name": "操作系统网络", "query": "操作系统与网络基础：TCP三次握手四次挥手、进程线程", "args": {"cat2": "C4.操作系统与网络", "question_type": "knowledge_probe"}},
    {"name": "秒杀系统设计", "query": "系统设计：设计一个秒杀系统，如何防止超卖，高并发下的方案", "args": {"cat2": "D2.高并发与限流", "question_type": "system_design"}},
    {"name": "算法手撕", "query": "手撕代码：算法题，链表、排序、滑动窗口", "args": {"cat2": "E2.算法手撕", "question_type": "algorithm_coding"}},
    {"name": "项目拷打", "query": "项目拷打：挑一个项目介绍，架构设计、技术选型、难点", "args": {"cat2": "A1.项目介绍与背景", "question_type": "project_followup"}},
    {"name": "RAG系统", "query": "RAG系统设计：检索增强生成、向量数据库、召回率", "args": {"cat2": "B2.RAG系统设计", "question_type": "knowledge_probe"}},
]

# 与 question_draw_service 一致的 question_type 关键词映射（简化版）
QT_FILTERS = {
    "algorithm_coding": ["算法", "算法", "算法", "代码"],
    "project_followup": ["项目", "Agent", "系统设计", "项目"],
    "knowledge_probe": ["基础", "Agent", "RAG", "原理"],
    "system_design": ["系统设计", "系统设计", "架构"],
}


def load_questions():
    conn = get_db_connection()
    return conn.execute(
        "SELECT id, question, cat1, cat2, tags FROM question_bank "
        "WHERE deleted_at IS NULL ORDER BY id"
    ).fetchall()


def sql_candidates(qs, scenario):
    """复刻 draw_questions 的 SQL 过滤逻辑（cat2 + question_type 关键词）"""
    args = scenario["args"]
    cat2 = args.get("cat2")
    qt = args.get("question_type")
    qt_kw = QT_FILTERS.get(qt, [qt, qt, qt])
    out = []
    for r in qs:
        text = f"{r['cat1'] or ''} {r['cat2'] or ''} {r['tags'] or ''} {r['question']}"
        if cat2 and cat2 != "全部" and cat2 not in text:
            continue
        if qt and not any(k in text for k in qt_kw):
            continue
        out.append(r)
    return out


def sql_draw(qs, scenario, count=3):
    """现状方案：候选池 + 固定种子加权随机抽取"""
    rng = random.Random(SEED + hash(scenario["name"]) % 1000)
    cands = sql_candidates(qs, scenario)
    if not cands:
        return [], []
    picked = rng.sample(cands, min(count, len(cands)))
    return cands, picked


def embed_batch(texts):
    req = urllib.request.Request(
        EMB_URL,
        data=json.dumps({"model": EMB_MODEL, "input": texts, "encoding_format": "float"}).encode(),
        headers={"Authorization": f"Bearer {EMB_KEY}", "Content-Type": "application/json"},
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


def get_emb(text, cache, key):
    if key in cache:
        return cache[key]
    vec = embed_batch([text])[0]
    cache[key] = vec
    with open(EMB_CACHE, "w") as f:
        json.dump(cache, f)
    return vec


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb + 1e-12)


def emb_top_k(qs, query_vec, k=20):
    scored = []
    cache = {}
    if os.path.exists(EMB_CACHE):
        cache = json.load(open(EMB_CACHE))
    # 批量嵌入全部题（缓存）
    todo = [r for r in qs if f"q{r['id']}" not in cache]
    for i in range(0, len(todo), EMB_BATCH):
        chunk = todo[i:i + EMB_BATCH]
        vecs = embed_batch([f"{r['question']} {r['cat2'] or ''} {r['tags'] or ''}" for r in chunk])
        for r, v in zip(chunk, vecs):
            cache[f"q{r['id']}"] = v
        with open(EMB_CACHE, "w") as f:
            json.dump(cache, f)
    for r in qs:
        scored.append((r, cosine(query_vec, cache[f"q{r['id']}"])))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [r for r, _ in scored[:k]], cache


RERANK_PROMPT = """你是面试官。面试场景意图：{query}

以下是候选面试题，请选出与意图**最相关**的 {n} 道（相关性 = 考察点与意图一致；宁可选窄不选宽）：
{items}

输出格式（严格 JSON）：
{{"selected": [题号, 题号, 题号]}}"""

SCORE_PROMPT = """你是面试官。面试场景意图：{query}

抽题系统抽出了以下 {n} 道题。请为每道题与意图的**相关性**打分（0-5 分）：
- 5 = 完全对应意图的考察点
- 3 = 相关但考察点有偏差
- 1 = 勉强相关（主题沾边但考察点不同）
- 0 = 完全无关

{items}

输出格式（严格 JSON）：
[{{"id": 题号, "score": 分数, "reason": "一句话原因"}}, ...]"""


async def llm_call(prompt, system_msg="你是一个资深面试官。"):
    """走统一 LLM 封装（app.services.llm，用户主账号配置）。"""
    from app.services.llm import _call_llm_with_retry
    return await _call_llm_with_retry(
        prompt, system_msg=system_msg, response_format={"type": "json_object"},
        user_id=1, model=None,
    )


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
    """兼容 LLM 打分输出的多种包裹形态（裸数组 / {"scores":[...]} / 单对象 / 碎片）"""
    data = parse_json(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("scores", "results", "result", "items"):
            v = data.get(k)
            if isinstance(v, list):
                return v
        if "score" in data:
            return [data]
    # 整体解析失败 → 逐个提取 {"id":..,"score":..} 对象碎片恢复
    out = []
    for m in re.finditer(r"\{[^{}]*\}", raw or ""):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and "score" in obj:
                out.append(obj)
        except (json.JSONDecodeError, TypeError):
            continue
    return out


async def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    t0 = time.monotonic()
    qs = load_questions()
    print(f"[eval] 题库 {len(qs)} 题")

    # 1) 场景查询向量 + 题库向量
    cache = {}
    if os.path.exists(EMB_CACHE):
        cache = json.load(open(EMB_CACHE))
    query_vecs = {}
    for s in SCENARIOS:
        query_vecs[s["name"]] = get_emb(s["query"], cache, f"sc_{s['name']}")
    for r in qs:
        if f"q{r['id']}" not in cache:
            pass
    # 批量嵌入题库（一次性）
    todo = [r for r in qs if f"q{r['id']}" not in cache]
    for i in range(0, len(todo), EMB_BATCH):
        chunk = todo[i:i + EMB_BATCH]
        vecs = embed_batch([f"{r['question']} {r['cat2'] or ''} {r['tags'] or ''}" for r in chunk])
        for r, v in zip(chunk, vecs):
            cache[f"q{r['id']}"] = v
        json.dump(cache, open(EMB_CACHE, "w"))

    lines = [f"# 抽题工具评估报告", "", f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}", "",
             f"- 题库: {len(qs)} 题（活跃）", f"- 场景: {len(SCENARIOS)} 个", ""]
    summary = []

    for s in SCENARIOS:
        name = s["name"]
        print(f"[eval] === 场景: {name} ===")
        # 方案 A：现状
        cands_a, picked_a = sql_draw(qs, s)
        # 方案 B：embedding top-20
        query_vec = query_vecs[name]
        scored_all = sorted(
            ((r, cosine(query_vec, cache[f"q{r['id']}"])) for r in qs),
            key=lambda x: x[1], reverse=True,
        )
        top20 = [r for r, _ in scored_all[:20]]
        top3_b = [r for r, _ in scored_all[:3]]
        # 方案 C：LLM rerank
        items_c = "\n".join(f"{r['id']}. {r['question']}" for r in top20)
        raw = await llm_call(RERANK_PROMPT.format(query=s["query"], n=3, items=items_c))
        data = parse_json(raw) or {}
        if isinstance(data, dict):
            for k in ("result", "results"):
                v = data.get(k)
                if isinstance(v, dict) and "selected" in v:
                    data = v
                    break
        sel_ids = data.get("selected", []) if isinstance(data, dict) else []
        picked_c = [next(r for r in top20 if r["id"] == int(i)) for i in sel_ids if any(r["id"] == int(i) for r in top20)]

        def fmt(items):
            return "\n".join(f"{r['id']}. {r['question']}（cat2={r['cat2']}）" for r in items)

        # LLM 打分：三个方案各一次
        scores = {}
        for tag, items in [("A_现状SQL", picked_a), ("B_embedding", top3_b), ("C_RAG_LLM", picked_c)]:
            if not items:
                scores[tag] = []
                continue
            raw = await llm_call(SCORE_PROMPT.format(query=s["query"], n=len(items), items=fmt(items)))
            scores[tag] = norm_score_list(raw)

        avg = {tag: (sum(x.get("score", 0) for x in v) / len(v) if v else 0.0) for tag, v in scores.items()}
        summary.append((name, len(cands_a), len(top20), avg))

        lines += [
            f"## {name}", "",
            f"- 意图: {s['query']}",
            f"- 方案A 候选池规模: **{len(cands_a)}** 题（SQL LIKE 过滤）",
            f"- 方案B top-20 与方案A 候选重叠: **{len(set(r['id'] for r in top20) & set(r['id'] for r in cands_a))}** 题",
            "",
            "### 抽取结果与相关性打分（0-5）",
            "",
            "| 方案 | 抽到题目 | 平均分 |",
            "|------|---------|--------|",
        ]
        for tag, items in [("A_现状SQL", picked_a), ("B_embedding", top3_b), ("C_RAG_LLM", picked_c)]:
            if not items:
                lines.append(f"| {tag} | （空） | - |")
                continue
            sc = {x.get("id"): x for x in scores.get(tag, [])}
            detail = "；".join(f"{r['id']}({sc.get(r['id'], {}).get('score', '?')}分)" for r in items)
            lines.append(f"| {tag} | {detail} | {avg.get(tag, 0):.1f} |")
        lines.append("")
        print(f"  A={avg.get('A_现状SQL', 0):.1f} B={avg.get('B_embedding', 0):.1f} C={avg.get('C_RAG_LLM', 0):.1f} (候选A={len(cands_a)}, top20重叠={len(set(r['id'] for r in top20) & set(r['id'] for r in cands_a))})")

    lines += ["## 汇总", "", "| 场景 | 方案A候选 | A均分 | B均分 | C均分 |", "|------|----------|-------|-------|-------|"]
    for name, ca, tb, avg in summary:
        lines.append(f"| {name} | {ca} | {avg.get('A_现状SQL', 0):.1f} | {avg.get('B_embedding', 0):.1f} | {avg.get('C_RAG_LLM', 0):.1f} |")
    path = os.path.join(REPORT_DIR, "draw_questions_eval.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[eval] 报告已写入 {path}，耗时 {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
