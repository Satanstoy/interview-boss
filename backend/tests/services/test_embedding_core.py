"""
Embedding 预筛服务测试套件

遵循 TDD 原则，每个测试对应一个用户需求或场景。
测试命名规范：test_<场景>_<预期行为>
"""
import numpy as np
import pytest


class TestEncodeTexts:
    """Embedding 文本编码测试"""

    # =========================================================
    # T-001: 正常编码返回正确维度
    # =========================================================
    def test_encode_texts_returns_correct_shape_and_dtype(self, monkeypatch):
        """
        正常输入应返回 (N, 1024) 的 float32 numpy array

        红灯阶段：embedding_service 模块尚未创建
        """
        import app.services.embedding_service as embedding_service

        monkeypatch.setattr(embedding_service, "_BACKEND", "hash")

        texts = ["什么是微服务架构", "解释一下 Redis 缓存穿透", "TCP 三次握手的过程"]
        result = embedding_service.encode_texts(texts)

        assert isinstance(result, np.ndarray)
        assert result.shape == (3, embedding_service._DIMENSION)
        assert result.dtype == np.float32

    # =========================================================
    # T-002: 空输入返回空数组
    # =========================================================
    def test_encode_texts_empty_input_returns_empty_array(self):
        """
        空列表输入应返回空 numpy array

        红灯阶段：embedding_service 模块尚未创建
        """
        from app.services.embedding_service import encode_texts

        result = encode_texts([])

        assert isinstance(result, np.ndarray)
        assert result.shape[0] == 0


class TestFaissIndex:
    """FAISS 向量索引和搜索测试"""

    # =========================================================
    # T-003: 基本 top-K 搜索
    # =========================================================
    def test_search_returns_top_k_indices_and_scores(self):
        """
        5 个已知向量中搜索最相似的 3 个

        构造: 向量 0~4，query 与向量 2 最相似
        """
        from app.services.embedding_service import build_index, search_index

        # 构造 5 个 1024 维向量（归一化, SiliconFlow bge-m3 维度）
        vectors = np.random.randn(5, 1024).astype(np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

        # query = 向量 2 + 小噪声（保证最相似）
        query = vectors[2] + np.random.randn(1024).astype(np.float32) * 0.01
        query /= np.linalg.norm(query)

        index = build_index(vectors)
        indices, scores = search_index(index, query.reshape(1, -1), top_k=3)

        assert len(indices) == 3
        assert indices[0] == 2  # 最相似的应该是向量 2
        assert all(-1.01 <= s <= 1.01 for s in scores)  # 归一化内积 ∈ [-1, 1]

    # =========================================================
    # T-004: K > N 返回全部
    # =========================================================
    def test_search_k_greater_than_n_returns_all(self):
        """
        K > 向量数量时应返回全部向量
        """
        from app.services.embedding_service import build_index, search_index

        vectors = np.random.randn(3, 1024).astype(np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        query = vectors[0].reshape(1, -1)

        index = build_index(vectors)
        indices, scores = search_index(index, query, top_k=10)

        assert len(indices) == 3  # 只有 3 个，全部返回

    # =========================================================
    # T-005: 空索引搜索返回空结果
    # =========================================================
    def test_search_empty_index_returns_empty(self):
        """
        空索引应返回空结果，不报错
        """
        from app.services.embedding_service import build_index, search_index

        empty_vectors = np.array([], dtype=np.float32).reshape(0, 1024)
        query = np.random.randn(1, 1024).astype(np.float32)

        index = build_index(empty_vectors)
        indices, scores = search_index(index, query, top_k=5)

        assert len(indices) == 0
        assert len(scores) == 0


class TestPrefilterCentroids:
    """预筛选 centroid 端到端测试"""

    # =========================================================
    # T-006: prefilter_centroids 返回 top-K 候选
    # =========================================================
    def test_prefilter_centroids_returns_top_k_candidates(self, monkeypatch):
        """
        给定一组 centroid（id + question + embedding）和一个 query 文本，
        应返回最相似的 K 个 centroid IDs
        """
        import app.services.embedding_service as embedding_service

        monkeypatch.setattr(embedding_service, "_BACKEND", "hash")

        # 构造 centroid 列表（模拟已有聚类）
        centroids = []
        for i, q in enumerate([
            "什么是微服务架构",
            "Redis 缓存穿透怎么解决",
            "TCP 三次握手的过程",
            "MySQL 索引优化策略",
            "Docker 和虚拟机的区别",
        ]):
            centroids.append({
                "id": i + 1,
                "question": q,
            })

        # 用真实的 encode_texts 生成 embedding
        texts = [c["question"] for c in centroids]
        embeddings = embedding_service.encode_texts(texts)
        for c, emb in zip(centroids, embeddings):
            c["embedding"] = emb

        # query: 与 "Redis 缓存穿透" 相似的问题
        result = embedding_service.prefilter_centroids(
            query_text="如何处理缓存击穿问题",
            centroids=centroids,
            top_k=3,
        )

        assert len(result) <= 3
        assert len(result) > 0
        # 应该包含 Redis 缓存相关的 centroid
        result_ids = [r["id"] for r in result]
        assert 2 in result_ids  # "Redis 缓存穿透怎么解决"

    # =========================================================
    # T-007: 无 embedding 时降级返回全部
    # =========================================================
    def test_prefilter_centroids_no_embedding_returns_all(self):
        """
        当 centroid 没有 embedding 字段时，应降级返回全部 centroid
        """
        from app.services.embedding_service import prefilter_centroids

        centroids = [
            {"id": 1, "question": "什么是微服务"},
            {"id": 2, "question": "Redis 缓存穿透"},
        ]
        # 没有 embedding 字段

        result = prefilter_centroids(
            query_text="什么是微服务架构",
            centroids=centroids,
            top_k=3,
        )

        assert len(result) == 2  # 全部返回
        assert result == centroids
