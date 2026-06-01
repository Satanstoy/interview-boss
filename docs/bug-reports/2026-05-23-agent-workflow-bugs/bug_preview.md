# Bug 预览报告

**日期:** 2026-05-23
**问题:** Agent 工作流模块（submit/build/batch_generate/shared）存在多处代码缺陷
**严重程度:** High

## 初步诊断

### 问题现象
- submit 流程：分类节点无法加载用户个人分类配置，taxonomy children 解析可能崩溃
- build 流程：清空题库节点使用裸 SQL 事务控制，可能与 SQLite 自动事务冲突
- shared 模块：质量评分函数对多题场景不公平，可能误判质量

### 根本原因
1. `run_db(get_taxonomy_for_position)` 传递函数引用但不传参数，丢失 user_id
2. `cat.get("children", [])` 假设 children 是字符串列表，但实际可能是字典列表
3. `evaluate_tagging_quality` 以固定 10 分为起点逐题扣分，不按题目数归一化
4. `clear_qb_node` 手动 `BEGIN`/`COMMIT` 与 Python sqlite3 自动事务管理冲突
5. 黑名单使用精确匹配，无法过滤 "请做一下自我介绍" 等变体

### 影响范围
- **功能:** submit 分类准确性、build 事务安全性、质量评分公平性
- **用户:** 所有提交面经的用户、使用题库重建功能的管理员
- **数据:** 不影响数据完整性，但影响分类结果准确性

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Medium | 分类节点无法使用个人分类配置 |
| 数据完整性 | Low | 事务管理不当可能导致部分写入 |
| 安全风险 | Low | 黑名单过滤不完全 |
| 评分公平性 | Medium | 多题场景评分偏低导致不必要的重试 |
