"""
端到端测试 — 两阶段流水线完整逻辑验证

覆盖场景：
1. 单条面经提交 → 标签 → 入队 → 触发聚类
2. 多条面经提交 → 批量聚类
3. 重建题库 → 清空 → 重新聚类
4. 数据一致性：无孤儿数据、队列状态正确、QB 和 QD 关系正确
5. 清理彻底性：_cleanup_old_sources_txn_v2 的完整覆盖

所有 LLM 调用均 mock，使用真实 SQLite 内存数据库。
"""
import json
import sqlite3
import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock


# ─────────────────────────────────────────────
#  Helper: 创建测试内存数据库
# ─────────────────────────────────────────────

def create_test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            bank_mode TEXT DEFAULT 'public',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            current_position_id INTEGER,
            personal_position TEXT DEFAULT ''
        );
        CREATE TABLE job_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            owner_id INTEGER,
            status TEXT DEFAULT 'approved',
            job_position TEXT DEFAULT '',
            url_signature TEXT DEFAULT '',
            updated_at TIMESTAMP,
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
            updated_at TIMESTAMP,
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
            owner_id INTEGER,
            submitted_by INTEGER,
            status TEXT DEFAULT 'approved',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMP,
            job_position TEXT DEFAULT '',
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
        CREATE TABLE analysis_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            FOREIGN KEY (interview_id) REFERENCES interview(id)
        );
        CREATE TABLE user_practice_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            user_answer TEXT,
            evaluation_result TEXT,
            score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE user_question_view (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            is_starred INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE user_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            UNIQUE(user_id, key)
        );
    """)
    conn.execute("INSERT INTO users (id, username, password_hash, is_admin) VALUES (1, 'admin', 'hash', 1)")
    conn.execute("INSERT INTO job_positions (id, name) VALUES (1, '后端开发')")
    conn.execute("INSERT INTO user_profile (user_id, key, value) VALUES (1, 'current_job_position', '后端开发')")
    conn.commit()
    return conn


def _make_interview(conn, iv_id, url, questions_list, company="测试公司", round_="一面", job_position="后端开发"):
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, job_position) VALUES (?, ?, ?, ?, ?, ?)",
        (iv_id, url, company, round_, questions_list, job_position)
    )
    conn.commit()


# ─────────────────────────────────────────────
#  Mock LLM
# ─────────────────────────────────────────────

def _mock_tag_batch(url, company, round_, questions, taxonomy_config=None, user_id=None):
    results = []
    for q in questions:
        if 'Redis' in q or '缓存' in q:
            results.append([url, company, round_, q, "数据库", "Redis", "Redis,缓存", "L2-中等"])
        elif 'TCP' in q or '网络' in q or 'HTTP' in q:
            results.append([url, company, round_, q, "计算机网络", "TCP", "TCP,网络", "L1-简单"])
        elif '算法' in q or '排序' in q or '快排' in q or '二分' in q or '归并' in q:
            results.append([url, company, round_, q, "算法", "排序", "排序,算法", "L3-困难"])
        else:
            results.append([url, company, round_, q, "未分类", "未分类", "", "L2-中等"])
    return results


def _mock_cluster_all_questions(items, user_id=None):
    groups = {}
    for item in items:
        cat2 = item.get('cat2', '未分类') or '未分类'
        if cat2 not in groups:
            groups[cat2] = []
        groups[cat2].append(item['id'])

    clusters = []
    for cat2, ids in groups.items():
        representative = next((i['question'] for i in items if i['id'] == ids[0]), '')
        clusters.append({"ids": ids, "representative": representative, "cat2": cat2})
    return clusters


def _mock_generate_unified(questions, sources_context=None, user_id=None):
    if len(questions) == 1:
        return questions[0]
    return f"（统一）{questions[0]} 等 {len(questions)} 个问题"


# ─────────────────────────────────────────────
#  Fixture: 每个测试注入内存 DB
# ─────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """mock get_db_connection 和 run_db，使用内存数据库"""
    conn = create_test_db()

    with patch('app.db.connection.get_db_connection', return_value=conn), \
         patch('app.db.operations.get_db_connection', return_value=conn), \
         patch('app.services.pipeline.get_db_connection', return_value=conn):

        async def _run_db_sync(func):
            return func()

        with patch('app.db.connection.run_db', side_effect=_run_db_sync), \
             patch('app.services.pipeline.run_db', side_effect=_run_db_sync):
            yield conn

    conn.close()


# ═════════════════════════════════════════════
#  测试 1: 单条面经完整流程
# ═════════════════════════════════════════════

class TestSingleInterview:
    """单条面经：标签 → 入队 → 聚类"""

    @patch('app.routers.submit.tag_questions_batch', side_effect=_mock_tag_batch)
    @patch('app.services.pipeline.cluster_all_questions', new_callable=AsyncMock, side_effect=_mock_cluster_all_questions)
    @patch('app.services.pipeline.generate_unified_question', new_callable=AsyncMock, side_effect=_mock_generate_unified)
    def test_full_pipeline(self, mock_uq, mock_cluster, mock_tag, mock_db):
        """单条面经走完两阶段流水线"""
        from app.services.pipeline import (
            tag_interview, enqueue_interview, should_trigger_clustering,
            dequeue_batch, cluster_batch, mark_batch_done, BATCH_SIZE
        )
        conn = mock_db

        async def _run():
            _make_interview(conn, 1, "https://iv1.com", "1. Redis 持久化？\n2. TCP 三次握手？\n3. 快排原理？")

            # 阶段1
            tagged = await tag_interview(1, "https://iv1.com", "腾讯", "一面",
                                         "1. Redis 持久化？\n2. TCP 三次握手？\n3. 快排原理？",
                                         job_position="后端开发")
            assert len(tagged) == 3

            # QD 写入了
            qd = conn.execute("SELECT * FROM questions_detail WHERE url = 'https://iv1.com'").fetchall()
            assert len(qd) == 3

            # QB 仍为空
            qb = conn.execute("SELECT * FROM question_bank").fetchall()
            assert len(qb) == 0

            # 入队
            qid = enqueue_interview(1)
            assert qid > 0

            # 触发条件
            assert should_trigger_clustering(BATCH_SIZE) is True

            # 阶段2
            batch = dequeue_batch(BATCH_SIZE)
            assert len(batch) == 1
            new_count = await cluster_batch(batch, user_id=1)
            mark_batch_done([b['queue_id'] for b in batch])

            # QB 生成（Redis/TCP/排序 三个聚类）
            qb_rows = conn.execute("SELECT * FROM question_bank WHERE owner_id IS NULL").fetchall()
            assert len(qb_rows) >= 2
            for r in qb_rows:
                assert r['sources'] and r['sources'] != '[]'
                assert r['original_questions'] and r['original_questions'] != '[]'
                assert r['frequency'] >= 1

            # 队列 done
            aq = conn.execute("SELECT * FROM analysis_queue WHERE interview_id = 1").fetchone()
            assert aq['status'] == 'done'

            # question_position 关联
            qp = conn.execute("SELECT * FROM question_position").fetchall()
            assert len(qp) == len(qb_rows)

        asyncio.run(_run())


# ═════════════════════════════════════════════
#  测试 2: 多条面经批量处理
# ═════════════════════════════════════════════

class TestBatchProcessing:
    """3 条面经提交后一起聚类"""

    @patch('app.routers.submit.tag_questions_batch', side_effect=_mock_tag_batch)
    @patch('app.services.pipeline.cluster_all_questions', new_callable=AsyncMock, side_effect=_mock_cluster_all_questions)
    @patch('app.services.pipeline.generate_unified_question', new_callable=AsyncMock, side_effect=_mock_generate_unified)
    def test_batch_merges_same_cat2(self, mock_uq, mock_cluster, mock_tag, mock_db):
        """相同 cat2 的题目被合并到同一聚类"""
        from app.services.pipeline import (
            tag_interview, enqueue_interview, should_trigger_clustering,
            dequeue_batch, cluster_batch, mark_batch_done, BATCH_SIZE
        )
        conn = mock_db

        async def _run():
            interviews = [
                (1, "https://iv1.com", "1. Redis 持久化？\n2. TCP 三次握手？"),
                (2, "https://iv2.com", "1. 缓存穿透？\n2. HTTP 状态码？"),
                (3, "https://iv3.com", "1. Redis 集群？\n2. 快排原理？"),
            ]
            for iv_id, url, ql in interviews:
                _make_interview(conn, iv_id, url, ql)
                await tag_interview(iv_id, url, "公司", "一面", ql, job_position="后端开发")
                enqueue_interview(iv_id)

            assert conn.execute("SELECT COUNT(*) as c FROM questions_detail").fetchone()['c'] == 6
            assert conn.execute("SELECT COUNT(*) as c FROM question_bank").fetchone()['c'] == 0
            assert should_trigger_clustering(BATCH_SIZE) is True

            batch = dequeue_batch(BATCH_SIZE)
            assert len(batch) == 3
            new_count = await cluster_batch(batch, user_id=1)
            mark_batch_done([b['queue_id'] for b in batch])

            qb_rows = conn.execute("SELECT * FROM question_bank WHERE owner_id IS NULL").fetchall()
            assert len(qb_rows) >= 3  # Redis/TCP/算法

            # Redis 聚类来自多个 URL
            redis_qb = [r for r in qb_rows if 'Redis' in (r['cat2'] or '')]
            assert len(redis_qb) >= 1
            sources = json.loads(redis_qb[0]['sources'])
            urls = {s['url'] for s in sources}
            assert len(urls) >= 2

            # 队列全部 done
            pending = conn.execute("SELECT COUNT(*) as c FROM analysis_queue WHERE status != 'done'").fetchone()['c']
            assert pending == 0

        asyncio.run(_run())


# ═════════════════════════════════════════════
#  测试 3: 重建题库流程
# ═════════════════════════════════════════════

class TestRebuildFlow:
    """清空 → 入队 → 聚类"""

    @patch('app.routers.submit.tag_questions_batch', side_effect=_mock_tag_batch)
    @patch('app.services.pipeline.cluster_all_questions', new_callable=AsyncMock, side_effect=_mock_cluster_all_questions)
    @patch('app.services.pipeline.generate_unified_question', new_callable=AsyncMock, side_effect=_mock_generate_unified)
    def test_rebuild_clears_old_and_creates_new(self, mock_uq, mock_cluster, mock_tag, mock_db):
        """重建后旧 QB 清除，新 QB 从 pipeline 生成"""
        from app.services.pipeline import (
            tag_interview, force_cluster_all_pending
        )
        conn = mock_db

        async def _run():
            # 准备数据
            for iv_id, url, ql in [
                (1, "https://iv1.com", "1. Redis 持久化？\n2. TCP 三次握手？"),
                (2, "https://iv2.com", "1. 缓存穿透？\n2. 快排原理？"),
            ]:
                _make_interview(conn, iv_id, url, ql)
                await tag_interview(iv_id, url, "公司", "一面", ql, job_position="后端开发")

            # 写入旧 QB
            conn.execute(
                "INSERT INTO question_bank (question, cat1, cat2, frequency, sources, original_questions, "
                "original_question_sources, owner_id, job_position) VALUES ('旧题', 'A', 'B', 1, '[]', '[]', '[]', NULL, '后端开发')"
            )
            conn.execute(
                "INSERT INTO user_practice_history (user_id, question_bank_id, user_answer, score) VALUES (1, 1, '答案', 80)"
            )
            conn.execute(
                "INSERT INTO user_question_view (user_id, question_bank_id, is_starred) VALUES (1, 1, 1)"
            )
            conn.commit()

            # ── 模拟重建 ──
            conn.execute("DELETE FROM user_practice_history WHERE question_bank_id IN (SELECT id FROM question_bank WHERE owner_id IS NULL)")
            conn.execute("DELETE FROM user_question_view WHERE question_bank_id IN (SELECT id FROM question_bank WHERE owner_id IS NULL)")
            conn.execute("DELETE FROM question_position WHERE question_id IN (SELECT id FROM question_bank WHERE owner_id IS NULL)")
            conn.execute("DELETE FROM question_bank WHERE owner_id IS NULL")
            conn.commit()

            assert conn.execute("SELECT COUNT(*) as c FROM question_bank").fetchone()['c'] == 0

            # 入队所有面经
            conn.execute("DELETE FROM analysis_queue")
            for iv_id in [1, 2]:
                conn.execute("INSERT INTO analysis_queue (interview_id, status) VALUES (?, 'pending')", (iv_id,))
            conn.commit()

            # 聚类
            result = await force_cluster_all_pending(user_id=1)

            qb_rows = conn.execute("SELECT * FROM question_bank WHERE owner_id IS NULL").fetchall()
            assert len(qb_rows) >= 2
            assert result['new_qb_count'] >= 2

            # 练习历史已清理
            ph = conn.execute("SELECT * FROM user_practice_history").fetchall()
            assert len(ph) == 0

            # 队列全部 done
            assert conn.execute("SELECT COUNT(*) as c FROM analysis_queue WHERE status != 'done'").fetchone()['c'] == 0

        asyncio.run(_run())


# ═════════════════════════════════════════════
#  测试 4: 数据一致性
# ═════════════════════════════════════════════

class TestDataConsistency:

    @patch('app.routers.submit.tag_questions_batch', side_effect=_mock_tag_batch)
    @patch('app.services.pipeline.cluster_all_questions', new_callable=AsyncMock, side_effect=_mock_cluster_all_questions)
    @patch('app.services.pipeline.generate_unified_question', new_callable=AsyncMock, side_effect=_mock_generate_unified)
    def test_phase1_does_not_touch_qb(self, mock_uq, mock_cluster, mock_tag, mock_db):
        """阶段1不碰 question_bank"""
        from app.services.pipeline import tag_interview
        conn = mock_db

        async def _run():
            _make_interview(conn, 1, "https://iv1.com", "1. Redis 持久化？")
            conn.execute("INSERT INTO question_bank (question, cat1, cat2, frequency, sources, owner_id, job_position) VALUES ('已有题', 'A', 'B', 1, '[]', NULL, '后端开发')")
            conn.commit()

            qb_before = conn.execute("SELECT * FROM question_bank").fetchall()
            await tag_interview(1, "https://iv1.com", "公司", "一面", "1. Redis 持久化？", job_position="后端开发")
            qb_after = conn.execute("SELECT * FROM question_bank").fetchall()

            assert len(qb_after) == len(qb_before)
            assert qb_after[0]['question'] == '已有题'

        asyncio.run(_run())

    @patch('app.routers.submit.tag_questions_batch', side_effect=_mock_tag_batch)
    @patch('app.services.pipeline.cluster_all_questions', new_callable=AsyncMock, side_effect=_mock_cluster_all_questions)
    @patch('app.services.pipeline.generate_unified_question', new_callable=AsyncMock, side_effect=_mock_generate_unified)
    def test_reprocess_no_duplicate_sources(self, mock_uq, mock_cluster, mock_tag, mock_db):
        """对同一 URL 重新聚类，sources 中无重复"""
        from app.services.pipeline import (
            tag_interview, enqueue_interview, dequeue_batch, cluster_batch, mark_batch_done
        )
        conn = mock_db

        async def _run():
            url = "https://iv1.com"
            _make_interview(conn, 1, url, "1. Redis 持久化？")

            # 第一次
            await tag_interview(1, url, "腾讯", "一面", "1. Redis 持久化？", job_position="后端开发")
            enqueue_interview(1)
            batch = dequeue_batch(20)
            await cluster_batch(batch, user_id=1)
            mark_batch_done([b['queue_id'] for b in batch])

            # 第二次
            conn.execute("DELETE FROM analysis_queue")
            conn.commit()
            await tag_interview(1, url, "腾讯", "一面", "1. Redis 持久化？\n2. 缓存穿透？", job_position="后端开发")
            enqueue_interview(1)
            batch2 = dequeue_batch(20)
            await cluster_batch(batch2, user_id=1)
            mark_batch_done([b['queue_id'] for b in batch2])

            # 验证无重复 URL
            qb_rows = conn.execute("SELECT * FROM question_bank WHERE owner_id IS NULL").fetchall()
            for qb in qb_rows:
                sources = json.loads(qb['sources'])
                urls = [s['url'] for s in sources]
                assert len(urls) == len(set(urls)), f"QB {qb['id']} 有重复 URL: {urls}"

        asyncio.run(_run())

    @patch('app.routers.submit.tag_questions_batch', side_effect=_mock_tag_batch)
    @patch('app.services.pipeline.cluster_all_questions', new_callable=AsyncMock, side_effect=_mock_cluster_all_questions)
    @patch('app.services.pipeline.generate_unified_question', new_callable=AsyncMock, side_effect=_mock_generate_unified)
    def test_queue_lifecycle(self, mock_uq, mock_cluster, mock_tag, mock_db):
        """队列状态：pending → processing → done/failed"""
        from app.services.pipeline import (
            enqueue_interview, dequeue_batch, mark_batch_done, mark_batch_failed,
            get_pending_count, get_processing_count
        )
        conn = mock_db

        async def _run():
            for i in range(1, 4):
                _make_interview(conn, i, f"https://iv{i}.com", "1. 题目？")
                enqueue_interview(i)

            assert get_pending_count() == 3
            assert get_processing_count() == 0

            batch = dequeue_batch(2)
            assert len(batch) == 2
            assert get_pending_count() == 1
            assert get_processing_count() == 2

            mark_batch_done([batch[0]['queue_id']])
            mark_batch_failed([batch[1]['queue_id']])

            assert get_pending_count() == 2  # 1 原始 + 1 回退
            assert get_processing_count() == 0
            assert conn.execute("SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'done'").fetchone()['c'] == 1

        asyncio.run(_run())


# ═════════════════════════════════════════════
#  测试 5: 清理彻底性
# ═════════════════════════════════════════════

class TestCleanupThoroughness:

    def test_cleanup_removes_oqs_by_url(self):
        """清理指定 URL 的 sources/oqs，保留其他 URL 的"""
        from app.db.operations import _cleanup_old_sources_txn_v2
        conn = create_test_db()
        url = "https://to-clean.com"

        conn.execute(
            "INSERT INTO question_bank (id, question, cat1, cat2, frequency, sources, "
            "original_questions, original_question_sources, owner_id, job_position) "
            "VALUES (100, '测试题', 'A', 'B', 2, ?, ?, ?, NULL, '后端开发')",
            (
                json.dumps([{"url": url, "company": "腾讯"}, {"url": "https://keep.com", "company": "阿里"}]),
                json.dumps(["题目A", "题目B"]),
                json.dumps([{"question": "题目A", "url": url}, {"question": "题目B", "url": "https://keep.com"}]),
            )
        )
        conn.execute("INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (100, 1)")
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        _cleanup_old_sources_txn_v2(cursor, url, "后端开发")
        conn.commit()

        qb = conn.execute("SELECT * FROM question_bank WHERE id = 100").fetchone()
        assert qb is not None
        sources = json.loads(qb['sources'])
        assert len(sources) == 1
        assert sources[0]['url'] == "https://keep.com"
        oqs = json.loads(qb['original_questions'])
        assert "题目A" not in oqs
        assert "题目B" in oqs
        conn.close()

    def test_cleanup_deletes_qb_when_all_sources_gone(self):
        """所有来源被移除后 QB 删除"""
        from app.db.operations import _cleanup_old_sources_txn_v2
        conn = create_test_db()
        url = "https://only-source.com"

        conn.execute(
            "INSERT INTO question_bank (id, question, cat1, cat2, frequency, sources, "
            "original_questions, original_question_sources, owner_id, job_position) "
            "VALUES (200, '唯一来源', 'A', 'B', 1, ?, ?, ?, NULL, '后端开发')",
            (
                json.dumps([{"url": url}]),
                json.dumps(["唯一来源"]),
                json.dumps([{"question": "唯一来源", "url": url}]),
            )
        )
        conn.execute("INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (200, 1)")
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("BEGIN")
        _cleanup_old_sources_txn_v2(cursor, url, "后端开发")
        conn.commit()

        assert conn.execute("SELECT * FROM question_bank WHERE id = 200").fetchone() is None
        assert len(conn.execute("SELECT * FROM question_position WHERE question_id = 200").fetchall()) == 0
        conn.close()

    def test_cleanup_handles_nonexistent_url(self):
        """清理不存在的 URL 不报错"""
        from app.db.operations import _cleanup_old_sources_txn_v2
        conn = create_test_db()
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        _cleanup_old_sources_txn_v2(cursor, "https://nonexistent.com", "后端开发")
        conn.commit()
        conn.close()


# ═════════════════════════════════════════════
#  测试 6: 边界条件
# ═════════════════════════════════════════════

class TestEdgeCases:

    @patch('app.routers.submit.tag_questions_batch', side_effect=_mock_tag_batch)
    def test_empty_questions_list(self, mock_tag, mock_db):
        """空题目列表不产生数据"""
        from app.services.pipeline import tag_interview
        conn = mock_db

        async def _run():
            _make_interview(conn, 1, "https://empty.com", "")
            tagged = await tag_interview(1, "https://empty.com", "公司", "一面", "", job_position="后端开发")
            assert tagged == []
            assert len(conn.execute("SELECT * FROM questions_detail").fetchall()) == 0

        asyncio.run(_run())

    def test_dequeue_empty_queue(self, mock_db):
        from app.services.pipeline import dequeue_batch
        assert dequeue_batch(20) == []

    def test_mark_done_empty_list(self, mock_db):
        from app.services.pipeline import mark_batch_done, mark_batch_failed
        mark_batch_done([])
        mark_batch_failed([])

    @patch('app.services.pipeline.cluster_all_questions', new_callable=AsyncMock, side_effect=_mock_cluster_all_questions)
    @patch('app.services.pipeline.generate_unified_question', new_callable=AsyncMock, side_effect=_mock_generate_unified)
    def test_cluster_empty_batch(self, mock_uq, mock_cluster, mock_db):
        from app.services.pipeline import cluster_batch

        async def _run():
            assert await cluster_batch([], user_id=1) == 0

        asyncio.run(_run())

    @patch('app.routers.submit.tag_questions_batch', side_effect=_mock_tag_batch)
    @patch('app.services.pipeline.cluster_all_questions', new_callable=AsyncMock, side_effect=_mock_cluster_all_questions)
    @patch('app.services.pipeline.generate_unified_question', new_callable=AsyncMock, side_effect=_mock_generate_unified)
    def test_reprocess_preserves_ai_answer(self, mock_uq, mock_cluster, mock_tag, mock_db):
        """重新聚类保留已有 AI 答案"""
        from app.services.pipeline import (
            tag_interview, enqueue_interview, dequeue_batch, cluster_batch, mark_batch_done
        )
        conn = mock_db

        async def _run():
            url = "https://with-answer.com"
            _make_interview(conn, 1, url, "1. Redis 持久化？")

            # 第一次
            await tag_interview(1, url, "腾讯", "一面", "1. Redis 持久化？", job_position="后端开发")
            enqueue_interview(1)
            batch = dequeue_batch(20)
            await cluster_batch(batch, user_id=1)
            mark_batch_done([b['queue_id'] for b in batch])

            # 加 AI 答案
            qb = conn.execute("SELECT id FROM question_bank WHERE owner_id IS NULL LIMIT 1").fetchone()
            conn.execute("UPDATE question_bank SET ai_answer = '这是AI答案' WHERE id = ?", (qb['id'],))
            conn.commit()

            # 第二次
            conn.execute("DELETE FROM analysis_queue")
            conn.commit()
            await tag_interview(1, url, "腾讯", "一面", "1. Redis 持久化？", job_position="后端开发")
            enqueue_interview(1)
            batch2 = dequeue_batch(20)
            await cluster_batch(batch2, user_id=1)
            mark_batch_done([b['queue_id'] for b in batch2])

            # AI 答案保留
            answered = conn.execute(
                "SELECT * FROM question_bank WHERE owner_id IS NULL AND ai_answer IS NOT NULL AND ai_answer != ''"
            ).fetchall()
            assert len(answered) >= 1
            assert any('这是AI答案' in (r['ai_answer'] or '') for r in answered)

        asyncio.run(_run())


# ═════════════════════════════════════════════
#  测试 7: 完整重建模拟（5条面经）
# ═════════════════════════════════════════════

class TestFullRebuildSimulation:

    @patch('app.routers.submit.tag_questions_batch', side_effect=_mock_tag_batch)
    @patch('app.services.pipeline.cluster_all_questions', new_callable=AsyncMock, side_effect=_mock_cluster_all_questions)
    @patch('app.services.pipeline.generate_unified_question', new_callable=AsyncMock, side_effect=_mock_generate_unified)
    def test_5_interviews_rebuild(self, mock_uq, mock_cluster, mock_tag, mock_db):
        """5条面经重建，验证数据一致性"""
        from app.services.pipeline import tag_interview, force_cluster_all_pending
        conn = mock_db

        async def _run():
            data = [
                (1, "https://iv1.com", "1. Redis 持久化？\n2. TCP 三次握手？\n3. 快排原理？"),
                (2, "https://iv2.com", "1. 缓存穿透？\n2. HTTP 状态码？"),
                (3, "https://iv3.com", "1. Redis 集群？\n2. 二分查找？"),
                (4, "https://iv4.com", "1. 缓存雪崩？\n2. TCP 四次挥手？"),
                (5, "https://iv5.com", "1. Redis 事务？\n2. 归并排序？"),
            ]

            for iv_id, url, ql in data:
                _make_interview(conn, iv_id, url, ql)
                await tag_interview(iv_id, url, "公司", "一面", ql, job_position="后端开发")

            # QD 完整
            assert conn.execute("SELECT COUNT(*) as c FROM questions_detail").fetchone()['c'] == 11

            # 清空 + 入队
            conn.execute("DELETE FROM question_bank WHERE owner_id IS NULL")
            conn.execute("DELETE FROM analysis_queue")
            for iv_id, _, _ in data:
                conn.execute("INSERT INTO analysis_queue (interview_id, status) VALUES (?, 'pending')", (iv_id,))
            conn.commit()

            # 聚类
            result = await force_cluster_all_pending(user_id=1)

            # 验证
            qb_rows = conn.execute("SELECT * FROM question_bank WHERE owner_id IS NULL").fetchall()
            assert len(qb_rows) >= 3  # Redis/TCP/算法

            for qb in qb_rows:
                sources = json.loads(qb['sources'])
                assert qb['frequency'] == len(sources)
                oqs = json.loads(qb['original_questions'])
                assert len(oqs) >= 1
                urls = [s['url'] for s in sources]
                assert len(urls) == len(set(urls)), f"重复 URL in QB {qb['id']}"

            # question_position 完整
            assert conn.execute("SELECT COUNT(*) as c FROM question_position").fetchone()['c'] == len(qb_rows)

            # 队列全部 done
            assert conn.execute("SELECT COUNT(*) as c FROM analysis_queue WHERE status != 'done'").fetchone()['c'] == 0

            # QD 不受影响
            assert conn.execute("SELECT COUNT(*) as c FROM questions_detail").fetchone()['c'] == 11

            # Redis 聚类来自多个 URL
            redis_qb = [r for r in qb_rows if 'Redis' in (r['cat2'] or '')]
            if redis_qb:
                redis_urls = {s['url'] for s in json.loads(redis_qb[0]['sources'])}
                assert len(redis_urls) >= 2

        asyncio.run(_run())
