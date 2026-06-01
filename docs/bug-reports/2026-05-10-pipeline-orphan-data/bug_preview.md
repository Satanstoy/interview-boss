# Bug 预览报告

**日期:** 2026-05-10
**问题:** 两段式流水相关接口在处理业务逻辑时会在数据库中留下孤儿数据，影响聚类质量
**严重程度:** High

## 初步诊断

### 问题现象
1. 删除 QB 题目后，其他 QB 记录的 `original_question_sources` 中残留已删除题目的引用
2. 批量删除 QB 题目时，完全不清理其他 QB 记录中的 stale 引用
3. 流水线聚类失败后，队列项永久卡在 'processing' 状态，阻塞后续聚类

### 根本原因
1. `delete_master_question` 清理了 `original_questions` 但遗漏了 `original_question_sources`
2. `batch_delete_master_bank` 没有任何 stale oqs 清理逻辑
3. 队列缺少超时恢复机制，'processing' 状态无自动回退

### 影响范围
- **功能:** 聚类质量下降、队列阻塞
- **用户:** 所有用户（公共题库受影响）
- **数据:** original_question_sources 中残留无效引用，frequency 可能虚高

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 数据完整性 | High | oqs_sources 残留已删除题目的来源信息 |
| 功能中断 | Medium | processing 队列卡住导致聚类流水停止 |
| 聚类质量 | Medium | stale 引用可能干扰 LLM 聚类决策 |
