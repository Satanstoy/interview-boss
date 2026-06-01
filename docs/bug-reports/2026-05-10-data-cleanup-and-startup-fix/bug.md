# Bug 详细分析报告

**Bug ID:** BUG-001, BUG-002
**发现日期:** 2026-05-10
**状态:** 已修复

## 问题概述

重建题库后数据质量检查发现两类问题。

### BUG-001: 23 条 frequency=0 的孤立题目
- **位置:** question_bank 表
- **根因:** 早期数据迁移或失败操作残留
- **修复:** 直接删除（无关联的 question_position/user_question_view/practice_history 数据）
- **严重程度:** P3

### BUG-002: 5 条 oqs 包含已删除面经的 URL
- **位置:** question_bank.original_question_sources
- **根因:** 重建时 sources 正确过滤了已软删除的面经 URL，但 original_question_sources 未同步清理
- **修复:** 手动清理 + 添加启动自动修复逻辑（connection.py init_db）
- **严重程度:** P2

## 所有代码路径验证

| 操作 | frequency 来源 | sources 去重 | oqs 一致性 | 结论 |
|------|---------------|-------------|-----------|------|
| 重建题库 | len(sources) | 按 URL | 构建时同步 | 安全 |
| 增量更新 | len(sources) | 按 URL 检查 | 合并新 URL | 安全 |
| 新建题目 | 1 | 1 条 | 空 | 安全 |
| 删除面经 | len(sources) | 移除 URL | 未动（启动修复兜底）| 安全 |
| 恢复面经 | len(sources) | 从 oqs 恢复 | 来源 | 安全 |
| 拆分题目 | len(sources) | 按 URL 去重 | 同步更新 | 安全 |
| 合并题目 | len(sources) | 按 URL 去重 | 同步更新 | 安全 |
| 启动自动修复 | len(sources) | N/A | 清理孤立 URL | 安全 |
| GET 端点 | 动态 SQL | filter_sources_by_mode | filter_oqs_by_mode | 安全 |
