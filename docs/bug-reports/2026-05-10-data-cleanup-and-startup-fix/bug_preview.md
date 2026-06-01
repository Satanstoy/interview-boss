# Bug 预览报告

**日期:** 2026-05-10
**问题:** 题库中有 23 条 frequency=0 的孤立题目 + 5 条 original_question_sources 包含已删除面经的 URL
**严重程度:** Medium

## 初步诊断

### 问题现象
1. 重建题库后有 23 条 frequency=0 的题目（无来源、无关联数据）
2. 5 条题目的 original_question_sources 包含一个已软删除面经的 URL，但 sources 中已正确移除

### 根本原因
1. frequency=0 题目来自早期数据迁移或失败操作的残留
2. oqs 孤立 URL 来自重建时 sources 正确过滤了已删除面经，但 original_question_sources 未同步清理

### 影响范围
- **功能:** frequency=0 题目在排序中异常，oqs 孤立 URL 导致展开来源详情时可能显示不存在的面经
- **数据:** 已修复，启动时自动修复逻辑已添加

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 数据完整性 | Low | 已修复并添加启动自动修复 |
