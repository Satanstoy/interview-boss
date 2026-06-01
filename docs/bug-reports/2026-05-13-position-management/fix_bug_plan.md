# 修复计划

**Bug ID:** BUG-001, BUG-002
**日期:** 2026-05-13
**优先级:** P1 (High)

## 修复步骤

### 步骤 1: 修复 switch_position 端点的 ON CONFLICT 问题
**文件:** `backend/app/routers/profile.py`
**行号:** 536-541
**修改类型:** 修正

**修改前:**
```python
conn.execute(
    "INSERT INTO taxonomy (position_name, categories_json, updated_at) "
    "VALUES (?, ?, CURRENT_TIMESTAMP) "
    "ON CONFLICT(position_name) DO NOTHING",
    (position_name, _json.dumps([], ensure_ascii=False))
)
```

**修改后:**
```python
conn.execute(
    "INSERT INTO taxonomy (position_name, categories_json, source, owner_id, updated_at) "
    "VALUES (?, ?, 'system', NULL, CURRENT_TIMESTAMP) "
    "ON CONFLICT(position_name, source, owner_id) DO NOTHING",
    (position_name, _json.dumps([], ensure_ascii=False))
)
```

### 步骤 2: 添加岗位删除后端端点（软删除）
**文件:** `backend/app/routers/profile.py`
**修改类型:** 新增

```python
@router.delete("/api/profile/position/{position_name}")
async def delete_position(position_name: str, admin: dict = Depends(get_admin_user)):
    """软删除岗位（仅管理员）"""
    def _delete():
        with get_db_connection() as conn:
            # 检查岗位是否存在
            row = conn.execute("SELECT id FROM job_positions WHERE name = ?", (position_name,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="岗位不存在")

            # 软删除：在 job_positions 表标记 is_deleted
            # 如果表没有 is_deleted 字段，需要先添加
            cols = {r[1] for r in conn.execute("PRAGMA table_info('job_positions')").fetchall()}
            if 'is_deleted' not in cols:
                conn.execute("ALTER TABLE job_positions ADD COLUMN is_deleted INTEGER DEFAULT 0")

            conn.execute(
                "UPDATE job_positions SET is_deleted = 1, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
                (position_name,)
            )
            conn.commit()
            return True

    await run_db(_delete)
    return {"status": "success", "message": f"岗位 '{position_name}' 已删除"}
```

### 步骤 3: 修改 _get_available_positions 排除已删除岗位
**文件:** `backend/app/routers/profile.py`
**行号:** 31-48
**修改类型:** 修正

**修改前:**
```python
pos_rows = conn.execute("SELECT name FROM job_positions ORDER BY name").fetchall()
```

**修改后:**
```python
pos_rows = conn.execute("SELECT name FROM job_positions WHERE is_deleted = 0 OR is_deleted IS NULL ORDER BY name").fetchall()
```

### 步骤 4: 添加前端删除按钮
**文件:** `frontend/src/components/SettingsPanel.vue`
**修改类型:** 新增

在岗位标签旁添加删除按钮（仅管理员可见）。

### 步骤 5: 添加前端删除 API 调用
**文件:** `frontend/src/api/index.js`
**修改类型:** 新增

```javascript
export const deletePosition = (position) => del(`${API}/profile/position/${encodeURIComponent(position)}`)
```

## 验证方法
1. 运行测试: `/root/.local/bin/uv run pytest backend/tests/test_position_management.py -v`
2. 在前端测试：添加新岗位、删除岗位

## 回滚方案
恢复原始代码。
