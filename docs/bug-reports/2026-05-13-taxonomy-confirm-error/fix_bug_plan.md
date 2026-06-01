# 修复计划

**Bug ID:** BUG-001
**日期:** 2026-05-13
**优先级:** P0 (Critical)

## 修复步骤

### 步骤 1: 修改 save_taxonomy_for_position 函数
**文件:** `backend/app/db/connection.py`
**行号:** 1033-1045
**修改类型:** 修正

**修改前:**
```python
def save_taxonomy_for_position(position_name: str, categories: list):
    """UPSERT taxonomy 到 taxonomy 表"""
    import json as _json
    with get_db_connection() as conn:
        categories_json = _json.dumps(categories, ensure_ascii=False)
        conn.execute(
            "INSERT INTO taxonomy (position_name, categories_json, updated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(position_name) DO UPDATE SET "
            "categories_json = excluded.categories_json, updated_at = CURRENT_TIMESTAMP",
            (position_name, categories_json)
        )
        conn.commit()
```

**修改后:**
```python
def save_taxonomy_for_position(position_name: str, categories: list, source: str = 'system', owner_id: int = None):
    """UPSERT taxonomy 到 taxonomy 表

    Args:
        position_name: 岗位名称
        categories: 分类列表
        source: 来源 ('system' 或 'user')
        owner_id: 用户ID (仅 user 来源时需要)
    """
    import json as _json
    with get_db_connection() as conn:
        categories_json = _json.dumps(categories, ensure_ascii=False)
        conn.execute(
            "INSERT INTO taxonomy (position_name, categories_json, source, owner_id, updated_at) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(position_name, source, owner_id) DO UPDATE SET "
            "categories_json = excluded.categories_json, updated_at = CURRENT_TIMESTAMP",
            (position_name, categories_json, source, owner_id)
        )
        conn.commit()
```

## 验证方法
1. 运行测试: `/root/.local/bin/uv run pytest backend/tests/test_taxonomy_confirm_error.py -v`
2. 在前端测试: 采纳 AI 生成的分类，确认保存成功

## 回滚方案
将 `save_taxonomy_for_position` 函数恢复为原始代码。
