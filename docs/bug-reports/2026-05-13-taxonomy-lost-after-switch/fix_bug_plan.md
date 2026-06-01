# 修复计划

**Bug ID:** BUG-001, BUG-002, BUG-003
**日期:** 2026-05-13
**优先级:** P1 (High)

## 修复步骤

### 步骤 1: 修改 get_taxonomy_for_position 函数
**文件:** `backend/app/db/connection.py`
**行号:** 1007-1030
**修改类型:** 修正

**修改前:**
```python
def get_taxonomy_for_position(position: str = None) -> dict:
    """从 taxonomy 表读取岗位分类配置，fallback 链: position 行 → default 行 → 常量"""
    import json as _json
    from app.core.prompts import DEFAULT_TAXONOMY
    if position is None:
        position = get_current_job_position()
    try:
        with get_db_connection() as conn:
            # 1. 按岗位名查找
            row = conn.execute(
                "SELECT categories_json FROM taxonomy WHERE position_name = ?", (position,)
            ).fetchone()
            if row and row['categories_json']:
                return {"job_position": position, "categories": _json.loads(row['categories_json'])}
            # 2. fallback 到默认行
            row2 = conn.execute(
                "SELECT position_name, categories_json FROM taxonomy WHERE is_default = 1"
            ).fetchone()
            if row2 and row2['categories_json']:
                return {"job_position": row2['position_name'], "categories": _json.loads(row2['categories_json'])}
    except Exception:
        pass
    # 3. 最终 fallback 到代码常量
    return DEFAULT_TAXONOMY
```

**修改后:**
```python
def get_taxonomy_for_position(position: str = None, user_id: int = None) -> dict:
    """从 taxonomy 表读取岗位分类配置，fallback 链: 用户个人分类 → 系统默认分类 → 常量

    Args:
        position: 岗位名称
        user_id: 用户ID（用于获取个人分类）
    """
    import json as _json
    from app.core.prompts import DEFAULT_TAXONOMY
    if position is None:
        position = get_current_job_position()
    try:
        with get_db_connection() as conn:
            # 1. 优先查找用户个人分类
            if user_id:
                row = conn.execute(
                    "SELECT categories_json FROM taxonomy WHERE position_name = ? AND source = 'user' AND owner_id = ?",
                    (position, user_id)
                ).fetchone()
                if row and row['categories_json']:
                    return {"job_position": position, "categories": _json.loads(row['categories_json'])}

            # 2. 查找系统默认分类
            row = conn.execute(
                "SELECT categories_json FROM taxonomy WHERE position_name = ? AND source = 'system'",
                (position,)
            ).fetchone()
            if row and row['categories_json']:
                return {"job_position": position, "categories": _json.loads(row['categories_json'])}

            # 3. fallback 到默认行
            row2 = conn.execute(
                "SELECT position_name, categories_json FROM taxonomy WHERE is_default = 1"
            ).fetchone()
            if row2 and row2['categories_json']:
                return {"job_position": row2['position_name'], "categories": _json.loads(row2['categories_json'])}
    except Exception:
        pass
    # 4. 最终 fallback 到代码常量
    return DEFAULT_TAXONOMY
```

### 步骤 2: 修改 confirm_taxonomy 端点
**文件:** `backend/app/routers/profile.py`
**行号:** 414-429
**修改类型:** 修正

**修改前:**
```python
@router.post("/api/profile/taxonomy/confirm")
async def confirm_taxonomy(req: dict, user: dict = Depends(get_current_user)):
    """用户确认采纳AI生成的分类体系（覆盖当前分类）"""
    from app.services.taxonomy_suggest import save_taxonomy_suggestion
    from app.db.connection import get_user_job_position

    categories = req.get("categories")
    if not categories or not isinstance(categories, list):
        raise HTTPException(status_code=400, detail="需要提供 categories 列表")

    # 获取用户的个人岗位，而不是全局岗位
    _, position = await run_db(lambda: get_user_job_position(user['id']))
    if not position:
        raise HTTPException(status_code=400, detail="请先选择目标岗位")

    await run_db(lambda: save_taxonomy_suggestion(position, categories))
    return {"status": "success", "position": position}
```

**修改后:**
```python
@router.post("/api/profile/taxonomy/confirm")
async def confirm_taxonomy(req: dict, user: dict = Depends(get_current_user)):
    """用户确认采纳AI生成的分类体系（保存为用户个人分类）"""
    from app.db.connection import get_user_job_position, save_taxonomy_for_position

    categories = req.get("categories")
    if not categories or not isinstance(categories, list):
        raise HTTPException(status_code=400, detail="需要提供 categories 列表")

    # 获取用户的个人岗位，而不是全局岗位
    _, position = await run_db(lambda: get_user_job_position(user['id']))
    if not position:
        raise HTTPException(status_code=400, detail="请先选择目标岗位")

    # 保存为用户个人分类
    await run_db(lambda: save_taxonomy_for_position(position, categories, source='user', owner_id=user['id']))
    return {"status": "success", "position": position}
```

### 步骤 3: 修改 profile 端点传递 user_id
**文件:** `backend/app/routers/profile.py`
**行号:** 111
**修改类型:** 修正

**修改前:**
```python
taxonomy_data = await run_db(lambda: get_taxonomy_for_position(current_pos))
```

**修改后:**
```python
taxonomy_data = await run_db(lambda: get_taxonomy_for_position(current_pos, user_id=user['id']))
```

### 步骤 4: 修改 update_profile 端点保存为用户个人分类
**文件:** `backend/app/routers/profile.py`
**行号:** 336
**修改类型:** 修正

**修改前:**
```python
from app.db.connection import save_taxonomy_for_position
await run_db(lambda: save_taxonomy_for_position(position, tc["categories"]))
```

**修改后:**
```python
from app.db.connection import save_taxonomy_for_position
await run_db(lambda: save_taxonomy_for_position(position, tc["categories"], source='user', owner_id=admin['id']))
```

## 验证方法
1. 运行测试: `/root/.local/bin/uv run pytest backend/tests/test_taxonomy_lost_after_switch.py -v`
2. 在前端测试：
   - 测试1: 采纳AI分类 → 切换岗位 → 切换回来 → 验证分类保持
   - 测试2: 采纳AI分类 → 点击"保存全局配置" → 验证分类保持

## 回滚方案
恢复原始代码。
