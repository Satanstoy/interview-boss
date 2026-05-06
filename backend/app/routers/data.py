import json
import logging
from fastapi import APIRouter, HTTPException, Query, Depends
from app.core.config import ALLOWED_UPDATE_COLUMNS
from app.core.auth import get_current_user
from app.db.connection import get_db_connection, run_db
from app.models.schemas import GenericUpdateRequest, BatchDataDeleteRequest

logger = logging.getLogger("interview-boss")

router = APIRouter()

# ── 表名白名单：防止 SQL 注入 ──
_ALLOWED_TABLES = {"jd", "interview", "questions_detail", "question_bank"}


def _safe_table_name(name: str) -> str:
    """验证表名是否在白名单中，防止 SQL 注入"""
    if name not in _ALLOWED_TABLES:
        raise ValueError(f"不被允许的表名: {name}")
    return name


@router.get("/api/data/{file_type}")
async def get_data(file_type: str, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500), user: dict = Depends(get_current_user)):
    table_map = {"jd": "jd", "interview": "interview", "tagged": "questions_detail"}
    table_name = table_map.get(file_type.lower())
    if not table_name:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    offset = (page - 1) * page_size

    def _query():
        safe_name = _safe_table_name(table_name)
        with get_db_connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM {safe_name}").fetchone()[0]
            rows = conn.execute(f"SELECT * FROM {safe_name} ORDER BY id ASC LIMIT ? OFFSET ?", (page_size, offset)).fetchall()
            return total, rows

    total, rows = await run_db(_query)

    result = []
    for r in rows:
        d = dict(r)
        if table_name == 'jd':
            result.append({"id": d['id'], "来源链接": d['url'], "公司": d['company'], "岗位名称": d['job_title'], "薪资范围": d['salary'], "核心技术要求": d['tech_stack'], "加分项": d['bonus'], "season": d.get('season', '')})
        elif table_name == 'interview':
            result.append({"id": d['id'], "来源链接": d['url'], "公司": d['company'], "面试轮次": d['round'], "考察重点": d['focus'], "具体题目清单": d['questions_list'], "难易程度": d['difficulty'], "season": d.get('season', '')})
        elif table_name == 'questions_detail':
            result.append({"id": d['id'], "来源链接": d['url'], "公司": d['company'], "面试轮次": d['round'], "题目": d['question'], "一级大类": d['cat1'], "二级子类": d['cat2'], "考点标签": d['tags'], "难度标签": d['diff_tag']})
    return {"items": result, "total": total, "page": page, "page_size": page_size}


@router.delete("/api/data/{file_type}/{record_id}")
async def delete_data(file_type: str, record_id: int, user: dict = Depends(get_current_user)):
    """通过 record_id 直接删除记录，避免行号偏移导致删错"""
    table_map = {"jd": "jd", "interview": "interview", "tagged": "questions_detail"}
    table_name = table_map.get(file_type.lower())
    if not table_name:
        raise HTTPException(status_code=400, detail="不支持的表类型")

    def _delete():
        safe_name = _safe_table_name(table_name)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            target_row = cursor.execute(f"SELECT id, url, questions_list FROM {safe_name} WHERE id = ?", (record_id,)).fetchone()
            if not target_row:
                raise HTTPException(status_code=404, detail="未找到该记录，可能已被删除")

            if table_name == 'interview':
                url = target_row['url']
                # 通过 sources 字段中的 URL 追溯受影响的 question_bank 记录
                affected_rows = cursor.execute("SELECT id, sources FROM question_bank").fetchall()
                for mr in affected_rows:
                    try:
                        sources = json.loads(mr['sources']) if mr['sources'] else []
                    except Exception:
                        sources = []
                    match_count = sum(1 for s in sources if s.get('url') == url)
                    if match_count > 0:
                        new_sources = [s for s in sources if s.get('url') != url]
                        cursor.execute(
                            "UPDATE question_bank SET frequency = ?, sources = ? WHERE id = ?",
                            (len(new_sources), json.dumps(new_sources), mr['id'])
                        )

                # 保留有 AI 答案的记录，即使 frequency 降为 0（避免答案丢失）
                cursor.execute(
                    "DELETE FROM question_bank WHERE frequency <= 0 AND (ai_answer IS NULL OR ai_answer = '' OR ai_answer = '[生成失败，请手动重试]')"
                )
                cursor.execute("DELETE FROM questions_detail WHERE url = ?", (url,))

            cursor.execute(f"DELETE FROM {safe_name} WHERE id = ?", (record_id,))
            conn.commit()

    try:
        await run_db(_delete)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("操作失败")
        raise HTTPException(status_code=500, detail="操作失败，请查看服务端日志")


@router.post("/api/data/batch-delete")
async def batch_delete_data(req: BatchDataDeleteRequest, user: dict = Depends(get_current_user)):
    """批量删除记录，单事务完成"""
    table_map = {"jd": "jd", "interview": "interview"}
    table_name = table_map.get(req.file_type.lower())
    if not table_name:
        raise HTTPException(status_code=400, detail="不支持的表类型，仅支持 jd 和 interview")
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    def _batch_delete():
        safe_name = _safe_table_name(table_name)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(req.ids))
            rows = cursor.execute(
                f"SELECT id, url FROM {safe_name} WHERE id IN ({placeholders})", req.ids
            ).fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="未找到任何匹配记录")

            if table_name == "interview":
                urls_to_delete = {r["url"] for r in rows if r["url"]}
                all_master = cursor.execute("SELECT id, sources FROM question_bank").fetchall()
                for mr in all_master:
                    try:
                        sources = json.loads(mr["sources"]) if mr["sources"] else []
                    except Exception:
                        sources = []
                    if any(s.get("url") in urls_to_delete for s in sources):
                        new_sources = [s for s in sources if s.get("url") not in urls_to_delete]
                        cursor.execute(
                            "UPDATE question_bank SET frequency = ?, sources = ? WHERE id = ?",
                            (len(new_sources), json.dumps(new_sources), mr["id"])
                        )
                cursor.execute(
                    "DELETE FROM question_bank WHERE frequency <= 0 AND (ai_answer IS NULL OR ai_answer = '' OR ai_answer = '[生成失败，请手动重试]')"
                )
                for url in urls_to_delete:
                    cursor.execute("DELETE FROM questions_detail WHERE url = ?", (url,))

            found_ids = [r["id"] for r in rows]
            ph2 = ",".join("?" * len(found_ids))
            cursor.execute(f"DELETE FROM {safe_name} WHERE id IN ({ph2})", found_ids)
            conn.commit()
            return len(found_ids)

    try:
        deleted = await run_db(_batch_delete)
        return {"status": "success", "deleted": deleted}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("批量删除失败")
        raise HTTPException(status_code=500, detail="操作失败，请查看服务端日志")


@router.put("/api/data/update")
async def update_generic_data(req: GenericUpdateRequest, user: dict = Depends(get_current_user)):
    try:
        _safe_table_name(req.table_name)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"安全拦截：不被允许操作的数据表 '{req.table_name}'")

    if not req.update_data:
        raise HTTPException(status_code=400, detail="更新数据不能为空")

    # 白名单校验：只允许更新指定字段
    allowed_cols = ALLOWED_UPDATE_COLUMNS.get(req.table_name, set())
    for col in req.update_data.keys():
        if col not in allowed_cols:
            raise HTTPException(status_code=400, detail=f"安全拦截：不允许更新字段 '{col}'，允许的字段: {allowed_cols}")

    # 防止通过通用更新接口意外清空 ai_answer
    if req.table_name == "question_bank" and "ai_answer" in req.update_data:
        new_val = req.update_data["ai_answer"]
        if not new_val or (isinstance(new_val, str) and not new_val.strip()):
            raise HTTPException(status_code=400, detail="不允许将 ai_answer 设置为空值，请使用 /api/master-bank/generate-answer 接口重新生成答案")

    # 安全校验：列名必须只含 [a-z_0-9]，防止 SQL 注入
    import re
    _COL_RE = re.compile(r'^[a-z_][a-z_0-9]*$')
    for col in req.update_data.keys():
        if not _COL_RE.match(col):
            raise HTTPException(status_code=400, detail=f"安全拦截：非法列名 '{col}'")

    set_clauses = [f"{col} = ?" for col in req.update_data.keys()]
    values = list(req.update_data.values())

    if req.table_name == "question_bank" and "updated_at" not in req.update_data:
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")

    values.append(req.record_id)

    sql = f"UPDATE {req.table_name} SET {', '.join(set_clauses)} WHERE id = ?"

    def _update():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(values))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="未找到对应的记录，可能已被删除")
            conn.commit()

    try:
        await run_db(_update)
        return {"status": "success", "message": f"{req.table_name} 表数据更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("操作失败")
        raise HTTPException(status_code=500, detail="数据库更新失败，请查看服务端日志")
