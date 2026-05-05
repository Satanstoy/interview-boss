"""LLM 聚类服务：cat2 预分组 + 两遍聚类 + 验证 + 禁止合并过滤"""
import logging
from typing import List, Dict, Any

from app.services.llm import _call_llm_with_retry, _extract_json

logger = logging.getLogger("interview-boss")

BATCH_SIZE = 30

# 禁止合并的题目对（基于文本关键词匹配）
# 格式: [(关键词A, 关键词B), ...] — 如果两道题分别命中不同关键词，则禁止合并
FORBIDDEN_PATTERNS = [
    ("badcase", "幻觉"),           # 修具体bug ≠ 防模型编造
    ("海量数据", "高并发"),         # 数据量级 ≠ Agent并发场景
    ("bean的生命周期", "循环依赖"),  # 生命周期 ≠ 三级缓存
]

# ── 聚类 prompt（cat2 内部使用） ──
CLUSTER_PROMPT = """你是一个面试题分析专家。以下是一批**同一细分领域**的面试题目，请你将**问的是完全相同的那一件事**的题目归为一组。

核心判定标准（极其严格）：
两道题只有在面试中**用完全相同的答案就能同时回答**时，才应该合并。
如果回答了题A之后，面试官还会追问题B → 说明这是两个不同的考察点，不能合并。

正确合并的例子：
✓ "介绍一下Agent" 和 "Agent的整体架构是什么" → 换了个问法
✓ "RAG是怎么做的" 和 "RAG各个部分怎么做（端到端设计）" → 同一个整体问题
✓ "Skill和MCP的区别" 和 "展开讲讲mcp和skills" → 同一件事
✓ "RRF融合算法" 和 "RRF的权重怎么设计" → 同一技术的细节追问

错误合并的例子（相关但不同环节/方面）：
✗ "RAG的分块策略" 和 "RAG的召回策略" → 分块≠召回
✗ "RRF融合算法" 和 "重排序" → 融合≠重排
✗ "badcase处理" 和 "幻觉应对" → 不同问题类型
✗ "记忆压缩" 和 "记忆检索" → 记忆管理的不同环节
✗ "有没有做过X" 和 "X的技术细节" → 问经验≠问技术
✗ "ReAct范式" 和 "Claude Code主循环" → 通用框架 vs 具体工具
✗ "记忆压缩" 和 "上下文过长怎么办" → 压缩记忆 ≠ 处理上下文窗口
✗ "代码沙箱是怎么执行的" 和 "把mcp改成skills怎么改" → 运行环境 ≠ 技术方案迁移
✗ "海量数据下怎么设计" 和 "Agent高并发怎么处理" → 数据量级 ≠ Agent并发场景
✗ "badcase怎么处理" 和 "幻觉怎么应对" → 修具体bug ≠ 防模型编造（被动修复 ≠ 主动预防）

合并前检查（对每一对候选题）：
1. 答案是否完全重叠？（不是"相关"，是"重叠"）
2. 回答A后面试官会不会追问B？如果会 → 不合并

规则：
1. 宁可漏合并10道题，也不要错合并1道题。精度优先
2. 独立的题目不要放入任何组
3. 每组选一道最完整/最长的题目作为代表题
4. 每组至少2道题

请严格按以下 JSON 格式返回，不要有任何其他文字：
{{"clusters": [{{"ids": [题号1, 题号2, ...], "representative": "最完整的题目文本"}}]}}

题目列表：
{questions}"""

# ── 第二遍 prompt（对独立题补漏，带已合并参考） ──
CLUSTER_PROMPT_PASS2 = """你是一个面试题分析专家。以下是**同一细分领域**的面试题目。

**已确认的合并组（供参考，不要再拆开）：**
{merged_refs}

**以下是第一轮判定为独立的题目：**
{questions}

请仔细检查这些独立题，找出其中**确实是同一件事、只是换了问法**的题目对。

判定标准（与上面已合并的例子同等严格）：
- 用同一份答案就能同时回答 → 合并
- 回答了A之后面试官还会追问题B → 不合并
- 共享关键词但不同环节/方面 → 不合并

规则：
1. 只合并你非常确定的，**不确定就保持独立**
2. 参照上面已合并组的严格程度——如果两道题的区分度比已合并组还大，就不要合并
3. 每组至少2道题，每组选最完整的题目作为代表

请严格按以下 JSON 格式返回，不要有任何其他文字：
{{"clusters": [{{"ids": [题号1, 题号2, ...], "representative": "最完整的题目文本"}}]}}
如果没有发现可以合并的，返回 {{"clusters": []}}"""

# ── 验证 prompt ──
VERIFY_PROMPT = """以下是一组被归为"同一道题"的面试题目，请判断它们是否真的应该合并。

判断标准：只有用**完全相同的答案就能同时回答**的题目才应该合并。
如果回答了题A之后，面试官还会追问题B → 不能合并。

题目列表：
{questions}

请返回JSON：{{"merge": true}} 或 {{"merge": false, "split": [[子组1的ids], [子组2的ids]]}}"""

# ── 增量匹配 prompt ──
MATCH_PROMPT = """你是一个面试题分析专家。以下是一个细分领域中**已有的题目聚类**和一批**新题目**。

**已有的聚类（每个聚类列出所有题目）：**
{existing_clusters}

**新题目：**
{new_questions}

请判断每道新题目是否属于上面某个已有聚类（即用完全相同的答案就能同时回答）。

判定标准：
- 新题目和某个聚类的题目问的是同一件事 → 归入该聚类
- 相关但不同环节/方面 → 不归入
- 没有匹配的聚类 → 标记为新题

请严格按以下 JSON 格式返回，不要有任何其他文字：
{{"matches": [{{"new_id": 新题号, "cluster_idx": 匹配的聚类序号（从0开始）}}], "unmatched": [无匹配的新题号]}}"""

# ── 统一问题生成 prompt ──
UNIFIED_QUESTION_PROMPT = """你是一个面试题分析专家。以下是一组**考察同一个知识点**的面试题目，请生成一个**统一的、清晰的**问题来概括这组题目。

要求：
1. 统一问题应该能让候选人清楚知道要回答什么
2. 保留关键的技术术语和上下文
3. 不要太笼统（如"介绍一下RAG"），也不要太具体（如某个项目的细节）
4. 长度控制在15-40字

题目列表：
{questions}

请严格按以下 JSON 格式返回，不要有任何其他文字：
{{"unified_question": "统一的问题文本"}}"""


def _format_questions(rows):
    return "\n".join(f"[{r['id']}] {r['question']}" for r in rows)


async def _cluster_batch(rows, prompt_template, merged_refs=""):
    prompt = prompt_template.format(questions=_format_questions(rows), merged_refs=merged_refs)
    content = await _call_llm_with_retry(prompt, response_format={"type": "json_object"})
    return _extract_json(content).get("clusters", [])


async def generate_unified_question(questions: list[str]) -> str:
    """为一组同义问题生成统一的代表问题"""
    if len(questions) == 1:
        return questions[0]
    questions_text = "\n".join(f"- {q}" for q in questions)
    prompt = UNIFIED_QUESTION_PROMPT.format(questions=questions_text)
    try:
        content = await _call_llm_with_retry(prompt, response_format={"type": "json_object"})
        result = _extract_json(content)
        unified = result.get("unified_question", "")
        if unified and len(unified) > 5:
            return unified
    except Exception as e:
        logger.warning(f"生成统一问题失败: {e}")
    # 回退：返回最长的问题
    return max(questions, key=len)


async def _verify_group(ids, id_map):
    """验证一个合并组（3题以上）是否应该合并"""
    if len(ids) <= 2:
        return [ids], True
    questions = "\n".join(f"[{qid}] {id_map.get(qid, '?')}" for qid in ids)
    prompt = VERIFY_PROMPT.format(questions=questions)
    try:
        content = await _call_llm_with_retry(prompt, response_format={"type": "json_object"})
        result = _extract_json(content)
        if result.get("merge", True):
            return [ids], True
        splits = result.get("split", [[qid] for qid in ids])
        return splits, False
    except Exception:
        return [ids], True


async def cluster_cat2_group(rows, id_map):
    """对一个 cat2 分组进行两遍聚类 + 验证"""
    if len(rows) <= 1:
        return []

    def make_batches(rows_list):
        if len(rows_list) <= BATCH_SIZE:
            return [rows_list]
        return [rows_list[i:i+BATCH_SIZE] for i in range(0, len(rows_list), BATCH_SIZE)]

    # 第一遍：严格聚类
    pass1_clusters = []
    for batch in make_batches(rows):
        clusters = await _cluster_batch(batch, CLUSTER_PROMPT)
        pass1_clusters.extend(clusters)

    merged_ids = set()
    for c in pass1_clusters:
        merged_ids.update(c.get("ids", []))

    independent_rows = [r for r in rows if r['id'] not in merged_ids]
    logger.info(f"    第一遍: {len(pass1_clusters)} 个组, 独立 {len(independent_rows)} 题")

    # 第二遍：对独立题补漏（带已合并参考）
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
            clusters = await _cluster_batch(batch, CLUSTER_PROMPT_PASS2, merged_refs=merged_refs)
            pass2_clusters.extend(clusters)
        merge2 = sum(1 for c in pass2_clusters if len(c.get("ids", [])) > 1)
        logger.info(f"    第二遍: 从独立题中发现 {merge2} 个额外合并组")

    # 合并两遍结果
    all_clusters = pass1_clusters + pass2_clusters

    # 验证所有 3+ 题的合并组，并去重
    verified = []
    used_ids = set()
    for c in all_clusters:
        ids = [qid for qid in c.get("ids", []) if qid not in used_ids]
        if len(ids) < 2:
            continue
        rep = c.get("representative", "")
        if len(ids) >= 3:
            splits, ok = await _verify_group(ids, id_map)
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

    # 禁止合并过滤（基于文本关键词）
    def _is_forbidden(ids):
        if len(ids) != 2:
            return False
        q1 = id_map.get(ids[0], "").lower()
        q2 = id_map.get(ids[1], "").lower()
        for kw_a, kw_b in FORBIDDEN_PATTERNS:
            # 两道题分别命中不同关键词 → 禁止合并
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

    # 补充独立题（未被任何合并组使用的题目）
    for row in rows:
        if row['id'] not in final_used_ids:
            final.append({"ids": [row['id']], "representative": row['question']})

    return final


async def cluster_all_questions(rows):
    """全量聚类入口：按 cat2 分组后逐组聚类

    Args:
        rows: questions_detail 行列表，需包含 id, question, cat2 字段

    Returns:
        list of cluster dicts: [{"ids": [...], "representative": "..."}]
    """
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
        clusters = await cluster_cat2_group(group, id_map)
        merge_count = sum(1 for c in clusters if len(c.get("ids", [])) > 1)
        logger.info(f"  结果: {merge_count} 个合并组")
        all_clusters.extend(clusters)

    if no_cat2:
        logger.info(f"聚类 无分类 ({len(no_cat2)} 题)")
        clusters = await cluster_cat2_group(no_cat2, id_map)
        all_clusters.extend(clusters)

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


async def match_new_questions(new_rows, existing_clusters_by_cat2):
    """增量匹配：将新题目与已有聚类匹配

    Args:
        new_rows: 新题目列表，需包含 id, question, cat2 字段
        existing_clusters_by_cat2: dict[cat2] -> list of cluster dicts
            每个 cluster: {"question_bank_id": int, "question": str, "all_questions": [str, ...]}

    Returns:
        dict with:
            "matched": list of {"new_id": int, "question_bank_id": int}
            "unmatched": list of new_rows that have no match
    """
    if not new_rows:
        return {"matched": [], "unmatched": []}

    # 按 cat2 分组
    cat2_groups = {}
    for r in new_rows:
        cat2 = r.get('cat2') or ''
        cat2_groups.setdefault(cat2, []).append(r)

    matched = []
    unmatched = []

    for cat2, group in cat2_groups.items():
        existing = existing_clusters_by_cat2.get(cat2, [])
        if not existing:
            unmatched.extend(group)
            continue

        # 构建已有聚类描述
        cluster_lines = []
        for idx, c in enumerate(existing):
            all_qs = c.get("all_questions", [c["question"]])
            cluster_lines.append(f"聚类{idx}: " + " | ".join(all_qs))
        existing_text = "\n".join(cluster_lines)

        new_lines = "\n".join(f"[{r['id']}] {r['question']}" for r in group)
        prompt = MATCH_PROMPT.format(existing_clusters=existing_text, new_questions=new_lines)

        try:
            content = await _call_llm_with_retry(prompt, response_format={"type": "json_object"})
            result = _extract_json(content)

            for m in result.get("matches", []):
                new_id = m.get("new_id")
                cluster_idx = m.get("cluster_idx")
                if new_id is not None and cluster_idx is not None and 0 <= cluster_idx < len(existing):
                    matched.append({
                        "new_id": new_id,
                        "question_bank_id": existing[cluster_idx]["question_bank_id"],
                    })

            matched_ids = {m["new_id"] for m in matched}
            for r in group:
                if r['id'] not in matched_ids:
                    unmatched.append(r)
        except Exception as e:
            logger.error(f"增量匹配失败 (cat2={cat2}): {e}")
            unmatched.extend(group)

    return {"matched": matched, "unmatched": unmatched}
