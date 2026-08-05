"""cluster 语义标签摘要记忆 — 实验模块（独立于生产聚类代码）。

实验思路（对齐 LLM-MemCluster / Lifecycle-Aware Clustering）：
为每个已有 cluster 维护 LLM 生成的语义标签摘要，新题按"聚类转分类"方式
增量分配，绕开 embedding 几何距离依赖。评估通过 evaluate.py 跑全流程。
"""
import json
import logging

logger = logging.getLogger("interview-boss")


def load_cluster_data(conn) -> tuple[list[dict], list[dict]]:
    """加载实验数据。

    Returns:
        (clusters, singletons):
        - clusters: frequency > 1 的已知 cluster，含代表题与 original_questions
        - singletons: frequency == 1 的孤岛题（模拟待聚合的新题）
    """
    rows = conn.execute(
        "SELECT id, question, cat1, cat2, frequency, original_questions "
        "FROM question_bank "
        "WHERE deleted_at IS NULL "
        "ORDER BY id"
    ).fetchall()
    clusters, singletons = [], []
    for r in rows:
        item = {
            "qb_id": r["id"],
            "question": r["question"],
            "cat1": r["cat1"] or "",
            "cat2": r["cat2"] or "",
            "freq": r["frequency"] or 1,
        }
        oq_raw = r["original_questions"] or "[]"
        try:
            oq = json.loads(oq_raw) if isinstance(oq_raw, str) else []
        except (json.JSONDecodeError, TypeError):
            oq = []
        oq = [str(q).strip() for q in oq if str(q).strip()]
        item["oq"] = oq
        if item["freq"] > 1:
            clusters.append(item)
        else:
            singletons.append(item)
    return clusters, singletons
