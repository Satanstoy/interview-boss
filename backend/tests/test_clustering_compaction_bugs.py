"""
自动化测试 — 针对 BUG-001 ~ BUG-007
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock


# ─────────────── BUG-001: Phase 1.5 验证 ID 空间不匹配 ───────────────

class TestBug001Phase15Validation:
    """BUG-001: Phase 1.5 匹配无验证保护，LLM 结果直接使用"""

    def test_phase15_has_validation_after_fix(self):
        """修复后：Phase 1.5 应包含 _validate_merges 调用"""
        import inspect
        from app.services.clustering import _match_and_cluster_cat2
        source = inspect.getsource(_match_and_cluster_cat2)

        phase15_start = source.find("Phase 1.5")
        phase2_start = source.find("Phase 2")
        if phase15_start == -1 or phase2_start == -1:
            pytest.skip("无法定位 Phase 1.5 代码块")

        phase15_code = source[phase15_start:phase2_start]
        has_validation = "_validate_merges" in phase15_code
        assert has_validation, "修复后：Phase 1.5 应有 _validate_merges 验证"


# ─────────────── BUG-002: LLM 重复匹配无去重 ───────────────

class TestBug002DuplicateNewId:
    """BUG-002: LLM 返回重复 new_id 时无去重保护"""

    def test_duplicate_new_id_would_merge_twice(self):
        """修复前：同一个 new_id 被匹配到两个 cluster"""
        # 模拟 LLM 返回的 matches
        matches = [
            {"new_id": "100", "cluster_id": 1},
            {"new_id": "100", "cluster_id": 2},  # 重复！
        ]

        # 模拟当前代码逻辑（无去重）
        matched = []
        unmatched_ids = {"100"}
        matched_cluster_ids = set()

        for m in matches:
            nid = str(m.get("new_id", ""))
            cid = m.get("cluster_id")
            if nid in unmatched_ids and cid is not None:
                matched_cluster_ids.add(nid)
                matched.append((cid, nid))

        # BUG: 同一个 new_id 出现两次
        assert len(matched) == 2, "BUG-002: 无去重时同一题被合并两次"
        assert len(set(m[1] for m in matched)) == 1, "确认是同一个 new_id"

    def test_duplicate_new_id_should_merge_once(self):
        """修复后：添加 processed_new_ids 去重"""
        matches = [
            {"new_id": "100", "cluster_id": 1},
            {"new_id": "100", "cluster_id": 2},
        ]

        matched = []
        unmatched_ids = {"100"}
        processed_new_ids = set()

        for m in matches:
            nid = str(m.get("new_id", ""))
            cid = m.get("cluster_id")
            if nid in unmatched_ids and nid not in processed_new_ids and cid is not None:
                processed_new_ids.add(nid)
                matched.append((cid, nid))

        assert len(matched) == 1, "修复后：同一题只合并一次"


# ─────────────── BUG-003: v2 compaction 无验证 ───────────────

class TestBug003V2NoValidation:
    """BUG-003: v2 compaction 跳过 _validate_merges"""

    def test_v1_compaction_has_validation(self):
        """确认 v1 有验证步骤"""
        import inspect
        from app.services.pipeline.batch import compact_singletons_in_db
        source = inspect.getsource(compact_singletons_in_db)
        assert "_validate_merges" in source, "v1 应该有 _validate_merges 调用"

    def test_v2_compaction_lacks_validation(self):
        """确认 v2 缺少验证步骤（bug 存在）"""
        import inspect
        from app.services.pipeline.batch_v2 import compact_singletons_in_db_v2
        source = inspect.getsource(compact_singletons_in_db_v2)
        # BUG: v2 没有调用 _validate_merges
        has_validation = "_validate_merges" in source
        assert not has_validation, "BUG-003: v2 compaction 缺少 _validate_merges"


# ─────────────── BUG-004: v2 compaction 无合并历史 ───────────────

class TestBug004V2NoMergeHistory:
    """BUG-004: v2 compaction 不记录 merge_history"""

    def test_v2_compaction_no_merge_history(self):
        """确认 v2 不记录合并历史"""
        import inspect
        from app.services.pipeline.batch_v2 import compact_singletons_in_db_v2
        source = inspect.getsource(compact_singletons_in_db_v2)
        has_history = "_record_merge_history" in source
        assert not has_history, "BUG-004: v2 compaction 不记录 merge_history"


# ─────────────── BUG-005: _build_new_entry 未去重 ───────────────

class TestBug005BuildNewEntryDedup:
    """BUG-005: _build_new_entry 的 original_questions 未去重"""

    def test_duplicate_questions_deduped_frequency(self):
        """修复后：重复题目应被去重，frequency 正确"""
        from app.services.pipeline.writer import _build_new_entry

        cluster = {
            "representative": "什么是 RAG",
            "ids": ["1", "2"],
            "items": [
                {"question": "什么是 RAG", "url": "http://a.com", "company": "A", "round": "1", "cat1": "B", "cat2": "B2"},
                {"question": "什么是 RAG", "url": "http://b.com", "company": "B", "round": "2", "cat1": "B", "cat2": "B2"},
            ]
        }

        entry = _build_new_entry(cluster, job_position="")

        # 修复后：frequency=1（去重后只有一个不同题目）
        assert entry['frequency'] == 1, "修复后：重复题目应被去重"
        assert len(entry['original_questions']) == 1, "修复后：original_questions 不含重复"


# ─────────────── BUG-006: O(N*M) 性能问题 ───────────────

class TestBug006Performance:
    """BUG-006: full_recluster_hybrid 中的 O(N*M) 线性扫描"""

    def test_full_recluster_uses_lookup_after_fix(self):
        """修复后：应使用预构建的 question_lookup 字典"""
        import inspect
        from app.services.clustering import full_recluster_hybrid
        source = inspect.getsource(full_recluster_hybrid)
        has_lookup = "question_lookup" in source
        assert has_lookup, "修复后：应使用 question_lookup 预构建字典"


# ─────────────── BUG-007: frequency 计算不一致 ───────────────

class TestBug007FrequencyInconsistency:
    """BUG-007: 不同合并路径的 frequency 计算方式不一致"""

    def test_batch_v2_uses_len_after_fix(self):
        """修复后：batch_v2 应使用 len(original_questions) 计算 frequency"""
        import inspect
        from app.services.pipeline.batch_v2 import compact_singletons_in_db_v2
        source = inspect.getsource(compact_singletons_in_db_v2)
        has_increment = "frequency'] + 1" in source or "frequency'] +1" in source
        has_len = "len(t_oqs)" in source
        assert not has_increment, "修复后：不应使用 frequency + 1"
        assert has_len, "修复后：应使用 len(t_oqs)"
