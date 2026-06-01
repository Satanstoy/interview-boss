# Bug 详细分析报告

**Bug ID:** BUG-001
**发现日期:** 2026-05-08
**状态:** 已确认

## 问题概述
知识图谱功能失效，管理员无法切换到公共或个人模式。根本原因是 SQL 语法错误导致混合模式查询失败，以及 Analytics 查询缺少软删除过滤。

## 根本原因分析

### BUG-001: SQL 括号不匹配导致混合模式查询失败
- **位置:** `backend/app/routers/master_bank.py:63`
- **症状:** 混合模式下所有题库查询返回 500 错误
- **根因:** SQL WHERE 子句中括号不匹配，`qb.owner_id = ?` 后有多余的 `)`
- **影响:** 
  - `GET /api/master-bank` - 主题库列表
  - `GET /api/master-bank/search` - 搜索
  - `POST /api/master-bank/toggle-star/{id}` - 收藏
  - `GET /api/master-bank/random` - 随机抽题
- **严重程度:** P0 (Critical)

**代码对比:**

```python
# 第 56 行（fallback 路径，正确）:
return from_clause, f"WHERE (({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR {prefix}owner_id = ?) AND {prefix}job_position = ? AND {deleted_filter}", [uid, pos_fallback]

# 第 63 行（主路径，错误）:
return from_clause, f"WHERE ({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR {prefix}owner_id = ?) AND {deleted_filter}", from_params + [uid]
```

**差异**: 第 56 行有 `((` 两个左括号，第 63 行只有一个 `(`。

### BUG-002: Analytics 查询缺少软删除过滤
- **位置:** `backend/app/routers/analytics.py:39-44`
- **症状:** 已删除的题目仍出现在分析结果和知识图谱中
- **根因:** `_build_analytics_bank_filter` 函数没有添加 `deleted_at IS NULL` 条件
- **影响:** 
  - `GET /api/knowledge-graph` - 知识图谱
  - `GET /api/analytics` - 统计分析
  - 所有使用 `_build_analytics_bank_filter` 的查询
- **严重程度:** P1 (High)

**代码对比:**

```python
# analytics.py 第 39-44 行（缺少 deleted_at 过滤）:
if mode == 'personal':
    return join_clause, "WHERE qb.owner_id = ?", join_params + [uid]
elif mode == 'mixed':
    return join_clause, "WHERE (qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ?", join_params + [uid]
else:
    return join_clause, "WHERE qb.owner_id IS NULL AND qb.status = 'approved'", join_params

# master_bank.py 第 60-65 行（有 deleted_at 过滤）:
if mode == 'personal':
    return from_clause, f"WHERE {prefix}owner_id = ? AND {deleted_filter}", from_params + [uid]
elif mode == 'mixed':
    return from_clause, f"WHERE ({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR {prefix}owner_id = ?) AND {deleted_filter}", from_params + [uid]
else:  # 'public'
    return from_clause, f"WHERE {prefix}owner_id IS NULL AND {prefix}status = 'approved' AND {deleted_filter}", from_params
```

## 复现步骤

### BUG-001 复现
1. 登录系统
2. 将题库模式切换为"混用"
3. 访问题库页面
4. **预期**: 正常显示题目列表
5. **实际**: 页面报错或显示空列表

### BUG-002 复现
1. 登录系统
2. 删除一些题目
3. 访问知识图谱页面
4. **预期**: 已删除题目不应出现
5. **实际**: 已删除题目仍显示在图谱中

## 修复建议

### BUG-001 修复
在 `master_bank.py` 第 63 行添加缺失的左括号：
```python
# 修复前:
f"WHERE ({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR {prefix}owner_id = ?) AND {deleted_filter}"

# 修复后:
f"WHERE (({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR {prefix}owner_id = ?) AND {deleted_filter}"
```

### BUG-002 修复
在 `analytics.py` 的 `_build_analytics_bank_filter` 函数中添加 `deleted_at IS NULL` 过滤：
```python
if mode == 'personal':
    return join_clause, "WHERE qb.owner_id = ? AND qb.deleted_at IS NULL", join_params + [uid]
elif mode == 'mixed':
    return join_clause, "WHERE ((qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ?) AND qb.deleted_at IS NULL", join_params + [uid]
else:
    return join_clause, "WHERE qb.owner_id IS NULL AND qb.status = 'approved' AND qb.deleted_at IS NULL", join_params
```
