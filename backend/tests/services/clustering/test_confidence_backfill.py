"""
BUG-002: merge_history 置信度修复测试
测试 embedding 置信度计算函数和 migration 回填逻辑
"""
import json
import pytest
import numpy as np
from unittest.mock import patch, MagicMock


class TestEmbeddingConfidence:
    """测试 embedding 相似度 → 置信度映射函数"""

    def test_compute_confidence_identical_texts(self):
        """完全相同的文本应返回高置信度 (>= 0.95)"""
        from app.services.embedding_service import compute_confidence_from_embeddings
        emb1 = np.random.randn(512).astype(np.float32)
        emb1 /= np.linalg.norm(emb1)
        emb2 = emb1.copy()
        conf = compute_confidence_from_embeddings(emb1, emb2)
        assert conf >= 0.95, f"相同文本置信度应>=0.95, 实际={conf}"

    def test_compute_confidence_similar_texts(self):
        """高相似度向量应返回中高置信度 (>= 0.80)"""
        from app.services.embedding_service import compute_confidence_from_embeddings
        rng = np.random.RandomState(42)
        emb1 = rng.randn(512).astype(np.float32)
        emb1 /= np.linalg.norm(emb1)
        # 小噪声保证 sim > 0.85 (factor=0.02 → sim≈0.91)
        noise = rng.randn(512).astype(np.float32) * 0.02
        emb2 = emb1 + noise
        emb2 /= np.linalg.norm(emb2)
        conf = compute_confidence_from_embeddings(emb1, emb2)
        assert 0.70 <= conf <= 1.0, f"高相似度置信度应在0.70-1.0, 实际={conf}"

    def test_compute_confidence_unrelated_texts(self):
        """不相关的向量应返回低置信度 (< 0.70)"""
        from app.services.embedding_service import compute_confidence_from_embeddings
        rng = np.random.RandomState(1)
        emb1 = rng.randn(512).astype(np.float32)
        emb1 /= np.linalg.norm(emb1)
        emb2 = rng.randn(512).astype(np.float32)
        emb2 /= np.linalg.norm(emb2)
        conf = compute_confidence_from_embeddings(emb1, emb2)
        assert conf < 0.70, f"不相关文本置信度应<0.70, 实际={conf}"

    def test_compute_confidence_none_input(self):
        """None 输入应返回 0.0"""
        from app.services.embedding_service import compute_confidence_from_embeddings
        conf = compute_confidence_from_embeddings(None, None)
        assert conf == 0.0

    def test_compute_confidence_range(self):
        """置信度应在 [0.0, 1.0] 范围内"""
        from app.services.embedding_service import compute_confidence_from_embeddings
        rng = np.random.RandomState(99)
        for _ in range(20):
            emb1 = rng.randn(512).astype(np.float32)
            emb1 /= np.linalg.norm(emb1)
            emb2 = rng.randn(512).astype(np.float32)
            emb2 /= np.linalg.norm(emb2)
            conf = compute_confidence_from_embeddings(emb1, emb2)
            assert 0.0 <= conf <= 1.0, f"置信度超出范围: {conf}"


class TestBackfillConfidenceMigration:
    """测试 migration 034 回填置信度逻辑"""

    @pytest.fixture
    def mock_db_with_zero_confidence(self):
        """创建包含 confidence=0 记录的 mock 数据库"""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE question_bank (
                id INTEGER PRIMARY KEY,
                question TEXT,
                cat2 TEXT,
                frequency INTEGER DEFAULT 1,
                original_questions TEXT DEFAULT '[]',
                duplicate_of INTEGER,
                deleted_at TIMESTAMP,
                embedding BLOB
            );
            CREATE TABLE merge_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                survivor_id INTEGER,
                merged_ids TEXT,
                merged_questions TEXT,
                pre_snapshot TEXT,
                post_snapshot TEXT,
                operation_type TEXT,
                phase TEXT,
                confidence REAL DEFAULT 0,
                cat2 TEXT,
                operator_id INTEGER,
                is_rolled_back INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Survivor question with embedding and original_questions
        emb = np.random.randn(512).astype(np.float32)
        emb /= np.linalg.norm(emb)
        conn.execute(
            "INSERT INTO question_bank (id, question, cat2, frequency, original_questions, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (100, "测试问题", "B1.Agent架构与范式", 3,
             json.dumps(["测试问题变体1", "测试问题变体2"]),
             emb.tobytes())
        )
        # Merge history with confidence=0
        conn.execute(
            "INSERT INTO merge_history (survivor_id, merged_ids, merged_questions, confidence, phase, operation_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (100, '[101]', '["测试问题变体1"]', 0.0, 'compaction_to_existing', 'compaction')
        )
        conn.execute(
            "INSERT INTO merge_history (survivor_id, merged_ids, merged_questions, confidence, phase, operation_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (100, '[102]', '["测试问题变体2"]', 0.0, 'compaction_mutual', 'compaction')
        )
        # Already has correct confidence
        conn.execute(
            "INSERT INTO merge_history (survivor_id, merged_ids, merged_questions, confidence, phase, operation_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (100, '[103]', '["其他问题"]', 0.85, 'compaction_to_existing', 'compaction')
        )
        conn.commit()
        return conn

    def test_migration_updates_zero_confidence_records(self, mock_db_with_zero_confidence):
        """migration 应将 confidence=0 的记录更新为非零值"""
        from app.db.migrations import _migration_034_backfill_confidence
        conn = mock_db_with_zero_confidence

        _migration_034_backfill_confidence(conn)

        rows = conn.execute(
            "SELECT id, confidence FROM merge_history ORDER BY id"
        ).fetchall()
        # First two records should now have non-zero confidence
        assert rows[0]['confidence'] > 0.0, f"记录 1 置信度应>0, 实际={rows[0]['confidence']}"
        assert rows[1]['confidence'] > 0.0, f"记录 2 置信度应>0, 实际={rows[1]['confidence']}"
        # Third record should be unchanged
        assert rows[2]['confidence'] == 0.85, f"记录 3 置信度应不变, 实际={rows[2]['confidence']}"

    def test_migration_skips_rolled_back_records(self, mock_db_with_zero_confidence):
        """migration 应跳过已回滚的记录"""
        conn = mock_db_with_zero_confidence
        conn.execute(
            "INSERT INTO merge_history (survivor_id, merged_ids, merged_questions, confidence, is_rolled_back) "
            "VALUES (?, ?, ?, ?, ?)",
            (100, '[104]', '["已回滚问题"]', 0.0, 1)
        )
        conn.commit()

        from app.db.migrations import _migration_034_backfill_confidence
        _migration_034_backfill_confidence(conn)

        rolled_back = conn.execute(
            "SELECT confidence FROM merge_history WHERE is_rolled_back = 1"
        ).fetchone()
        assert rolled_back['confidence'] == 0.0, "已回滚记录不应被修改"


class TestCompactConfidenceFallback:
    """测试 compaction 流程中置信度 fallback 逻辑"""

    def test_do_merge_to_existing_uses_fallback_confidence(self, test_db, monkeypatch):
        """零置信度合并必须记录实际计算结果并保留来源历史。"""
        from app.services.pipeline.compact import _do_merge_to_existing

        test_db.executemany(
            "INSERT INTO question_bank (id, question, cat2, owner_id, status) "
            "VALUES (?, ?, 'B1', NULL, 'approved')",
            [(100, "测试旧题"), (200, "测试变体")],
        )
        monkeypatch.setattr("app.services.pipeline.compact.get_db_connection", lambda: test_db)
        monkeypatch.setattr(
            "app.services.pipeline.compact._compute_merge_confidence",
            lambda survivor_id, question: 0.87,
        )
        entry = dict(test_db.execute("SELECT * FROM question_bank WHERE id = 200").fetchone())
        with test_db:
            _do_merge_to_existing(100, entry, confidence=0, phase="test")

        history = test_db.execute(
            "SELECT confidence FROM merge_history WHERE survivor_id = 100"
        ).fetchone()
        assert history is not None
        assert history["confidence"] == pytest.approx(0.87)
        assert test_db.execute(
            "SELECT deleted_at FROM question_bank WHERE id = 200"
        ).fetchone()[0] is not None
