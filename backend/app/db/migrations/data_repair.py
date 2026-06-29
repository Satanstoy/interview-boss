"""Data repair domain migrations: 011, 014, 017, 018, 019, 020."""

import json
import logging

from app.core.prompts import DEFAULT_TAXONOMY

logger = logging.getLogger("interview-boss")


def _migration_011_data_backfills(conn):
    """Data backfills: question_bank.job_position -> job_positions + question_position,
    user_profile.current_job_position -> users.current_position_id,
    embedding cleanup, empty season backfill,
    taxonomy from user_profile JSON -> taxonomy table."""
    cursor = conn.cursor()

    # ── 数据迁移：question_bank.job_position → job_positions + question_position ──
    jp_count = conn.execute("SELECT COUNT(*) FROM job_positions").fetchone()[0]
    if jp_count == 0:
        # 从 question_bank 提取所有不重复的岗位
        positions = conn.execute(
            "SELECT DISTINCT job_position FROM question_bank WHERE job_position IS NOT NULL AND job_position != ''"
        ).fetchall()
        for row in positions:
            pos_name = row[0]
            conn.execute("INSERT OR IGNORE INTO job_positions (name) VALUES (?)", (pos_name,))
            pos_id = conn.execute("SELECT id FROM job_positions WHERE name = ?", (pos_name,)).fetchone()[0]
            # 为属于该岗位的所有题目建立关联
            conn.execute(
                "INSERT OR IGNORE INTO question_position (question_id, position_id) "
                "SELECT id, ? FROM question_bank WHERE job_position = ?", (pos_id, pos_name)
            )
        migrated_count = conn.execute("SELECT COUNT(*) FROM question_position").fetchone()[0]
        logger.info(f"已迁移 {len(positions)} 个岗位、{migrated_count} 条题目-岗位关联到 job_positions/question_position 表")

    # ── 迁移：user_profile.current_job_position → users.current_position_id ──
    users_without_pos = conn.execute("SELECT id FROM users WHERE current_position_id IS NULL").fetchall()
    if users_without_pos:
        cur_pos_row = conn.execute("SELECT value FROM user_profile WHERE key = 'current_job_position'").fetchone()
        if cur_pos_row and cur_pos_row[0]:
            pos_id_row = conn.execute("SELECT id FROM job_positions WHERE name = ?", (cur_pos_row[0],)).fetchone()
            if pos_id_row:
                conn.execute("UPDATE users SET current_position_id = ?, updated_at = CURRENT_TIMESTAMP WHERE current_position_id IS NULL", (pos_id_row[0],))
                logger.info(f"已将 {len(users_without_pos)} 个用户的 current_position_id 迁移为 {cur_pos_row[0]}")

    # ── 迁移：清理 embedding 相关数据 ──
    conn.execute("UPDATE question_bank SET vector = NULL, updated_at = CURRENT_TIMESTAMP WHERE vector IS NOT NULL")
    conn.execute("DELETE FROM user_profile WHERE key IN ('embedding_model', 'similarity_threshold', 'embedding_api_key', 'embedding_base_url')")

    # ── 迁移：回填空 season 为默认招聘季 ──
    empty_season_count = conn.execute("SELECT COUNT(*) FROM interview WHERE season IS NULL OR season = ''").fetchone()[0]
    if empty_season_count > 0:
        conn.execute("UPDATE interview SET season = '2027届暑期实习', updated_at = CURRENT_TIMESTAMP WHERE season IS NULL OR season = ''")
        logger.info(f"已将 {empty_season_count} 条面经的招聘季回填为 2027届暑期实习")
        # 同步设置 active_season
        conn.execute(
            "INSERT INTO user_profile (key, value, updated_at) VALUES ('active_season', '2027届暑期实习', CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP"
        )

    # ── 迁移：taxonomy 从 user_profile JSON → taxonomy 表 ──
    tx_count = conn.execute("SELECT COUNT(*) FROM taxonomy").fetchone()[0]
    if tx_count == 0:
        # seed 默认 taxonomy
        conn.execute(
            "INSERT OR IGNORE INTO taxonomy (position_name, categories_json, is_default) VALUES (?, ?, 1)",
            (DEFAULT_TAXONOMY["job_position"], json.dumps(DEFAULT_TAXONOMY["categories"], ensure_ascii=False))
        )
        # 从 user_profile 迁移已有的 taxonomy 配置
        tx_rows = conn.execute("SELECT key, value FROM user_profile WHERE key LIKE 'taxonomy_config%'").fetchall()
        for tx_row in tx_rows:
            try:
                tc = json.loads(tx_row['value'])
                pos = tc.get('job_position', '')
                cats = tc.get('categories', [])
                if pos and cats:
                    conn.execute(
                        "INSERT OR REPLACE INTO taxonomy (position_name, categories_json) VALUES (?, ?)",
                        (pos, json.dumps(cats, ensure_ascii=False))
                    )
            except Exception:
                pass
        migrated_tx = conn.execute("SELECT COUNT(*) FROM taxonomy").fetchone()[0]
        logger.info(f"已迁移 {migrated_tx} 个岗位的 taxonomy 配置到 taxonomy 表")


def _migration_014_data_repairs(conn):
    """Data repairs: frequency vs original_questions, original_question_sources
    orphan URL fix, empty OQS backfill, empty sources sub-arrays fix,
    missing URL entries fix, analysis_status columns."""
    cursor = conn.cursor()

    # ── 修复: question_bank.frequency 应等于 original_questions 数组长度 ──
    _fix_rows = conn.execute("SELECT id, frequency, original_questions FROM question_bank").fetchall()
    _fix_count = 0
    for _r in _fix_rows:
        _qb_id, _freq, _oqs_raw = _r[0], _r[1], _r[2]
        try:
            _oqs = json.loads(_oqs_raw) if _oqs_raw else []
        except Exception:
            _oqs = []
        _actual = len(_oqs) if _oqs else _freq
        if _freq != _actual and _actual > 0:
            conn.execute("UPDATE question_bank SET frequency = ? WHERE id = ?", (_actual, _qb_id))
            _fix_count += 1
    if _fix_count > 0:
        logger.info(f"已修复 {_fix_count} 条 question_bank 记录的 frequency 字段（基于 original_questions 计数）")

    # ── 修复: original_question_sources 中包含 sources 中不存在的 URL ──
    _oqs_rows = conn.execute("SELECT id, sources, original_question_sources FROM question_bank WHERE original_question_sources != '[]' AND original_question_sources IS NOT NULL").fetchall()
    _oqs_fix = 0
    for _r in _oqs_rows:
        _qb_id, _src_raw, _oqs_raw = _r[0], _r[1], _r[2]
        try:
            _srcs = json.loads(_src_raw) if _src_raw else []
            _oqs = json.loads(_oqs_raw) if _oqs_raw else []
        except Exception:
            continue
        _src_urls = {s.get('url') for s in _srcs if s.get('url')}
        _changed = False
        for _item in _oqs:
            _before = len(_item.get('sources', []))
            _item['sources'] = [s for s in _item.get('sources', []) if s.get('url') in _src_urls]
            if len(_item['sources']) != _before:
                _changed = True
        if _changed:
            conn.execute("UPDATE question_bank SET original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (json.dumps(_oqs, ensure_ascii=False), _qb_id))
            _oqs_fix += 1
    if _oqs_fix > 0:
        logger.info(f"已修复 {_oqs_fix} 条 original_question_sources 中的孤立 URL")

    # ── 修复: original_question_sources 为空但 sources 非空的题目 ──
    _empty_oqs_rows = conn.execute(
        "SELECT id, question, sources FROM question_bank "
        "WHERE (original_question_sources IS NULL OR original_question_sources = '' OR original_question_sources = '[]') "
        "AND sources IS NOT NULL AND sources != '' AND sources != '[]' AND frequency > 0"
    ).fetchall()
    _backfill_count = 0
    # 预加载 questions_detail 的 url -> question 映射
    _qd_map = {}  # url -> [(question, company, round), ...]
    for _qd in conn.execute("SELECT question, url, company, round FROM questions_detail WHERE deleted_at IS NULL AND url IS NOT NULL AND url != ''"):
        _qd_map.setdefault(_qd[1], []).append((_qd[0], _qd[2], _qd[3]))
    for _r in _empty_oqs_rows:
        _qb_id, _qb_question, _src_raw = _r[0], _r[1], _r[2]
        try:
            _srcs = json.loads(_src_raw) if _src_raw else []
        except Exception:
            continue
        _new_oqs = []
        for _s in _srcs:
            _url = _s.get('url', '')
            _company = _s.get('company', '')
            _round = _s.get('round', '')
            # 尝试从 questions_detail 找到原始题目文本
            _oq_text = _qb_question  # fallback
            if _url in _qd_map:
                for _qd_q, _qd_c, _qd_r in _qd_map[_url]:
                    if _qd_q and _qd_q != _qb_question:
                        _oq_text = _qd_q
                        break
            _new_oqs.append({"question": _oq_text, "sources": [{"url": _url, "company": _company, "round": _round}]})
        if _new_oqs:
            conn.execute("UPDATE question_bank SET original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (json.dumps(_new_oqs, ensure_ascii=False), _qb_id))
            _backfill_count += 1
    if _backfill_count > 0:
        logger.info(f"已回填 {_backfill_count} 条题目的 original_question_sources")

    # ── 修复: original_question_sources 中 sources 为空数组的条目 ──
    _empty_src_oqs_rows = conn.execute(
        "SELECT id, sources, original_question_sources FROM question_bank "
        "WHERE original_question_sources LIKE '%\"sources\": []%' AND frequency > 0"
    ).fetchall()
    _fix_empty_src = 0
    for _r in _empty_src_oqs_rows:
        _qb_id, _src_raw, _oqs_raw = _r[0], _r[1], _r[2]
        try:
            _srcs = json.loads(_src_raw) if _src_raw else []
            _oqs = json.loads(_oqs_raw) if _oqs_raw else []
        except Exception:
            continue
        _src_urls = {s.get('url') for s in _srcs if s.get('url')}
        _changed = False
        for _item in _oqs:
            if _item.get('sources'):
                continue  # 已有 sources，跳过
            _oq_text = _item.get('question', '')
            if not _oq_text:
                continue
            # 从 questions_detail 查找匹配的 URL
            for _url in _src_urls:
                if _url in _qd_map:
                    for _qd_q, _qd_c, _qd_r in _qd_map[_url]:
                        if _qd_q == _oq_text:
                            _item['sources'] = [{"url": _url, "company": _qd_c or '', "round": _qd_r or ''}]
                            _changed = True
                            break
                if _changed:
                    break
            # 仍然没有 sources 的条目，使用第一个 source URL 作为 fallback
            if not _item.get('sources') and _srcs:
                _s = _srcs[0]
                _item['sources'] = [{"url": _s.get('url', ''), "company": _s.get('company', ''), "round": _s.get('round', '')}]
                _changed = True
        if _changed:
            conn.execute("UPDATE question_bank SET original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (json.dumps(_oqs, ensure_ascii=False), _qb_id))
            _fix_empty_src += 1
    if _fix_empty_src > 0:
        logger.info(f"已修复 {_fix_empty_src} 条 original_question_sources 中空 sources 条目")

    # ── 修复: sources 中有 URL 但 oqs 中缺失对应条目的题目 ──
    _gap_rows = conn.execute(
        "SELECT id, question, sources, original_question_sources FROM question_bank "
        "WHERE original_question_sources IS NOT NULL AND original_question_sources != '' AND original_question_sources != '[]' "
        "AND sources IS NOT NULL AND sources != '' AND sources != '[]' AND frequency > 0"
    ).fetchall()
    _gap_fix = 0
    for _r in _gap_rows:
        _qb_id, _qb_question, _src_raw, _oqs_raw = _r[0], _r[1], _r[2], _r[3]
        try:
            _srcs = json.loads(_src_raw) if _src_raw else []
            _oqs = json.loads(_oqs_raw) if _oqs_raw else []
        except Exception:
            continue
        _oqs_urls = {s.get('url') for item in _oqs for s in item.get('sources', []) if s.get('url')}
        _changed = False
        for _s in _srcs:
            _url = _s.get('url', '')
            if _url and _url not in _oqs_urls:
                # 从 questions_detail 查找原始题目文本
                _oq_text = _qb_question
                if _url in _qd_map:
                    for _qd_q, _qd_c, _qd_r in _qd_map[_url]:
                        if _qd_q and _qd_q != _qb_question:
                            _oq_text = _qd_q
                            break
                _oqs.append({"question": _oq_text, "sources": [{"url": _url, "company": _s.get('company', ''), "round": _s.get('round', '')}]})
                _oqs_urls.add(_url)
                _changed = True
        if _changed:
            conn.execute("UPDATE question_bank SET original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (json.dumps(_oqs, ensure_ascii=False), _qb_id))
            _gap_fix += 1
    if _gap_fix > 0:
        logger.info(f"已修复 {_gap_fix} 条 original_question_sources 中缺失的 URL 条目")

    # ── 迁移：interview 表添加分析状态追踪列（断点续传）──
    iv_columns = {row[1] for row in cursor.execute("PRAGMA table_info('interview')").fetchall()}
    if "analysis_status" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN analysis_status TEXT DEFAULT 'idle'")
    if "analysis_stage" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN analysis_stage TEXT")
    if "analysis_result" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN analysis_result TEXT")
    if "analysis_updated_at" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN analysis_updated_at TIMESTAMP")


def _migration_017_backfill_normalized_sources(conn):
    """Backfill normalized tables from existing JSON columns in question_bank."""
    cursor = conn.cursor()
    count = cursor.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0]
    if count > 0:
        logger.info("Normalized tables already populated, skipping backfill")
        return

    rows = cursor.execute(
        "SELECT id, sources, original_questions, original_question_sources FROM question_bank"
    ).fetchall()

    for row in rows:
        qb_id = row[0]

        # Backfill question_sources
        try:
            sources = json.loads(row[1]) if row[1] else []
        except Exception:
            sources = []
        for s in sources:
            if isinstance(s, dict):
                cursor.execute(
                    "INSERT OR IGNORE INTO question_sources (question_bank_id, url, company, round) VALUES (?, ?, ?, ?)",
                    (qb_id, s.get('url', ''), s.get('company', ''), s.get('round', ''))
                )

        # Backfill question_original_items + question_original_item_sources
        try:
            oqs_src = json.loads(row[3]) if row[3] else []
        except Exception:
            oqs_src = []
        if not isinstance(oqs_src, list):
            continue

        for item in oqs_src:
            if not isinstance(item, dict):
                continue
            q_text = item.get('question', '')
            if not q_text:
                continue
            cursor.execute(
                "INSERT OR IGNORE INTO question_original_items (question_bank_id, question_text) VALUES (?, ?)",
                (qb_id, q_text)
            )
            item_id = cursor.execute(
                "SELECT id FROM question_original_items WHERE question_bank_id = ? AND question_text = ?",
                (qb_id, q_text)
            ).fetchone()[0]

            for s in item.get('sources', []):
                if isinstance(s, dict):
                    cursor.execute(
                        "INSERT OR IGNORE INTO question_original_item_sources (original_item_id, url, company, round) VALUES (?, ?, ?, ?)",
                        (item_id, s.get('url', ''), s.get('company', ''), s.get('round', ''))
                    )

    qs_count = cursor.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0]
    qoi_count = cursor.execute("SELECT COUNT(*) FROM question_original_items").fetchone()[0]
    qois_count = cursor.execute("SELECT COUNT(*) FROM question_original_item_sources").fetchone()[0]
    logger.info(f"Backfilled normalized tables: {qs_count} sources, {qoi_count} original items, {qois_count} item sources from {len(rows)} QB records")


def _migration_018_composite_indexes(conn):
    """Add composite indexes for common query patterns."""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qb_owner_status_position ON question_bank(owner_id, status, job_position)")


def _migration_019_fix_cascades(conn):
    """Fix missing ON DELETE CASCADE on user_practice_history.question_bank_id."""
    cursor = conn.cursor()
    # SQLite doesn't support ALTER TABLE to modify FK constraints.
    # Recreate the table with CASCADE.
    cursor.execute("ALTER TABLE user_practice_history RENAME TO user_practice_history_old")
    cursor.execute('''
        CREATE TABLE user_practice_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            user_answer TEXT,
            evaluation_result TEXT,
            score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute('''
        INSERT INTO user_practice_history (id, user_id, question_bank_id, user_answer, evaluation_result, score, created_at, updated_at)
        SELECT id, user_id, question_bank_id, user_answer, evaluation_result, score, created_at, updated_at
        FROM user_practice_history_old
    ''')
    cursor.execute("DROP TABLE user_practice_history_old")
    # Recreate indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_uph_user ON user_practice_history(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_uph_question ON user_practice_history(question_bank_id)")


def _migration_020_drop_json_columns(conn):
    """Drop deprecated JSON TEXT columns and static frequency from question_bank.

    WARNING: Only run after all write paths have been updated to use normalized tables.
    Currently commented out in _MIGRATIONS — enable after production validation.
    """
    cursor = conn.cursor()
    # Safety check: ensure normalized tables are populated
    qs_count = cursor.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0]
    qb_count = cursor.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0]
    if qs_count == 0 and qb_count > 0:
        raise RuntimeError("Cannot drop JSON columns: normalized tables are empty")

    cursor.execute("ALTER TABLE question_bank DROP COLUMN sources")
    cursor.execute("ALTER TABLE question_bank DROP COLUMN original_questions")
    cursor.execute("ALTER TABLE question_bank DROP COLUMN original_question_sources")
    cursor.execute("ALTER TABLE question_bank DROP COLUMN is_starred")
    cursor.execute("ALTER TABLE question_bank DROP COLUMN frequency")
    logger.info("Dropped JSON columns and static frequency from question_bank")


def _migration_021_performance_indexes(conn):
    """Add indexes for common query patterns identified in performance audit."""
    # question_bank: composite index for bank_mode filtering
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qb_deleted_owner_status ON question_bank(deleted_at, owner_id, status)")
    # questions_detail: index on question text for delete/edit operations
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qd_question ON questions_detail(question)")
    # user_practice_history: composite index for daily trend queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uph_user_date ON user_practice_history(user_id, created_at)")
    # analysis_queue: index for dequeue operations
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_status_created ON analysis_queue(status, created_at)")
