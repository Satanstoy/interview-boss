"""cluster 语义标签摘要记忆 — 实验模块（独立于生产聚类代码）。

实验思路（对齐 LLM-MemCluster / Lifecycle-Aware Clustering）：
为每个已有 cluster 维护 LLM 生成的语义标签摘要，新题按"聚类转分类"方式
增量分配，绕开 embedding 几何距离依赖。评估通过 evaluate.py 跑全流程。
"""
import json
import logging
import re

from app.services.clustering.clusterer import _normalize_question_text
from app.services.llm import _call_llm_with_retry

from app.services.clustering.experiments.prompts import CLUSTER_LABEL_PROMPT

logger = logging.getLogger("interview-boss")

LABELS_PER_BATCH = 20


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
    tie-break：规范化文本相同的 cluster 归到 id 最小者；substring 按
    dict 插入顺序（clusters 由 load_cluster_data 按 id 升序加载）取第一个命中。
    Returns: {singleton_qb_id: cluster_qb_id}
    """
    norm_clusters: dict[str, int] = {}
    for c in clusters:
        k = _normalize_question_text(c["question"])
        if k and (k not in norm_clusters or c["qb_id"] < norm_clusters[k]):
            norm_clusters[k] = c["qb_id"]
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


async def generate_cluster_labels(clusters: list[dict], user_id: int | None = None) -> dict[int, str]:
    """为每个 cluster 生成语义标签摘要。

    Returns: {cluster_qb_id: label_text}
    任何 cluster 失败都回退为代表题文本，保证 100% 覆盖率。
    """
    labels: dict[int, str] = {}
    for i in range(0, len(clusters), LABELS_PER_BATCH):
        batch = clusters[i : i + LABELS_PER_BATCH]
        batch_ids = {c["qb_id"] for c in batch}
        lines = "\n".join(
            f"{c['qb_id']} | {c['question']} | " + " | ".join(c["oq"][:6])
            for c in batch
        )
        prompt = CLUSTER_LABEL_PROMPT.format(qb_id="{qb_id}", questions=lines)
        try:
            raw = await _call_llm_with_retry(
                prompt,
                system_msg="你是一个面试题题库管理专家。",
                response_format={"type": "json_object"},
                user_id=user_id,
                model=None,
            )
            parsed = _extract_json_array(raw)
            for item in parsed:
                qid_raw = item.get("qb_id")
                label = (item.get("label") or "").strip()
                if qid_raw is None or not label:
                    continue
                try:
                    qid = int(qid_raw)
                except (ValueError, TypeError):
                    continue
                if qid not in batch_ids:  # 过滤幻觉 id，避免流入 Task 4 prompt
                    continue
                labels[qid] = label
        except Exception as e:
            logger.warning(f"[experiment] 标签摘要生成失败，回退代表题: {e}")
        for c in batch:
            labels.setdefault(c["qb_id"], c["question"][:40])
    return labels


def _extract_json_array(raw: str) -> list[dict]:
    """从 LLM 输出提取 JSON 数组（容忍 markdown 代码块包裹）"""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            # 兼容 {"clusters": [...]} 包裹
            data = data.get("clusters") or data.get("items") or []
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
                return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                return []
        return []
