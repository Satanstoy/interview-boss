"""测试 LLM 聚类：cat2 预分组 + 验证步骤"""
import json
import asyncio
import sqlite3
import sys
import os

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from app.services.llm import _call_llm_with_retry, _extract_json

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "multimodal.db")
BATCH_SIZE = 30

# 禁止合并的题目对（基于文本关键词匹配）
# 格式: [(关键词A, 关键词B), ...] — 如果两道题分别命中不同关键词，则禁止合并
FORBIDDEN_PATTERNS = [
    ("badcase", "幻觉"),           # 修具体bug ≠ 防模型编造
    ("海量数据", "高并发"),         # 数据量级 ≠ Agent并发场景
    ("bean的生命周期", "循环依赖"),  # 生命周期 ≠ 三级缓存
]

# ── 聚类 prompt（cat2 内部使用，更精确） ──
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


def load_questions(cat1=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if cat1:
        where = "WHERE qb.cat1 = ?"
        params = (cat1,)
    else:
        where = "WHERE qb.cat1 IS NOT NULL"
        params = ()
    rows = conn.execute(f"""
        SELECT qb.id, qb.question, qb.cat1, qd.cat2
        FROM question_bank qb
        LEFT JOIN questions_detail qd ON qb.question = qd.question
        {where}
        ORDER BY qb.cat1, qd.cat2, qb.id
    """, params).fetchall()
    conn.close()
    return rows


def format_questions(rows):
    return "\n".join(f"[{r['id']}] {r['question']}" for r in rows)


async def cluster_batch(rows, prompt_template=CLUSTER_PROMPT, merged_refs=""):
    prompt = prompt_template.format(questions=format_questions(rows), merged_refs=merged_refs)
    content = await _call_llm_with_retry(prompt, response_format={"type": "json_object"})
    result = _extract_json(content)
    return result.get("clusters", [])


async def verify_group(ids, id_map):
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
        else:
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

    # ── 第一遍：严格聚类 ──
    pass1_clusters = []
    for batch in make_batches(rows):
        clusters = await cluster_batch(batch, CLUSTER_PROMPT)
        pass1_clusters.extend(clusters)

    # 收集第一遍合并的 IDs 和独立题
    merged_ids = set()
    for c in pass1_clusters:
        merged_ids.update(c.get("ids", []))

    independent_rows = [r for r in rows if r['id'] not in merged_ids]
    print(f"    第一遍: {len(pass1_clusters)} 个组, 独立 {len(independent_rows)} 题")

    # ── 第二遍：对独立题补漏（带已合并参考） ──
    pass2_clusters = []
    if len(independent_rows) >= 2:
        # 构建已合并组的参考文本
        merged_refs_lines = []
        for c in pass1_clusters:
            ids = c.get("ids", [])
            if len(ids) > 1:
                examples = " | ".join(f"[{qid}] {id_map.get(qid, '?')}" for qid in ids)
                merged_refs_lines.append(f"  ✓ {examples}")
        merged_refs = "\n".join(merged_refs_lines) if merged_refs_lines else "  （无）"

        for batch in make_batches(independent_rows):
            clusters = await cluster_batch(batch, CLUSTER_PROMPT_PASS2, merged_refs=merged_refs)
            pass2_clusters.extend(clusters)
        merge2 = sum(1 for c in pass2_clusters if len(c.get("ids", [])) > 1)
        print(f"    第二遍: 从独立题中发现 {merge2} 个额外合并组")

    # ── 合并两遍结果 ──
    all_clusters = pass1_clusters + pass2_clusters

    # ── 验证所有 3+ 题的合并组，并去重 ──
    verified = []
    used_ids = set()
    for c in all_clusters:
        ids = c.get("ids", [])
        rep = c.get("representative", "")
        # 跳过已被其他组使用的 ID
        ids = [qid for qid in ids if qid not in used_ids]
        if len(ids) < 2:
            continue
        if len(ids) >= 3:
            splits, ok = await verify_group(ids, id_map)
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

    # ── 禁止合并过滤（基于文本关键词） ──
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
    for c in verified:
        ids = c["ids"]
        if _is_forbidden(ids):
            print(f"  禁止合并: {id_map.get(ids[0], '?')[:30]} + {id_map.get(ids[1], '?')[:30]}")
            continue
        final.append(c)

    return final


async def run_category(cat1, rows):
    """对一个 cat1 分类运行聚类"""
    print(f"\n{'='*60}")
    print(f"  {cat1} ({len(rows)} 题)")
    print(f"{'='*60}")

    # 按 cat2 分组
    cat2_groups = {}
    no_cat2 = []
    for r in rows:
        cat2 = r['cat2']
        if cat2:
            cat2_groups.setdefault(cat2, []).append(r)
        else:
            no_cat2.append(r)

    print(f"\n按 cat2 分组:")
    for cat2, group in sorted(cat2_groups.items(), key=lambda x: -len(x[1])):
        print(f"  {cat2}: {len(group)} 题")
    if no_cat2:
        print(f"  无分类: {len(no_cat2)} 题")

    id_map = {r['id']: r['question'] for r in rows}
    all_clusters = []

    for cat2, group in sorted(cat2_groups.items(), key=lambda x: -len(x[1])):
        print(f"\n--- {cat2} ({len(group)} 题) ---")
        clusters = await cluster_cat2_group(group, id_map)
        merge_count = sum(1 for c in clusters if len(c.get("ids", [])) > 1)
        print(f"  聚类结果: {merge_count} 个合并组")
        for c in clusters:
            ids = c.get("ids", [])
            rep = c.get("representative", "")
            if len(ids) > 1:
                print(f"  合并 {len(ids)} 题: {rep[:60]}...")
                for qid in ids:
                    q = id_map.get(qid, "?")
                    print(f"    [{qid}] {q[:70]}")
        all_clusters.extend(clusters)

    if no_cat2:
        # 无分类的单独聚类
        print(f"\n--- 无分类 ({len(no_cat2)} 题) ---")
        clusters = await cluster_cat2_group(no_cat2, id_map)
        all_clusters.extend(clusters)

    # 统计
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

    print(f"\n--- {cat1} 汇总 ---")
    print(f"合并前: {total} 题 | 合并后: {after} 题 | 减少 {saved} 题 ({saved/total*100:.1f}%)")
    print(f"发现 {len(merge_groups)} 个重复组，涉及 {len(clustered_ids)} 道题")

    return total, after, len(merge_groups)


async def main():
    # 支持命令行指定 cat1，否则跑全部
    if len(sys.argv) > 1:
        cat1_filter = sys.argv[1]
    else:
        cat1_filter = None

    rows = load_questions(cat1_filter)
    if not rows:
        print("没有找到题目")
        return

    # 按 cat1 分组
    cat1_groups = {}
    for r in rows:
        cat1 = r['cat1'] or '其他'
        cat1_groups.setdefault(cat1, []).append(r)

    print(f"共 {len(rows)} 道题，{len(cat1_groups)} 个一类分类\n")
    for cat1, group in sorted(cat1_groups.items(), key=lambda x: -len(x[1])):
        print(f"  {cat1}: {len(group)} 题")

    grand_total = 0
    grand_after = 0

    for cat1, group in sorted(cat1_groups.items(), key=lambda x: -len(x[1])):
        total, after, _ = await run_category(cat1, group)
        grand_total += total
        grand_after += after

    print(f"\n{'='*60}")
    print(f"  全局汇总")
    print(f"{'='*60}")
    print(f"合并前: {grand_total} 题")
    print(f"合并后: {grand_after} 题")
    print(f"总减少: {grand_total - grand_after} 题 ({(grand_total-grand_after)/grand_total*100:.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
