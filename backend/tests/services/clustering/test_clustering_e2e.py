"""
E2E 测试：三阶段聚类质量优化

测试目标：
1. 按 cat2 分组聚类，跨领域不干扰
2. LLM 语义分组替代简化批量验证
3. 传递性合并处理
4. 端到端聚类质量验证
5. 向后兼容性
"""
import pytest
import numpy as np
from unittest.mock import patch, MagicMock, AsyncMock


def _make_normalized(*vectors):
    """创建归一化向量矩阵"""
    base = np.array(vectors, dtype=np.float32)
    for i in range(len(base)):
        norm = np.linalg.norm(base[i])
        if norm > 0:
            base[i] /= norm
    return base


def _setup_mocks(mock_encode, mock_build, embeddings):
    """统一设置 encode_texts 和 build_index 的 mock"""
    mock_encode.return_value = embeddings

    mock_index = MagicMock()
    def fake_search(query, k):
        scores = np.dot(embeddings, query.T).flatten()
        top_k_idx = np.argsort(scores)[::-1][:k]
        top_k_scores = scores[top_k_idx]
        # FAISS search returns (scores, indices) — scores first!
        return top_k_scores.reshape(1, -1), top_k_idx.reshape(1, -1).astype(np.int64)
    mock_index.search = fake_search
    mock_build.return_value = mock_index


# ════════════════════════════════════════════════════════════════
# T-002: 按 cat2 分组聚类测试
# ════════════════════════════════════════════════════════════════

class TestCat2Grouping:
    """测试按 cat2 分组后聚类"""

    @pytest.mark.asyncio
    @patch('app.services.clustering._call_llm_with_retry')
    @patch('app.services.embedding_service.build_index')
    @patch('app.services.embedding_service.encode_texts')
    async def test_cross_cat2_questions_not_merged(self, mock_encode, mock_build, mock_llm):
        """不同 cat2 的题目不应被合并"""
        from app.services.clustering import cluster_three_stage_v2

        questions = [
            {"id": 1, "question": "Redis 缓存穿透怎么解决", "cat1": "后端", "cat2": "Redis", "tags": "", "frequency": 1},
            {"id": 2, "question": "Vue 生命周期有哪些钩子", "cat1": "前端", "cat2": "Vue", "tags": "", "frequency": 1},
            {"id": 3, "question": "TCP 三次握手过程", "cat1": "后端", "cat2": "计算机网络", "tags": "", "frequency": 1},
            {"id": 4, "question": "Redis 缓存穿透如何处理", "cat1": "后端", "cat2": "Redis", "tags": "", "frequency": 1},
        ]

        # id=1 和 id=4 相似（Redis），其余不相似
        embeddings = _make_normalized(
            [1.0] + [0.0] * 511,    # id=1 Redis
            [0.0, 1.0] + [0.0] * 510,  # id=2 Vue
            [0.0, 0.0, 1.0] + [0.0] * 509,  # id=3 TCP
            [0.9, 0.1] + [0.0] * 510,  # id=4 Redis
        )
        _setup_mocks(mock_encode, mock_build, embeddings)

        # Mock LLM: 只有 Redis 组会调用
        call_prompts = []
        async def mock_llm_fn(prompt, **kwargs):
            call_prompts.append(prompt)
            if "Redis" in prompt:
                return '{"groups": [{"ids": [1, 4], "representative": "Redis 缓存穿透"}]}'
            return '{"groups": []}'
        mock_llm.side_effect = mock_llm_fn

        result = await cluster_three_stage_v2(questions)

        merged_ids = {mid for _, mid, _ in result['merged']}
        # id=4 应被合并（id=1 是 survivor，id=4 被合并）
        assert 4 in merged_ids or 1 in merged_ids, "相同 cat2 的重复题目应该被合并"

        # 验证跨 cat2 没有合并
        for surv, mid, conf in result['merged']:
            pair = {surv, mid}
            # 不应有跨 cat2 的合并对
            cats = {q['cat2'] for q in questions if q['id'] in pair}
            assert len(cats) == 1, f"跨 cat2 合并: {pair} -> {cats}"


# ════════════════════════════════════════════════════════════════
# T-003: LLM 语义分组替代批量验证测试
# ════════════════════════════════════════════════════════════════

class TestLLMSemanticGrouping:
    """测试 LLM 语义分组（替代简化的一对一验证）"""

    @pytest.mark.asyncio
    @patch('app.services.clustering._call_llm_with_retry')
    @patch('app.services.embedding_service.build_index')
    @patch('app.services.embedding_service.encode_texts')
    async def test_llm_groups_similar_questions(self, mock_encode, mock_build, mock_llm):
        """LLM 应将语义相同的题目分到同一组"""
        from app.services.clustering import cluster_three_stage_v2

        questions = [
            {"id": 1, "question": "介绍一下 ReAct", "cat1": "AI", "cat2": "AI Agent", "tags": "", "frequency": 1},
            {"id": 2, "question": "ReAct 范式的原理是什么", "cat1": "AI", "cat2": "AI Agent", "tags": "", "frequency": 1},
            {"id": 3, "question": "LLM 幻觉问题怎么解决", "cat1": "AI", "cat2": "AI Agent", "tags": "", "frequency": 1},
        ]

        # id=1 和 id=2 相似，id=3 不同
        embeddings = _make_normalized(
            [1.0] + [0.0] * 511,    # id=1 ReAct
            [0.95, 0.05] + [0.0] * 510,  # id=2 ReAct
            [0.0, 1.0] + [0.0] * 510,  # id=3 幻觉
        )
        _setup_mocks(mock_encode, mock_build, embeddings)

        mock_llm.return_value = '{"groups": [{"ids": [1, 2], "representative": "ReAct 范式的原理是什么"}]}'

        result = await cluster_three_stage_v2(questions)

        merged_ids = {mid for _, mid, _ in result['merged']}
        assert 2 in merged_ids or 1 in merged_ids, "ReAct 相关题目应被合并"
        assert 3 not in merged_ids, "LLM 幻觉问题不应被合并到 ReAct 组"


# ════════════════════════════════════════════════════════════════
# T-004: 传递性合并测试
# ════════════════════════════════════════════════════════════════

class TestTransitiveMerge:
    """测试传递性合并: A≈C 且 B≈C → A,B,C 合并"""

    @pytest.mark.asyncio
    @patch('app.services.clustering._call_llm_with_retry')
    @patch('app.services.embedding_service.build_index')
    @patch('app.services.embedding_service.encode_texts')
    async def test_transitive_merge_via_llm(self, mock_encode, mock_build, mock_llm):
        """LLM 语义分组应能发现传递性关系"""
        from app.services.clustering import cluster_three_stage_v2

        questions = [
            {"id": 1, "question": "JVM怎么进行垃圾回收", "cat1": "Java", "cat2": "JVM", "tags": "", "frequency": 1},
            {"id": 2, "question": "Java 内存管理机制是什么", "cat1": "Java", "cat2": "JVM", "tags": "", "frequency": 1},
            {"id": 3, "question": "JVM GC 算法有哪些", "cat1": "Java", "cat2": "JVM", "tags": "", "frequency": 1},
        ]

        # 所有三题彼此相似度 > 0.55（粗筛都能命中）
        # id=3 与 id=1 和 id=2 都高度相似（传递性桥接）
        embeddings = _make_normalized(
            [1.0, 0.6, 0.0] + [0.0] * 509,   # id=1 GC
            [0.6, 1.0, 0.0] + [0.0] * 509,   # id=2 内存管理
            [0.8, 0.8, 0.1] + [0.0] * 509,   # id=3 GC+内存管理（桥接）
        )
        _setup_mocks(mock_encode, mock_build, embeddings)

        # LLM 发现传递性：三个都关于 JVM GC/内存
        mock_llm.return_value = '{"groups": [{"ids": [1, 2, 3], "representative": "JVM GC 算法有哪些"}]}'

        result = await cluster_three_stage_v2(questions)

        merged_ids = {mid for _, mid, _ in result['merged']}
        # 三题合并 = 2 个 merged_ids（survivor 不在其中）
        assert len(merged_ids) >= 2, f"传递性合并应产生 ≥2 个合并，实际: {len(merged_ids)}"


# ════════════════════════════════════════════════════════════════
# T-005 ~ T-007: E2E 集成测试
# ════════════════════════════════════════════════════════════════

class TestE2EClusteringQuality:
    """端到端聚类质量测试"""

    @pytest.mark.asyncio
    @patch('app.services.clustering._call_llm_with_retry')
    @patch('app.services.embedding_service.build_index')
    @patch('app.services.embedding_service.encode_texts')
    async def test_e2e_known_duplicates_merged(self, mock_encode, mock_build, mock_llm):
        """T-005: E2E — 已知重复对应被合并，高频题为 survivor"""
        from app.services.clustering import cluster_three_stage_v2

        questions = [
            {"id": 1, "question": "TCP为什么是三次握手", "cat1": "后端", "cat2": "计算机网络", "tags": "", "frequency": 2},
            {"id": 2, "question": "TCP三次握手的作用是什么", "cat1": "后端", "cat2": "计算机网络", "tags": "", "frequency": 1},
            {"id": 3, "question": "介绍一下 ReAct", "cat1": "AI", "cat2": "AI Agent", "tags": "", "frequency": 1},
            {"id": 4, "question": "ReAct 范式的原理是什么", "cat1": "AI", "cat2": "AI Agent", "tags": "", "frequency": 1},
        ]

        embeddings = _make_normalized(
            [1.0] + [0.0] * 511,    # id=1 TCP
            [0.95, 0.05] + [0.0] * 510,  # id=2 TCP
            [0.0, 1.0] + [0.0] * 510,  # id=3 ReAct
            [0.05, 0.95] + [0.0] * 510,  # id=4 ReAct
        )
        _setup_mocks(mock_encode, mock_build, embeddings)

        # 需要 side_effect，因为 LLM 会被调用 2 次（每个 cat2 一次）
        async def mock_llm_fn(prompt, **kwargs):
            if "计算机网络" in prompt:
                return '{"groups": [{"ids": [1, 2], "representative": "TCP三次握手的作用是什么"}]}'
            if "AI Agent" in prompt:
                return '{"groups": [{"ids": [3, 4], "representative": "ReAct 范式的原理是什么"}]}'
            return '{"groups": []}'
        mock_llm.side_effect = mock_llm_fn

        result = await cluster_three_stage_v2(questions)

        merged_ids = {mid for _, mid, _ in result['merged']}
        survivors = {surv for surv, _, _ in result['merged']}
        assert 2 in merged_ids, "TCP 重复对中低频题(id=2)应被合并"
        assert 3 in merged_ids, "ReAct 重复对中低频题(id=3)应被合并"
        assert 1 in survivors, "高频题 (id=1, freq=2) 应为 survivor"
        assert 4 in survivors, "ReAct 对中 id=4 应为 survivor（高频优先，id 相同时取大）"

    @pytest.mark.asyncio
    @patch('app.services.clustering._call_llm_with_retry')
    @patch('app.services.embedding_service.build_index')
    @patch('app.services.embedding_service.encode_texts')
    async def test_e2e_boundary_not_merged(self, mock_encode, mock_build, mock_llm):
        """T-006: E2E — 边界案例不误合并"""
        from app.services.clustering import cluster_three_stage_v2

        questions = [
            {"id": 1, "question": "Redis 缓存穿透怎么解决", "cat1": "后端", "cat2": "Redis", "tags": "", "frequency": 1},
            {"id": 2, "question": "Redis 缓存雪崩怎么解决", "cat1": "后端", "cat2": "Redis", "tags": "", "frequency": 1},
            {"id": 3, "question": "TCP 三次握手过程", "cat1": "后端", "cat2": "计算机网络", "tags": "", "frequency": 1},
            {"id": 4, "question": "TCP 四次挥手过程", "cat1": "后端", "cat2": "计算机网络", "tags": "", "frequency": 1},
        ]

        # 同 cat2 有一定相似度（粗筛会命中），但 LLM 判断不合并
        embeddings = _make_normalized(
            [1.0, 0.5] + [0.0] * 510,   # 缓存穿透
            [0.8, 0.7] + [0.0] * 510,   # 缓存雪崩
            [0.0, 0.0, 1.0, 0.5] + [0.0] * 508,  # 三次握手
            [0.0, 0.0, 0.8, 0.7] + [0.0] * 508,  # 四次挥手
        )
        _setup_mocks(mock_encode, mock_build, embeddings)

        # LLM 判断：所有都是独立题目
        mock_llm.return_value = '{"groups": []}'

        result = await cluster_three_stage_v2(questions)

        assert len(result['merged']) == 0, "边界案例不应被合并"

    @pytest.mark.asyncio
    @patch('app.services.clustering._call_llm_with_retry')
    @patch('app.services.embedding_service.build_index')
    @patch('app.services.embedding_service.encode_texts')
    async def test_e2e_different_cat2_independent(self, mock_encode, mock_build, mock_llm):
        """T-007: E2E — 不同 cat2 的题目独立处理"""
        from app.services.clustering import cluster_three_stage_v2

        questions = [
            {"id": 1, "question": "Redis 缓存穿透怎么解决", "cat1": "后端", "cat2": "Redis", "tags": "", "frequency": 1},
            {"id": 2, "question": "Vue 生命周期有哪些钩子", "cat1": "前端", "cat2": "Vue", "tags": "", "frequency": 1},
            {"id": 3, "question": "Redis 缓存穿透如何处理", "cat1": "后端", "cat2": "Redis", "tags": "", "frequency": 1},
        ]

        embeddings = _make_normalized(
            [1.0] + [0.0] * 511,    # id=1 Redis
            [0.0, 1.0] + [0.0] * 510,  # id=2 Vue
            [0.95, 0.05] + [0.0] * 510,  # id=3 Redis
        )
        _setup_mocks(mock_encode, mock_build, embeddings)

        call_count = 0
        async def mock_llm_fn(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if "Redis" in prompt:
                return '{"groups": [{"ids": [1, 3], "representative": "Redis 缓存穿透"}]}'
            return '{"groups": []}'
        mock_llm.side_effect = mock_llm_fn

        result = await cluster_three_stage_v2(questions)

        merged_ids = {mid for _, mid, _ in result['merged']}
        assert 3 in merged_ids or 1 in merged_ids, "同 cat2 的重复题应被合并"
        assert 2 not in merged_ids, "Vue 题目不应被合并"


# ════════════════════════════════════════════════════════════════
# T-008: 向后兼容性测试
# ════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """测试增量聚类不受影响"""

    def test_process_incremental_batch_still_exists(self):
        """process_incremental_batch 函数仍然存在"""
        from app.services.clustering import process_incremental_batch
        assert callable(process_incremental_batch)

    def test_cluster_three_stage_v2_has_correct_signature(self):
        """cluster_three_stage_v2 函数签名正确"""
        import inspect
        from app.services.clustering import cluster_three_stage_v2
        sig = inspect.signature(cluster_three_stage_v2)
        params = list(sig.parameters.keys())
        assert 'questions' in params, "缺少 questions 参数"
        assert 'user_id' in params, "缺少 user_id 参数"
        assert 'similarity_threshold' in params, "缺少 similarity_threshold 参数"

    def test_similarity_threshold_default_lowered(self):
        """默认阈值应从 0.75 降低到 0.55"""
        import inspect
        from app.services.clustering import cluster_three_stage_v2
        sig = inspect.signature(cluster_three_stage_v2)
        threshold_default = sig.parameters['similarity_threshold'].default
        assert threshold_default <= 0.60, f"默认阈值 {threshold_default} 过高，应 ≤ 0.60"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
