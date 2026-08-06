"""漏合并复核：找出 round N 中被判"维持孤岛"的题里可能漏合并的候选。

方法：
1. 从 round{N}_results.json 读中间结果（无缓存则重新生成标签）
2. 对每个维持孤岛题，与全部聚类标签做字符级 Jaccard 相似度预筛
3. 相似度 > 阈值的候选对，用 LLM 宽松复核："这两道题是否应视为同一道面试题"
4. 输出"可疑漏合并"清单 + 全部候选对统计

运行：docker compose run --rm -v $PWD/backend:/app/backend backend python -m app.services.clustering.experiments.review_islands --round 1 --user-id 1
输出：backend/experiment_reports/round<N>_islands_review.md
"""
import argparse
import asyncio
import json
import logging
import os
import time

from app.db.connection import get_db_connection

logging.basicConfig(level=logging.INFO)

REPORT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "experiment_reports")
)

SIM_THRESHOLD = 0.30
TOP_CANDIDATES = 3

ISLAND_REVIEW_PROMPT = """你是面试题去重专家。下面有两道面试题，请判断它们**是否应该视为同一道面试题**（合并到同一个聚类）。

合并标准：表述不同但考察点完全相同（如"怎样做限流" vs "限流方案有哪些"）。
不合并标准：
- 考察点不同的（如"TCP 三次握手" vs "IO 多路复用"、"缓存使用场景" vs "缓存穿透击穿怎么解决"）
- 主题相近但问题不同的（如"Redis 数据结构有哪些" vs "Redis 为什么快"）
- 具体算法题 vs 口述思路（如"合并两个有序链表" vs "口述算法题的解题思路"）

【题目 A】
{question_a}

【题目 B（已有聚类标签）】
{label} | {question_b}

输出格式（严格 JSON，不要输出其他内容）：
{{"same": true 或 false, "reason": "一句话原因"}}"""


def _load_results(round_no: int) -> dict:
    path = os.path.join(REPORT_DIR, f"round{round_no}_results.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def jaccard_sim(a: str, b: str) -> float:
    """字符级 Jaccard 相似度（中文题面关键词重叠检测，免费预筛）"""
    set_a, set_b = set(a), set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def find_candidates(singleton_q: str, labels: dict[int, str]) -> list[tuple[int, str, float]]:
    """对孤岛题找出 top-N 相似标签候选（含相似度）"""
    scored = []
    for qid, label in labels.items():
        sim = jaccard_sim(singleton_q, label)
        if sim >= SIM_THRESHOLD:
            scored.append((qid, label, sim))
    scored.sort(key=lambda t: t[2], reverse=True)
    return scored[:TOP_CANDIDATES]


async def main(round_no: int, user_id: int | None):
    os.makedirs(REPORT_DIR, exist_ok=True)
    conn = get_db_connection()
    t0 = time.monotonic()

    from app.services.clustering.experiments.memory_labels import (
        load_cluster_data,
        generate_cluster_labels,
    )
    from app.services.llm import _call_llm_with_retry

    clusters, singletons = load_cluster_data(conn)

    # 1) 标签：优先读缓存，无则重新生成
    results_file = os.path.join(REPORT_DIR, f"round{round_no}_results.json")
    if os.path.exists(results_file):
        saved = _load_results(round_no)
        labels = {int(k): v for k, v in saved["labels"].items()}
        saved_results = {int(k): v for k, v in saved["results"].items()}
        print(f"[review] 从 {results_file} 读取标签 {len(labels)} 个、分配结果 {len(saved_results)} 条")
    else:
        labels = await generate_cluster_labels(clusters, user_id=user_id)
        saved_results = None
        print(f"[review] 无缓存，重新生成标签 {len(labels)} 个")

    # 2) 维持孤岛题（排除预筛命中和 LLM 合并的）
    if saved_results is not None:
        island_ids = {
            int(qid) for qid, r in saved_results.items()
            if r["match"] is None and not r["reason"].startswith("LLM 调用失败")
        }
    else:
        # 无缓存时只能全部孤岛（不准确，仅兜底）
        island_ids = {s["qb_id"] for s in singletons}
    islands = [s for s in singletons if s["qb_id"] in island_ids]
    print(f"[review] 待复核孤岛题 {len(islands)} 条")

    # 3) 相似度预筛 → 候选对
    candidates = []  # (singleton, [(qid, label, sim)])
    for s in islands:
        cands = find_candidates(s["question"], labels)
        if cands:
            candidates.append((s, cands))
    total_pairs = sum(len(c) for _, c in candidates)
    print(f"[review] 相似度预筛候选: {len(candidates)} 条孤岛题 / {total_pairs} 对")

    # 4) LLM 复核候选对
    reviewed = []  # (singleton, qid, label, sim, same, reason)
    for s, cands in candidates:
        for qid, label, sim in cands:
            question_b = next((c["question"] for c in clusters if c["qb_id"] == qid), "")
            prompt = ISLAND_REVIEW_PROMPT.format(
                question_a=s["question"], label=label, question_b=question_b
            )
            try:
                raw = await _call_llm_with_retry(
                    prompt,
                    system_msg="你是一个面试题去重专家。",
                    response_format=None,
                    user_id=user_id,
                )
                data = _extract_json_object(raw)
                same = bool(data.get("same"))
                reason = str(data.get("reason", ""))[:200]
            except Exception as e:
                same, reason = False, f"LLM 调用失败: {e}"[:200]
            reviewed.append((s, qid, label, sim, same, reason))

    elapsed = time.monotonic() - t0
    _write_report(round_no, conn, reviewed, len(islands), total_pairs, elapsed)
    print(f"[review] 完成: 复核 {len(reviewed)} 对, 判定应合并 {sum(1 for r in reviewed if r[4])} 对, "
          f"耗时 {elapsed:.1f}s -> {REPORT_DIR}/round{round_no}_islands_review.md")


def _write_report(round_no, conn, reviewed, island_count, total_pairs, elapsed):
    same_pairs = [r for r in reviewed if r[4]]
    lines = [
        f"# 漏合并复核报告 round {round_no}",
        "",
        f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}  **耗时**: {elapsed:.1f}s",
        "",
        "## 复核概览",
        "",
        f"- 维持孤岛题: {island_count}",
        f"- 相似度预筛候选对: {total_pairs}",
        f"- LLM 复核判定**应合并**: **{len(same_pairs)}** 对",
        "",
        "## 疑似漏合并清单（LLM 判定应合并）",
        "",
    ]
    for i, (s, qid, label, sim, same, reason) in enumerate(same_pairs, 1):
        src = _q_by_id(conn, s["qb_id"])
        target = _q_by_id(conn, qid)
        lines += [
            f"### {i}. 孤岛题 {s['qb_id']} → 聚类 {qid}（字符相似度 {sim:.2f}）",
            f"- 孤岛题: {src}",
            f"- 目标代表题: {target}",
            f"- 目标标签: {label}",
            f"- 复核原因: {reason}",
            "",
        ]
    lines += [f"## 候选对全量（{len(reviewed)} 对，按相似度降序）", ""]
    for s, qid, label, sim, same, reason in sorted(reviewed, key=lambda r: r[3], reverse=True):
        mark = "✅应合并" if same else "❌不合并"
        lines.append(
            f"- sim={sim:.2f} {mark} 孤岛{s['qb_id']} → 聚类{qid} [{label}]（{reason[:60]}）"
        )
    path = os.path.join(REPORT_DIR, f"round{round_no}_islands_review.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[review] 报告已写入 {path}")


def _q_by_id(conn, qid: int) -> str:
    row = conn.execute("SELECT question FROM question_bank WHERE id = ?", (qid,)).fetchone()
    return row["question"] if row else f"(缺失 {qid})"


def _extract_json_object(raw: str) -> dict:
    import re

    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, default=1)
    parser.add_argument("--user-id", type=int, default=1, help="实验使用的 LLM 配置用户（默认 1=主账号）")
    args = parser.parse_args()
    asyncio.run(main(args.round, args.user_id))
