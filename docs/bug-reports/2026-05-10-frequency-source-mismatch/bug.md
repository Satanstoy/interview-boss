# Bug 详细分析报告

**Bug ID:** BUG-001, BUG-002
**发现日期:** 2026-05-10
**状态:** 已确认

## 问题概述

题库卡片左侧"频率"数字与"来源详情"显示的数量不一致。频率始终等于去重后的 URL 数（通过动态 SQL 计算），而来源详情在聚类题目上显示的是原始问题文本数量（`original_questions.length`），二者语义完全不同。

## 根本原因分析

### BUG-001: sourceCount 计算逻辑与 frequency 语义不一致

- **位置:** `frontend/src/components/QuestionCard.vue:254-258`
- **症状:** 聚类题目的频率数字（如 3）与"来源详情 N条"（如 5）不一致
- **根因:**
  ```javascript
  // QuestionCard.vue:254-258
  const sourceCount = computed(() => {
    const q = props.question
    if (q.original_questions && q.original_questions.length > 0) return q.original_questions.length  // ← BUG: 返回的是原始问题文本数量
    if (q.sources && q.sources.length > 0) return q.sources.length
    return 0
  })
  ```
  - `frequency` = 动态 SQL 计算的去重 URL 数（`get_dynamic_frequency_sql()`），等同于 `sources.length`
  - `sourceCount` = `original_questions.length`（聚类前有多少条原始问题文本）
  - 场景举例：5 条原始问题中有 3 条来自同一份面经（同一 URL），则 `frequency=3` 但 `sourceCount=5`

- **影响:** 所有聚类题目（2+ 条原始问题合并的题目）均显示不一致的数字
- **严重程度:** P1

### BUG-002: original_question_sources 未按 bank_mode 过滤

- **位置:** `backend/app/routers/master_bank.py:90-108`
- **症状:** 在 personal/mixed 模式下，sources 被过滤但 original_question_sources 包含不属于当前模式的来源
- **根因:**
  ```python
  # master_bank.py:98 — sources 已过滤
  d['sources'] = filter_sources_by_mode(raw_sources, bank_mode, user['id'])
  # master_bank.py:104 — original_question_sources 完全未过滤！
  d['original_question_sources'] = json.loads(d['original_question_sources']) if d['original_question_sources'] else []
  ```
  - `sources` 调用了 `filter_sources_by_mode()` 按模式过滤
  - `original_question_sources` 直接 JSON 反序列化，未做任何过滤
  - 结果：展开来源详情时，能看到不属于当前 bank_mode 的来源

- **影响:** personal/mixed 模式下来源详情数据泄露（显示了不应可见的来源）
- **严重程度:** P2

## 增量场景下的数据污染风险

当用户重建题库后增量分析新面经时：

1. **`_apply_incremental_txn()`** (operations.py:150) 中：
   - 匹配到已有题目时，往 `sources` 追加新 URL，`frequency = len(sources)` ✅ 正确
   - 往 `original_questions` 追加新问题文本（如果不在列表中）
   - 往 `original_question_sources` 追加新问题及其来源

2. **数据不会相互污染：** 每条面经的 URL 唯一，sources 按 URL 去重，incremental update 用 `existing_urls` set 检查重复。原始问题按文本去重（`new_q_text not in orig_qs`）。

3. **真正的污染风险在显示层：** 即使数据完全正确，BUG-001 导致显示的数字不对。修复 sourceCount 计算即可消除。

## 复现步骤

1. 重建题库（含聚类）
2. 查看任何聚类题目的卡片
3. 左侧"频率"显示 N，展开"来源详情"显示 M
4. 当 N ≠ M 时 bug 复现（N = 去重 URL 数，M = 原始问题文本数）

## 修复建议

见 `fix_bug_plan.md`
