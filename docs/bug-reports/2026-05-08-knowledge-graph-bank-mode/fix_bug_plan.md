# 修复计划

**Bug ID:** BUG-001, BUG-002
**日期:** 2026-05-08
**优先级:** P0 (Critical)

## 修复步骤

### 步骤 1: 修复 master_bank.py 中的 SQL 括号错误
**文件:** `backend/app/routers/master_bank.py`
**行号:** 63
**修改类型:** 修正

**修改前:**
```python
elif mode == 'mixed':
    return from_clause, f"WHERE ({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR {prefix}owner_id = ?) AND {deleted_filter}", from_params + [uid]
```

**修改后:**
```python
elif mode == 'mixed':
    return from_clause, f"WHERE (({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR {prefix}owner_id = ?) AND {deleted_filter}", from_params + [uid]
```

### 步骤 2: 修复 analytics.py 中缺少的软删除过滤
**文件:** `backend/app/routers/analytics.py`
**行号:** 39-44
**修改类型:** 修正

**修改前:**
```python
if mode == 'personal':
    return join_clause, "WHERE qb.owner_id = ?", join_params + [uid]
elif mode == 'mixed':
    return join_clause, "WHERE (qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ?", join_params + [uid]
else:
    return join_clause, "WHERE qb.owner_id IS NULL AND qb.status = 'approved'", join_params
```

**修改后:**
```python
if mode == 'personal':
    return join_clause, "WHERE qb.owner_id = ? AND qb.deleted_at IS NULL", join_params + [uid]
elif mode == 'mixed':
    return join_clause, "WHERE ((qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ?) AND qb.deleted_at IS NULL", join_params + [uid]
else:
    return join_clause, "WHERE qb.owner_id IS NULL AND qb.status = 'approved' AND qb.deleted_at IS NULL", join_params
```

## 验证方法
1. 运行 pytest 测试验证 SQL 语法正确性
2. 启动后端服务，测试混合模式下的题库查询
3. 测试知识图谱功能是否正常加载
4. 验证已删除题目不再出现在分析结果中

## 回滚方案
如果修复失败，可以通过 git revert 回滚到修复前的版本：
```bash
git revert HEAD
```
