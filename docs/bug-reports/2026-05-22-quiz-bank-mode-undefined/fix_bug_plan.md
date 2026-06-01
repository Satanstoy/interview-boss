# 修复计划

**Bug ID:** BUG-001
**日期:** 2026-05-22
**优先级:** P0

## 修复步骤

### 步骤 1: 添加 bank_mode 变量定义
**文件:** `backend/app/routers/practice.py`
**行号:** 72（在 `_build_bank_where_clause` 调用之后）
**修改类型:** 新增

**修改前:**
```python
    from_clause, where_clause, base_params = _build_bank_where_clause(user, "qb")

    def _query():
```

**修改后:**
```python
    from_clause, where_clause, base_params = _build_bank_where_clause(user, "qb")
    bank_mode = user.get('bank_mode', 'public')

    def _query():
```

## 验证方法
1. 运行 pytest 测试确认修复
2. 启动后端服务，前端点击抽测确认题目正常显示

## 回滚方案
删除添加的一行代码即可回滚
