"""
测试：修复重新分析面经时的清理顺序问题

问题：cluster_batch 中 _cleanup_old_sources_txn_v2 在聚类之后执行，
导致旧 QB 条目参与聚类决策。

修复：在加载 existing_rows 之前先清理当前批次 URL 的旧 QB 贡献。
"""

import json
import sqlite3
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.faiss_index_manager import FAISSIndexManager
import asyncio


# ============================================================
# Helper
# ============================================================
def create_test_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            bank_mode TEXT DEFAULT 'public',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE job_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE interview (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            company TEXT,
            round TEXT,
            focus TEXT,
            questions_list TEXT,
            difficulty TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            season TEXT DEFAULT '',
            owner_id INTEGER REFERENCES users(id),
            status TEXT DEFAULT 'approved',
            job_position TEXT DEFAULT '',
            deleted_at TIMESTAMP,
            analysis_status TEXT DEFAULT 'idle',
            analysis_stage TEXT,
            analysis_result TEXT,
            analysis_updated_at TIMESTAMP
        );
        CREATE TABLE questions_detail (
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
            deleted_at TIMESTAMP
        );
        CREATE TABLE question_bank (
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
            embedding BLOB,
            cluster_id INTEGER DEFAULT NULL,
            owner_id INTEGER,
            submitted_by INTEGER,
            status TEXT DEFAULT 'approved',
            job_position TEXT DEFAULT '',
            duplicate_of INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES users(id),
            FOREIGN KEY (submitted_by) REFERENCES users(id)
        );
        CREATE TABLE question_position (
            question_id INTEGER NOT NULL,
            position_id INTEGER NOT NULL,
            PRIMARY KEY (question_id, position_id),
            FOREIGN KEY (question_id) REFERENCES question_bank(id) ON DELETE CASCADE,
            FOREIGN KEY (position_id) REFERENCES job_positions(id) ON DELETE CASCADE
        );
        CREATE TABLE user_practice_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            user_answer TEXT,
            evaluation_result TEXT,
            score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id)
        );
        CREATE TABLE user_question_view (
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
        CREATE TABLE analysis_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER NOT NULL,
            question_detail_id INTEGER,
            status TEXT DEFAULT 'pending',
            owner_id INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            UNIQUE(question_detail_id),
            FOREIGN KEY (interview_id) REFERENCES interview(id)
        );
    """)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES (1, 'testuser', 'hash', 1)"
    )
    conn.execute("INSERT INTO job_positions (id, name) VALUES (1, 'agent开发')")
    conn.commit()
    return conn


def make_question_bank_row(
    conn,
    qb_id,
    question,
    cat2="B1.Agent架构与范式",
    frequency=1,
    sources=None,
    oqs=None,
    oqs_sources=None,
    owner_id=None,
    job_position="agent开发",
    ai_answer=None,
):
    if sources is None:
        sources = json.dumps(
            [{"url": "http://example.com/1", "company": "测试公司", "round": "一面"}],
            ensure_ascii=False,
        )
    if oqs is None:
        oqs = json.dumps([question], ensure_ascii=False)
    if oqs_sources is None:
        oqs_sources = json.dumps(
            [{"question": question, "sources": [{"url": "http://example.com/1"}]}],
            ensure_ascii=False,
        )
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, tags, difficulty, frequency, sources, "
        "original_questions, original_question_sources, owner_id, job_position, ai_answer) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            qb_id,
            question,
            "B.Agent与LLM应用",
            cat2,
            "Agent架构设计",
            "L2-中等",
            frequency,
            sources,
            oqs,
            oqs_sources,
            owner_id,
            job_position,
            ai_answer,
        ),
    )
    conn.commit()


def make_interview(conn, interview_id, url, questions_list, job_position="agent开发"):
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, job_position, owner_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (interview_id, url, "测试公司", "一面", questions_list, job_position, 1),
    )
    conn.commit()


def make_questions_detail(conn, url, questions, job_position="agent开发"):
    for i, q in enumerate(questions):
        conn.execute(
            "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag, job_position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                url,
                "测试公司",
                "一面",
                q,
                "B.Agent与LLM应用",
                "B1.Agent架构与范式",
                "Agent架构设计",
                "L2-中等",
                job_position,
            ),
        )
    conn.commit()


async def mock_run_db_sync(func):
    """Mock run_db to run synchronously in the same thread (avoids SQLite thread issues)"""
    return func()


# ============================================================
# T-001: 聚类前清理 — 旧条目不参与聚类
# ============================================================
class TestCleanupBeforeClustering:
    """cluster_batch 应先清理旧 QB 贡献，再加载 existing_rows 做聚类"""

    @pytest.mark.asyncio
    async def test_old_qb_excluded_from_clustering_context(self):
        """
        重新分析面经X时，面经X的独占旧 QB 条目不应出现在聚类上下文中。

        场景：
        - QB条目1: question="什么是RAG", sources=[面经X], 独占URL_X
        - 新 tagged 数据: URL_X → ["请解释RAG架构"]

        预期：
        - cluster_all_questions 接收的 all_items 中不应包含 QB条目1
        - 因为 URL_X 的旧贡献应在聚类前被清理（独占 → 整条删除）
        """
        conn = create_test_db()
        make_interview(conn, 1, "http://url-x.com", "什么是RAG")

        # 旧 QB 条目：独占 URL_X
        sources_x = json.dumps(
            [{"url": "http://url-x.com", "company": "公司X", "round": "一面"}],
            ensure_ascii=False,
        )
        oqs_x = json.dumps(["什么是RAG"], ensure_ascii=False)
        oqs_src_x = json.dumps(
            [{"question": "什么是RAG", "sources": [{"url": "http://url-x.com"}]}],
            ensure_ascii=False,
        )
        make_question_bank_row(
            conn,
            1,
            "什么是RAG",
            frequency=1,
            sources=sources_x,
            oqs=oqs_x,
            oqs_sources=oqs_src_x,
        )

        # 新 tagged 数据
        make_questions_detail(conn, "http://url-x.com", ["请解释RAG架构"])

        captured_new_rows = []
        captured_existing = {}

        async def mock_process_incremental(new_rows, existing_by_cat2, user_id=None):
            captured_new_rows.extend(new_rows)
            captured_existing.update(existing_by_cat2)
            return {"matched_to_existing": [], "new_clusters": []}

        with (
            patch("app.services.pipeline.queue.get_db_connection", return_value=conn),
            patch("app.services.pipeline.batch.get_db_connection", return_value=conn),
            patch("app.services.pipeline.writer.get_db_connection", return_value=conn),
            patch("app.db.connection.run_db", side_effect=mock_run_db_sync),
            patch(
                "app.services.pipeline.batch.process_incremental_batch",
                side_effect=mock_process_incremental,
            ),
            patch(
                "app.services.clustering.generate_unified_question",
                new_callable=AsyncMock,
                return_value="mock unified",
            ),
            patch(
                "app.services.pipeline.batch.get_index_manager",
                return_value=FAISSIndexManager(),
            ),
        ):
            from app.services.pipeline import (
                cluster_batch,
                enqueue_questions,
                dequeue_batch,
            )

            enqueue_questions(1)
            batch = dequeue_batch(20)
            await cluster_batch(batch, user_id=1)

        # 关键断言：聚类上下文中不应包含旧的 QB 条目
        assert captured_existing == {}, (
            f"旧 QB 条目不应出现在聚类上下文中，但发现: {captured_existing}"
        )

        # 新题应存在
        assert len(captured_new_rows) == 1, (
            f"应有 1 个新题，实际: {len(captured_new_rows)}"
        )

        conn.close()

    @pytest.mark.asyncio
    async def test_shared_qb_kept_but_url_removed(self):
        """
        QB条目有多个来源URL时，只移除目标URL的贡献，其他URL保留。

        场景：
        - QB条目1: question="什么是RAG", sources=[面经X, 面经Y]
        - 重新分析面经X

        预期：
        - 聚类上下文中 QB条目1 仍存在（因为面经Y还在）
        - 但 sources 中只剩面经Y
        """
        conn = create_test_db()
        make_interview(conn, 1, "http://url-x.com", "什么是RAG")
        make_interview(conn, 2, "http://url-y.com", "什么是RAG")

        # QB 条目：有两个来源
        sources_xy = json.dumps(
            [
                {"url": "http://url-x.com", "company": "公司X", "round": "一面"},
                {"url": "http://url-y.com", "company": "公司Y", "round": "二面"},
            ],
            ensure_ascii=False,
        )
        oqs = json.dumps(["什么是RAG"], ensure_ascii=False)
        oqs_src = json.dumps(
            [
                {
                    "question": "什么是RAG",
                    "sources": [
                        {"url": "http://url-x.com"},
                        {"url": "http://url-y.com"},
                    ],
                },
            ],
            ensure_ascii=False,
        )
        make_question_bank_row(
            conn,
            1,
            "什么是RAG",
            frequency=2,
            sources=sources_xy,
            oqs=oqs,
            oqs_sources=oqs_src,
        )

        make_questions_detail(conn, "http://url-x.com", ["请解释RAG架构"])

        captured_existing = {}

        async def mock_process_incremental(new_rows, existing_by_cat2, user_id=None):
            captured_existing.update(existing_by_cat2)
            return {"matched_to_existing": [], "new_clusters": []}

        with (
            patch("app.services.pipeline.queue.get_db_connection", return_value=conn),
            patch("app.services.pipeline.batch.get_db_connection", return_value=conn),
            patch("app.services.pipeline.writer.get_db_connection", return_value=conn),
            patch("app.db.connection.run_db", side_effect=mock_run_db_sync),
            patch(
                "app.services.pipeline.batch.process_incremental_batch",
                side_effect=mock_process_incremental,
            ),
            patch(
                "app.services.clustering.generate_unified_question",
                new_callable=AsyncMock,
                return_value="mock unified",
            ),
            patch(
                "app.services.pipeline.batch.get_index_manager",
                return_value=FAISSIndexManager(),
            ),
        ):
            from app.services.pipeline import (
                cluster_batch,
                enqueue_questions,
                dequeue_batch,
            )

            enqueue_questions(1)
            batch = dequeue_batch(20)
            await cluster_batch(batch, user_id=1)

        # QB条目1 应仍在聚类上下文中（因为 URL_Y 还在）
        existing_items = [item for rows in captured_existing.values() for item in rows]
        assert len(existing_items) == 1, (
            f"共享条目应保留在聚类上下文中，实际: {len(existing_items)}"
        )

        # sources 中应只剩 URL_Y
        qb_after = conn.execute(
            "SELECT sources FROM question_bank WHERE id = 1"
        ).fetchone()
        if qb_after:
            remaining_sources = json.loads(qb_after["sources"])
            urls = [s["url"] for s in remaining_sources]
            assert "http://url-x.com" not in urls, "URL_X 应被移除"
            assert "http://url-y.com" in urls, "URL_Y 应保留"

        conn.close()

    @pytest.mark.asyncio
    async def test_ai_answer_preserved_after_recluster(self):
        """
        重新分析后，如果新聚类包含已有条目，AI答案应被保留。
        """
        conn = create_test_db()
        make_interview(conn, 1, "http://url-x.com", "什么是RAG")
        make_interview(conn, 2, "http://url-y.com", "什么是RAG")

        # QB 条目：有两个来源，有 AI 答案
        sources_xy = json.dumps(
            [
                {"url": "http://url-x.com", "company": "公司X", "round": "一面"},
                {"url": "http://url-y.com", "company": "公司Y", "round": "二面"},
            ],
            ensure_ascii=False,
        )
        make_question_bank_row(
            conn,
            1,
            "什么是RAG",
            frequency=2,
            sources=sources_xy,
            oqs=json.dumps(["什么是RAG"], ensure_ascii=False),
            oqs_sources=json.dumps(
                [
                    {
                        "question": "什么是RAG",
                        "sources": [
                            {"url": "http://url-x.com"},
                            {"url": "http://url-y.com"},
                        ],
                    },
                ],
                ensure_ascii=False,
            ),
            ai_answer="RAG是检索增强生成的缩写...",
        )

        make_questions_detail(conn, "http://url-x.com", ["请解释RAG架构"])

        async def mock_process_incremental(new_rows, existing_by_cat2, user_id=None):
            return {
                "matched_to_existing": [],
                "new_clusters": [
                    {
                        "representative": "什么是RAG",
                        "items": [
                            {
                                "question": "什么是RAG",
                                "cat1": "B.Agent与LLM应用",
                                "cat2": "B1.Agent架构与范式",
                                "tags": "Agent架构设计",
                                "diff_tag": "L2-中等",
                                "url": "http://url-x.com",
                                "company": "公司X",
                                "round": "一面",
                            }
                        ],
                    }
                ],
            }

        with (
            patch("app.services.pipeline.queue.get_db_connection", return_value=conn),
            patch("app.services.pipeline.batch.get_db_connection", return_value=conn),
            patch("app.services.pipeline.writer.get_db_connection", return_value=conn),
            patch("app.db.connection.run_db", side_effect=mock_run_db_sync),
            patch(
                "app.services.pipeline.batch.process_incremental_batch",
                side_effect=mock_process_incremental,
            ),
            patch(
                "app.services.clustering.generate_unified_question",
                new_callable=AsyncMock,
                return_value="什么是RAG",
            ),
            patch(
                "app.services.pipeline.batch.get_index_manager",
                return_value=FAISSIndexManager(),
            ),
        ):
            from app.services.pipeline import (
                cluster_batch,
                enqueue_questions,
                dequeue_batch,
            )

            enqueue_questions(1)
            batch = dequeue_batch(20)
            await cluster_batch(batch, user_id=1)

        # 新聚类应有 AI 答案
        new_qb = conn.execute(
            "SELECT * FROM question_bank WHERE id > 1 AND ai_answer IS NOT NULL AND ai_answer != ''"
        ).fetchone()
        assert new_qb is not None, "新聚类应继承 AI 答案"
        assert "RAG是检索增强生成" in new_qb["ai_answer"], (
            f"AI 答案内容不正确: {new_qb['ai_answer']}"
        )

        conn.close()
