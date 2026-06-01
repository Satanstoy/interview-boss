# Bug 预览报告

**日期:** 2026-05-10
**问题:** 前端题库卡片上"频率"数字与"来源详情"数量不一致
**严重程度:** High

## 初步诊断

### 问题现象
在题库列表中，每道题卡片左侧显示的"频率"数字（如 3）与点击展开后"来源详情 N条"的数字（如 5）不一致。用户期望这两个数字始终相同，因为它们都应该表示"这道题在多少份面经中出现过"。

### 根本原因
存在两个独立的数据不一致源：

**BUG-001: `sourceCount` 计算逻辑错误**
- `QuestionCard.vue` 的 `sourceCount` 计算属性在有 `original_questions` 时返回 `original_questions.length`（聚类前的原始问题文本数）
- `frequency` 来自后端动态 SQL，始终等于去重后的 URL 数（`sources.length`）
- 当多个原始问题来自同一份面经时（同一 URL），`original_questions.length > sources.length`

**BUG-002: `original_question_sources` 未按 bank_mode 过滤**
- GET `/api/master-bank` 端点用 `filter_sources_by_mode()` 过滤了 `sources`
- 但 `original_question_sources` 完全未过滤，直接返回原始数据
- 在 personal/mixed 模式下，`sources` 被过滤缩短，但 `original_question_sources` 未变

### 影响范围
- **功能:** 题库列表中每张题卡的频率数字与来源详情数量显示不一致
- **用户:** 所有使用题库功能的用户（公共/个人/混合模式均受影响）
- **数据:** 不影响数据完整性，仅为显示层问题

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Medium | 不影响核心功能但影响用户信任度 |
| 数据完整性 | Low | 数据本身正确，仅显示层计算有误 |
| 安全风险 | None | 无安全风险 |
