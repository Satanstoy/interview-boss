"""流式增量聚类服务：匹配已有聚类 + 内部聚类新题"""
import asyncio
import logging
from typing import List, Dict, Any

from app.services.llm import _call_llm_with_retry, _extract_json

logger = logging.getLogger("interview-boss")

MAX_CONCURRENCY = 2

# ──────────────────────────── Prompts ────────────────────────────

MATCH_EXISTING_PROMPT = """你是一个面试题去重专家。你的任务是将一批【新题目】归类到【已有标准题库】中。

注意：【待匹配的新题目】是一个不超过 40 道题的微批次，请逐题判断是否与已有题库中的某道题真正重复。

匹配判断准则（核心）：
不要过于拘泥于字面词汇的完全一致，重点判断【考察的技术盲区是否完全重叠】。

可以合并（同一技术点的不同提问角度）：
- "TCP为什么是三次握手" ≈ "TCP三次握手的作用"
- "Redis 持久化方式有哪些？" ≈ "Redis 的 RDB 和 AOF 持久化有什么区别？"
- "介绍一下 ReAct" ≈ "ReAct 范式的原理是什么"

坚决不合并：
- 包含层级关系的概念：如 "Agent" 与 "ReAct"（ReAct 是 Agent 的一种范式，不是同一道题）
- 平级但不同的技术：如 "MCP" 与 "Function Call"（都是工具调用方案但考察点不同）
- 同一领域但不同子问题：如 "RAG 的 embedding 怎么设计" ≠ "RAG 的检索召回率怎么提升"

原则：只有当准备了其中一道题的答案，可以直接回答另一道题时，才能匹配。不确定时，宁可不匹配，也不要错配。

【已有标准题库】（格式：[聚类ID] 代表题目）：
{existing_clusters}

【待匹配的新题目】（微批次，共 {count} 题）：
{new_questions}

请输出 JSON 格式，列出成功匹配的结果。如果没有匹配项，输出空数组。
{{"matches": [{{"new_id": "新题ID", "cluster_id": "已有聚类ID"}}]}}
只输出 JSON，不要解释。"""

CLUSTER_NEW_PROMPT = """你是一个面试题聚类专家。以下是一个不超过 40 道题的微批次，请在它们内部寻找**真正重复**的题目并进行合并。

合并判断准则（核心）：
不要过于拘泥于字面词汇的完全一致，重点判断【考察的技术盲区是否完全重叠】。

可以合并（同一技术点的不同提问角度）：
- "TCP为什么是三次握手" ≈ "TCP三次握手的作用"
- "Redis 持久化方式有哪些？" ≈ "Redis 的 RDB 和 AOF 持久化有什么区别？"
- "介绍一下 ReAct" ≈ "ReAct 范式的原理是什么"

坚决不合并：
- 包含层级关系的概念：如 "Agent" 与 "ReAct"
- 平级但不同的技术：如 "MCP" 与 "Function Call"
- 同一领域但不同子问题：如 "RAG 的 embedding 怎么设计" ≠ "RAG 的检索召回率怎么提升"

原则：**宁可少合并，不要错合并。**

【待聚类的新题目】（微批次，共 {count} 题）：
{unmatched_questions}

请输出 JSON 格式。只有确实重复的才放入 clusters，独立的题目不需要输出。
{{"clusters": [{{"ids": ["题号1", "题号2"], "representative": "选取其中表述最清晰的一道题作为代表"}}]}}
只输出 JSON，不要解释。"""


# ──────────────────────────── 公开入口 ────────────────────────────

async def process_incremental_batch(
    new_rows: List[Dict],
    existing_by_cat2: Dict[str, List[Dict]],
    user_id=None,
) -> Dict[str, Any]:
    """流式增量聚类主入口。

    参数：
        new_rows: 一批新题，每项需含 id, question, cat2
        existing_by_cat2: {cat2: [{"id": qb_id, "question": 代表题}]}
        user_id: 调用者用户 ID

    返回：
        {
            "matched_to_existing": [{"qd_id": ..., "cluster_id": ..., ...}],
            "new_clusters": [{"ids": [...], "representative": "...", "items": [...]}]
        }
    """
    cat2_groups = {}
    no_cat2 = []
    for r in new_rows:
        cat2 = r.get('cat2') or ''
        if cat2:
            cat2_groups.setdefault(cat2, []).append(r)
        else:
            no_cat2.append(r)

    if no_cat2:
        cat2_groups[''] = no_cat2

    all_matched = []
    all_new_clusters = []

    # 顺序处理每个 cat2 组，组间强制间隔 1.5s 避免 429
    cat2_list = list(cat2_groups.items())
    for i, (cat2, questions) in enumerate(cat2_list):
        existing = existing_by_cat2.get(cat2, [])
        try:
            res = await _match_and_cluster_cat2(cat2, questions, existing, user_id)
            all_matched.extend(res['matched'])
            all_new_clusters.extend(res['new_clusters'])
        except Exception as e:
            logger.error(f"[{cat2 or '无分类'}] cat2 处理异常: {e}")

        # 组间打散发车间隔
        if i < len(cat2_list) - 1:
            await asyncio.sleep(1.5)

    return {
        "matched_to_existing": all_matched,
        "new_clusters": all_new_clusters,
    }


# ──────────────────────────── 内部函数 ────────────────────────────

async def _match_and_cluster_cat2(cat2, new_questions, existing_clusters, user_id):
    """处理单个 cat2 分组：匹配已有 → 内部聚类剩余"""
    matched = []
    unmatched_ids = {str(q['id']) for q in new_questions}

    # Phase 1: 匹配已有聚类
    if existing_clusters:
        try:
            prompt = MATCH_EXISTING_PROMPT.format(
                existing_clusters=_format_existing_clusters(existing_clusters),
                new_questions=_format_new_questions(new_questions),
                count=len(new_questions),
            )
            content = await _call_llm_with_retry(
                prompt, response_format={"type": "json_object"}, user_id=user_id
            )
            result = _extract_json(content)

            matched_cluster_ids = set()
            for m in result.get("matches", []):
                nid = str(m.get("new_id", ""))
                cid = m.get("cluster_id")
                if nid in unmatched_ids and cid is not None:
                    matched_cluster_ids.add(nid)
                    q = next((q for q in new_questions if str(q['id']) == nid), None)
                    if q:
                        matched.append({
                            "qd_id": q['id'],
                            "cluster_id": cid,
                            "question": q['question'],
                            "cat1": q.get('cat1', ''),
                            "cat2": q.get('cat2', cat2),
                            "tags": q.get('tags', ''),
                            "diff_tag": q.get('diff_tag', ''),
                            "url": q.get('url', ''),
                            "company": q.get('company', ''),
                            "round": q.get('round', ''),
                        })

            unmatched_ids -= matched_cluster_ids
            if matched_cluster_ids:
                logger.info(f"  [{cat2 or '无分类'}] 匹配已有聚类: {len(matched_cluster_ids)} 题")

        except Exception as e:
            logger.warning(f"  [{cat2 or '无分类'}] 匹配已有聚类失败: {e}")

    # Phase 2: 剩余新题内部聚类
    unmatched_questions = [q for q in new_questions if str(q['id']) in unmatched_ids]
    new_clusters = await _cluster_unmatched(unmatched_questions, user_id)

    return {"matched": matched, "new_clusters": new_clusters}


async def _cluster_unmatched(unmatched_questions, user_id):
    """将未匹配的新题进行内部聚类"""
    if len(unmatched_questions) < 2:
        return [{"ids": [str(q['id'])], "representative": q['question'], "items": [q]}
                for q in unmatched_questions]

    prompt = CLUSTER_NEW_PROMPT.format(
        unmatched_questions=_format_new_questions(unmatched_questions),
        count=len(unmatched_questions),
    )

    try:
        content = await _call_llm_with_retry(
            prompt, response_format={"type": "json_object"}, user_id=user_id
        )
        result = _extract_json(content)

        clusters = []
        clustered_ids = set()

        for c in result.get("clusters", []):
            ids = [str(i) for i in c.get("ids", [])]
            if len(ids) >= 2:
                clustered_ids.update(ids)
                items = [q for q in unmatched_questions if str(q['id']) in ids]
                rep = c.get("representative", "")
                if not rep or len(rep) < 3:
                    rep = max((q['question'] for q in items), key=len)
                clusters.append({"ids": ids, "representative": rep, "items": items})

        # 未被聚类的题目各自独立
        for q in unmatched_questions:
            if str(q['id']) not in clustered_ids:
                clusters.append({
                    "ids": [str(q['id'])],
                    "representative": q['question'],
                    "items": [q],
                })

        logger.info(f"    内部聚类: {len(clusters)} 个结果（含独立题）")
        return clusters

    except Exception as e:
        logger.warning(f"    内部聚类失败: {e}")
        return [{"ids": [str(q['id'])], "representative": q['question'], "items": [q]}
                for q in unmatched_questions]


def _format_existing_clusters(clusters):
    """格式化已有聚类供 Prompt 使用（只传 ID + 代表题，节省 Token）"""
    lines = []
    for c in clusters:
        lines.append(f"[{c['id']}] {c['question']}")
    return "\n".join(lines)


def _format_new_questions(questions):
    return "\n".join(f"[{q['id']}] {q['question']}" for q in questions)


# ──────────────────────────── 保留的工具函数 ────────────────────────────

async def generate_unified_question(questions: list[str], sources_context: list[dict] | None = None, user_id=None) -> str:
    """为一组同义问题选择代表题（使用最长的原始问题）"""
    if len(questions) == 1:
        return questions[0]
    return max(questions, key=len)


async def match_new_questions(new_rows, existing_clusters_by_cat2, user_id=None):
    """增量匹配：将新题目与已有聚类匹配（用于个人题库合并）"""
    if not new_rows:
        return {"matched": [], "unmatched": []}

    cat2_groups = {}
    for r in new_rows:
        cat2 = r.get('cat2') or ''
        cat2_groups.setdefault(cat2, []).append(r)

    matched = []
    still_unmatched = []

    for cat2, group in cat2_groups.items():
        existing = existing_clusters_by_cat2.get(cat2, [])
        if not existing:
            still_unmatched.extend(group)
            continue

        # 构建 cluster_id → question_bank_id 映射（兼容两种格式）
        id_to_qb = {}
        normalized = []
        for c in existing:
            cid = c.get('id') or c.get('question_bank_id')
            id_to_qb[cid] = cid
            normalized.append({**c, 'id': cid})

        prompt = MATCH_EXISTING_PROMPT.format(
            existing_clusters=_format_existing_clusters(normalized),
            new_questions=_format_new_questions(group),
            count=len(group),
        )

        try:
            content = await _call_llm_with_retry(prompt, response_format={"type": "json_object"}, user_id=user_id)
            result = _extract_json(content)

            group_matched_ids = set()
            for m in result.get("matches", []):
                new_id = m.get("new_id")
                cluster_id = m.get("cluster_id")
                if new_id is not None and cluster_id is not None and cluster_id in id_to_qb:
                    matched.append({"new_id": new_id, "question_bank_id": id_to_qb[cluster_id]})
                    group_matched_ids.add(new_id)
            for r in group:
                if r['id'] not in group_matched_ids:
                    still_unmatched.append(r)
        except Exception as e:
            logger.warning(f"同分类增量匹配失败: {e}")
            still_unmatched.extend(group)

    return {"matched": matched, "unmatched": still_unmatched}
