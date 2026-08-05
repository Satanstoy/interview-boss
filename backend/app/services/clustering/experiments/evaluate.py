"""聚类实验评估入口：生产数据全流程 + Markdown 报告。

运行：docker compose run --rm backend python -m app.services.clustering.experiments.evaluate [--round N]
输出：backend/experiment_reports/round<N>.md
"""
import argparse
import asyncio
import logging
import os
import time

from app.db.connection import get_db_connection

logging.basicConfig(level=logging.INFO)

REPORT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "experiment_reports")
)


async def main(round_no: int):
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
    labels = await generate_cluster_labels(clusters, user_id=None)
    label_failback = sum(1 for c in clusters if labels.get(c["qb_id"]) == c["question"][:40])

    # 3) LLM 增量分配（跳过已被文本预筛命中的）
    results = await assign_singletons(singletons, clusters, labels, user_id=None)

    llm_assign = {
        qid: r for qid, r in results.items()
        if qid not in pre_matches and r["match"] is not None
    }
    new_island = {
        qid: r for qid, r in results.items() if r["match"] is None
    }

    elapsed = time.monotonic() - t0
    _write_report(round_no, conn, stats, pre_matches, labels, results, llm_assign, new_island, label_failback, elapsed)
    print(f"[experiment] 完成: 已知cluster={stats['known_clusters']} 孤岛={stats['singletons']} "
          f"确定性合并={len(pre_matches)} LLM合并={len(llm_assign)} 维持孤岛={len(new_island)} "
          f"耗时={elapsed:.1f}s -> {REPORT_DIR}/round{round_no}.md")


def _write_report(round_no, conn, stats, pre_matches, labels, results, llm_assign, new_island, label_failback, elapsed):
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
        f"- 孤岛率变化: {stats['singletons']} → {len(new_island)}（-{(1 - len(new_island) / max(stats['singletons'], 1)) * 100:.1f}%）",
        "",
        "## 抽样核验（LLM 合并前 25 条）",
        "",
    ]
    for i, (qid, r) in enumerate(sorted(llm_assign.items(), key=lambda kv: kv[0])[:25], 1):
        target = _q_by_id(conn, r["match"])
        src = _q_by_id(conn, qid)
        lines += [
            f"### {i}. 孤岛题 {qid} → 聚类 {r['match']}",
            f"- 孤岛题: {src}",
            f"- 目标代表题: {target}",
            f"- 原因: {r['reason']}",
            "",
        ]
    lines += ["## 标签摘要样本（前 10 个聚类）", ""]
    for cid, label in sorted(labels.items())[:10]:
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


def _q_by_id(conn, qid: int) -> str:
    row = conn.execute("SELECT question FROM question_bank WHERE id = ?", (qid,)).fetchone()
    return row["question"] if row else f"(缺失 {qid})"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(main(args.round))
