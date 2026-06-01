# Bug 预览报告

**日期:** 2026-05-08
**问题:** 管理员点击"AI生成答案"时返回404错误"请求的资源不存在"
**严重程度:** High

## 初步诊断

### 问题现象
管理员在高频题库中点击"AI生成答案"按钮时，系统返回错误"生成失败: 请求的资源不存在"。该问题在管理员使用公共模式浏览题库时出现。

### 根本原因
`generate_master_answer` 端点使用 `_build_bank_where_clause` 函数构建查询条件，该函数会 JOIN `question_position` 表进行岗位过滤。如果题目在 `question_position` 表中没有对应记录，查询将返回空结果，导致404错误。

具体问题代码 (`master_bank.py:781-788`):
```python
from_clause, where_clause, base_params = _build_bank_where_clause(user, "qb")

def _get():
    with get_db_connection() as conn:
        return conn.execute(
            f"SELECT qb.question, qb.ai_answer {from_clause} WHERE qb.id = ? AND {where_clause[6:]}",
            [question_id] + base_params
        ).fetchone()
```

`_build_bank_where_clause` 返回的 `from_clause` 包含:
```sql
FROM question_bank qb JOIN question_position qp ON qb.id = qp.question_id AND qp.position_id = ?
```

如果题目没有在 `question_position` 表中注册，JOIN 会过滤掉该题目。

### 影响范围
- **功能:** AI生成答案、批量生成答案、随机抽题等使用 `_build_bank_where_clause` 的端点
- **用户:** 所有用户（管理员和普通用户）
- **数据:** 不影响数据完整性，只是查询被过度过滤

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | High | AI生成功能完全不可用 |
| 数据完整性 | Low | 不影响数据 |
| 安全风险 | Low | 无安全风险 |
