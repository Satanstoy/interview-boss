"""LLM 聚类服务：cat2 预分组 + 两遍聚类 + 验证 + 禁止合并过滤"""
import logging
from typing import List, Dict, Any

from app.services.llm import _call_llm_with_retry, _extract_json

logger = logging.getLogger("interview-boss")

BATCH_SIZE = 15


def _format_questions(rows):
    return "\n".join(f"[{r['id']}] {r['question']}" for r in rows)


# --------------- Prompts ---------------

CLUSTER_PROMPT = """你是一个面试题聚类专家。请将以下面试题分组——**只有问的是同一道题**的才能归为一组。

严格合并标准（必须同时满足）：
1. 两道题问的是**完全相同的知识点或操作**
2. 候选人如果能回答其中一道，必然能回答另一道
3. 只是"属于同一个话题"不够，必须是"同一道题的不同说法"

可以合并的例子：
- "Redis 持久化方式有哪些？" ≈ "Redis 的 RDB 和 AOF 持久化有什么区别？"
- "TCP 三次握手的过程？" ≈ "描述一下 TCP 建立连接的过程"
- "什么是 RAG？" ≈ "介绍一下 RAG 技术"

不能合并的例子（考察点不同）：
- "RAG 的 embedding 怎么设计？" ≠ "RAG 的检索召回率怎么提升？"（embedding ≠ 召回率）
- "限流怎么做？" ≠ "Redis 是单线程吗？"（限流 ≠ Redis 架构）
- "Java 线程池原理" ≠ "计算机网络 IO 多路复用"（线程池 ≠ IO）
- "介绍你的 Agent 项目" ≠ "Agent 的记忆系统怎么做的？"（项目介绍 ≠ 记忆系统）
- "LRU Cache 怎么实现？" ≠ "滑动窗口最大值"（两道不同的算法题）

原则：**宁可少合并，不要错合并。不确定时就不要合并。**

{questions}

{merged_refs}

输出 JSON 格式：
{{"clusters": [{{"ids": [题号1, 题号2], "representative": "代表题"}}]}}
只有确实重复的才放入 clusters。独立的题目不需要输出。只输出 JSON，不要解释。"""

CLUSTER_PROMPT_PASS2 = """你是一个面试题聚类专家。以下题目在第一遍聚类中被判定为独立题。
请再次检查，是否有**真正重复**的题目可以合并（同一道题的不同说法）。

注意：仅仅"属于同一话题"不算重复！必须是候选人答其中一道就能答另一道的程度。

已确认的合并组参考：
{merged_refs}

待检查的独立题：
{questions}

输出 JSON 格式：
{{"clusters": [{{"ids": [题号1, 题号2], "representative": "代表题"}}]}}
只有确实重复的才合并。只输出 JSON，不要解释。"""

VERIFY_PROMPT = """请判断以下面试题是否是**同一道题的不同表述**。

判断标准：候选人如果准备了其中一道题的答案，能否直接用同一份答案回答其他题？
- 如果能 → 合并（返回 {{"merge": true}}）
- 如果不能（需要额外准备不同知识点）→ 不合并（返回 {{"merge": false, "split": [[题号1], [题号2], ...]}}）

{questions}

只输出 JSON，不要解释。"""

UNIFIED_QUESTION_PROMPT = """请为以下一组同义面试题生成一个统一的代表问题。
要求：保留所有题目的核心考点，去除冗余的公司/轮次信息，生成简洁专业的面试题。

题目列表：
{questions_with_sources}

输出 JSON 格式：
{{"unified_question": "统一后的题目"}}
只输出 JSON，不要解释。"""

MATCH_PROMPT = """你是一个面试题匹配专家。请判断以下新题目是否与已有聚类中的题目**真正重复**。

严格标准：只有新题和聚类中的题是"同一道题的不同说法"才算匹配。仅仅"属于同一话题"不算匹配。

已有聚类：
{existing_clusters}

新题目：
{new_questions}

对每个新题目，判断是否与某个已有聚类真正重复。不确定时不要匹配。

输出 JSON 格式：
{{"matches": [{{"new_id": 新题号, "cluster_idx": 聚类索引}}]}}
只输出 JSON，不要解释。"""

CROSS_CAT_MERGE_PROMPT = """你是一个面试题聚类专家。以下题目来自不同的分类，但在各自分类内未找到同义题。
请判断这些题目中是否有**真正重复**的题（同一道题的不同说法，候选人答其中一道就能答另一道）。

注意：仅仅"属于同一话题"不算重复！

{questions}

输出 JSON 格式：
{{"clusters": [{{"ids": [题号1, 题号2], "representative": "代表题"}}]}}
只有确实重复的才合并。只输出 JSON，不要解释。"""

FORBIDDEN_PATTERNS = [
    ("操作系统", "数据库"),
    ("计算机网络", "数据库"),
    ("操作系统", "计算机网络"),
    ("redis", "mysql"),
    ("linux", "mysql"),
]


# --------------- Clustering functions ---------------

async def _cluster_batch(rows, prompt_template, merged_refs="", user_id=None):
    prompt = prompt_template.format(questions=_format_questions(rows), merged_refs=merged_refs)
    content = await _call_llm_with_retry(prompt, response_format={"type": "json_object"}, user_id=user_id)
    return _extract_json(content).get("clusters", [])


async def generate_unified_question(questions: list[str], sources_context: list[dict] | None = None, user_id=None) -> str:
    """为一组同义问题生成统一的代表问题"""
    if len(questions) == 1:
        return questions[0]

    if sources_context:
        lines = []
        for sc in sources_context:
            q = sc.get("question", "")
            company = sc.get("company", "")
            round_ = sc.get("round", "")
            suffix = f"（{company} / {round_}）" if company else ""
            lines.append(f"- {q}{suffix}")
        questions_with_sources = "\n".join(lines)
    else:
        questions_with_sources = "\n".join(f"- {q}" for q in questions)

    prompt = UNIFIED_QUESTION_PROMPT.format(questions_with_sources=questions_with_sources)
    try:
        content = await _call_llm_with_retry(prompt, response_format={"type": "json_object"}, user_id=user_id)
        result = _extract_json(content)
        unified = result.get("unified_question", "")
        if unified and len(unified) > 5:
            return unified
    except Exception as e:
        logger.warning(f"生成统一问题失败: {e}")
    return max(questions, key=len)


async def _verify_group(ids, id_map, user_id=None):
    """验证一个合并组（3题以上）是否应该合并"""
    if len(ids) <= 2:
        return [ids], True
    questions = "\n".join(f"[{qid}] {id_map.get(qid, '?')}" for qid in ids)
    prompt = VERIFY_PROMPT.format(questions=questions)
    try:
        content = await _call_llm_with_retry(prompt, response_format={"type": "json_object"}, user_id=user_id)
        result = _extract_json(content)
        if result.get("merge", True):
            return [ids], True
        splits = result.get("split", [[qid] for qid in ids])
        return splits, False
    except Exception:
        return [[qid] for qid in ids], False


async def cluster_cat2_group(rows, id_map, user_id=None):
    """对一个 cat2 分组进行两遍聚类 + 验证"""
    if len(rows) <= 1:
        return []

    def make_batches(rows_list):
        if len(rows_list) <= BATCH_SIZE:
            return [rows_list]
        return [rows_list[i:i+BATCH_SIZE] for i in range(0, len(rows_list), BATCH_SIZE)]

    pass1_clusters = []
    for batch in make_batches(rows):
        clusters = await _cluster_batch(batch, CLUSTER_PROMPT, user_id=user_id)
        pass1_clusters.extend(clusters)

    merged_ids = set()
    for c in pass1_clusters:
        merged_ids.update(c.get("ids", []))

    independent_rows = [r for r in rows if r['id'] not in merged_ids]
    logger.info(f"    第一遍: {len(pass1_clusters)} 个组, 独立 {len(independent_rows)} 题")

    pass2_clusters = []
    if len(independent_rows) >= 2:
        merged_refs_lines = []
        for c in pass1_clusters:
            ids = c.get("ids", [])
            if len(ids) > 1:
                examples = " | ".join(f"[{qid}] {id_map.get(qid, '?')}" for qid in ids)
                merged_refs_lines.append(f"  ✓ {examples}")
        merged_refs = "\n".join(merged_refs_lines) if merged_refs_lines else "  （无）"

        for batch in make_batches(independent_rows):
            clusters = await _cluster_batch(batch, CLUSTER_PROMPT_PASS2, merged_refs=merged_refs, user_id=user_id)
            pass2_clusters.extend(clusters)
        merge2 = sum(1 for c in pass2_clusters if len(c.get("ids", [])) > 1)
        logger.info(f"    第二遍: 从独立题中发现 {merge2} 个额外合并组")

    all_clusters = pass1_clusters + pass2_clusters

    verified = []
    used_ids = set()
    for c in all_clusters:
        ids = [qid for qid in c.get("ids", []) if qid not in used_ids]
        if len(ids) < 2:
            continue
        rep = c.get("representative", "")
        if len(ids) >= 3:
            splits, ok = await _verify_group(ids, id_map, user_id=user_id)
            if ok:
                verified.append({"ids": ids, "representative": rep})
                used_ids.update(ids)
            else:
                for sub_ids in splits:
                    sub_ids = [qid for qid in sub_ids if qid not in used_ids]
                    if len(sub_ids) >= 2:
                        sub_rep = max(sub_ids, key=lambda qid: len(id_map.get(qid, "")))
                        verified.append({"ids": sub_ids, "representative": id_map.get(sub_rep, "")})
                        used_ids.update(sub_ids)
        else:
            verified.append({"ids": ids, "representative": rep})
            used_ids.update(ids)

    def _is_forbidden(ids):
        if len(ids) != 2:
            return False
        q1 = id_map.get(ids[0], "").lower()
        q2 = id_map.get(ids[1], "").lower()
        for kw_a, kw_b in FORBIDDEN_PATTERNS:
            if (kw_a in q1 and kw_b in q2) or (kw_a in q2 and kw_b in q1):
                return True
        return False

    final = []
    final_used_ids = set()
    for c in verified:
        ids = c["ids"]
        if _is_forbidden(ids):
            logger.info(f"  禁止合并: {id_map.get(ids[0], '?')[:30]} + {id_map.get(ids[1], '?')[:30]}")
            continue
        final.append(c)
        final_used_ids.update(ids)

    for row in rows:
        if row['id'] not in final_used_ids:
            final.append({"ids": [row['id']], "representative": row['question']})

    return final


async def cluster_all_questions(rows, user_id=None):
    """全量聚类入口：按 cat2 分组后逐组聚类 + 跨分类合并"""
    cat2_groups = {}
    no_cat2 = []
    for r in rows:
        cat2 = r['cat2']
        if cat2:
            cat2_groups.setdefault(cat2, []).append(r)
        else:
            no_cat2.append(r)

    id_map = {r['id']: r['question'] for r in rows}
    all_clusters = []

    for cat2, group in sorted(cat2_groups.items(), key=lambda x: -len(x[1])):
        logger.info(f"聚类 {cat2} ({len(group)} 题)")
        clusters = await cluster_cat2_group(group, id_map, user_id=user_id)
        merge_count = sum(1 for c in clusters if len(c.get("ids", [])) > 1)
        logger.info(f"  结果: {merge_count} 个合并组")
        all_clusters.extend(clusters)

    if no_cat2:
        logger.info(f"聚类 无分类 ({len(no_cat2)} 题)")
        clusters = await cluster_cat2_group(no_cat2, id_map, user_id=user_id)
        all_clusters.extend(clusters)

    # ── 跨分类合并：不同 cat2 中语义相同的单题互相比较 ──
    all_clusters = await _cross_cat2_merge(all_clusters, id_map, user_id=user_id)

    clustered_ids = set()
    merge_groups = []
    for c in all_clusters:
        ids = c.get("ids", [])
        if len(ids) > 1:
            merge_groups.append(c)
            clustered_ids.update(ids)

    total = len(rows)
    saved = len(clustered_ids) - len(merge_groups)
    after = total - saved
    logger.info(f"聚类完成: {total} → {after} 题，减少 {saved} 题 ({saved/total*100:.1f}%)")

    return all_clusters


async def _cross_cat2_merge(all_clusters, id_map, user_id=None):
    """跨 cat2 合并：不同 cat2 分组中的单题互相比较"""
    singletons = [c for c in all_clusters if len(c.get("ids", [])) == 1]
    multi = [c for c in all_clusters if len(c.get("ids", [])) > 1]

    if len(singletons) < 2:
        return all_clusters

    rows_for_merge = [{"id": c["ids"][0], "question": id_map.get(c["ids"][0], "")} for c in singletons]

    # 按 BATCH_SIZE 分批
    cross_clusters = []
    for i in range(0, len(rows_for_merge), BATCH_SIZE):
        batch = rows_for_merge[i:i + BATCH_SIZE]
        if len(batch) < 2:
            cross_clusters.append({"ids": [batch[0]["id"]], "representative": batch[0]["question"]})
            continue
        try:
            clusters = await _cluster_batch(batch, CROSS_CAT_MERGE_PROMPT, user_id=user_id)
            cross_clusters.extend(clusters)
        except Exception as e:
            logger.warning(f"跨分类合并批次失败: {e}")
            for r in batch:
                cross_clusters.append({"ids": [r["id"]], "representative": r["question"]})

    # 合并结果
    merged_ids = set()
    new_multi = []
    remaining_singletons = []
    for c in cross_clusters:
        ids = c.get("ids", [])
        if len(ids) > 1:
            new_multi.append({"ids": ids, "representative": c.get("representative", "")})
            merged_ids.update(ids)
    for c in singletons:
        if c["ids"][0] not in merged_ids:
            remaining_singletons.append(c)

    cross_merge_count = len(new_multi)
    if cross_merge_count:
        logger.info(f"跨分类合并: 发现 {cross_merge_count} 个跨分类重复组")

    return multi + new_multi + remaining_singletons


async def match_new_questions(new_rows, existing_clusters_by_cat2, user_id=None):
    """增量匹配：将新题目与已有聚类匹配（先同 cat2，再跨 cat2）"""
    if not new_rows:
        return {"matched": [], "unmatched": []}

    cat2_groups = {}
    for r in new_rows:
        cat2 = r.get('cat2') or ''
        cat2_groups.setdefault(cat2, []).append(r)

    matched = []
    still_unmatched = []

    # ── 第一遍：同 cat2 匹配 ──
    for cat2, group in cat2_groups.items():
        existing = existing_clusters_by_cat2.get(cat2, [])
        if not existing:
            still_unmatched.extend(group)
            continue

        cluster_lines = []
        for idx, c in enumerate(existing):
            all_qs = c.get("all_questions", [c["question"]])
            cluster_lines.append(f"聚类{idx}: " + " | ".join(all_qs))
        existing_text = "\n".join(cluster_lines)

        new_lines = "\n".join(f"[{r['id']}] {r['question']}" for r in group)
        prompt = MATCH_PROMPT.format(existing_clusters=existing_text, new_questions=new_lines)

        try:
            content = await _call_llm_with_retry(prompt, response_format={"type": "json_object"}, user_id=user_id)
            result = _extract_json(content)

            group_matched_ids = set()
            for m in result.get("matches", []):
                new_id = m.get("new_id")
                cluster_idx = m.get("cluster_idx")
                if new_id is not None and cluster_idx is not None and 0 <= cluster_idx < len(existing):
                    matched.append({"new_id": new_id, "question_bank_id": existing[cluster_idx]["question_bank_id"]})
                    group_matched_ids.add(new_id)
            for r in group:
                if r['id'] not in group_matched_ids:
                    still_unmatched.append(r)
        except Exception as e:
            logger.warning(f"同分类增量匹配失败: {e}")
            still_unmatched.extend(group)

    # ── 第二遍：跨 cat2 匹配（仅当有未匹配题且有其他 cat2 的聚类时） ──
    if still_unmatched:
        all_existing = []
        for cat2, clusters in existing_clusters_by_cat2.items():
            all_existing.extend(clusters)
        if all_existing:
            cluster_lines = []
            for idx, c in enumerate(all_existing):
                all_qs = c.get("all_questions", [c["question"]])
                cluster_lines.append(f"聚类{idx}: " + " | ".join(all_qs))
            existing_text = "\n".join(cluster_lines)
            new_lines = "\n".join(f"[{r['id']}] {r['question']}" for r in still_unmatched)
            prompt = MATCH_PROMPT.format(existing_clusters=existing_text, new_questions=new_lines)
            try:
                content = await _call_llm_with_retry(prompt, response_format={"type": "json_object"}, user_id=user_id)
                result = _extract_json(content)
                cross_matched_ids = set()
                for m in result.get("matches", []):
                    new_id = m.get("new_id")
                    cluster_idx = m.get("cluster_idx")
                    if new_id is not None and cluster_idx is not None and 0 <= cluster_idx < len(all_existing):
                        matched.append({"new_id": new_id, "question_bank_id": all_existing[cluster_idx]["question_bank_id"]})
                        cross_matched_ids.add(new_id)
                if cross_matched_ids:
                    logger.info(f"跨分类增量匹配: 额外匹配 {len(cross_matched_ids)} 题")
                still_unmatched = [r for r in still_unmatched if r['id'] not in cross_matched_ids]
            except Exception as e:
                logger.warning(f"跨分类增量匹配失败: {e}")

    return {"matched": matched, "unmatched": still_unmatched}
