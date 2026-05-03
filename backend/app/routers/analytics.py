
import logging
from collections import Counter
from fastapi import APIRouter, HTTPException
from app.db.connection import get_db_connection, run_db
from app.services.utils import normalize_category

logger = logging.getLogger("multimodal-parser")

router = APIRouter()


@router.get("/api/analytics")
async def get_analytics():
    def _query():
        tech_counter, tag_counter, level_counter = Counter(), Counter(), Counter()
        with get_db_connection() as conn:
            for r in conn.execute("SELECT tech_stack FROM jd").fetchall():
                if r['tech_stack']:
                    tech_counter.update([t.strip().lstrip('0123456789. ') for t in r['tech_stack'].split('\n') if t.strip()])
            for r in conn.execute("SELECT tags, diff_tag FROM questions_detail").fetchall():
                if r['tags']:
                    tag_counter.update([t.strip() for t in r['tags'].split(",") if t.strip()])
                if r['diff_tag']:
                    level_counter[r['diff_tag']] += 1
        return dict(tech_counter.most_common(10)), dict(tag_counter.most_common(10)), dict(tag_counter.most_common(20)), dict(level_counter)

    tech, topics, popular, difficulty = await run_db(_query)
    return {"tech_trends": tech, "interview_topics": topics, "popular_tags": popular, "difficulty_distribution": difficulty}


@router.post("/api/normalize-categories")
async def normalize_categories():
    """批量规范化现有数据库中 cat1/cat2 字段的格式（去除多余空格）"""
    def _normalize():
        updated_detail = 0
        updated_master = 0
        with get_db_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT id, cat1, cat2 FROM questions_detail").fetchall()
            for r in rows:
                new_cat1 = normalize_category(r['cat1'])
                new_cat2 = normalize_category(r['cat2'])
                if new_cat1 != r['cat1'] or new_cat2 != r['cat2']:
                    cursor.execute("UPDATE questions_detail SET cat1 = ?, cat2 = ? WHERE id = ?", (new_cat1, new_cat2, r['id']))
                    updated_detail += 1
            rows = cursor.execute("SELECT id, cat1, cat2 FROM master_question_bank").fetchall()
            for r in rows:
                new_cat1 = normalize_category(r['cat1'])
                new_cat2 = normalize_category(r['cat2'])
                if new_cat1 != r['cat1'] or new_cat2 != r['cat2']:
                    cursor.execute("UPDATE master_question_bank SET cat1 = ?, cat2 = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_cat1, new_cat2, r['id']))
                    updated_master += 1
            conn.commit()
        return updated_detail, updated_master

    try:
        detail_count, master_count = await run_db(_normalize)
        return {"status": "success", "message": f"规范化完成：questions_detail 更新 {detail_count} 条，master_question_bank 更新 {master_count} 条"}
    except Exception as e:
        logger.exception("操作失败")
        raise HTTPException(status_code=500, detail=f"规范化失败: {str(e)}")


@router.post("/api/clear-db")
async def clear_db():
    """清空所有数据库表（执行前自动创建备份）"""
    import os
    import shutil
    from app.core.config import DB_PATH
    backup_path = f"{DB_PATH}.bak.{int(__import__('time').time())}"
    try:
        shutil.copy2(DB_PATH, backup_path)
        logger.info(f"清空前已创建数据库备份: {backup_path}")
    except Exception as e:
        logger.error(f"创建备份失败，拒绝清空操作: {e}")
        raise HTTPException(status_code=500, detail=f"备份创建失败，清空操作已中止: {str(e)}")

    def _clear():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jd")
            cursor.execute("DELETE FROM interview")
            cursor.execute("DELETE FROM questions_detail")
            cursor.execute("DELETE FROM master_question_bank")
            cursor.execute("DELETE FROM sqlite_sequence")
            conn.commit()

    try:
        await run_db(_clear)
        return {"status": "success", "message": f"已清空所有数据库表（备份已保存至 {os.path.basename(backup_path)}）"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清空失败: {str(e)}")


@router.post("/api/sync-db")
async def sync_db():
    """使用 Embedding 语义聚类重建题库（与 build_master_bank 逻辑一致）"""
    from app.routers.master_bank import build_master_bank
    try:
        result = await build_master_bank()
        return {"status": "success", "message": f"数据库同步完成，共 {result.get('total_unique', 0)} 道核心真题"}
    except Exception as e:
        logger.exception("操作失败")
        raise HTTPException(status_code=500, detail=f"数据库同步失败: {str(e)}")
