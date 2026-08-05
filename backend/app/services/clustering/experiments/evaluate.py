"""聚类实验评估入口：生产数据全流程 + Markdown 报告。

运行：docker compose run --rm backend python -m app.services.clustering.experiments.evaluate [--round N] [--user-id 1]
输出：backend/experiment_reports/round<N>.md
"""
import argparse
import asyncio
import logging
import os
import random
import time

from app.db.connection import get_db_connection

logging.basicConfig(level=logging.INFO)

REPORT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "experiment_reports")
)

SAMPLE_LLM_ASSIGNS = 25
SAMPLE_ISLANDS = 15
SAMPLE_LABELS = 10
_SAMPLE_SEED = 42


async def main(round_no: int, user_id: int | None = 1):
    os.makedirs(REPORT_DIR, exist_ok=True)
    conn = get_db_connection()
    t0 = time.monotonic()

    from app.services.clustering.experiments.memory_labels import (
        load_cluster_data,
        generate_cluster_labels,
        assign_singletons,
        text_prefilter,
    )

    clusters, singletons = load_cluster_data(conn)
    stats = {
        "total_qb": len(clusters) + len(singletons),
        "known_clusters": len(clusters),
        "singletons": len(singletons),
    }

    # 1) 文本预筛（零成本确定性分配）
    pre_matches = text_prefilter(singletons, clusters)

    # 2) 标签摘要生成
    labels = await generate_cluster_labels(clusters, user_id=user_id)
    label_failback = sum(1 for c in clusters if labels.get(c["qb_id"]) == c["question"][:40])

    # 3) LLM 增量分配（跳过已被文本预筛命中的）
    results = await assign_singletons(singletons, clusters, labels, user_id=user_id)

    llm_assign = {
        qid: r for qid, r in results.items()
        if qid not in pre_matches and r["match"] is not None
    }
    llm_failed = {
        qid: r for qid, r in results.items()
        if qid not in pre_matches and r["reason"].startswith("LLM 调用失败")
    }
    new_island = {
        qid: r for qid, r in results.items()
        if qid not in pre_matches and r["match"] is None and qid not in llm_failed
    }
    cluster_oq = {c["qb_id"]: c["oq"] for c in clusters}

    elapsed = time.monotonic() - t0
    _write_report(round_no, conn, stats, pre_matches, labels, results, llm_assign,
                  llm_failed, new_island, cluster_oq, label_failback, elapsed)
    print(f"[experiment] 完成: 已知cluster={stats['known_clusters']} 孤岛={stats['singletons']} "
          f"确定性合并={len(pre_matches)} LLM合并={len(llm_assign)} 维持孤岛={len(new_island)} "
          f"耗时={elapsed:.1f}s -> {REPORT_DIR}/round{round_no}.md")


def _write_report(round_no, conn, stats, pre_matches, labels, results, llm_assign,
                  llm_failed, new_island, cluster_oq, label_failback, elapsed):
    lines = [
        f"# 聚类实验报告 round {round_no}",
        "",
        f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}  **耗时**: {elapsed:.1f}s",
        "",
        "## 数据概览",
        "",
        f"- 题库总数: {stats['total_qb']}",
        f"- 已知聚类（frequency>1）: {stats['known_clusters']}",
        f"- 孤岛题（frequency=1）: {stats['singletons']}",
        "",
        "## 分配结果",
        "",
        f"- 文本预筛确定性合并: **{len(pre_matches)}**",
        f"- LLM 判断合并到已有聚类: **{len(llm_assign)}**",
        f"- 维持独立新题: **{len(new_island)}**",
        f"- LLM 调用失败: **{len(llm_failed)}** 条（未计入维持孤岛）",
        f"- 孤岛率变化: {stats['singletons']} → {len(new_island)}（-{(1 - len(new_island) / max(stats['singletons'], 1)) * 100:.1f}%）",
        "",
        f"## 抽样核验（LLM 合并前 {SAMPLE_LLM_ASSIGNS} 条）",
        "",
    ]
    for i, (qid, r) in enumerate(_seeded_sample(llm_assign.items(), SAMPLE_LLM_ASSIGNS), 1):
        target = _q_by_id(conn, r["match"])
        src = _q_by_id(conn, qid)
        target_oq = " | ".join(cluster_oq.get(r["match"], [])[:3])
        lines += [
            f"### {i}. 孤岛题 {qid} → 聚类 {r['match']}",
            f"- 孤岛题: {src}",
            f"- 目标代表题: {target}",
            f"- 目标聚类原始题面: {target_oq}",
            f"- 原因: {r['reason']}",
            "",
        ]
    lines += [f"## 维持孤岛样本（前 {SAMPLE_ISLANDS} 条）", ""]
    for qid, r in _seeded_sample(new_island.items(), SAMPLE_ISLANDS):
        src = _q_by_id(conn, qid)
        lines += [
            f"- 孤岛题 {qid}: {src}",
            f"  - 原因: {r['reason']}",
            "",
        ]
    lines += [f"## 标签摘要样本（前 {SAMPLE_LABELS} 个聚类）", ""]
    for cid, label in sorted(labels.items())[:SAMPLE_LABELS]:
        lines.append(f"- cluster {cid}: {label}")
    lines.append("")
    lines += ["## 成本估算", ""]
    lines += [
        f"- 标签摘要 LLM 调用: {max(1, (stats['known_clusters'] + 19) // 20)} 次",
        f"- 增量分配 LLM 调用: {sum(1 for qid in results if qid not in pre_matches)} 次",
        f"- 摘要回退代表题（LLM 失败）: {label_failback} 个",
        "",
    ]
    path = os.path.join(REPORT_DIR, f"round{round_no}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[experiment] 报告已写入 {path}")


def _seeded_sample(items, k: int):
    """固定种子随机抽样，保证同一 round 报告可复现"""
    sample_items = sorted(items)
    random.Random(_SAMPLE_SEED).shuffle(sample_items)
    return sample_items[:k]


def _q_by_id(conn, qid: int) -> str:
    row = conn.execute("SELECT question FROM question_bank WHERE id = ?", (qid,)).fetchone()
    return row["question"] if row else f"(缺失 {qid})"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, default=1)
    parser.add_argument("--user-id", type=int, default=1, help="实验使用的 LLM 配置用户（user_llm_config 表，默认 1=主账号）")
    args = parser.parse_args()
    asyncio.run(main(args.round, args.user_id))
