"""Schema hygiene migrations 090+: repair destructive FK strategies."""

from __future__ import annotations

import logging

logger = logging.getLogger("interview-boss")


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _column_exists(conn, table: str, column: str) -> bool:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info('{table}')")}
    return column in cols


def _fk_on_delete(conn, table: str, column: str) -> str | None:
    """返回该列 FK 的 ON DELETE 动作。"""
    for r in conn.execute(f"PRAGMA foreign_key_list('{table}')"):
        if r[3] == column:
            return r[6]  # on_delete 列
    return None


def migration_090_analysis_queue_fk(conn):
    """Add ON DELETE CASCADE to analysis_queue.interview_id."""
    if not _table_exists(conn, "analysis_queue"):
        return

    if not _column_exists(conn, "analysis_queue", "interview_id"):
        return

    # 检查是否已经是 CASCADE
    current_action = _fk_on_delete(conn, "analysis_queue", "interview_id")
    if current_action == "CASCADE":
        logger.info("migration_090: analysis_queue.interview_id 已是 CASCADE，跳过")
        return

    # 获取当前列信息
    columns = [row[1] for row in conn.execute("PRAGMA table_info('analysis_queue')")]
    cols = ", ".join(columns)

    # 创建新表（与 085 结构一致，仅修改 FK 策略）
    conn.execute("DROP TABLE IF EXISTS analysis_queue_new")
    conn.execute("""
        CREATE TABLE analysis_queue_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            question_detail_id INTEGER,
            owner_id INTEGER DEFAULT NULL,
            FOREIGN KEY (interview_id) REFERENCES interview(id) ON DELETE CASCADE,
            FOREIGN KEY (question_detail_id) REFERENCES questions_detail(id) ON DELETE CASCADE,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    # 复制数据
    conn.execute(f"INSERT INTO analysis_queue_new ({cols}) SELECT {cols} FROM analysis_queue")

    # 删除旧表
    conn.execute("DROP TABLE analysis_queue")

    # 重命名新表
    conn.execute("ALTER TABLE analysis_queue_new RENAME TO analysis_queue")

    # 重建索引
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_interview ON analysis_queue(interview_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_owner ON analysis_queue(owner_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_question_detail ON analysis_queue(question_detail_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_status ON analysis_queue(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_status_created ON analysis_queue(status, created_at)")

    logger.info("migration_090: analysis_queue.interview_id 已添加 ON DELETE CASCADE")


def migration_092_preserve_quality_issue_history(conn):
    """Keep quality issues after their source question is physically removed.

    A quality issue is an audit record, not disposable child data.  The old
    ``ON DELETE CASCADE`` FK removed it during a merge, making historical
    review results impossible to inspect.  ``source_qb_id`` keeps the
    original identity while ``qb_id`` is nulled by SQLite when the source is
    deleted.
    """
    if not _table_exists(conn, "quality_issue"):
        return

    table_info = {
        row[1]: row for row in conn.execute("PRAGMA table_info('quality_issue')")
    }
    qb_fk_action = _fk_on_delete(conn, "quality_issue", "qb_id")
    qb_not_null = bool(table_info.get("qb_id") and table_info["qb_id"][3])
    has_source_id = "source_qb_id" in table_info

    def _install_source_id_protection():
        conn.execute(
            "UPDATE quality_issue SET source_qb_id = qb_id "
            "WHERE source_qb_id IS NULL AND qb_id IS NOT NULL"
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS quality_issue_source_qb_id_backfill
            AFTER INSERT ON quality_issue
            WHEN NEW.source_qb_id IS NULL AND NEW.qb_id IS NOT NULL
            BEGIN
                UPDATE quality_issue SET source_qb_id = NEW.qb_id WHERE id = NEW.id;
            END
            """
        )

    if qb_fk_action == "SET NULL" and not qb_not_null and has_source_id:
        _install_source_id_protection()
        logger.info("migration_092: quality_issue history preservation already enabled")
        return

    columns = [
        "id",
        "qb_id",
        "source_qb_id",
        "variant_index",
        "issue_type",
        "suggested_action",
        "reason",
        "suggested_value",
        "confidence",
        "status",
        "created_at",
        "reviewed_at",
        "reviewed_by",
        "target_qb_id",
        "new_cat2",
        "review_version",
        "review_task_id",
        "trigger_reason",
        "variant_key",
        "source_question",
        "source_cat2",
        "issue_fingerprint",
        "superseded_at",
        "superseded_by",
    ]
    existing = set(table_info)
    copy_columns = []
    select_expressions = []
    for column in columns:
        if column == "source_qb_id":
            copy_columns.append(column)
            select_expressions.append("source_qb_id" if has_source_id else "qb_id")
        elif column in existing:
            copy_columns.append(column)
            select_expressions.append(column)

    conn.execute("DROP TABLE IF EXISTS quality_issue_new")
    conn.execute(
        """
        CREATE TABLE quality_issue_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qb_id INTEGER DEFAULT NULL,
            source_qb_id INTEGER DEFAULT NULL,
            variant_index INTEGER,
            issue_type TEXT NOT NULL,
            suggested_action TEXT NOT NULL,
            reason TEXT,
            suggested_value TEXT,
            confidence REAL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            reviewed_at TEXT,
            reviewed_by INTEGER,
            target_qb_id INTEGER DEFAULT NULL,
            new_cat2 TEXT DEFAULT NULL,
            review_version TEXT,
            review_task_id TEXT,
            trigger_reason TEXT,
            variant_key TEXT NOT NULL DEFAULT '',
            source_question TEXT DEFAULT NULL,
            source_cat2 TEXT DEFAULT NULL,
            issue_fingerprint TEXT,
            superseded_at TEXT,
            superseded_by INTEGER,
            FOREIGN KEY (qb_id) REFERENCES question_bank(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO quality_issue_new ({}) SELECT {} FROM quality_issue".format(
            ", ".join(copy_columns), ", ".join(select_expressions)
        )
    )
    conn.execute("DROP TABLE quality_issue")
    conn.execute("ALTER TABLE quality_issue_new RENAME TO quality_issue")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_quality_issue_fingerprint "
        "ON quality_issue(issue_fingerprint)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_quality_issue_review_version "
        "ON quality_issue(qb_id, review_version, status)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_quality_issue_active_fingerprint "
        "ON quality_issue(issue_fingerprint) "
        "WHERE issue_fingerprint IS NOT NULL AND status IN ('pending', 'approved')"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_quality_issue_review_version "
        "ON quality_issue(qb_id, review_version, issue_type, variant_key) "
        "WHERE review_version IS NOT NULL"
    )
    _install_source_id_protection()
    logger.info(
        "migration_092: quality_issue 保留来源题 ID，来源题删除时审计记录改为 SET NULL"
    )
