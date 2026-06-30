import pytest


# ─────────────────────────────────────────────────────
# BUG-001: merge_history 表缺少回滚字段
# ─────────────────────────────────────────────────────

class TestBug001_MergeHistorySchema:
    """BUG-001: merge_history 表缺少 is_rolled_back/rolled_back_at/rolled_back_by"""

    def test_merge_history_should_have_rollback_columns(self, test_db):
        """merge_history 表应包含 is_rolled_back, rolled_back_at, rolled_back_by 列"""
        conn = test_db
        # 检查表是否存在
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='merge_history'"
        ).fetchone()
        assert table is not None, "merge_history 表不存在"

        columns = {row[1] for row in conn.execute("PRAGMA table_info(merge_history)").fetchall()}
        assert 'is_rolled_back' in columns, "缺少 is_rolled_back 列"
        assert 'rolled_back_at' in columns, "缺少 rolled_back_at 列"
        assert 'rolled_back_by' in columns, "缺少 rolled_back_by 列"

    def test_admin_merge_history_query_should_not_error(self, test_db):
        """管理员查询 merge-history 时不应因缺少列而报错"""
        conn = test_db
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

    def test_merge_feedback_table_should_exist(self, test_db):
        """merge_feedback 表应存在于数据库中"""
        conn = test_db
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='merge_feedback'"
        ).fetchone()
        assert table is not None, "merge_feedback 表不存在"

    def test_merge_feedback_has_required_columns(self, test_db):
        """merge_feedback 表应包含必需列"""
        conn = test_db
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

        assert "local_parent" in source
        assert "local_rank" in source
        assert "grouped_clusters = await asyncio.gather" in source
        assert "    parent = {}\n    rank = {}" not in source
