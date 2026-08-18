"""Practice plans and per-user spaced-repetition state migration."""

import json


def _migration_055_practice_review_system(conn):
    """Create named study plans, review state, and review event history."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS practice_decks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            deck_type TEXT NOT NULL DEFAULT 'system',
            criteria_json TEXT NOT NULL DEFAULT '{}',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_question_review (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'new',
            proficiency INTEGER NOT NULL DEFAULT 0,
            review_count INTEGER NOT NULL DEFAULT 0,
            lapse_count INTEGER NOT NULL DEFAULT 0,
            last_rating TEXT DEFAULT '',
            last_score INTEGER,
            last_reviewed_at TIMESTAMP,
            next_review_at TIMESTAMP,
            interval_days REAL NOT NULL DEFAULT 0,
            ease_factor REAL NOT NULL DEFAULT 2.3,
            stability_days REAL NOT NULL DEFAULT 0,
            difficulty REAL NOT NULL DEFAULT 0.3,
            algorithm TEXT NOT NULL DEFAULT 'sm2_lite',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE,
            UNIQUE (user_id, question_bank_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS practice_review_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            review_id INTEGER NOT NULL,
            rating TEXT NOT NULL,
            score INTEGER,
            source TEXT NOT NULL DEFAULT 'flashcard',
            reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE,
            FOREIGN KEY (review_id) REFERENCES user_question_review(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_practice_deck_key "
        "ON practice_decks(deck_key)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_uqr_user_question "
        "ON user_question_review(user_id, question_bank_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_uqr_due "
        "ON user_question_review(user_id, next_review_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_uqr_proficiency "
        "ON user_question_review(user_id, proficiency)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_practice_events_user_time "
        "ON practice_review_events(user_id, reviewed_at)"
    )

    decks = (
        ("due", "今日复习", "先处理已经到期和还没开始的题", {"kind": "due"}, 1),
        (
            "high-frequency",
            "高频必刷",
            "从高频题库同步来的面试重点",
            {"kind": "high_frequency", "min_frequency": 3},
            2,
        ),
        ("starred", "收藏题单", "把收藏题集中起来反复背", {"kind": "starred"}, 3),
        (
            "unpracticed",
            "还没刷过",
            "题库里尚未建立记忆记录的题",
            {"kind": "unpracticed"},
            4,
        ),
        ("all", "全部题库", "按复习优先级浏览全部可见题目", {"kind": "all"}, 5),
    )
    for key, name, description, criteria, sort_order in decks:
        conn.execute(
            """
            INSERT INTO practice_decks
                (deck_key, name, description, criteria_json, sort_order)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(deck_key) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                criteria_json = excluded.criteria_json,
                sort_order = excluded.sort_order,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, name, description, json.dumps(criteria, ensure_ascii=False), sort_order),
        )

    # Preserve the old answer-evaluation history in the new queue.  These
    # rows are intentionally due immediately so the first flashcard review
    # lets the scheduler establish a real interval instead of hiding legacy
    # practice behind the new table.
    conn.execute(
        """
        INSERT OR IGNORE INTO user_question_review (
            user_id, question_bank_id, state, proficiency, review_count,
            last_rating, last_score, last_reviewed_at, next_review_at,
            interval_days, ease_factor, stability_days, difficulty, algorithm
        )
        SELECT
            user_id,
            question_bank_id,
            CASE WHEN MAX(COALESCE(score, 0)) >= 85 THEN 'review' ELSE 'learning' END,
            CASE
                WHEN MAX(COALESCE(score, 0)) >= 85 THEN 3
                WHEN MAX(COALESCE(score, 0)) >= 65 THEN 2
                ELSE 1
            END,
            COUNT(*),
            CASE
                WHEN MAX(COALESCE(score, 0)) >= 85 THEN 'good'
                WHEN MAX(COALESCE(score, 0)) >= 65 THEN 'hard'
                ELSE 'again'
            END,
            MAX(score),
            MAX(created_at),
            CURRENT_TIMESTAMP,
            1,
            2.3,
            1,
            0.6,
            'sm2_lite'
        FROM user_practice_history
        GROUP BY user_id, question_bank_id
        """
    )


def _migration_094_review_event_answer_snapshot(conn):
    """Store the user answer snapshot on self-check review events (migration 094).

    双写收敛后 user_practice_history 已停写，练习记录 history tab 需读
    practice_review_events。新增可选 user_answer 快照列，仅 self_check
    源写入（闪卡复习无用户答案文本）。
    """

    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(practice_review_events)").fetchall()
    }
    if "user_answer" not in columns:
        conn.execute(
            "ALTER TABLE practice_review_events ADD COLUMN user_answer TEXT"
        )

    # best-effort 回填：从存量 user_practice_history 取每个 (user, question) 最新答案
    existing = conn.execute(
        "SELECT COUNT(*) AS c FROM practice_review_events WHERE user_answer IS NOT NULL"
    ).fetchone()
    if existing and existing[0] == 0:
        conn.execute(
            """
            UPDATE practice_review_events SET user_answer = (
                SELECT uph.user_answer FROM user_practice_history uph
                WHERE uph.user_id = practice_review_events.user_id
                  AND uph.question_bank_id = practice_review_events.question_bank_id
                ORDER BY uph.created_at DESC LIMIT 1
            )
            WHERE source = 'self_check' AND user_answer IS NULL
            """
        )


def _migration_096_review_event_evaluation_snapshot(conn):
    """Store the full evaluation JSON on self-check review events (migration 096).

    补 R11 回归：round-2 迁移 history 只快照了 user_answer，丢掉了
    evaluation_result（维度分解/改进建议）。新增可选 evaluation_result
    JSON 快照列，仅 self_check 源写入，history 端点返回它。
    """

    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(practice_review_events)").fetchall()
    }
    if "evaluation_result" not in columns:
        conn.execute(
            "ALTER TABLE practice_review_events ADD COLUMN evaluation_result TEXT"
        )

    # best-effort 回填：从存量 user_practice_history 取每个 (user, question) 最新评估 JSON
    existing = conn.execute(
        "SELECT COUNT(*) AS c FROM practice_review_events WHERE evaluation_result IS NOT NULL"
    ).fetchone()
    if existing and existing[0] == 0:
        conn.execute(
            """
            UPDATE practice_review_events SET evaluation_result = (
                SELECT uph.evaluation_result FROM user_practice_history uph
                WHERE uph.user_id = practice_review_events.user_id
                  AND uph.question_bank_id = practice_review_events.question_bank_id
                ORDER BY uph.created_at DESC LIMIT 1
            )
            WHERE source = 'self_check' AND evaluation_result IS NULL
            """
        )


