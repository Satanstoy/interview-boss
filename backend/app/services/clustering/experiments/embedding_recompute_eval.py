"""题库 embedding 全量重算（bge-m3）+ search_questions 效果实测。

阶段 0（重算前基线）：hash fallback 编码查询 → DB 存量向量检索（模拟当前生产行为）
阶段 1：bge-m3 全量重算 320 题 → 写 DB（embedding/embedding_model/embedding_dim）
阶段 2：bge-m3 编码查询 → 检索对比
阶段 3：mimo 评分两种检索的 top-5 → 报告

运行（挂载源码 + 生产 DB）：
docker compose run --rm -v $PWD/backend:/app/backend backend python -m app.services.clustering.experiments.embedding_recompute_eval
输出：backend/experiment_reports/embedding_recompute_eval.md
"""
import asyncio
import json
import os
import sqlite3
import struct
import time
import urllib.request

from app.db.connection import get_db_connection

REPORT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "experiment_reports"))
EMB_URL = "https://api.siliconflow.cn/v1/embeddings"
# API key 从环境变量读取，禁止硬编码（tech-audit-2026-08-13 D4-1）
EMB_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
if not EMB_KEY:
    raise SystemExit("请设置环境变量 SILICONFLOW_API_KEY（SiliconFlow 平台密钥）后再运行本实验脚本")
EMB_MODEL = "BAAI/bge-m3"
BATCH = 32

QUERIES = [
    "缓存穿透、击穿、雪崩怎么解决",
    "Java 线程池的核心参数和工作原理",
    "MySQL 索引为什么用 B+树",
    "Redis 分布式锁怎么实现，有什么问题",
    "JVM 内存模型和 GC 机制",
    "秒杀系统的架构设计，如何防止超卖",
]


def load_questions():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, question, cat1, cat2, tags, embedding FROM question_bank "
        "WHERE deleted_at IS NULL ORDER BY id"
    ).fetchall()
    out = []
    for r in rows:
        out.append({"id": r["id"], "question": r["question"], "cat2": r["cat2"] or "",
                    "text": f"{r['question']} {r['cat2'] or ''} {r['tags'] or ''}"})
    return out


def parse_embedding_blob(blob: bytes) -> list[float]:
    """DB 存量向量：float32 little-endian bytes → list"""
    if not blob:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def embed_bgem3(texts):
    req = urllib.request.Request(
        EMB_URL,
        data=json.dumps({"model": EMB_MODEL, "input": texts, "encoding_format": "float"}).encode(),
        headers={"Authorization": f"Bearer {EMB_KEY}", "Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
            out = [None] * len(texts)
            for d in data["data"]:
                out[d["index"]] = d["embedding"]
            return out
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  embed 重试 {attempt + 1}: {e}")
            time.sleep(2)


def hash_query_vector(query: str) -> list[float]:
    """复刻 _encode_texts_hash 的 512 维伪随机向量（token-level blake2b）"""
    import hashlib

    tokens = query.replace("，", " ").replace("、", " ").replace("。", " ").split()
    dim = 512
    vec = [0.0] * dim
    for tok in tokens:
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % dim
        val = (int.from_bytes(digest[4:], "little") / (2**32)) - 0.5
        vec[idx] += val
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / norm for x in vec]


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb + 1e-9)


async def llm_call(prompt):
    from app.services.llm import _call_llm_with_retry
    return await _call_llm_with_retry(
        prompt, system_msg="你是一个资深面试官。", response_format=None, user_id=1, model=None,
    )


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
    """兼容 LLM 打分输出的多种包裹形态（裸数组 / 对象包裹 / 单对象 / 碎片）"""
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


async def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    t0 = time.monotonic()
    qs = load_questions()
    print(f"[recompute] 题库 {len(qs)} 题")

    # 读取 DB 存量向量（onnx 512 维）
    conn = get_db_connection()
    rows = conn.execute("SELECT id, embedding FROM question_bank WHERE deleted_at IS NULL").fetchall()
    old_vec = {r["id"]: parse_embedding_blob(r["embedding"]) for r in rows}
    dims = {len(v) for v in old_vec.values() if v}
    print(f"[recompute] 存量向量维度: {dims}")

    # ---- 阶段 0：hash 基线（模拟当前生产查询编码）----
    hash_q = {q: hash_query_vector(q) for q in QUERIES}

    # ---- 阶段 1：bge-m3 重算题库（检测已重算则跳过）----
    already = conn.execute(
        "SELECT COUNT(*) FROM question_bank WHERE deleted_at IS NULL AND embedding_model = ?",
        (EMB_MODEL,),
    ).fetchone()[0]
    if already == len(qs):
        print(f"[recompute] 检测到已是 {EMB_MODEL}，跳过重算（读取 DB 向量）")
        new_vec = {}
        for r in conn.execute(
            "SELECT id, embedding FROM question_bank WHERE deleted_at IS NULL"
        ).fetchall():
            new_vec[r["id"]] = parse_embedding_blob(r["embedding"])
    else:
        print("[recompute] bge-m3 编码题库...")
        new_vec = {}
        for i in range(0, len(qs), BATCH):
            chunk = qs[i:i + BATCH]
            vecs = embed_bgem3([x["text"] for x in chunk])
            for x, v in zip(chunk, vecs):
                new_vec[x["id"]] = v
            print(f"  编码 {i + len(chunk)}/{len(qs)}")
        bge_q = {q: v for q, v in zip(QUERIES, embed_bgem3(QUERIES))}

        # ---- 阶段 2：写 DB ----
        conn2 = get_db_connection()
        with conn2:
            for x in qs:
                v = new_vec[x["id"]]
                blob = struct.pack(f"<{len(v)}f", *v)
                conn2.execute(
                    "UPDATE question_bank SET embedding = ?, embedding_model = ?, embedding_dim = ? WHERE id = ?",
                    (blob, EMB_MODEL, len(v), x["id"]),
                )
        print(f"[recompute] 已写入 DB（{EMB_MODEL}, {len(new_vec[qs[0]['id']])} 维）")

    # 查询向量（两种方案共用 bge-m3 编码查询；hash 基线用 hash 编码）
    bge_q = {q: v for q, v in zip(QUERIES, embed_bgem3(QUERIES))}

    # ---- 阶段 3：检索 + 打分 ----
    lines = [f"# 题库 embedding 重算评估：hash 基线 vs bge-m3", "",
             f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}", "",
             f"- 题库: {len(qs)} 题", f"- 存量维度: {dims}", f"- 重算后: bge-m3 {len(new_vec[qs[0]['id']])} 维", ""]
    summary = []
    for q in QUERIES:
        # hash 检索（用存量向量）
        scored_h = sorted(((x, cosine(hash_q[q], old_vec.get(x["id"], []))) for x in qs),
                          key=lambda t: t[1], reverse=True)[:5]
        scored_b = sorted(((x, cosine(bge_q[q], new_vec[x["id"]])) for x in qs),
                          key=lambda t: t[1], reverse=True)[:5]

        def fmt(items):
            return "\n".join(f"{x['id']}. {x['question']}（cat2={x['cat2']}）" for x, s in items)

        async def score(tag, items):
            raw = await llm_call(SCORE_PROMPT.format(query=q, items=fmt(items)))
            sc_list = norm_score_list(raw)
            sc = {}
            for x in sc_list:
                try:
                    sc[int(x.get("id"))] = x.get("score", 0)
                except (TypeError, ValueError):
                    continue
            avg = sum(sc.get(x["id"], 0) for x, _ in items) / len(items) if items else 0.0
            return tag, avg, sc

        s_h, s_b = await asyncio.gather(score("hash基线", scored_h), score("bge-m3", scored_b))
        summary.append((q, s_h, s_b))
        print(f"[recompute] {q[:16]}... hash={s_h[1]:.1f} bge-m3={s_b[1]:.1f}")

        lines += [f"## {q}", "",
                  "| 方案 | 召回 top-5 | 平均分 |",
                  "|------|----------|--------|"]
        for tag, avg, sc, items in ((s_h[0], s_h[1], s_h[2], scored_h), (s_b[0], s_b[1], s_b[2], scored_b)):
            detail = "；".join(f"{x['id']}({sc.get(x['id'], '?')}分)" for x, _ in items)
            lines.append(f"| {tag} | {detail} | {avg:.1f} |")
        lines.append("")

    lines += ["## 汇总", "", "| 查询 | hash基线 | bge-m3 |", "|------|---------|--------|"]
    for q, s_h, s_b in summary:
        lines.append(f"| {q[:20]} | {s_h[1]:.1f} | {s_b[1]:.1f} |")
    lines += [f"| **平均** | **{sum(s[1] for _, s, _ in summary) / len(summary):.1f}** | "
              f"**{sum(s[1] for _, _, s in summary) / len(summary):.1f}** |", ""]
    path = os.path.join(REPORT_DIR, "embedding_recompute_eval.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[recompute] 报告已写入 {path}，耗时 {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
