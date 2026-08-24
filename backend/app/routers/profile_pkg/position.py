"""岗位管理端点"""
import re
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_current_user, get_admin_user
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

router = APIRouter()

_MAX_POSITION_LEN = 30


@router.put("/api/profile/my-position")
async def switch_my_position(req: dict, user: dict = Depends(get_current_user)):
    """普通用户只能切换到管理员登记的 active 岗位。"""
    position_name = req.get("position", "").strip()
    if not position_name:
        raise HTTPException(status_code=400, detail="需要提供 position")
    if len(position_name) > _MAX_POSITION_LEN:
        raise HTTPException(status_code=400, detail="岗位名称不能超过 30 个字符")
    if not re.match(r'^[一-龥a-zA-Z0-9\s/\-_()（）]+$', position_name):
        raise HTTPException(status_code=400, detail="岗位名称仅允许中英文、数字、空格、斜杠、连字符和括号")

    def _switch():
        with get_db_connection() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info('job_positions')").fetchall()}
            deleted_filter = "AND (is_deleted = 0 OR is_deleted IS NULL)" if "is_deleted" in columns else ""
            position_row = conn.execute(
                f"SELECT id, name FROM job_positions WHERE name = ? {deleted_filter}",
                (position_name,),
            ).fetchone()
            if not position_row:
                raise HTTPException(status_code=404, detail="岗位不存在或已下线，请选择系统提供的岗位")
            taxonomy_row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'taxonomy'"
            ).fetchone()
            if taxonomy_row:
                taxonomy_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info('taxonomy')").fetchall()
                }
                tags_filter = "AND tags_json IS NOT NULL AND tags_json != '[]'" if "tags_json" in taxonomy_columns else ""
                configured = conn.execute(
                    "SELECT 1 FROM taxonomy WHERE position_name = ? "
                    "AND source = 'system' AND owner_id IS NULL "
                    "AND categories_json IS NOT NULL AND categories_json != '[]' "
                    f"{tags_filter} LIMIT 1",
                    (position_name,),
                ).fetchone()
                if not configured:
                    raise HTTPException(status_code=409, detail="该岗位尚未配置系统分类，请联系管理员")
            conn.execute(
                "UPDATE users SET personal_position = NULL, current_position_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (position_row["id"], user['id'])
            )
            conn.commit()
            return position_row["name"], position_row["id"]

    position_name, position_id = await run_db(_switch)
    return {
        "status": "success",
        "current_job_position": position_name,
        "current_position": position_name,
        "current_position_id": position_id,
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
            columns = {row[1] for row in conn.execute("PRAGMA table_info('job_positions')").fetchall()}
            deleted_filter = "AND (is_deleted = 0 OR is_deleted IS NULL)" if "is_deleted" in columns else ""
            if position_id:
                row = conn.execute(
                    f"SELECT id, name FROM job_positions WHERE id = ? {deleted_filter}",
                    (position_id,),
                ).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="岗位不存在或已下线")
                conn.execute("UPDATE users SET current_position_id = ?, personal_position = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row['id'], admin['id']))
                conn.commit()
                return row['name']
            elif position_name:
                row = conn.execute(
                    f"SELECT id, name FROM job_positions WHERE name = ? {deleted_filter}",
                    (position_name,),
                ).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="岗位不存在或已下线")
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
            taxonomy_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'taxonomy'"
            ).fetchone()
            if taxonomy_exists and not user.get("is_admin"):
                taxonomy_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info('taxonomy')").fetchall()
                }
                tags_filter = "AND tags_json IS NOT NULL AND tags_json != '[]'" if "tags_json" in taxonomy_columns else ""
                configured = {
                    row["position_name"]
                    for row in conn.execute(
                        "SELECT position_name FROM taxonomy "
                        "WHERE source = 'system' AND owner_id IS NULL "
                        "AND categories_json IS NOT NULL AND categories_json != '[]' "
                        f"{tags_filter}"
                    ).fetchall()
                }
                rows = [row for row in rows if row["name"] in configured]
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
    """下线岗位（仅管理员）；保留岗位、题目和 taxonomy 历史数据。"""
    def _delete():
        with get_db_connection() as conn:
            row = conn.execute("SELECT id FROM job_positions WHERE name = ?", (position_name,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="岗位不存在")

            active_count = conn.execute(
                "SELECT COUNT(*) FROM job_positions WHERE is_deleted = 0 OR is_deleted IS NULL"
            ).fetchone()[0]
            already_retired = conn.execute(
                "SELECT is_deleted FROM job_positions WHERE name = ?", (position_name,)
            ).fetchone()[0]
            if already_retired:
                return False
            if active_count <= 1:
                raise HTTPException(status_code=409, detail="不能下线最后一个 active 岗位")

            conn.execute(
                "UPDATE job_positions SET is_deleted = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["id"],),
            )
            conn.commit()
            return True

    changed = await run_db(_delete)
    message = f"岗位 '{position_name}' 已下线" if changed else f"岗位 '{position_name}' 已经是下线状态"
    return {"status": "success", "message": message}
