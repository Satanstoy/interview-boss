"""岗位管理端点"""
import re
import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_current_user, get_admin_user
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

router = APIRouter()

_MAX_POSITION_LEN = 30


@router.put("/api/profile/my-position")
async def switch_my_position(req: dict, user: dict = Depends(get_current_user)):
    """普通用户切换个人岗位（仅对自己生效，不写入公共 job_positions 表）"""
    position_name = req.get("position", "").strip()
    if not position_name:
        raise HTTPException(status_code=400, detail="需要提供 position")
    if len(position_name) > _MAX_POSITION_LEN:
        raise HTTPException(status_code=400, detail="岗位名称不能超过 30 个字符")
    if not re.match(r'^[一-龥a-zA-Z0-9\s/\-_()（）]+$', position_name):
        raise HTTPException(status_code=400, detail="岗位名称仅允许中英文、数字、空格、斜杠、连字符和括号")

    def _switch():
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE users SET personal_position = ?, current_position_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (position_name, user['id'])
            )
            conn.commit()

    await run_db(_switch)
    return {
        "status": "success",
        "current_job_position": position_name,
        "current_position": position_name,
        "current_position_id": None,
    }


@router.put("/api/profile/position")
async def switch_position(req: dict, admin: dict = Depends(get_admin_user)):
    """切换当前岗位（支持 position_id 或 position 名称）"""
    position_id = req.get("position_id")
    position_name = req.get("position", "").strip()

    if position_name:
        if len(position_name) > 100:
            raise HTTPException(status_code=400, detail="岗位名称不能超过 100 个字符")
        if not re.match(r'^[一-龥a-zA-Z0-9\s/\-_()（）]+$', position_name):
            raise HTTPException(status_code=400, detail="岗位名称仅允许中英文、数字、空格、斜杠、连字符和括号")

    def _switch():
        with get_db_connection() as conn:
            if position_id:
                row = conn.execute("SELECT id, name FROM job_positions WHERE id = ?", (position_id,)).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="岗位不存在")
                conn.execute("UPDATE users SET current_position_id = ?, personal_position = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row['id'], admin['id']))
                conn.commit()
                return row['name']
            elif position_name:
                row = conn.execute("SELECT id, name FROM job_positions WHERE name = ?", (position_name,)).fetchone()
                if not row:
                    conn.execute("INSERT INTO job_positions (name) VALUES (?)", (position_name,))
                    pos_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    row = {'id': pos_id, 'name': position_name}
                    conn.execute(
                        "INSERT INTO taxonomy (position_name, categories_json, source, owner_id, updated_at) "
                        "VALUES (?, ?, 'system', NULL, CURRENT_TIMESTAMP) "
                        "ON CONFLICT(position_name, source, owner_id) DO NOTHING",
                        (position_name, json.dumps([], ensure_ascii=False))
                    )
                else:
                    cols = {r[1] for r in conn.execute("PRAGMA table_info('job_positions')").fetchall()}
                    if 'is_deleted' in cols:
                        conn.execute("UPDATE job_positions SET is_deleted = 0 WHERE id = ? AND is_deleted = 1", (row['id'],))
                conn.execute("UPDATE users SET current_position_id = ?, personal_position = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row['id'], admin['id']))
                conn.commit()
                return row['name']
            else:
                raise HTTPException(status_code=400, detail="需要提供 position_id 或 position")

    result = await run_db(_switch)
    return {"status": "success", "current_job_position": result}


@router.get("/api/positions")
async def list_positions(user: dict = Depends(get_current_user)):
    """列出所有岗位"""
    def _query():
        with get_db_connection() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info('job_positions')").fetchall()}
            if 'is_deleted' in cols:
                rows = conn.execute(
                    "SELECT id, name, description FROM job_positions "
                    "WHERE is_deleted = 0 OR is_deleted IS NULL ORDER BY name"
                ).fetchall()
            else:
                rows = conn.execute("SELECT id, name, description FROM job_positions ORDER BY name").fetchall()
            return [dict(r) for r in rows]
    positions = await run_db(_query)
    return {"positions": positions}


@router.post("/api/positions")
async def create_position(req: dict, admin: dict = Depends(get_admin_user)):
    """新建岗位"""
    name = req.get("name", "").strip()
    description = req.get("description", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="岗位名称不能为空")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="岗位名称不能超过 100 个字符")
    if not re.match(r'^[一-龥a-zA-Z0-9\s/\-_()（）]+$', name):
        raise HTTPException(status_code=400, detail="岗位名称仅允许中英文、数字、空格、斜杠、连字符和括号")

    def _create():
        with get_db_connection() as conn:
            existing = conn.execute("SELECT id FROM job_positions WHERE name = ?", (name,)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="岗位已存在")
            conn.execute("INSERT INTO job_positions (name, description) VALUES (?, ?)", (name, description))
            pos_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
            return pos_id

    pos_id = await run_db(_create)
    return {"status": "success", "id": pos_id, "name": name}


@router.delete("/api/profile/position/{position_name}")
async def delete_position(position_name: str, admin: dict = Depends(get_admin_user)):
    """软删除岗位（仅管理员）"""
    def _delete():
        with get_db_connection() as conn:
            row = conn.execute("SELECT id FROM job_positions WHERE name = ?", (position_name,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="岗位不存在")

            cols = {r[1] for r in conn.execute("PRAGMA table_info('job_positions')").fetchall()}
            if 'is_deleted' not in cols:
                conn.execute("ALTER TABLE job_positions ADD COLUMN is_deleted INTEGER DEFAULT 0")

            conn.execute("UPDATE job_positions SET is_deleted = 1 WHERE name = ?", (position_name,))
            conn.commit()
            return True

    await run_db(_delete)
    return {"status": "success", "message": f"岗位 '{position_name}' 已删除"}
