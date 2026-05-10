import json
import logging
import os
from app.db.connection import get_db_connection
from app.services.utils import _extract_url_signature, normalize_category

logger = logging.getLogger("interview-boss")


# ═══════════════════════════════════════════════════
#  通用工具
# ═══════════════════════════════════════════════════

def _purge_soft_deleted(url: str, owner_id=None):
    """物理删除指定 URL 的软删除记录及其关联数据，让重新上传能干净进行。"""
    sig = _extract_url_signature(url)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 找到匹配的软删除记录
        conditions = []
        params = []
        if owner_id is not None:
            conditions.append("owner_id = ?")
            params.append(owner_id)
        else:
            conditions.append("owner_id IS NULL")
        conditions.append("deleted_at IS NOT NULL")

        where = " AND ".join(conditions)

        # 清理 interview 及其关联数据
        old_interviews = cursor.execute(
            f"SELECT id, url FROM interview WHERE url = ? AND {where}", [url, *params]
        ).fetchall()
        if sig:
            old_interviews += cursor.execute(
                f"SELECT id, url FROM interview WHERE url_signature = ? AND {where}", [sig, *params]
            ).fetchall()

        for row in old_interviews:
            old_url = row['url']
            if old_url:
                cursor.execute("DELETE FROM questions_detail WHERE url = ? AND deleted_at IS NOT NULL", (old_url,))
            cursor.execute("DELETE FROM interview WHERE id = ?", (row['id'],))

        # 清理 jd 及其关联数据
        old_jds = cursor.execute(
            f"SELECT id, url FROM jd WHERE url = ? AND {where}", [url, *params]
        ).fetchall()
        if sig:
            old_jds += cursor.execute(
                f"SELECT id, url FROM jd WHERE url_signature = ? AND {where}", [sig, *params]
            ).fetchall()

        for row in old_jds:
            old_url = row['url']
            if old_url:
                cursor.execute("DELETE FROM questions_detail WHERE url = ? AND deleted_at IS NOT NULL", (old_url,))
                cursor.execute("DELETE FROM interview WHERE url = ? AND deleted_at IS NOT NULL", (old_url,))
            cursor.execute("DELETE FROM jd WHERE id = ?", (row['id'],))

        conn.commit()


def _check_duplicate_url_sync(url: str, owner_id=None) -> bool:
    """检查 URL 是否已存在活跃记录。

    owner_id=None（公共上传）：检查所有活跃记录（全局唯一）。
    owner_id=int（个人上传）：只检查该用户自己的活跃记录。
    """
    if not url:
        return False
    sig = _extract_url_signature(url)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if owner_id is not None:
            # 个人上传：仅检查该用户自己的活跃记录
            cursor.execute("SELECT 1 FROM jd WHERE url = ? AND owner_id = ? AND deleted_at IS NULL", (url, owner_id))
            if cursor.fetchone(): return True
            cursor.execute("SELECT 1 FROM interview WHERE url = ? AND owner_id = ? AND deleted_at IS NULL", (url, owner_id))
            if cursor.fetchone(): return True
            if sig:
                cursor.execute("SELECT 1 FROM jd WHERE url_signature = ? AND owner_id = ? AND deleted_at IS NULL", (sig, owner_id))
                if cursor.fetchone(): return True
                cursor.execute("SELECT 1 FROM interview WHERE url_signature = ? AND owner_id = ? AND deleted_at IS NULL", (sig, owner_id))
                if cursor.fetchone(): return True
        else:
            # 公共上传：检查所有活跃记录（URL 全局唯一，不管 owner）
            cursor.execute("SELECT 1 FROM jd WHERE url = ? AND deleted_at IS NULL", (url,))
            if cursor.fetchone(): return True
            cursor.execute("SELECT 1 FROM interview WHERE url = ? AND deleted_at IS NULL", (url,))
            if cursor.fetchone(): return True
            if sig:
                cursor.execute("SELECT 1 FROM jd WHERE url_signature = ? AND deleted_at IS NULL", (sig,))
                if cursor.fetchone(): return True
                cursor.execute("SELECT 1 FROM interview WHERE url_signature = ? AND deleted_at IS NULL", (sig,))
                if cursor.fetchone(): return True

    # 活跃记录不存在，清理可能残留的软删除记录
    _purge_soft_deleted(url, owner_id)
    return False


# ═══════════════════════════════════════════════════
#  事务内原子操作（接受外部 cursor）
# ═══════════════════════════════════════════════════

def _insert_interview_txn(cursor, saved_url, data, questions, season, owner_id, status, job_position):
    sig = _extract_url_signature(saved_url)
    cursor.execute(
        "INSERT INTO interview (url, company, round, focus, questions_list, difficulty, season, owner_id, status, url_signature, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (saved_url, data.get("公司", "未提供"), data.get("面试轮次", "未提供"), data.get("考察重点", "未提供"),
         questions, data.get("难易程度", "未提供"), season, owner_id, status, sig, job_position)
    )


def _insert_details_txn(cursor, tagged_rows, job_position=""):
    for tr in tagged_rows:
        cursor.execute(
            "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*tr, job_position)
        )


def _cleanup_old_sources_txn(cursor, url: str):
    """移除某面经对 question_bank 的所有贡献，frequency=0 直接删除。"""
    affected_rows = cursor.execute(
        "SELECT id, sources FROM question_bank WHERE sources LIKE ?",
        (f"%{url}%",)
    ).fetchall()
    for mr in affected_rows:
        try:
            sources = json.loads(mr['sources']) if mr['sources'] else []
        except Exception:
            sources = []
        new_sources = [s for s in sources if s.get('url') != url]
        if len(new_sources) != len(sources):
            cursor.execute(
                "UPDATE question_bank SET frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (len(new_sources), json.dumps(new_sources, ensure_ascii=False), mr['id'])
            )
    cursor.execute("DELETE FROM question_bank WHERE frequency <= 0 AND owner_id IS NULL")


def _cleanup_old_sources_txn_v2(cursor, url: str, job_position: str = ""):
    """彻底移除某面经对 question_bank 的所有贡献。

    比 v1 多清理：
    - original_questions 中属于该 URL 的条目
    - original_question_sources 中属于该 URL 的条目
    - 被删除 QB 记录的 question_position 映射
    """
    affected_rows = cursor.execute(
        "SELECT id, sources, original_questions, original_question_sources FROM question_bank WHERE sources LIKE ?",
        (f"%{url}%",)
    ).fetchall()

    ids_to_delete = []
    for mr in affected_rows:
        try:
            sources = json.loads(mr['sources']) if mr['sources'] else []
        except Exception:
            sources = []
        try:
            oqs = json.loads(mr['original_questions']) if mr['original_questions'] else []
        except Exception:
            oqs = []
        try:
            oqs_sources = json.loads(mr['original_question_sources']) if mr['original_question_sources'] else []
        except Exception:
            oqs_sources = []

        # 移除属于该 URL 的 source
        new_sources = [s for s in sources if s.get('url') != url]
        # 移除属于该 URL 的 original_question_sources，并同步移除对应的 original_questions
        new_oqs_sources = [s for s in oqs_sources if s.get('url') != url]
        removed_questions = {s['question'] for s in oqs_sources if s.get('url') == url}
        new_oqs = [q for q in oqs if q not in removed_questions]

        if len(new_sources) != len(sources):
            if len(new_sources) == 0:
                # 所有来源都被移除，标记删除
                ids_to_delete.append(mr['id'])
            else:
                cursor.execute(
                    "UPDATE question_bank SET frequency = ?, sources = ?, "
                    "original_questions = ?, original_question_sources = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (len(new_sources),
                     json.dumps(new_sources, ensure_ascii=False),
                     json.dumps(new_oqs, ensure_ascii=False),
                     json.dumps(new_oqs_sources, ensure_ascii=False),
                     mr['id'])
                )

    # 删除 frequency=0 的公共 QB 记录及其关联数据
    if ids_to_delete:
        placeholders = ','.join('?' * len(ids_to_delete))
        cursor.execute(f"DELETE FROM question_position WHERE question_id IN ({placeholders})", ids_to_delete)
        cursor.execute(f"DELETE FROM question_bank WHERE id IN ({placeholders})", ids_to_delete)

    # 兜底：清理 frequency<=0 的公共记录
    cursor.execute("DELETE FROM question_position WHERE question_id IN "
                   "(SELECT id FROM question_bank WHERE frequency <= 0 AND owner_id IS NULL)")
    cursor.execute("DELETE FROM question_bank WHERE frequency <= 0 AND owner_id IS NULL")


def _replace_details_txn(cursor, url, tagged_rows, job_position=""):
    cursor.execute("DELETE FROM questions_detail WHERE url = ?", (url,))
    _insert_details_txn(cursor, tagged_rows, job_position)


def _apply_incremental_txn(cursor, matched, unmatched_rows, idx_to_row, submitter_is_admin, user_id, current_pos, owner_id=None):
    """增量更新 question_bank（matched 增频，unmatched 新建）。

    owner_id: 传入时用于 unmatched 新建行的 owner_id（个人题库场景）。
    返回需要后台生成 AI 答案的 (question_id, question_text) 列表。
    """
    submitter_id = user_id
    if not submitter_id:
        admin_username = os.getenv("ADMIN_USERNAME", "sj")
        admin_row = cursor.execute("SELECT id FROM users WHERE username = ?", (admin_username,)).fetchone()
        submitter_id = admin_row[0] if admin_row else None
    status = 'approved' if submitter_is_admin else 'pending'

    answer_tasks = []

    for m in matched:
        new_idx = m["new_id"]
        qb_id = m["question_bank_id"]
        row = idx_to_row.get(new_idx)
        if not row:
            continue
        url, company, round_ = row[0], row[1], row[2]
        new_q_text = row[3] if len(row) > 3 else ''
        new_source = {"url": url, "company": company, "round": round_}
        existing = cursor.execute("SELECT sources, original_questions, original_question_sources FROM question_bank WHERE id = ?", (qb_id,)).fetchone()
        if existing:
            try:
                sources = json.loads(existing['sources']) if existing['sources'] else []
            except Exception:
                sources = []
            existing_urls = {s.get('url') for s in sources}
            if url not in existing_urls:
                sources.append(new_source)
                # 回写 original_questions
                try:
                    orig_qs = json.loads(existing['original_questions']) if existing['original_questions'] else []
                    orig_qs_src = json.loads(existing['original_question_sources']) if existing['original_question_sources'] else []
                except Exception:
                    orig_qs, orig_qs_src = [], []
                if new_q_text and new_q_text not in orig_qs:
                    orig_qs.append(new_q_text)
                    orig_qs_src.append({"question": new_q_text, "sources": [new_source]})
                elif new_q_text:
                    # 问题文本已存在：将新 URL 合并到对应条目的 sources 中
                    _merged = False
                    for _oqs_item in orig_qs_src:
                        if _oqs_item.get("question") == new_q_text:
                            _oqs_urls = {s.get("url") for s in _oqs_item.get("sources", [])}
                            if url not in _oqs_urls:
                                _oqs_item.setdefault("sources", []).append(new_source)
                            _merged = True
                            break
                    if not _merged:
                        # question text 匹配但 oqs 中没有对应条目，新建一个
                        orig_qs_src.append({"question": new_q_text, "sources": [new_source]})
                # 安全网：确保每个 source URL 至少在 oqs 中有一个条目
                _oqs_all_urls = {s.get("url") for item in orig_qs_src for s in item.get("sources", [])}
                if url not in _oqs_all_urls:
                    orig_qs_src.append({"question": new_q_text or "", "sources": [new_source]})
                cursor.execute(
                    "UPDATE question_bank SET frequency = ?, sources = ?, original_questions = ?, original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (len(sources), json.dumps(sources, ensure_ascii=False), json.dumps(orig_qs, ensure_ascii=False), json.dumps(orig_qs_src, ensure_ascii=False), qb_id)
                )

    for item in unmatched_rows:
        row = item.get("_orig_row") if isinstance(item, dict) else item
        url, company, round_, q_text = row[0], row[1], row[2], row[3]
        cat1 = normalize_category(row[4])
        cat2 = normalize_category(row[5]) if len(row) > 5 else ''
        tags = row[6] if len(row) > 6 else ''
        diff_tag = row[7] if len(row) > 7 else '未知'
        sources_json = json.dumps([{"url": url, "company": company, "round": round_}], ensure_ascii=False)
        oqs_json = json.dumps([{"question": q_text, "sources": [{"url": url, "company": company, "round": round_}]}], ensure_ascii=False)
        cursor.execute(
            "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, sources, original_question_sources, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
            (q_text, cat1, cat2, tags, diff_tag, sources_json, oqs_json, owner_id, submitter_id, status, current_pos)
        )
        new_id = cursor.lastrowid
        # BUG-008: 同步 question_position 关联表，否则新题在主库 INNER JOIN 查询中不可见
        pos_row = cursor.execute("SELECT id FROM job_positions WHERE name = ?", (current_pos,)).fetchone()
        if pos_row:
            cursor.execute("INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)", (new_id, pos_row[0]))
        if status == 'approved':
            answer_tasks.append((new_id, q_text))

    return answer_tasks


# ═══════════════════════════════════════════════════
#  事务编排器（三个业务操作各对应一个）
# ═══════════════════════════════════════════════════

def submit_interview_txn(saved_url, data, questions, season, owner_id, status,
                         job_position, tagged_rows, matched, unmatched_rows,
                         idx_to_row, submitter_is_admin, user_id, qb_owner_id=None):
    """操作3 提交新面经：insert_interview + insert_details + incremental_update。

    qb_owner_id: question_bank 中 unmatched 新建行的 owner_id（个人题库传 user_id）。
    单事务，全部成功或全部回滚。
    返回 (answer_tasks, interview_id)。
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN")
            _insert_interview_txn(cursor, saved_url, data, questions, season, owner_id, status, job_position)
            interview_id = cursor.lastrowid
            _insert_details_txn(cursor, tagged_rows, job_position)
            answer_tasks = _apply_incremental_txn(
                cursor, matched, unmatched_rows, idx_to_row,
                submitter_is_admin, user_id, job_position,
                owner_id=qb_owner_id
            )
            conn.commit()
            return answer_tasks, interview_id
        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e):
                raise ValueError("该 URL 已存在，不可重复上传")
            raise


def submit_interview_txn_tag_only(saved_url, data, questions, season, owner_id, status,
                                  job_position, tagged_rows):
    """提交新面经（仅打标签）：insert_interview + insert_details，不做聚类。

    聚类由两阶段流水线的阶段2负责。
    单事务，返回 interview_id。
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN")
            _insert_interview_txn(cursor, saved_url, data, questions, season, owner_id, status, job_position)
            interview_id = cursor.lastrowid
            _insert_details_txn(cursor, tagged_rows, job_position)
            conn.commit()
            return interview_id
        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e):
                raise ValueError("该 URL 已存在，不可重复上传")
            raise


def sync_interview_details(url, tagged_rows, job_position,
                           matched, unmatched_rows, idx_to_row,
                           submitter_is_admin, user_id):
    """操作1 重新分析面经：cleanup + replace_details + incremental_update。

    单事务，全部成功或全部回滚。
    返回 answer_tasks。
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN")
            _cleanup_old_sources_txn(cursor, url)
            _replace_details_txn(cursor, url, tagged_rows, job_position)
            answer_tasks = _apply_incremental_txn(
                cursor, matched, unmatched_rows, idx_to_row,
                submitter_is_admin, user_id, job_position
            )
            conn.commit()
            return answer_tasks
        except Exception:
            conn.rollback()
            raise


# ═══════════════════════════════════════════════════
#  个人题库（无需聚类，直接插入）
# ═══════════════════════════════════════════════════

def insert_personal_questions_txn(tagged_rows, user_id, job_position):
    """个人题库：直接插入 question_bank，不做聚类匹配。

    返回 answer_tasks。
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN")
            answer_tasks = []
            for row in tagged_rows:
                url, company, round_, q_text = row[0], row[1], row[2], row[3]
                cat1 = normalize_category(row[4])
                cat2 = normalize_category(row[5]) if len(row) > 5 else ''
                tags = row[6] if len(row) > 6 else ''
                diff_tag = row[7] if len(row) > 7 else '未知'
                sources_json = json.dumps([{"url": url, "company": company, "round": round_}], ensure_ascii=False)
                cursor.execute(
                    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, sources, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 'approved', ?)",
                    (q_text, cat1, cat2, tags, diff_tag, sources_json, user_id, user_id, job_position)
                )
                new_id = cursor.lastrowid
                pos_row = cursor.execute("SELECT id FROM job_positions WHERE name = ?", (job_position,)).fetchone()
                if pos_row:
                    cursor.execute("INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)", (new_id, pos_row[0]))
                answer_tasks.append((new_id, q_text))
            conn.commit()
            return answer_tasks
        except Exception:
            conn.rollback()
            raise


# ═══════════════════════════════════════════════════
#  JD 插入（独立操作，不涉及聚类）
# ═══════════════════════════════════════════════════

def _insert_jd(saved_url: str, data: dict, tech_stack: str, season: str = "", owner_id: int = None, status: str = "approved", job_position: str = ""):
    with get_db_connection() as conn:
        sig = _extract_url_signature(saved_url)
        try:
            conn.execute(
                "INSERT INTO jd (url, company, job_title, salary, tech_stack, bonus, season, owner_id, status, url_signature, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (saved_url, data.get("公司", "未提供"), data.get("岗位名称", "未提供"), data.get("薪资范围", "未提供"), tech_stack, data.get("加分项", "未提供"), season, owner_id, status, sig, job_position)
            )
            conn.commit()
        except Exception as e:
            if "UNIQUE" in str(e):
                raise ValueError("该 URL 已存在，不可重复上传")
            raise


def _insert_interview(saved_url: str, data: dict, questions: str, season: str = "", owner_id: int = None, status: str = "approved", job_position: str = ""):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            _insert_interview_txn(cursor, saved_url, data, questions, season, owner_id, status, job_position)
            conn.commit()
        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e):
                raise ValueError("该 URL 已存在，不可重复上传")
            raise
