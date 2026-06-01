# Bug 详细分析报告

**Bug ID:** BUG-001, BUG-002
**发现日期:** 2026-05-10
**状态:** 已确认

## 问题概述

来源详情展示有两个独立 Bug：[原文]链接指向错误 URL，以及收起/展开时来源数量不一致。

## 根本原因分析

### BUG-001: [原文]链接指向错误 URL

- **位置:** `backend/app/db/operations.py:189-191`
- **症状:** 展开来源详情后，某个原始问题的 [原文] 链接不指向该问题实际出现的面经 URL
- **根因:**
  ```python
  # operations.py:189-191
  if new_q_text and new_q_text not in orig_qs:
      orig_qs.append(new_q_text)
      orig_qs_src.append({"question": new_q_text, "sources": [new_source]})
  # 当 new_q_text 已在 orig_qs 中时，上面整个 if 块被跳过
  # 新 URL 不会合并到已有的 original_question_sources 条目中
  ```
  - 重建时 `original_question_sources` 结构：每条 question 只有 1 个 source
  - 增量更新时：相同问题文本从新 URL 出现，但 `original_question_sources` 不更新
  - 结果：`sources` 有新 URL，`original_question_sources` 仍指向旧 URL
  - 前端 `getOrigSources(oq)` 从 `original_question_sources` 取源 → 拿到旧 URL

- **影响:** 增量更新后，已存在聚类题目的来源链接可能指向错误 URL
- **严重程度:** P1

### BUG-002: 收起显示 N 条，展开显示 M 条

- **位置:** `frontend/src/components/QuestionCard.vue:136` vs `:141-167`
- **症状:** "来源详情 3条" badge 显示 3，展开后实际显示 4 条来源卡片
- **根因:**
  - Badge 计算：`sourceCount = sources.length`（按 URL 去重后的列表，= 3）
  - 展开渲染：`v-for="oq in original_questions"` + `getOrigSources(oq)`（按问题文本遍历，= 4 条目）
  - 语义不同：`sources` 按 URL 去重，`original_question_sources` 按问题文本存储（多个问题可来自同一 URL，但这里每个问题独立算一条）

  数据结构示例：
  ```json
  sources: [
    {"url": "a.com"},  // 来源 1
    {"url": "b.com"},  // 来源 2
    {"url": "c.com"}   // 来源 3
  ]
  original_question_sources: [
    {"question": "Q1", "sources": [{"url": "a.com"}]},
    {"question": "Q2", "sources": [{"url": "a.com"}]},  // 与 Q1 同 URL
    {"question": "Q3", "sources": [{"url": "b.com"}]},
    {"question": "Q4", "sources": [{"url": "c.com"}]}
  ]
  // sources.length = 3, original_question_sources 条目数 = 4
  ```

- **影响:** 用户困惑，收起和展开看到的数量不一致
- **严重程度:** P2

## 复现步骤

### BUG-001
1. 重建题库（含聚类），假设题目 "什么是微服务" 来自小红书面经
2. 上传新面经（来自知乎），其中也包含 "什么是微服务"
3. 增量匹配成功，sources 正确添加了知乎 URL
4. 展开来源详情 → "什么是微服务" 的 [原文] 仍指向小红书（旧 URL）

### BUG-002
1. 重建题库，聚类结果：4 个原始问题来自 3 个不同 URL
2. 查看题卡 → badge 显示"3条"
3. 展开来源详情 → 实际显示 4 条（按 original_question_sources 条目数）
4. 3 ≠ 4，bug 复现

## 修复建议

见 `fix_bug_plan.md`
