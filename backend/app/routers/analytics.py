import logging
import json
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_current_user, get_admin_user
from app.db.connection import get_db_connection, run_db, get_user_job_position
from app.services.utils import normalize_category

logger = logging.getLogger("interview-boss")

router = APIRouter()


def _build_analytics_bank_filter(user: dict):
    """构建 analytics 查询的题库过滤条件（复用 bank_mode + job_position 逻辑）

    Returns:
        (join_clause, where_clause, params)
    """
    mode = user.get('bank_mode', 'public')
    uid = user['id']
    pos_id, pos_name = get_user_job_position(uid)

    # 使用 question_position 关联表
    join_clause = "JOIN question_position qp ON qb.id = qp.question_id AND qp.position_id = ?"
    join_params = [pos_id] if pos_id else []

    if not pos_id:
        # fallback: 旧的 job_position 列
        join_clause = ""
        if mode == 'personal':
            return "", "WHERE qb.owner_id = ? AND qb.job_position = ?", [uid, pos_name]
        elif mode == 'mixed':
            return "", "WHERE ((qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ?) AND qb.job_position = ?", [uid, pos_name]
        else:
            return "", "WHERE qb.owner_id IS NULL AND qb.status = 'approved' AND qb.job_position = ?", [pos_name]

    if mode == 'personal':
        return join_clause, "WHERE qb.owner_id = ? AND qb.deleted_at IS NULL", join_params + [uid]
    elif mode == 'mixed':
        return join_clause, "WHERE ((qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ?) AND qb.deleted_at IS NULL", join_params + [uid]
    else:
        return join_clause, "WHERE qb.owner_id IS NULL AND qb.status = 'approved' AND qb.deleted_at IS NULL", join_params

@router.get("/api/analytics")
async def get_analytics(user: dict = Depends(get_current_user)):
    mode = user.get('bank_mode', 'public')
    uid = user['id']

    def _query():
        tech_counter, tag_counter, level_counter = Counter(), Counter(), Counter()
        with get_db_connection() as conn:
            # 按 bank_mode 过滤 JD 数据
            if mode == 'personal':
                jd_where = "WHERE deleted_at IS NULL AND owner_id = ?"
                jd_params = (uid,)
            elif mode == 'mixed':
                jd_where = "WHERE deleted_at IS NULL AND ((owner_id IS NULL AND status = 'approved') OR owner_id = ?)"
                jd_params = (uid,)
            else:
                jd_where = "WHERE deleted_at IS NULL AND owner_id IS NULL AND status = 'approved'"
                jd_params = ()

            for r in conn.execute(f"SELECT tech_stack FROM jd {jd_where}", jd_params).fetchall():
                if r['tech_stack']:
                    tech_counter.update([t.strip().lstrip('0123456789. ') for t in r['tech_stack'].split('\n') if t.strip()])

            # 按 bank_mode 过滤 questions_detail 数据（通过关联 interview 表）
            if mode == 'personal':
                qd_where = "WHERE qd.deleted_at IS NULL AND iv.owner_id = ?"
                qd_params = (uid,)
            elif mode == 'mixed':
                qd_where = "WHERE qd.deleted_at IS NULL AND ((iv.owner_id IS NULL AND iv.status = 'approved') OR iv.owner_id = ?)"
                qd_params = (uid,)
            else:
                qd_where = "WHERE qd.deleted_at IS NULL AND iv.owner_id IS NULL AND iv.status = 'approved'"
                qd_params = ()

            for r in conn.execute(
                f"SELECT qd.tags, qd.diff_tag FROM questions_detail qd JOIN interview iv ON qd.url = iv.url {qd_where}",
                qd_params
            ).fetchall():
                if r['tags']:
                    tag_counter.update([t.strip() for t in r['tags'].split(",") if t.strip()])
                if r['diff_tag']:
                    level_counter[r['diff_tag']] += 1
        return dict(tech_counter.most_common(10)), dict(tag_counter.most_common(10)), dict(tag_counter.most_common(20)), dict(level_counter)

    tech, topics, popular, difficulty = await run_db(_query)
    return {"tech_trends": tech, "interview_topics": topics, "popular_tags": popular, "difficulty_distribution": difficulty}


@router.get("/api/practice-stats")
async def get_practice_stats(user: dict = Depends(get_current_user)):
    """返回学习进度统计数据：各难度练习情况、每日趋势、薄弱项（按用户隔离）"""

    uid = user['id']

    def _query():
        with get_db_connection() as conn:
            # 根据用户 bank_mode + job_position 决定题库范围
            join_clause, bank_where, bank_params = _build_analytics_bank_filter(user)

            # Master bank difficulty distribution
            diff_counts = {}
            for r in conn.execute(
                f"SELECT qb.difficulty, COUNT(*) as cnt FROM question_bank qb {join_clause} {bank_where} GROUP BY qb.difficulty", bank_params
            ).fetchall():
                diff_counts[r['difficulty'] or '未标注'] = r['cnt']

            # Practice history aggregated stats (per user)
            practiced = {}
            for r in conn.execute(
                "SELECT question_bank_id, MAX(score) as best_score, COUNT(*) as attempt_count "
                "FROM user_practice_history WHERE user_id = ? GROUP BY question_bank_id", [uid]
            ).fetchall():
                practiced[r['question_bank_id']] = {
                    'best_score': r['best_score'] or 0,
                    'attempt_count': r['attempt_count']
                }

            # Map practiced question_ids to their difficulty
            practiced_ids = list(practiced.keys())
            practiced_diff = {}
            if practiced_ids:
                placeholders = ','.join('?' * len(practiced_ids))
                for r in conn.execute(
                    f"SELECT id, difficulty FROM question_bank WHERE id IN ({placeholders})",
                    practiced_ids
                ).fetchall():
                    practiced_diff[r['id']] = r['difficulty'] or '未标注'

            # Per-difficulty practice stats
            by_difficulty = {}
            for diff, total in diff_counts.items():
                practiced_in_diff = [
                    qid for qid, d in practiced_diff.items() if d == diff
                ]
                scores = [practiced[qid]['best_score'] for qid in practiced_in_diff]
                by_difficulty[diff] = {
                    'total': total,
                    'practiced': len(practiced_in_diff),
                    'avg_score': round(sum(scores) / len(scores), 1) if scores else 0
                }

            # Daily trend (last 14 days)
            daily_trend = []
            for i in range(13, -1, -1):
                day = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                rows = conn.execute(
                    "SELECT COUNT(*) as cnt, AVG(score) as avg_s "
                    "FROM user_practice_history WHERE user_id = ? AND date(created_at) = ?",
                    (uid, day)
                ).fetchone()
                daily_trend.append({
                    'date': day,
                    'count': rows['cnt'] or 0,
                    'avg_score': round(rows['avg_s'] or 0, 1)
                })

            # Weak questions (recent score < 60)
            weak_rows = conn.execute(
                "SELECT uph.question_bank_id as question_id, qb.question, uph.score, uph.created_at "
                "FROM user_practice_history uph "
                "JOIN question_bank qb ON uph.question_bank_id = qb.id "
                "WHERE uph.user_id = ? AND uph.score < 60 "
                "ORDER BY uph.created_at DESC LIMIT 5",
                [uid]
            ).fetchall()
            recent_weak = [dict(r) for r in weak_rows]

            # Overall stats
            total_score = sum(p['best_score'] for p in practiced.values())
            avg_score = round(total_score / len(practiced), 1) if practiced else 0

            return {
                'total_questions': sum(diff_counts.values()),
                'practiced_questions': len(practiced),
                'avg_score': avg_score,
                'by_difficulty': by_difficulty,
                'daily_trend': daily_trend,
                'recent_weak': recent_weak,
                'practiced_details': practiced
            }

    data = await run_db(_query)
    return data


@router.post("/api/normalize-categories")
async def normalize_categories(admin: dict = Depends(get_admin_user)):
    """批量规范化现有数据库中 cat1/cat2 字段的格式（去除多余空格）"""
    def _normalize():
        updated_detail = 0
        updated_master = 0
        with get_db_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT id, cat1, cat2 FROM questions_detail WHERE deleted_at IS NULL").fetchall()
            for r in rows:
                new_cat1 = normalize_category(r['cat1'])
                new_cat2 = normalize_category(r['cat2'])
                if new_cat1 != r['cat1'] or new_cat2 != r['cat2']:
                    cursor.execute("UPDATE questions_detail SET cat1 = ?, cat2 = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_cat1, new_cat2, r['id']))
                    updated_detail += 1
            rows = cursor.execute("SELECT id, cat1, cat2 FROM question_bank").fetchall()
            for r in rows:
                new_cat1 = normalize_category(r['cat1'])
                new_cat2 = normalize_category(r['cat2'])
                if new_cat1 != r['cat1'] or new_cat2 != r['cat2']:
                    cursor.execute("UPDATE question_bank SET cat1 = ?, cat2 = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_cat1, new_cat2, r['id']))
                    updated_master += 1
            conn.commit()
        return updated_detail, updated_master

    try:
        detail_count, master_count = await run_db(_normalize)
        return {"status": "success", "message": f"规范化完成：questions_detail 更新 {detail_count} 条，question_bank 更新 {master_count} 条"}
    except Exception as e:
        logger.exception("操作失败")
        raise HTTPException(status_code=500, detail="规范化失败，请查看服务端日志")


@router.post("/api/clear-db")
async def clear_db(admin: dict = Depends(get_admin_user)):
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
        raise HTTPException(status_code=500, detail="备份创建失败，清空操作已中止")

    def _clear():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jd")
            cursor.execute("DELETE FROM interview")
            cursor.execute("DELETE FROM questions_detail")
            cursor.execute("DELETE FROM question_bank")
            cursor.execute("DELETE FROM user_practice_history")
            cursor.execute("DELETE FROM user_question_view")
            cursor.execute("DELETE FROM question_position")
            cursor.execute("DELETE FROM sqlite_sequence")
            conn.commit()

    try:
        await run_db(_clear)
        return {"status": "success", "message": f"已清空所有数据库表（备份已保存至 {os.path.basename(backup_path)}）"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="清空失败，请查看服务端日志")


@router.post("/api/sync-db")
async def sync_db(admin: dict = Depends(get_admin_user)):
    """使用 Embedding 语义聚类重建题库（与 build_master_bank 逻辑一致）"""
    from app.routers.master_bank import build_master_bank
    try:
        result = await build_master_bank()
        return {"status": "success", "message": f"数据库同步完成，共 {result.get('total_unique', 0)} 道核心真题"}
    except Exception as e:
        logger.exception("操作失败")
        raise HTTPException(status_code=500, detail="数据库同步失败，请查看服务端日志")


@router.get("/api/knowledge-graph")
async def get_knowledge_graph(user: dict = Depends(get_current_user)):
    """构建知识点关联图谱数据（节点 + 边）"""

    def _query():
        with get_db_connection() as conn:
            join_clause, bank_where, bank_params = _build_analytics_bank_filter(user)
            rows = conn.execute(
                f"SELECT qb.cat1, qb.cat2, qb.tags FROM question_bank qb {join_clause} {bank_where} AND qb.tags IS NOT NULL AND qb.tags != ''",
                bank_params
            ).fetchall()
        return [dict(r) for r in rows]

    rows = await run_db(_query)

    tag_cat_counts = defaultdict(Counter)
    tag_counts = Counter()
    cooccurrence = Counter()
    cat1_counts = Counter()

    for row in rows:
        cat1 = row['cat1'] or '未分类'
        cat1_counts[cat1] += 1
        tags = [t.strip() for t in (row['tags'] or '').split(',') if t.strip()]
        for tag in tags:
            tag_counts[tag] += 1
            tag_cat_counts[tag][cat1] += 1
        tags_sorted = sorted(set(tags))
        for i in range(len(tags_sorted)):
            for j in range(i + 1, len(tags_sorted)):
                cooccurrence[(tags_sorted[i], tags_sorted[j])] += 1

    cat1_list = sorted(cat1_counts.keys())
    cat1_index = {c: i for i, c in enumerate(cat1_list)}

    nodes = []
    for cat1 in cat1_list:
        nodes.append({
            "id": f"cat:{cat1}",
            "name": cat1,
            "category": cat1_index[cat1],
            "size": cat1_counts[cat1],
            "type": "category"
        })

    for tag, count in tag_counts.items():
        primary_cat = tag_cat_counts[tag].most_common(1)[0][0] if tag_cat_counts[tag] else '未分类'
        nodes.append({
            "id": f"tag:{tag}",
            "name": tag,
            "category": cat1_index.get(primary_cat, 0),
            "size": count,
            "type": "tag"
        })

    links = []
    for tag in tag_counts:
        if tag_cat_counts[tag]:
            primary_cat = tag_cat_counts[tag].most_common(1)[0][0]
            links.append({
                "source": f"tag:{tag}",
                "target": f"cat:{primary_cat}",
                "weight": tag_cat_counts[tag][primary_cat]
            })

    for (tag_a, tag_b), count in cooccurrence.items():
        if count >= 2:
            links.append({
                "source": f"tag:{tag_a}",
                "target": f"tag:{tag_b}",
                "weight": count
            })

    return {
        "nodes": nodes,
        "links": links,
        "categories": [{"name": c} for c in cat1_list]
    }
