"""cluster 语义标签摘要记忆 — 实验模块（独立于生产聚类代码）。

实验思路（对齐 LLM-MemCluster / Lifecycle-Aware Clustering）：
为每个已有 cluster 维护 LLM 生成的语义标签摘要，新题按"聚类转分类"方式
增量分配，绕开 embedding 几何距离依赖。评估通过 evaluate.py 跑全流程。
"""
import json
import logging

from app.services.clustering.clusterer import _normalize_question_text

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
        if not isinstance(oq, list):
            oq = []
        oq = [str(q).strip() for q in oq if str(q).strip()]
        item["oq"] = oq
        if item["freq"] > 1:
            clusters.append(item)
        else:
            singletons.append(item)
    return clusters, singletons


def text_prefilter(singletons: list[dict], clusters: list[dict]) -> dict[int, int]:
    """文本级确定性分配：孤岛题 → 已有 cluster。

    匹配规则（按优先级）：
    1. 规范化文本精确相等
    2. 一方包含另一方（长度 >= 8 时）
    Returns: {singleton_qb_id: cluster_qb_id}
    """
    norm_clusters = {_normalize_question_text(c["question"]): c["qb_id"] for c in clusters}
    matches: dict[int, int] = {}
    for s in singletons:
        s_norm = _normalize_question_text(s["question"])
        if not s_norm:
            continue
        if s_norm in norm_clusters:
            matches[s["qb_id"]] = norm_clusters[s_norm]
            continue
        for c_norm, c_qb_id in norm_clusters.items():
            if len(s_norm) >= 8 and len(c_norm) >= 8 and (
                s_norm in c_norm or c_norm in s_norm
            ):
                matches[s["qb_id"]] = c_qb_id
                break
    return matches
