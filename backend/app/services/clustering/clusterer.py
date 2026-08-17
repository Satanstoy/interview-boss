"""聚类引擎：内部聚类 + 三阶段聚类 V2"""

import asyncio
import logging
import re
from typing import List, Dict, Any

from app.core.config import (
    CLUSTER_MAX_CONCURRENCY,
    CLUSTER_MIN_SIMILARITY,
    CLUSTER_V2_SIM_THRESHOLD,
    CLUSTER_V2_FAISS_TOP_K,
)
from app.services.llm import _call_llm_with_retry, _extract_json
from app.services.clustering.prompts import CLUSTER_NEW_PROMPT

logger = logging.getLogger("interview-boss")

MAX_CONCURRENCY = CLUSTER_MAX_CONCURRENCY


def _normalize_question_text(text: str) -> str:
    """用于零成本精确命中的轻量文本标准化。"""
    text = (text or "").strip().lower()
    replacements = {
        "？": "?",
        "！": "!",
        "，": ",",
        "。": ".",
        "：": ":",
        "；": ";",
        "（": "(",
        "）": ")",
        "、": ",",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return re.sub(r"[\s\?？!！。.,，、:：;；]+", "", text)


def _format_new_questions(questions):
    return "\n".join(f"[{q['id']}] {q['question']}" for q in questions)


# ═══════════════════════════════════════════════════════════════
# 三阶段聚类 V2（embedding 预组织 + LLM 语义分组核心）
#
# 改进点（参考 ClusterFusion 2025 论文思路）：
#   1. 降低 embedding 阈值 0.75→0.55（粗筛不决策）
#   2. 按 cat2 分组聚类（跨领域不干扰）
#   3. 增大 FAISS top-K 5→10（提高传递性召回）
#   4. LLM 分组聚类替代简化批量验证（语义决策核心）
#   5. Union-find 传递性合并
# ═══════════════════════════════════════════════════════════════

_V2_GROUP_PROMPT = """你是面试题去重专家。以下是一个分类（{cat2}）下的面试题候选组，请将其中语义真正重复的题目分到同一组。

判断准则（核心）：
如果两道题考察的**核心知识点完全相同**，只是提问角度不同，才应该合并。

可以合并（同一技术点的不同提问角度）：
- "TCP为什么是三次握手" ≈ "TCP三次握手的作用"
- "介绍一下 ReAct" ≈ "ReAct 范式的原理是什么"
- "Redis 持久化方式有哪些？" ≈ "Redis 的 RDB 和 AOF 持久化有什么区别？"
- "volatile关键字的作用" ≈ "Java 中 volatile 有什么用"
- "上下文过长怎么办" ≈ "agent 怎么管理长上下文"

**坚决不合并（即使在同一分类下）：**
- 不同技术主题：「数据库优化」≠「项目介绍」≠「代码质量」
- 不同业务场景：「秒杀系统」≠「数据同步」≠「实习经历」
- 泛化问题：「项目介绍」「拷打项目」这种泛化问题不要和其他具体问题合并
- 只是都涉及"AI"但主题不同：「AI工具使用」≠「AI辅助编程质量」≠「AI前沿动态」

**⚠️ 特别注意：**
- 如果题目之间没有明确的知识点重叠，宁可不合并
- "其他"分类下的题目通常不相关，要特别谨慎
- 独立题目不需要输出，不要强行找关联

【待聚类的题目】（分类：{cat2}，共 {count} 题）：
{questions}

返回 JSON 格式：
{{"groups": [{{"ids": ["题号1", "题号2"], "representative": "表述最清晰的代表题"}}]}}
只返回 JSON。没有可合并的就返回 {{"groups": []}}"""

_V2_SIMILARITY_THRESHOLD = CLUSTER_V2_SIM_THRESHOLD
_V2_FAISS_TOP_K = CLUSTER_V2_FAISS_TOP_K


def _union_find(parent: dict, x):
    """Find with path compression."""
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union_merge(parent: dict, rank: dict, a, b):
    """Union by rank."""
    ra, rb = _union_find(parent, a), _union_find(parent, b)
    if ra == rb:
        return
    if rank[ra] < rank[rb]:
        ra, rb = rb, ra
    parent[rb] = ra
    if rank[ra] == rank[rb]:
        rank[ra] += 1


async def _cluster_unmatched(unmatched_questions, user_id):
    """将未匹配的新题进行内部聚类（带 embedding 门控）"""
    _min_cluster_sim = CLUSTER_MIN_SIMILARITY

    if len(unmatched_questions) < 2:
        return [
            {"ids": [str(q["id"])], "representative": q["question"], "items": [q]}
            for q in unmatched_questions
        ]

    exact_groups = {}
    for q in unmatched_questions:
        key = _normalize_question_text(q.get("question", ""))
        if key:
            exact_groups.setdefault(key, []).append(q)

    exact_clusters = []
    exact_clustered_ids = set()
    for group in exact_groups.values():
        if len(group) < 2:
            continue
        ids = [str(q["id"]) for q in group]
        exact_clustered_ids.update(ids)
        exact_clusters.append(
            {
                "ids": ids,
                "representative": max((q["question"] for q in group), key=len),
                "items": group,
            }
        )

    if exact_clusters:
        unmatched_questions = [
            q for q in unmatched_questions if str(q["id"]) not in exact_clustered_ids
        ]
        logger.info(f"    内部聚类精确文本命中: {len(exact_clusters)} 个聚类")
        if len(unmatched_questions) < 2:
            singles = [
                {"ids": [str(q["id"])], "representative": q["question"], "items": [q]}
                for q in unmatched_questions
            ]
            return exact_clusters + singles

    prompt = CLUSTER_NEW_PROMPT.format(
        unmatched_questions=_format_new_questions(unmatched_questions),
        count=len(unmatched_questions),
    )

    try:
        content = await _call_llm_with_retry(
            prompt, response_format={"type": "json_object"}, user_id=user_id
        )
        result = _extract_json(content)

        # 预编码所有题目 embedding（一次批量调用）
        try:
            from app.services import embedding_service
            import numpy as np

            texts = [q["question"] for q in unmatched_questions]
            embeddings = embedding_service.encode_texts(texts)
            # hash fallback 只适合测试/降级检索，不能否决 LLM 的语义聚类。
            if getattr(embedding_service, "_SESSION", None) is None:
                emb_map = {}
            else:
                emb_map = {
                    str(q["id"]): embeddings[i]
                    for i, q in enumerate(unmatched_questions)
                }
        except Exception:
            emb_map = {}

        clusters = list(exact_clusters)
        clustered_ids = set()

        for c in result.get("clusters", []):
            ids = [str(i) for i in c.get("ids", [])]
            if len(ids) >= 2:
                # embedding 门控：检查聚类内平均相似度
                if emb_map and all(i in emb_map for i in ids):
                    sims = []
                    for i in range(len(ids)):
                        for j in range(i + 1, len(ids)):
                            sim = float(np.dot(emb_map[ids[i]], emb_map[ids[j]]))
                            sims.append(sim)
                    avg_sim = sum(sims) / len(sims) if sims else 0
                    if avg_sim < _min_cluster_sim:
                        logger.info(
                            f"    embedding 门控拒绝: avg_sim={avg_sim:.3f} < {_min_cluster_sim}, "
                            f"拆散聚类 {ids}"
                        )
                        continue

                clustered_ids.update(ids)
                items = [q for q in unmatched_questions if str(q["id"]) in ids]
                rep = c.get("representative", "")
                if not rep or len(rep) < 3:
                    rep = max((q["question"] for q in items), key=len)
                clusters.append({"ids": ids, "representative": rep, "items": items})

        # 未被聚类的题目各自独立
        for q in unmatched_questions:
            if str(q["id"]) not in clustered_ids:
                clusters.append(
                    {
                        "ids": [str(q["id"])],
                        "representative": q["question"],
                        "items": [q],
                    }
                )

        logger.info(f"    内部聚类: {len(clusters)} 个结果（含独立题）")
        return clusters

    except Exception as e:
        logger.warning(f"    内部聚类失败: {e}")
        return [
            {"ids": [str(q["id"])], "representative": q["question"], "items": [q]}
            for q in unmatched_questions
        ]


async def cluster_three_stage_v2(
    questions: List[Dict],
    user_id=None,
    similarity_threshold: float = _V2_SIMILARITY_THRESHOLD,
) -> Dict[str, Any]:
    """三阶段聚类 V2：精确匹配 → Embedding 粗筛 → 按 cat2 LLM 语义分组。

    改进：
    - 降低 embedding 阈值（0.75→0.55），粗筛不决策
    - 按 cat2 分组，每组独立 LLM 聚类
    - 增大 FAISS top-K（5→10）
    - LLM 语义分组替代简化批量验证
    - Union-find 传递性合并

    Args:
        questions: [{"id", "question", "cat1", "cat2", "tags", "frequency"}]
        user_id: 用户 ID
        similarity_threshold: Embedding 余弦相似度阈值（粗筛）

    Returns:
        {"merged": [(survivor_id, merged_id, confidence)], "unmatched": [id]}
    """
    from app.services.embedding_service import encode_texts, build_index

    merged_pairs = []
    merged_ids = set()

    # ═══════════════════════════════════════════════════════════
    # Stage 1: 精确文本匹配（零成本）
    # ═══════════════════════════════════════════════════════════
    text_map = {}
    for q in questions:
        text = (q.get("question") or "").strip()
        if text:
            text_map.setdefault(text, []).append(q["id"])

    stage1_count = 0
    for text, ids in text_map.items():
        if len(ids) < 2:
            continue
        survivors = [(q["frequency"], q["id"]) for q in questions if q["id"] in ids]
        survivors.sort(reverse=True)
        survivor_id = survivors[0][1]
        for _, mid in survivors[1:]:
            if mid not in merged_ids:
                merged_pairs.append((survivor_id, mid, 1.0))
                merged_ids.add(mid)
                stage1_count += 1

    logger.info(f"[V2] Stage 1 精确匹配: {stage1_count} 对")

    # ═══════════════════════════════════════════════════════════
    # Stage 2: Embedding 粗筛 + 按 cat2 分组
    # ═══════════════════════════════════════════════════════════
    remaining = [q for q in questions if q["id"] not in merged_ids]
    if len(remaining) < 2:
        return {"merged": merged_pairs, "unmatched": [q["id"] for q in remaining]}

    # 编码所有剩余题目
    texts = [q.get("question", "") for q in remaining]
    embeddings = encode_texts(texts)

    # 构建 FAISS 索引
    index = build_index(embeddings)

    # 搜索每个题目的最近邻（top-K=10）
    candidate_pairs = []
    seen_pairs = set()

    for i in range(len(remaining)):
        q_emb = embeddings[i : i + 1]
        k = min(_V2_FAISS_TOP_K, len(remaining))
        scores, indices = index.search(q_emb, k)

        for j, (idx, score) in enumerate(zip(indices[0], scores[0])):
            idx = int(idx)
            if idx == i or idx >= len(remaining):
                continue
            pair = (min(i, idx), max(i, idx))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            if score >= similarity_threshold:
                candidate_pairs.append((pair[0], pair[1], float(score)))

    candidate_pairs.sort(key=lambda x: x[2], reverse=True)

    logger.info(
        f"[V2] Stage 2 Embedding 粗筛: {len(candidate_pairs)} 候选对 (阈值={similarity_threshold})"
    )

    if not candidate_pairs:
        unmatched = [q["id"] for q in remaining]
        return {"merged": merged_pairs, "unmatched": unmatched}

    # 按 cat2 分组候选对
    cat2_candidates = {}  # cat2 -> set of question indices
    for i1, i2, sim in candidate_pairs:
        cat2_1 = remaining[i1].get("cat2", "") or ""
        cat2_2 = remaining[i2].get("cat2", "") or ""
        # 同 cat2 的对归入该 cat2
        if cat2_1 == cat2_2:
            cat2 = cat2_1
        else:
            # 跨 cat2 的对：保守处理，归入各自 cat2
            cat2 = cat2_1
        cat2_candidates.setdefault(cat2, set())
        cat2_candidates[cat2].add(i1)
        cat2_candidates[cat2].add(i2)
        if cat2_1 != cat2_2:
            cat2_candidates.setdefault(cat2_2, set())
            cat2_candidates[cat2_2].add(i2)

    # ═══════════════════════════════════════════════════════════
    # Stage 3: 按 cat2 分组 LLM 语义聚类
    # ═══════════════════════════════════════════════════════════
    # 并发处理所有 cat2 组
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def _process_cat2_group(cat2, idx_set):
        """处理单个 cat2 组的 LLM 分组"""
        idx_list = sorted(idx_set)
        if len(idx_list) < 2:
            return []

        # "其他"分类跳过（是兜底分类，容易误合并）
        if cat2 in ("其他", ""):
            logger.info(
                f"[V2] Stage 3 [{cat2 or '未分类'}] 跳过（兜底分类，避免误合并）"
            )
            return []

        # 初始化 union-find
        local_parent = {}
        local_rank = {}
        for idx in idx_list:
            local_parent[idx] = idx
            local_rank[idx] = 0

        # 构建 prompt
        q_list = []
        for idx in idx_list:
            q = remaining[idx]
            q_list.append(f"[{q['id']}] {q.get('question', '')}")
        questions_text = "\n".join(q_list)

        prompt = _V2_GROUP_PROMPT.format(
            cat2=cat2 or "未分类",
            count=len(idx_list),
            questions=questions_text,
        )

        async with semaphore:
            try:
                content = await _call_llm_with_retry(
                    prompt, response_format={"type": "json_object"}, user_id=user_id
                )
                result = _extract_json(content)

                for group in result.get("groups", []):
                    ids = [str(i) for i in group.get("ids", [])]
                    if len(ids) < 2:
                        continue
                    # 找到对应的 remaining index
                    id_to_idx = {str(remaining[idx]["id"]): idx for idx in idx_list}
                    group_indices = [id_to_idx[sid] for sid in ids if sid in id_to_idx]
                    if len(group_indices) < 2:
                        continue
                    # Union-find 合并
                    for gi in group_indices[1:]:
                        _union_merge(local_parent, local_rank, group_indices[0], gi)

                logger.info(f"[V2] Stage 3 [{cat2 or '未分类'}] LLM 分组完成")

            except Exception as e:
                logger.warning(f"[V2] Stage 3 [{cat2 or '未分类'}] LLM 分组失败: {e}")
                return []

        group_clusters = {}
        for idx in local_parent:
            root = _union_find(local_parent, idx)
            group_clusters.setdefault(root, []).append(idx)
        return [members for members in group_clusters.values() if len(members) >= 2]

    # 并发执行所有 cat2 组
    grouped_clusters = await asyncio.gather(
        *[
            _process_cat2_group(cat2, idx_set)
            for cat2, idx_set in cat2_candidates.items()
        ]
    )

    # 从每个 cat2 的局部 union-find 结果提取合并结果
    for members in [members for group in grouped_clusters for members in group]:
        # 选 frequency 最高的作为 survivor
        member_qs = [
            (remaining[idx].get("frequency", 1), remaining[idx]["id"], idx)
            for idx in members
        ]
        member_qs.sort(reverse=True)
        survivor_id = member_qs[0][1]
        for _, mid, mid_idx in member_qs[1:]:
            if mid not in merged_ids:
                merged_pairs.append((survivor_id, mid, 0.9))
                merged_ids.add(mid)

    logger.info(
        f"[V2] Stage 3 总合并: {len(merged_pairs) - stage1_count} 对 (传递性合并后)"
    )

    unmatched = [q["id"] for q in remaining if q["id"] not in merged_ids]
    return {"merged": merged_pairs, "unmatched": unmatched}
