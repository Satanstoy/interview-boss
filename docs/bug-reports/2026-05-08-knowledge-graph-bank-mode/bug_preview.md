# Bug 预览报告

**日期:** 2026-05-08
**问题:** 知识图谱失效 + 管理员无法切换到公共/个人模式
**严重程度:** Critical

## 初步诊断

### 问题现象
1. **知识图谱失效**: 用户访问知识图谱页面时，图表无法正常加载或显示为空
2. **管理员模式切换失败**: 管理员尝试切换到公共或个人模式时，切换失败或数据无法加载

### 根本原因

#### BUG-001: SQL 语法错误导致混合模式查询失败
**位置**: `backend/app/routers/master_bank.py:63`

**技术原因**: `_build_bank_where_clause` 函数在构建 `mixed` 模式的 SQL 查询时，括号不匹配：

```python
# 第 63 行（有 bug）:
return from_clause, f"WHERE ({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR {prefix}owner_id = ?) AND {deleted_filter}", from_params + [uid]
```

生成的 SQL:
```sql
WHERE (qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ?) AND qb.deleted_at IS NULL
```

**问题**: `qb.owner_id = ?` 后面有一个多余的 `)`，导致 SQLite 语法错误。

正确的 SQL 应该是:
```sql
WHERE ((qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ?) AND qb.deleted_at IS NULL
```

#### BUG-002: Analytics 查询缺少软删除过滤
**位置**: `backend/app/routers/analytics.py:39-44`

**技术原因**: `_build_analytics_bank_filter` 函数在所有三种模式下都缺少 `deleted_at IS NULL` 过滤条件，导致已删除的题目仍会出现在分析结果和知识图谱中。

### 影响范围
- **功能**: 题库查询、知识图谱、搜索、收藏、随机抽题
- **用户**: 所有使用混合模式的用户
- **数据**: 不影响数据完整性，但会导致查询失败或显示已删除数据

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Critical | 混合模式下所有题库相关功能完全失效 |
| 数据完整性 | Low | 不影响数据，但可能显示已删除数据 |
| 安全风险 | Low | 无直接安全风险 |
