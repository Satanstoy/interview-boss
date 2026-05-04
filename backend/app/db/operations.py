import json
from app.db.connection import get_db_connection
from app.services.utils import _extract_url_signature


def _check_duplicate_url_sync(url: str) -> bool:
    if not url:
        return False
    sig = _extract_url_signature(url)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 先按精确 URL 匹配
        cursor.execute("SELECT 1 FROM jd WHERE url = ?", (url,))
        if cursor.fetchone():
            return True
        cursor.execute("SELECT 1 FROM interview WHERE url = ?", (url,))
        if cursor.fetchone():
            return True
        # 再按 URL 签名匹配（增强去重）
        if sig:
            cursor.execute("SELECT id, url FROM jd")
            for row in cursor.fetchall():
                if _extract_url_signature(row['url']) == sig:
                    return True
            cursor.execute("SELECT id, url FROM interview")
            for row in cursor.fetchall():
                if _extract_url_signature(row['url']) == sig:
                    return True
    return False


def _insert_jd(saved_url: str, data: dict, tech_stack: str):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO jd (url, company, job_title, salary, tech_stack, bonus) VALUES (?, ?, ?, ?, ?, ?)",
            (saved_url, data.get("公司", "未提供"), data.get("岗位名称", "未提供"), data.get("薪资范围", "未提供"), tech_stack, data.get("加分项", "未提供"))
        )
        conn.commit()


def _insert_interview(saved_url: str, data: dict, questions: str, season: str = ""):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO interview (url, company, round, focus, questions_list, difficulty, season) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (saved_url, data.get("公司", "未提供"), data.get("面试轮次", "未提供"), data.get("考察重点", "未提供"), questions, data.get("难易程度", "未提供"), season)
        )
        conn.commit()


def _insert_details(tagged_rows: list):
    with get_db_connection() as conn:
        for tr in tagged_rows:
            conn.execute(
                "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(tr)
            )
        conn.commit()


def _cleanup_old_sources(url: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
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
        conn.commit()


def _replace_details(url: str, tagged_rows: list):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM questions_detail WHERE url = ?", (url,))
        for tr in tagged_rows:
            cursor.execute(
                "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(tr)
            )
        conn.commit()
