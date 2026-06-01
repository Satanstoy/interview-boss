# Bug 预览报告

**日期:** 2026-05-10
**问题:** 来源详情中 [原文] 链接指向错误 URL；收起/展开时来源数量不一致
**严重程度:** High

## 初步诊断

### 问题现象

1. **[原文] 链接错误：** 展开题卡的"来源详情"，某个原始问题下显示的 [原文] 链接指向的不是正确的面经 URL（例如应该指向小红书链接却指向了其他链接）。
2. **数量不一致：** 收起时 badge 显示"3条"，展开后实际可见 4 条来源。

### 根本原因

**BUG-001（[原文]链接错误）：**
- 位置：`backend/app/db/operations.py:189-191`
- 增量更新时，`_apply_incremental_txn()` 在 `new_q_text not in orig_qs` 为 False 时跳过 `original_question_sources` 更新
- 如果同一问题文本从新 URL 出现，新 URL 不会记录到 `original_question_sources` 中
- 结果：`sources`（主来源列表）有新 URL，但 `original_question_sources` 仍指向旧 URL

**BUG-002（数量不一致）：**
- 位置：`frontend/src/components/QuestionCard.vue:136` vs `:141`
- 收起 badge 用 `sources.length`（按 URL 去重 = 3）
- 展开用 `original_question_sources` 条目数（按问题文本计 = 4，多个问题可来自同一 URL）
- 两个数据源语义不同：一个是去重 URL 数，一个是原始问题数

### 影响范围
- **功能:** 来源详情的链接跳转和数量显示
- **用户:** 所有查看题库来源详情的用户
- **数据:** `original_question_sources` 数据可能不完整（增量更新场景）

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Medium | 链接错误导致用户无法溯源到正确面经 |
| 数据完整性 | Medium | original_question_sources 在增量更新中可能丢失新 URL |
| 安全风险 | None | 无安全风险 |
