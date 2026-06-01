"""事务一致性测试 — 验证多表写入操作的原子性

使用内存 SQLite 真实执行 SQL，模拟中途失败场景，
确保 BEGIN/rollback 能正确防止孤儿数据。
"""
import json
import sqlite3
import pytest
from unittest.mock import patch, MagicMock


# ── 完整 schema（从 init_db 提取的关键表定义）──────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0,
    bank_mode TEXT DEFAULT 'public',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    current_position_id INTEGER,
    personal_position TEXT
);

CREATE TABLE IF NOT EXISTS job_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS question_bank (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    cat1 TEXT,
    cat2 TEXT,
    tags TEXT,
    difficulty TEXT,
    frequency INTEGER DEFAULT 1,
    ai_answer TEXT,
    vector TEXT,
    sources TEXT DEFAULT '[]',
    original_questions TEXT DEFAULT '[]',
    original_question_sources TEXT DEFAULT '[]',
    is_starred INTEGER DEFAULT 0,
    owner_id INTEGER,
    submitted_by INTEGER,
    status TEXT DEFAULT 'approved',
    job_position TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users(id),
    FOREIGN KEY (submitted_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS questions_detail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT,
    company TEXT,
    round TEXT,
    question TEXT,
    cat1 TEXT,
    cat2 TEXT,
    tags TEXT,
    diff_tag TEXT,
    job_position TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    deleted_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_qd_url ON questions_detail(url);

CREATE TABLE IF NOT EXISTS interview (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT,
    company TEXT,
    round TEXT,
    focus TEXT,
    questions_list TEXT,
    difficulty TEXT,
    season TEXT DEFAULT '',
    owner_id INTEGER REFERENCES users(id),
    status TEXT DEFAULT 'approved',
    job_position TEXT DEFAULT '',
    url_signature TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jd (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT,
    company TEXT,
    job_title TEXT,
    salary TEXT,
    tech_stack TEXT,
    bonus TEXT,
    season TEXT DEFAULT '',
    owner_id INTEGER REFERENCES users(id),
    status TEXT DEFAULT 'approved',
    url_signature TEXT DEFAULT '',
    job_position TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_question_view (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    question_bank_id INTEGER NOT NULL,
    is_starred INTEGER DEFAULT 0,
    personal_tags TEXT DEFAULT '',
    note TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS question_position (
    question_id INTEGER NOT NULL,
    position_id INTEGER NOT NULL,
    PRIMARY KEY (question_id, position_id),
    FOREIGN KEY (question_id) REFERENCES question_bank(id) ON DELETE CASCADE,
    FOREIGN KEY (position_id) REFERENCES job_positions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_practice_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    question_bank_id INTEGER NOT NULL,
    user_answer TEXT,
    evaluation_result TEXT,
    score INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (question_bank_id) REFERENCES question_bank(id)
);
"""


def _make_memory_conn():
    """创建带完整 schema 的内存 SQLite 连接"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    return conn


def _seed(conn):
    """插入基础种子数据"""
    conn.execute("INSERT INTO users (id, username, password_hash, is_admin) VALUES (1, 'admin', 'hash', 1)")
    conn.execute("INSERT INTO users (id, username, password_hash, is_admin) VALUES (2, 'user', 'hash', 0)")
    conn.execute("INSERT INTO job_positions (id, name) VALUES (1, 'agent开发')")
    conn.commit()


def _count(conn, table, where="1=1"):
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


# ═══════════════════════════════════════════════════════════════
#  T-001: build_master_bank / _save 重建题库
# ═══════════════════════════════════════════════════════════════

class TestT001_RebuildSave:
    """_save 函数：DELETE 3表 → INSERT 2表，中途失败必须完全回滚"""

    def test_save_success_commits_all(self):
        """成功时：旧数据被删除，新数据被写入"""
        conn = _make_memory_conn()
        _seed(conn)
        # 插入旧题库数据
        conn.execute("INSERT INTO question_bank (id, question, job_position, owner_id) VALUES (100, '旧题目', 'agent开发', NULL)")
        conn.execute("INSERT INTO question_position (question_id, position_id) VALUES (100, 1)")
        conn.execute("INSERT INTO user_question_view (user_id, question_bank_id) VALUES (1, 100)")
        conn.commit()

        # 模拟 _save：DELETE 3表 + INSERT 新数据
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("DELETE FROM user_question_view WHERE question_bank_id IN (SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)", ('agent开发',))
            cursor.execute("DELETE FROM question_position WHERE question_id IN (SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)", ('agent开发',))
            cursor.execute("DELETE FROM question_bank WHERE job_position = ? AND owner_id IS NULL", ('agent开发',))
            cursor.execute("INSERT INTO question_bank (question, job_position, owner_id, submitted_by) VALUES (?, ?, NULL, 1)", ('新题目A', 'agent开发'))
            cursor.execute("INSERT INTO question_bank (question, job_position, owner_id, submitted_by) VALUES (?, ?, NULL, 1)", ('新题目B', 'agent开发'))
            pos_row = cursor.execute("SELECT id FROM job_positions WHERE name = 'agent开发'").fetchone()
            cursor.execute("INSERT OR IGNORE INTO question_position (question_id, position_id) SELECT id, ? FROM question_bank WHERE job_position = ?", (pos_row[0], 'agent开发'))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        assert _count(conn, 'question_bank') == 2
        assert _count(conn, 'question_bank', "question = '旧题目'") == 0
        assert _count(conn, 'user_question_view') == 0
        conn.close()

    def test_save_insert_failure_rolls_back_everything(self):
        """INSERT 失败时：旧数据应完整保留（全部回滚）"""
        conn = _make_memory_conn()
        _seed(conn)
        # 插入旧题库数据
        conn.execute("INSERT INTO question_bank (id, question, job_position, owner_id) VALUES (100, '旧题目', 'agent开发', NULL)")
        conn.execute("INSERT INTO question_position (question_id, position_id) VALUES (100, 1)")
        conn.execute("INSERT INTO user_question_view (user_id, question_bank_id) VALUES (1, 100)")
        conn.commit()

        old_qb = _count(conn, 'question_bank')
        old_qp = _count(conn, 'question_position')
        old_uqv = _count(conn, 'user_question_view')

        # 模拟 _save 中途失败（用显式事务）
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("DELETE FROM user_question_view WHERE question_bank_id IN (SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)", ('agent开发',))
            cursor.execute("DELETE FROM question_position WHERE question_id IN (SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)", ('agent开发',))
            cursor.execute("DELETE FROM question_bank WHERE job_position = ? AND owner_id IS NULL", ('agent开发',))
            # 第一条 INSERT 成功
            cursor.execute("INSERT INTO question_bank (question, job_position, owner_id, submitted_by) VALUES (?, ?, NULL, 1)", ('新题目A', 'agent开发'))
            # 第二条 INSERT 触发错误（NOT NULL 约束）
            cursor.execute("INSERT INTO question_bank (question, job_position, owner_id, submitted_by) VALUES (NULL, ?, NULL, 1)", ('agent开发',))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()

        # 验证：旧数据完整保留
        assert _count(conn, 'question_bank') == old_qb, "旧题目应保留"
        assert _count(conn, 'question_position') == old_qp, "旧 position 关联应保留"
        assert _count(conn, 'user_question_view') == old_uqv, "旧 view 记录应保留"
        assert _count(conn, 'question_bank', "question = '旧题目'") == 1
        conn.close()


# ═══════════════════════════════════════════════════════════════
#  T-002: split_question / _split 拆分题目
# ═══════════════════════════════════════════════════════════════

class TestT002_SplitQuestion:
    """_split：INSERT新题 + question_position + UPDATE/DELETE原题，中途失败必须完全回滚"""

    def _seed_cluster(self, conn):
        """插入一个含 2 道原始题的聚类"""
        conn.execute(
            "INSERT INTO question_bank (id, question, cat1, cat2, tags, difficulty, frequency, sources, "
            "original_questions, original_question_sources, job_position, owner_id, submitted_by) "
            "VALUES (10, '统一问题', 'A', 'A1', 'tag', 'L1', 2, '[]', "
            "'[\"原始题A\", \"原始题B\"]', "
            "'[{\"question\":\"原始题A\",\"sources\":[{\"url\":\"u1\"}]}, "
            " {\"question\":\"原始题B\",\"sources\":[{\"url\":\"u2\"}]}]', "
            "'agent开发', NULL, 1)"
        )
        conn.execute("INSERT INTO question_position (question_id, position_id) VALUES (10, 1)")
        conn.commit()

    def test_split_success_creates_new_row_and_updates_original(self):
        conn = _make_memory_conn()
        _seed(conn)
        self._seed_cluster(conn)

        original_q = "原始题A"
        row = conn.execute("SELECT * FROM question_bank WHERE id = 10").fetchone()
        orig_qs = json.loads(row['original_questions'])

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            # INSERT 新题
            cursor.execute(
                "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, sources, "
                "original_questions, original_question_sources, job_position, owner_id, submitted_by) "
                "VALUES (?, ?, ?, ?, ?, 1, '[]', '[]', '[]', ?, NULL, 1)",
                (original_q, row['cat1'], row['cat2'], row['tags'], row['difficulty'], row['job_position'])
            )
            new_id = cursor.execute("SELECT last_insert_rowid()").fetchone()[0]
            cursor.execute("INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, 1)", (new_id,))
            # UPDATE 原聚类
            new_orig = [q for q in orig_qs if q != original_q]
            cursor.execute("UPDATE question_bank SET original_questions = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 10",
                           (json.dumps(new_orig),))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        assert _count(conn, 'question_bank') == 2
        assert _count(conn, 'question_bank', f"id = {new_id}") == 1
        updated = conn.execute("SELECT original_questions FROM question_bank WHERE id = 10").fetchone()
        assert "原始题A" not in updated['original_questions']
        conn.close()

    def test_split_position_insert_fails_rolls_back_new_question(self):
        """question_position INSERT 失败时，新 question_bank 行应被回滚"""
        conn = _make_memory_conn()
        _seed(conn)
        self._seed_cluster(conn)

        original_q = "原始题A"
        row = conn.execute("SELECT * FROM question_bank WHERE id = 10").fetchone()
        orig_qs = json.loads(row['original_questions'])
        old_count = _count(conn, 'question_bank')

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute(
                "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, sources, "
                "original_questions, original_question_sources, job_position, owner_id, submitted_by) "
                "VALUES (?, ?, ?, ?, ?, 1, '[]', '[]', '[]', ?, NULL, 1)",
                (original_q, row['cat1'], row['cat2'], row['tags'], row['difficulty'], row['job_position'])
            )
            new_id = cursor.execute("SELECT last_insert_rowid()").fetchone()[0]
            # 故意让 QP INSERT 失败（引用不存在的 position_id=999，但有 CASCADE 所以用 FK 违规）
            cursor.execute("INSERT INTO question_position (question_id, position_id) VALUES (?, 999)", (new_id,))
            new_orig = [q for q in orig_qs if q != original_q]
            cursor.execute("UPDATE question_bank SET original_questions = ? WHERE id = 10", (json.dumps(new_orig),))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()

        assert _count(conn, 'question_bank') == old_count, "新题目应回滚"
        original = conn.execute("SELECT original_questions FROM question_bank WHERE id = 10").fetchone()
        assert "原始题A" in original['original_questions'], "原聚类不应被修改"
        conn.close()


# ═══════════════════════════════════════════════════════════════
#  T-003: merge_question / _merge 合并题目
# ═══════════════════════════════════════════════════════════════

class TestT003_MergeQuestion:
    """_merge：UPDATE目标聚类 + DELETE/UPDATE源聚类，中途失败必须完全回滚"""

    def _seed_two_clusters(self, conn):
        conn.execute(
            "INSERT INTO question_bank (id, question, original_questions, original_question_sources, sources, frequency, job_position, owner_id, submitted_by) "
            "VALUES (20, '目标聚类', '[\"目标原始\"]', '[{\"question\":\"目标原始\",\"sources\":[]}]', '[]', 1, 'agent开发', NULL, 1)"
        )
        conn.execute(
            "INSERT INTO question_bank (id, question, original_questions, original_question_sources, sources, frequency, job_position, owner_id, submitted_by) "
            "VALUES (21, '源聚类', '[\"源原始A\",\"源原始B\"]', "
            "'[{\"question\":\"源原始A\",\"sources\":[{\"url\":\"u1\"}]}, {\"question\":\"源原始B\",\"sources\":[{\"url\":\"u2\"}]}]', "
            "'[{\"url\":\"u1\"},{\"url\":\"u2\"}]', 2, 'agent开发', NULL, 1)"
        )
        conn.commit()

    def test_merge_success_removes_source_question(self):
        conn = _make_memory_conn()
        _seed(conn)
        self._seed_two_clusters(conn)

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            # UPDATE 目标
            cursor.execute("UPDATE question_bank SET original_questions = ?, frequency = ? WHERE id = 20",
                           (json.dumps(["目标原始", "源原始A"]), 2))
            # DELETE 源（只剩1个原始题时降级为 UPDATE，这里模拟2→1→删除场景）
            cursor.execute("DELETE FROM question_bank WHERE id = 21")
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        assert _count(conn, 'question_bank') == 1
        assert _count(conn, 'question_bank', "id = 21") == 0
        conn.close()

    def test_merge_source_delete_fails_rolls_back_target_update(self):
        """源聚类删除失败时，目标聚类的 UPDATE 应回滚

        注意：必须使用 SQL 级别的错误（IntegrityError/OperationalError），
        而非 Python 级别的错误（InterfaceError），因为只有 SQL 级错误
        才会让 SQLite 进入 'failed transaction' 状态，使 rollback 生效。
        """
        conn = _make_memory_conn()
        _seed(conn)
        self._seed_two_clusters(conn)

        # 在 question_bank 上加一个 NOT NULL 约束来触发 IntegrityError
        # （通过在 UPDATE 中违反 NOT NULL 来模拟源 DELETE 前的错误）
        conn.execute("CREATE TABLE _trap (id INTEGER NOT NULL)")
        conn.commit()

        old_target = conn.execute("SELECT original_questions FROM question_bank WHERE id = 20").fetchone()

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            # UPDATE 目标成功
            cursor.execute("UPDATE question_bank SET original_questions = ? WHERE id = 20",
                           (json.dumps(["目标原始", "源原始A"]),))
            # DELETE 源失败 — 触发 SQL 级 IntegrityError
            cursor.execute("INSERT INTO _trap VALUES (NULL)")
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()

        # 目标聚类应保持原状
        current_target = conn.execute("SELECT original_questions FROM question_bank WHERE id = 20").fetchone()
        assert current_target['original_questions'] == old_target['original_questions'], \
            "目标聚类应保持原状"
        # 源聚类应保持
        assert _count(conn, 'question_bank', "id = 21") == 1, "源聚类应保留"
        conn.close()


# ═══════════════════════════════════════════════════════════════
#  T-004: delete_master_question / _delete 级联删除
# ═══════════════════════════════════════════════════════════════

class TestT004_DeleteMasterQuestion:
    """_delete：5表级联删除，中途失败必须完全回滚"""

    def _seed_question_with_deps(self, conn):
        conn.execute(
            "INSERT INTO question_bank (id, question, job_position, owner_id, submitted_by) "
            "VALUES (50, '待删除题目', 'agent开发', NULL, 1)"
        )
        conn.execute("INSERT INTO question_position (question_id, position_id) VALUES (50, 1)")
        conn.execute("INSERT INTO user_question_view (user_id, question_bank_id) VALUES (1, 50)")
        conn.execute("INSERT INTO user_practice_history (user_id, question_bank_id) VALUES (1, 50)")
        conn.execute("INSERT INTO questions_detail (url, question, job_position) VALUES ('http://test.com', '待删除题目', 'agent开发')")
        # 引用该题目的其他 QB
        conn.execute(
            "INSERT INTO question_bank (id, question, original_questions, job_position, owner_id, submitted_by) "
            "VALUES (51, '其他聚类', '[\"待删除题目\"]', 'agent开发', NULL, 1)"
        )
        conn.commit()

    def test_delete_success_removes_from_all_tables(self):
        conn = _make_memory_conn()
        _seed(conn)
        self._seed_question_with_deps(conn)

        question_id = 50
        question_text = "待删除题目"

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("DELETE FROM questions_detail WHERE question = ?", (question_text,))
            # 清理其他 QB 的 stale 引用
            other_qb = cursor.execute(
                "SELECT id, original_questions FROM question_bank WHERE id != ? AND original_questions LIKE ?",
                (question_id, f'%{question_text}%')
            ).fetchall()
            for qb in other_qb:
                oq = json.loads(qb['original_questions'])
                oq = [q for q in oq if q != question_text]
                cursor.execute("UPDATE question_bank SET original_questions = ? WHERE id = ?",
                               (json.dumps(oq), qb['id']))
            cursor.execute("DELETE FROM user_question_view WHERE question_bank_id = ?", (question_id,))
            cursor.execute("DELETE FROM question_position WHERE question_id = ?", (question_id,))
            # 注意：user_practice_history 没有 ON DELETE CASCADE，必须先删
            cursor.execute("DELETE FROM user_practice_history WHERE question_bank_id = ?", (question_id,))
            cursor.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        assert _count(conn, 'question_bank', "id = 50") == 0
        assert _count(conn, 'user_practice_history', "question_bank_id = 50") == 0
        assert _count(conn, 'user_question_view', "question_bank_id = 50") == 0
        assert _count(conn, 'question_position', "question_id = 50") == 0
        assert _count(conn, 'questions_detail', "question = '待删除题目'") == 0
        # 其他 QB 的引用应被清理
        other = conn.execute("SELECT original_questions FROM question_bank WHERE id = 51").fetchone()
        assert "待删除题目" not in other['original_questions']
        conn.close()

    def test_delete_practice_history_failure_rolls_back_everything(self):
        """practice_history 删除失败时，所有表数据应完整保留"""
        conn = _make_memory_conn()
        _seed(conn)
        self._seed_question_with_deps(conn)

        question_id = 50
        question_text = "待删除题目"

        # 记录各表初始行数
        initial_qb = _count(conn, 'question_bank')
        initial_uph = _count(conn, 'user_practice_history')
        initial_uqv = _count(conn, 'user_question_view')
        initial_qp = _count(conn, 'question_position')
        initial_qd = _count(conn, 'questions_detail')

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("DELETE FROM questions_detail WHERE question = ?", (question_text,))
            cursor.execute("DELETE FROM user_question_view WHERE question_bank_id = ?", (question_id,))
            cursor.execute("DELETE FROM question_position WHERE question_id = ?", (question_id,))
            cursor.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
            # 最后一步失败
            cursor.execute("DELETE FROM user_practice_history WHERE question_bank_id = ?", ("not_an_int",))
            conn.commit()
        except Exception:
            conn.rollback()

        assert _count(conn, 'question_bank') == initial_qb, "question_bank 应回滚"
        assert _count(conn, 'user_practice_history') == initial_uph, "practice_history 应回滚"
        assert _count(conn, 'user_question_view') == initial_uqv, "user_question_view 应回滚"
        assert _count(conn, 'question_position') == initial_qp, "question_position 应回滚"
        assert _count(conn, 'questions_detail') == initial_qd, "questions_detail 应回滚"
        conn.close()


# ═══════════════════════════════════════════════════════════════
#  T-005: soft_delete 级联软删除
# ═══════════════════════════════════════════════════════════════

class TestT005_SoftDelete:
    """级联软删除：UPDATE interview + UPDATE questions_detail + cleanup sources，中途失败必须完全回滚"""

    def _seed_interview_data(self, conn):
        conn.execute("INSERT INTO interview (id, url, company, owner_id, job_position) VALUES (1, 'http://test.com', '测试公司', 1, 'agent开发')")
        conn.execute("INSERT INTO questions_detail (url, company, question, job_position) VALUES ('http://test.com', '测试公司', '题目A', 'agent开发')")
        conn.execute("INSERT INTO questions_detail (url, company, question, job_position) VALUES ('http://test.com', '测试公司', '题目B', 'agent开发')")
        conn.execute(
            "INSERT INTO question_bank (id, question, sources, frequency, job_position, owner_id, submitted_by) "
            "VALUES (100, '题库题', '[{\"url\":\"http://test.com\"}]', 1, 'agent开发', NULL, 1)"
        )
        conn.commit()

    def test_soft_delete_success_marks_all_deleted(self):
        conn = _make_memory_conn()
        _seed(conn)
        self._seed_interview_data(conn)

        url = 'http://test.com'
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            # cleanup sources
            affected = cursor.execute("SELECT id, sources FROM question_bank WHERE sources LIKE ?", (f'%{url}%',)).fetchall()
            for r in affected:
                sources = json.loads(r['sources'])
                new_sources = [s for s in sources if s.get('url') != url]
                if len(new_sources) != len(sources):
                    cursor.execute("UPDATE question_bank SET frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                   (len(new_sources), json.dumps(new_sources), r['id']))
            cursor.execute("DELETE FROM question_bank WHERE frequency <= 0 AND owner_id IS NULL")
            # 级联软删除
            cursor.execute("UPDATE questions_detail SET deleted_at = CURRENT_TIMESTAMP WHERE url = ? AND deleted_at IS NULL", (url,))
            cursor.execute("UPDATE interview SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (1,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        assert conn.execute("SELECT deleted_at FROM interview WHERE id = 1").fetchone()['deleted_at'] is not None
        assert _count(conn, 'questions_detail', "deleted_at IS NULL AND url = 'http://test.com'") == 0
        assert _count(conn, 'questions_detail', "deleted_at IS NOT NULL AND url = 'http://test.com'") == 2
        conn.close()

    def test_soft_delete_qd_failure_rolls_back_interview(self):
        """questions_detail 更新失败时，interview 的软删除应回滚"""
        conn = _make_memory_conn()
        _seed(conn)
        self._seed_interview_data(conn)

        # 创建一个 NOT NULL 约束表来触发 SQL 级错误
        conn.execute("CREATE TABLE _trap (id INTEGER NOT NULL)")
        conn.commit()

        url = 'http://test.com'
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            # 先清理 sources
            affected = cursor.execute("SELECT id, sources FROM question_bank WHERE sources LIKE ?", (f'%{url}%',)).fetchall()
            for r in affected:
                sources = json.loads(r['sources'])
                new_sources = [s for s in sources if s.get('url') != url]
                cursor.execute("UPDATE question_bank SET frequency = ?, sources = ? WHERE id = ?",
                               (len(new_sources), json.dumps(new_sources), r['id']))
            # interview 软删除成功
            cursor.execute("UPDATE interview SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (1,))
            # questions_detail 更新失败（SQL 级 IntegrityError）
            cursor.execute("INSERT INTO _trap VALUES (NULL)")
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()

        # interview 应保持未删除
        assert conn.execute("SELECT deleted_at FROM interview WHERE id = 1").fetchone()['deleted_at'] is None
        # questions_detail 也应保持未删除
        assert _count(conn, 'questions_detail', "deleted_at IS NULL AND url = 'http://test.com'") == 2
        conn.close()


# ═══════════════════════════════════════════════════════════════
#  T-006: retag_master_question 重新打标
# ═══════════════════════════════════════════════════════════════

class TestT006_RetagMasterQuestion:
    """QB 更新成功但 QD 更新失败时，两表 tag 应保持一致（全部回滚）"""

    def test_retag_success_updates_both_tables(self):
        conn = _make_memory_conn()
        _seed(conn)
        conn.execute("INSERT INTO question_bank (id, question, cat1, cat2, tags, difficulty, job_position, owner_id, submitted_by) VALUES (10, '测试题', '旧cat1', '旧cat2', '旧tag', 'L1', 'agent开发', NULL, 1)")
        conn.execute("INSERT INTO questions_detail (question, cat1, cat2, tags, diff_tag) VALUES ('测试题', '旧cat1', '旧cat2', '旧tag', 'L1')")
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("UPDATE question_bank SET cat1 = '新cat1', cat2 = '新cat2', tags = '新tag', difficulty = 'L2', updated_at = CURRENT_TIMESTAMP WHERE id = 10")
            cursor.execute("UPDATE questions_detail SET cat1 = '新cat1', cat2 = '新cat2', tags = '新tag', diff_tag = 'L2', updated_at = CURRENT_TIMESTAMP WHERE question = '测试题'")
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        qb = conn.execute("SELECT cat1, cat2, tags FROM question_bank WHERE id = 10").fetchone()
        qd = conn.execute("SELECT cat1, cat2, tags FROM questions_detail WHERE question = '测试题'").fetchone()
        assert qb['cat1'] == '新cat1'
        assert qd['cat1'] == '新cat1'
        conn.close()

    def test_retag_qd_failure_rolls_back_qb(self):
        """QD 更新失败时，QB 的 tag 更新应被回滚"""
        conn = _make_memory_conn()
        _seed(conn)
        conn.execute("INSERT INTO question_bank (id, question, cat1, cat2, tags, difficulty, job_position, owner_id, submitted_by) VALUES (10, '测试题', '旧cat1', '旧cat2', '旧tag', 'L1', 'agent开发', NULL, 1)")
        conn.execute("INSERT INTO questions_detail (question, cat1, cat2, tags, diff_tag) VALUES ('测试题', '旧cat1', '旧cat2', '旧tag', 'L1')")
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("UPDATE question_bank SET cat1 = '新cat1', cat2 = '新cat2', tags = '新tag' WHERE id = 10")
            # 故意失败
            cursor.execute("UPDATE questions_detail SET nonexistent_column = 'x' WHERE question = '测试题'")
            conn.commit()
        except Exception:
            conn.rollback()

        qb = conn.execute("SELECT cat1, tags FROM question_bank WHERE id = 10").fetchone()
        qd = conn.execute("SELECT cat1, tags FROM questions_detail WHERE question = '测试题'").fetchone()
        assert qb['cat1'] == '旧cat1', "QB cat1 应回滚"
        assert qd['cat1'] == '旧cat1', "QD cat1 应保持不变"
        conn.close()


# ═══════════════════════════════════════════════════════════════
#  T-007: upload_to_bank 上传题目
# ═══════════════════════════════════════════════════════════════

class TestT007_UploadToBank:
    """INSERT QB + INSERT QP，QP 失败时 QB 应回滚"""

    def test_upload_success_creates_qb_and_qp(self):
        conn = _make_memory_conn()
        _seed(conn)

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, job_position, owner_id, submitted_by, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved')",
                           ('新上传题', 'A', 'A1', 'tag', 'L1', 'agent开发', 2, 2))
            new_id = cursor.execute("SELECT last_insert_rowid()").fetchone()[0]
            cursor.execute("INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, 1)", (new_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        assert _count(conn, 'question_bank', "question = '新上传题'") == 1
        qb_id = conn.execute("SELECT id FROM question_bank WHERE question = '新上传题'").fetchone()[0]
        assert _count(conn, 'question_position', f"question_id = {qb_id}") == 1
        conn.close()

    def test_upload_qp_failure_rolls_back_qb(self):
        """QP INSERT 失败时，QB INSERT 应回滚"""
        conn = _make_memory_conn()
        _seed(conn)
        old_qb_count = _count(conn, 'question_bank')

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, job_position, owner_id, submitted_by, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved')",
                           ('新上传题', 'A', 'A1', 'tag', 'L1', 'agent开发', 2, 2))
            new_id = cursor.execute("SELECT last_insert_rowid()").fetchone()[0]
            # 故意让 QP INSERT 失败（FK 违规：position_id 不存在）
            cursor.execute("INSERT INTO question_position (question_id, position_id) VALUES (?, 999)", (new_id,))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()

        assert _count(conn, 'question_bank') == old_qb_count, "新题目应回滚"
        assert _count(conn, 'question_bank', "question = '新上传题'") == 0
        conn.close()


# ═══════════════════════════════════════════════════════════════
#  T-008: clear_db 清空数据库
# ═══════════════════════════════════════════════════════════════

class TestT008_ClearDB:
    """多表 DELETE，中途失败不应有部分清空"""

    def test_clear_success_empties_all_tables(self):
        conn = _make_memory_conn()
        _seed(conn)
        conn.execute("INSERT INTO interview (url, company, job_position, owner_id) VALUES ('u', 'c', 'pos', 1)")
        conn.execute("INSERT INTO questions_detail (url, question) VALUES ('u', 'q')")
        conn.execute("INSERT INTO question_bank (question, job_position, owner_id, submitted_by) VALUES ('q', 'pos', NULL, 1)")
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("DELETE FROM jd")
            cursor.execute("DELETE FROM interview")
            cursor.execute("DELETE FROM questions_detail")
            cursor.execute("DELETE FROM question_bank")
            cursor.execute("DELETE FROM user_practice_history")
            cursor.execute("DELETE FROM user_question_view")
            cursor.execute("DELETE FROM question_position")
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        assert _count(conn, 'interview') == 0
        assert _count(conn, 'questions_detail') == 0
        assert _count(conn, 'question_bank') == 0
        conn.close()

    def test_clear_mid_failure_rolls_back_all(self):
        """中途失败（模拟不存在的表）时，所有表数据应保留"""
        conn = _make_memory_conn()
        _seed(conn)
        conn.execute("INSERT INTO interview (url, company, job_position, owner_id) VALUES ('u', 'c', 'pos', 1)")
        conn.execute("INSERT INTO questions_detail (url, question) VALUES ('u', 'q')")
        conn.execute("INSERT INTO question_bank (question, job_position, owner_id, submitted_by) VALUES ('q', 'pos', NULL, 1)")
        conn.commit()

        initial_iv = _count(conn, 'interview')
        initial_qd = _count(conn, 'questions_detail')
        initial_qb = _count(conn, 'question_bank')

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("DELETE FROM jd")
            cursor.execute("DELETE FROM interview")
            cursor.execute("DELETE FROM questions_detail")
            cursor.execute("DELETE FROM question_bank")
            # 第5步失败
            cursor.execute("DELETE FROM nonexistent_table_xyz")
            conn.commit()
        except Exception:
            conn.rollback()

        assert _count(conn, 'interview') == initial_iv, "interview 数据应保留"
        assert _count(conn, 'questions_detail') == initial_qd, "questions_detail 数据应保留"
        assert _count(conn, 'question_bank') == initial_qb, "question_bank 数据应保留"
        conn.close()


# ═══════════════════════════════════════════════════════════════
#  T-009: _purge_soft_deleted 物理清理
# ═══════════════════════════════════════════════════════════════

class TestT009_PurgeSoftDeleted:
    """物理删除软删除记录，中途失败不应有部分清理"""

    def test_purge_success_removes_all_soft_deleted(self):
        conn = _make_memory_conn()
        _seed(conn)
        conn.execute("INSERT INTO interview (id, url, owner_id, deleted_at, job_position) VALUES (1, 'http://test.com', 1, '2026-01-01', 'pos')")
        conn.execute("INSERT INTO questions_detail (url, question, deleted_at) VALUES ('http://test.com', 'q1', '2026-01-01')")
        conn.execute("INSERT INTO jd (id, url, owner_id, deleted_at, job_position) VALUES (1, 'http://test.com', 1, '2026-01-01', 'pos')")
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("DELETE FROM questions_detail WHERE url = ? AND deleted_at IS NOT NULL", ('http://test.com',))
            cursor.execute("DELETE FROM interview WHERE id = ?", (1,))
            cursor.execute("DELETE FROM questions_detail WHERE url = ? AND deleted_at IS NOT NULL", ('http://test.com',))
            cursor.execute("DELETE FROM jd WHERE id = ?", (1,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        assert _count(conn, 'interview', "deleted_at IS NOT NULL") == 0
        assert _count(conn, 'jd', "deleted_at IS NOT NULL") == 0
        conn.close()

    def test_purge_jd_failure_rolls_back_interview_purge(self):
        """JD 删除失败时，interview 的清理应被回滚"""
        conn = _make_memory_conn()
        _seed(conn)
        conn.execute("INSERT INTO interview (id, url, owner_id, deleted_at, job_position) VALUES (1, 'http://test.com', 1, '2026-01-01', 'pos')")
        conn.execute("INSERT INTO questions_detail (url, question, deleted_at) VALUES ('http://test.com', 'q1', '2026-01-01')")
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute("DELETE FROM questions_detail WHERE url = ? AND deleted_at IS NOT NULL", ('http://test.com',))
            cursor.execute("DELETE FROM interview WHERE id = ?", (1,))
            # 故意失败
            cursor.execute("DELETE FROM nonexistent_table_xyz")
            conn.commit()
        except Exception:
            conn.rollback()

        assert _count(conn, 'interview', "id = 1") == 1, "interview 记录应保留"
        assert _count(conn, 'questions_detail', "url = 'http://test.com'") == 1, "questions_detail 记录应保留"
        conn.close()


# ═══════════════════════════════════════════════════════════════
#  T-010: batch_delete_master_bank 批量删除
# ═══════════════════════════════════════════════════════════════

class TestT010_BatchDeleteMasterBank:
    """批量级联删除，中途失败必须完全回滚"""

    def _seed_batch(self, conn):
        for i in range(60, 63):
            conn.execute(
                f"INSERT INTO question_bank (id, question, job_position, owner_id, submitted_by) VALUES ({i}, '批量题{i}', 'agent开发', NULL, 1)")
            conn.execute(f"INSERT INTO question_position (question_id, position_id) VALUES ({i}, 1)")
            conn.execute(f"INSERT INTO user_question_view (user_id, question_bank_id) VALUES (1, {i})")
        conn.commit()

    def test_batch_delete_success(self):
        conn = _make_memory_conn()
        _seed(conn)
        self._seed_batch(conn)
        ids = [60, 61, 62]

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            ph = ",".join("?" * len(ids))
            cursor.execute(f"DELETE FROM user_question_view WHERE question_bank_id IN ({ph})", ids)
            cursor.execute(f"DELETE FROM question_position WHERE question_id IN ({ph})", ids)
            cursor.execute(f"DELETE FROM question_bank WHERE id IN ({ph})", ids)
            cursor.execute(f"DELETE FROM user_practice_history WHERE question_bank_id IN ({ph})", ids)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        assert _count(conn, 'question_bank', "id IN (60,61,62)") == 0
        assert _count(conn, 'user_question_view', "question_bank_id IN (60,61,62)") == 0
        conn.close()

    def test_batch_delete_failure_rolls_back_all(self):
        conn = _make_memory_conn()
        _seed(conn)
        self._seed_batch(conn)
        ids = [60, 61, 62]
        old_qb = _count(conn, 'question_bank')

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        try:
            ph = ",".join("?" * len(ids))
            cursor.execute(f"DELETE FROM user_question_view WHERE question_bank_id IN ({ph})", ids)
            cursor.execute(f"DELETE FROM question_position WHERE question_id IN ({ph})", ids)
            cursor.execute(f"DELETE FROM question_bank WHERE id IN ({ph})", ids)
            # 故意失败
            cursor.execute("DELETE FROM nonexistent_table_xyz")
            conn.commit()
        except Exception:
            conn.rollback()

        assert _count(conn, 'question_bank') == old_qb, "所有 QB 数据应保留"
        assert _count(conn, 'user_question_view', "question_bank_id IN (60,61,62)") == 3, "所有 view 记录应保留"
        assert _count(conn, 'question_position', "question_id IN (60,61,62)") == 3, "所有 position 记录应保留"
        conn.close()
