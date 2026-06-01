# Bug 预览报告

**日期:** 2026-05-13
**问题:** 采纳AI分类时服务器内部错误
**严重程度:** Critical

## 初步诊断

### 问题现象
用户在系统配置界面点击"采纳此分类"按钮后，收到"服务器内部错误"提示，AI生成的分类无法保存。

### 根本原因
`save_taxonomy_for_position()` 函数使用 `ON CONFLICT(position_name)` 进行 UPSERT 操作，但数据库的唯一索引已变更为复合索引 `(position_name, source, owner_id)`，导致 SQLite 报错：
```
sqlite3.OperationalError: ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint
```

### 影响范围
- **功能:** AI智能生成分类的采纳功能完全不可用
- **用户:** 所有用户
- **数据:** 不影响数据完整性，但无法保存新分类

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Critical | AI分类采纳功能完全不可用 |
| 数据完整性 | Low | 不影响现有数据 |
| 安全风险 | Low | 无安全风险 |
