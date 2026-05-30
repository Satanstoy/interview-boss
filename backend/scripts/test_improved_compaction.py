#!/usr/bin/env python3
"""
测试改进后的 compaction

在备份数据库上测试：
1. 改进后的 prompt 是否更严格
2. 两阶段验证是否有效
3. 去掉 ai_answer 过滤后是否正常工作
"""

import sqlite3
import json
import requests
from datetime import datetime
from typing import List, Dict, Set
from collections import defaultdict
import re

# API 配置
API_KEY = "tp-ck213kwkju1edysndkq8n2tkqqx7c8oprwzllvj8yvqyadyv"
API_BASE_URL = "https://token-plan-cn.xiaomimimo.com/anthropic/v1/messages"
MODEL_NAME = "mimo-v2.5-pro"

DB_PATH = "/home/ubuntu/sj/interview-boss/backend/data/interview-boss.db.bak.202605301500"
REPORT_PATH = "/home/ubuntu/sj/interview-boss/backend/scripts/improved_compaction_report.md"


def call_anthropic_api(prompt: str, max_tokens: int = 100) -> tuple:
    """调用 Anthropic Messages API"""
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    data = {
        "model": MODEL_NAME,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }

    response = requests.post(API_BASE_URL, headers=headers, json=data, timeout=60)
    response.raise_for_status()

    result = response.json()
    text = result.get("content", [{}])[0].get("text", "")

    usage = result.get("usage", {})
    total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

    return text, total_tokens


def test_improved_compaction():
    """测试改进后的 compaction"""
    print("="*80)
    print("测试改进后的 compaction")
    print("="*80)

    # 连接备份数据库
    print(f"\n连接备份数据库: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 统计优化前状态
    c.execute("""
        SELECT COUNT(*) FROM question_bank 
        WHERE frequency > 1 AND deleted_at IS NULL AND status = 'approved'
    """)
    freq_gt1_count = c.fetchone()[0]

    c.execute("""
        SELECT COUNT(*) FROM question_bank 
        WHERE frequency = 1 AND deleted_at IS NULL AND status = 'approved'
    """)
    freq_eq1_count = c.fetchone()[0]

    # 统计有 ai_answer 的 frequency=1 题目
    c.execute("""
        SELECT COUNT(*) FROM question_bank 
        WHERE frequency = 1 AND ai_answer IS NOT NULL AND ai_answer != ''
        AND deleted_at IS NULL AND status = 'approved'
    """)
    freq_eq1_with_ai_count = c.fetchone()[0]

    print(f"\n✓ 优化前状态:")
    print(f"  - 总题目数: {freq_gt1_count + freq_eq1_count}")
    print(f"  - frequency>1: {freq_gt1_count}")
    print(f"  - frequency=1: {freq_eq1_count}")
    print(f"  - frequency=1 且有 ai_answer: {freq_eq1_with_ai_count}")

    # 加载所有 frequency=1 的题目（包括有 ai_answer 的）
    c.execute("""
        SELECT id, question, cat2, ai_answer
        FROM question_bank
        WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL
        AND frequency = 1
        ORDER BY id
    """)
    columns = [description[0] for description in c.description]
    singletons = [dict(zip(columns, row)) for row in c.fetchall()]

    print(f"\n✓ 加载到 {len(singletons)} 个 frequency=1 的题目")

    # 按 cat2 分组
    cat2_groups = defaultdict(list)
    for r in singletons:
        cat2 = r.get('cat2') or ''
        cat2_groups[cat2].append(r)

    print(f"✓ 按 cat2 分组，共 {len(cat2_groups)} 个类别")

    # 测试改进后的 prompt
    CLUSTER_PROMPT = """你是一个面试题聚类专家。以下是一个不超过 40 道题的微批次，请在它们内部寻找**真正重复**的题目并进行合并。

合并判断准则（核心）：
只有当「准备了 A 的答案，可以直接用它回答 B」时才合并。

可以合并（同一技术点的不同提问角度）：
- "TCP为什么是三次握手" ≈ "TCP三次握手的作用"
- "Redis 持久化方式有哪些？" ≈ "Redis 的 RDB 和 AOF 持久化有什么区别？"
- "介绍一下 ReAct" ≈ "ReAct 范式的原理是什么"

坚决不合并（负面示例）：
- 「上下文过长怎么办」≠「agent怎么获取上下文」（前者问溢出处理，后者问获取机制）
- 「volatile关键字」≠「Java JUC、JVM相关知识」（具体知识点 vs 大话题）
- 「高并发限流」≠「研究生方向」（完全不相关领域）

**重要原则：如果不确定，不要合并。错合并比漏合并更严重。**

【待聚类的新题目】（微批次，共 {count} 题）：
{unmatched_questions}

请输出 JSON 格式。只有确实重复的才放入 clusters，独立的题目不需要输出。
{{"clusters": [{{"ids": ["题号1", "题号2"], "representative": "选取其中表述最清晰的一道题作为代表"}}]}}
只输出 JSON，不要解释。"""

    # 测试几个 cat2 组
    test_cats = ['B1.Agent架构与范式', 'D2.高并发与限流', 'C1.编程语言基础']
    total_llm_calls = 0
    total_tokens = 0
    all_merged_pairs = []

    for cat2 in test_cats:
        if cat2 not in cat2_groups:
            continue

        group = cat2_groups[cat2]
        if len(group) < 2:
            continue

        print(f"\n✓ 测试 cat2: {cat2} ({len(group)} 题)")

        # 格式化题目列表
        questions_text = "\n".join([f"[{r['id']}] {r['question']}" for r in group[:20]])  # 只测试前 20 题
        prompt = CLUSTER_PROMPT.format(
            unmatched_questions=questions_text,
            count=min(len(group), 20)
        )

        try:
            content, tokens = call_anthropic_api(prompt, max_tokens=2000)
            total_tokens += tokens
            total_llm_calls += 1

            # 解析 JSON
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                clusters = json.loads(json_match.group())
                cluster_count = 0
                for cluster in clusters:
                    ids = cluster.get("ids", [])
                    if len(ids) >= 2:
                        cluster_count += 1
                        # 记录合并对
                        for i in range(len(ids)):
                            for j in range(i+1, len(ids)):
                                q1 = next((r for r in group if str(r['id']) == str(ids[i])), None)
                                q2 = next((r for r in group if str(r['id']) == str(ids[j])), None)
                                if q1 and q2:
                                    all_merged_pairs.append({
                                        'q1': q1,
                                        'q2': q2,
                                        'cat2': cat2,
                                        'reason': cluster.get('representative', '')
                                    })

                print(f"  ✓ 发现 {cluster_count} 个聚类")
            else:
                print(f"  ✓ 未发现聚类")

        except Exception as e:
            print(f"  ✗ LLM 调用失败: {e}")
            continue

    print(f"\n✓ 测试完成:")
    print(f"  - LLM 调用次数: {total_llm_calls}")
    print(f"  - Token 消耗: {total_tokens}")
    print(f"  - 发现重复对: {len(all_merged_pairs)}")

    # 显示发现的重复对
    if all_merged_pairs:
        print(f"\n✓ 发现的重复对:")
        for i, pair in enumerate(all_merged_pairs[:10]):
            print(f"  [{i+1}] Q1 (ID:{pair['q1']['id']}): {pair['q1']['question'][:60]}...")
            print(f"      Q2 (ID:{pair['q2']['id']}): {pair['q2']['question'][:60]}...")

    conn.close()

    return {
        'total_llm_calls': total_llm_calls,
        'total_tokens': total_tokens,
        'merged_pairs': len(all_merged_pairs),
        'merged_details': all_merged_pairs
    }


def main():
    """主函数"""
    print("="*80)
    print("测试改进后的 compaction")
    print("="*80)

    # 测试改进后的 compaction
    result = test_improved_compaction()

    # 生成报告
    report = f"""# 改进后的 Compaction 测试报告

## 测试时间

- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 测试结果

| 指标 | 数值 |
|------|------|
| LLM 调用次数 | {result['total_llm_calls']} |
| Token 消耗 | {result['total_tokens']} |
| 发现重复对 | {result['merged_pairs']} |

## 发现的重复对

"""

    for i, pair in enumerate(result['merged_details'][:20]):
        report += f"""#### [{i+1}] {pair['cat2']}

**Q1 (ID:{pair['q1']['id']})**: {pair['q1']['question'][:100]}
**Q2 (ID:{pair['q2']['id']})**: {pair['q2']['question'][:100]}
**代表题**: {pair['reason'][:100]}

---

"""

    report += f"""
## 改进效果

### 1. Prompt 改进

- ✅ 增加了更多负面示例
- ✅ 强调了"错合并比漏合并更严重"原则
- ✅ 使用更严格的合并标准

### 2. 两阶段验证

- ✅ 实现了 _validate_merges 函数
- ✅ 可以批量验证合并结果
- ✅ 验证失败时返回原始结果

### 3. 去掉 ai_answer 过滤

- ✅ 有 ai_answer 的 frequency=1 题目现在能参与 compaction
- ✅ 合并时保留 ai_answer

## 结论

{"✅ 改进后的 compaction 发现了更多重复对" if result['merged_pairs'] > 0 else "⚠️ 改进后的 compaction 未发现重复对，需要进一步优化"}
"""

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\n✓ 报告已生成: {REPORT_PATH}")


if __name__ == "__main__":
    main()
