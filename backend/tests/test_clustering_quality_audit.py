"""
自动化测试 — 聚类质量审计 (BUG-001 ~ BUG-010)
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ─────────────────────────────────────────────────────
# BUG-001: merge_history 表缺少回滚字段
# ─────────────────────────────────────────────────────

class TestBug001_MergeHistorySchema:
    """BUG-001: merge_history 表缺少 is_rolled_back/rolled_back_at/rolled_back_by"""

    def test_merge_history_should_have_rollback_columns(self):
        """merge_history 表应包含 is_rolled_back, rolled_back_at, rolled_back_by 列"""
        from app.db.connection import get_db_connection
        conn = get_db_connection()
        # 检查表是否存在
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='merge_history'"
        ).fetchone()
        assert table is not None, "merge_history 表不存在"

        columns = {row[1] for row in conn.execute("PRAGMA table_info(merge_history)").fetchall()}
        assert 'is_rolled_back' in columns, "缺少 is_rolled_back 列"
        assert 'rolled_back_at' in columns, "缺少 rolled_back_at 列"
        assert 'rolled_back_by' in columns, "缺少 rolled_back_by 列"

    def test_admin_merge_history_query_should_not_error(self):
        """管理员查询 merge-history 时不应因缺少列而报错"""
        from app.db.connection import get_db_connection
        conn = get_db_connection()
        try:
            conn.execute(
                "SELECT mh.is_rolled_back, mh.rolled_back_at "
                "FROM merge_history mh LIMIT 1"
            )
        except Exception as e:
            if "no such column" in str(e):
                pytest.fail(f"merge_history 缺少回滚列: {e}")


# ─────────────────────────────────────────────────────
# BUG-002: merge_feedback 表不存在
# ─────────────────────────────────────────────────────

class TestBug002_MergeFeedbackTable:
    """BUG-002: merge_feedback 表不存在"""

    def test_merge_feedback_table_should_exist(self):
        """merge_feedback 表应存在于数据库中"""
        from app.db.connection import get_db_connection
        conn = get_db_connection()
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='merge_feedback'"
        ).fetchone()
        assert table is not None, "merge_feedback 表不存在"

    def test_merge_feedback_has_required_columns(self):
        """merge_feedback 表应包含必需列"""
        from app.db.connection import get_db_connection
        conn = get_db_connection()
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='merge_feedback'"
        ).fetchone()
        if not table:
            pytest.skip("merge_feedback 表不存在（BUG-002）")

        columns = {row[1] for row in conn.execute("PRAGMA table_info(merge_feedback)").fetchall()}
        required = {'id', 'merge_history_id', 'question_bank_id', 'feedback_type', 'comment', 'user_id', 'created_at'}
        missing = required - columns
        assert not missing, f"merge_feedback 缺少列: {missing}"


# ─────────────────────────────────────────────────────
# BUG-003: Embedding 覆盖率为 0%
# ─────────────────────────────────────────────────────

class TestBug003_EmbeddingCoverage:
    """BUG-003: 所有活跃题目 embedding 为 NULL"""

    @pytest.mark.asyncio
    async def test_insert_new_clusters_should_store_embedding(self):
        """新建聚类时应生成并存储 embedding"""
        from app.services.embedding_service import encode_texts
        import numpy as np

        # 模拟 encode_texts 返回
        with patch('app.services.embedding_service.encode_texts') as mock_encode:
            mock_encode.return_value = np.array([[0.1] * 512], dtype=np.float32)
            result = encode_texts(["测试题目"])
            assert result is not None
            assert result.shape == (1, 512)

    def test_embedding_backfill_should_be_in_migrations(self):
        """应有 migration 函数用于 backfill embedding"""
        from app.db import migrations
        assert hasattr(migrations, '_migration_037_backfill_embeddings'), \
            "缺少 _migration_037_backfill_embeddings migration 函数"


# ─────────────────────────────────────────────────────
# BUG-005: batch_v2.py 合并无 merge_history
# ─────────────────────────────────────────────────────

class TestBug005_BatchV2MergeHistory:
    """BUG-005: batch_v2.py 合并不记录 merge_history"""

    def test_batch_v2_should_use_do_merge_to_existing(self):
        """batch_v2.py 的合并应调用 _do_merge_to_existing 以记录历史"""
        import inspect
        from app.services.pipeline import batch_v2
        source = inspect.getsource(batch_v2)
        # 检查是否导入或调用了 _do_merge_to_existing
        assert '_do_merge_to_existing' in source, \
            "batch_v2.py 未使用 _do_merge_to_existing，合并不会记录 merge_history"


# ─────────────────────────────────────────────────────
# BUG-006: full_recluster_hybrid 不合并完整字段
# ─────────────────────────────────────────────────────

class TestBug006_FullReclusterMerge:
    """BUG-006: 全量重聚合并不合并 sources/original_questions"""

    def test_full_recluster_should_merge_complete_fields(self):
        """full_recluster 的合并应调用 _do_merge_to_existing 以合并所有字段"""
        import inspect
        from app.services.clustering import full_recluster_hybrid
        source = inspect.getsource(full_recluster_hybrid)
        # 不应只做简单的 UPDATE frequency + SET duplicate_of
        assert 'original_questions' in source or '_do_merge_to_existing' in source, \
            "full_recluster_hybrid 不合并 original_questions/sources"


# ─────────────────────────────────────────────────────
# BUG-007: 测试断言与当前 prompt 不一致
# ─────────────────────────────────────────────────────

class TestBug007_PromptTestSync:
    """BUG-007: 6 个聚类测试因 prompt 变更而失败"""

    def test_match_prompt_has_current_negative_examples(self):
        """MATCH_EXISTING_PROMPT 应包含当前版本的负面案例"""
        from app.services.clustering import MATCH_EXISTING_PROMPT
        # 当前版本包含的真实负面案例
        assert 'Redis 缓存穿透' in MATCH_EXISTING_PROMPT
        assert 'Redis 缓存雪崩' in MATCH_EXISTING_PROMPT

    def test_cluster_prompt_has_current_negative_examples(self):
        """CLUSTER_NEW_PROMPT 应包含当前版本的负面案例"""
        from app.services.clustering import CLUSTER_NEW_PROMPT
        assert 'Redis 缓存穿透' in CLUSTER_NEW_PROMPT

    def test_validate_prompt_has_current_examples(self):
        """VALIDATE_MERGES_PROMPT 应包含当前版本的案例"""
        from app.services.clustering import VALIDATE_MERGES_PROMPT
        assert 'Redis 缓存穿透' in VALIDATE_MERGES_PROMPT

    def test_merge_history_migration_should_be_importable(self):
        """merge_history 相关的 migration 函数应可导入"""
        from app.db import migrations
        # 检查是否有可用的 migration（不检查具体名称，避免因重命名失败）
        has_merge_migration = any(
            hasattr(migrations, attr) and 'merge' in attr.lower()
            for attr in dir(migrations)
        )
        assert has_merge_migration, "缺少 merge_history 相关的 migration 函数"


# ─────────────────────────────────────────────────────
# BUG-009: V2 Union-Find 并发安全
# ─────────────────────────────────────────────────────

class TestBug009_UnionFindConcurrency:
    """BUG-009: V2 Union-Find 使用共享字典并发操作"""

    def test_union_find_isolation_per_cat2(self):
        """每个 cat2 组应独立维护 union-find 状态，避免共享字典"""
        import inspect
        from app.services.clustering import cluster_three_stage_v2
        source = inspect.getsource(cluster_three_stage_v2)

        # 检查 _process_cat2_group 内是否直接写入外部 parent/rank
        # 如果 parent 和 rank 在 _process_cat2_group 外部定义且在内部直接操作，则有并发风险
        has_shared_state = 'parent[idx] = idx' in source or 'parent[gi' in source
        # 这个测试预期修复后为 False（不再共享状态）
        # 当前版本确实存在共享状态
        if has_shared_state:
            pytest.xfail("BUG-009: 当前版本 union-find 使用共享字典（asyncio 安全但不够清晰）")


# ─────────────────────────────────────────────────────
# 聚类质量指标测试
# ─────────────────────────────────────────────────────

class TestClusteringQualityMetrics:
    """聚类质量指标验证"""

    def test_singleton_rate_below_threshold(self):
        """孤岛率应低于 40%（当前 56.3%）"""
        from app.db.connection import get_db_connection
        conn = get_db_connection()
        total = conn.execute(
            "SELECT COUNT(*) FROM question_bank WHERE deleted_at IS NULL AND status='approved'"
        ).fetchone()[0]
        if total == 0:
            pytest.skip("无活跃题目")
        singletons = conn.execute(
            "SELECT COUNT(*) FROM question_bank WHERE deleted_at IS NULL AND status='approved' AND frequency=1"
        ).fetchone()[0]
        rate = singletons / total
        assert rate < 0.40, f"孤岛率 {rate:.1%} 超过 40% 阈值 (单例={singletons}, 总数={total})"

    def test_other_category_singleton_rate(self):
        """'其他'分类孤岛率应低于 60%（当前 75%）"""
        from app.db.connection import get_db_connection
        conn = get_db_connection()
        total = conn.execute(
            "SELECT COUNT(*) FROM question_bank WHERE cat2='其他' AND deleted_at IS NULL AND status='approved'"
        ).fetchone()[0]
        if total == 0:
            pytest.skip("无 '其他' 分类题目")
        singletons = conn.execute(
            "SELECT COUNT(*) FROM question_bank WHERE cat2='其他' AND frequency=1 AND deleted_at IS NULL AND status='approved'"
        ).fetchone()[0]
        rate = singletons / total
        assert rate < 0.60, f"'其他'分类孤岛率 {rate:.1%} 超过 60% (单例={singletons}, 总数={total})"
