# Bug 预览报告

**日期:** 2026-05-10
**问题:** 面经删除后高频题库来源未同步清理
**严重程度:** Medium

## 初步诊断

### 问题现象
用户在面经库删除一个面经（如包含"简单介绍agent"的腾讯面经），高频题库中对应题目的来源信息没有被清理，frequency 和 sources 仍显示已删除面经的 URL。

### 根本原因
经代码审查确认，`backend/app/routers/data.py:177-182` 的面经删除端点已在同一事务中调用 `_cleanup_sources_for_url()` 清理 `question_bank.sources`。同时 `filter_original_question_sources_by_mode()` 在 GET 端点自动过滤指向已软删除面经的 `original_question_sources` 条目。

问题可能发生在：
1. 删除操作执行但前端未刷新题库数据（已确认 `fetchTableData` 会刷新 master_bank）
2. 同一面经被上传两次（不同 xsec_token），删除一条后另一条仍存在
3. 服务未加载最新代码（服务启动时间早于代码修改时间）

### 影响范围
- **功能:** 题库来源显示可能不一致
- **数据:** sources 和 frequency 应在删除事务中保持一致

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 数据完整性 | Low | 代码已有事务保护，GET 端点有过滤 |
| 功能中断 | Low | 重启后自动修复孤立 oqs |
