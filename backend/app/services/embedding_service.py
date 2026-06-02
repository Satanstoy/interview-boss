"""Embedding 预筛服务

使用 bge-small-zh-v1.5 模型对面试题文本进行向量化，
用于聚类匹配前的候选集预筛选。

存储方案参考 OpenClaw：embedding 作为 BLOB 存储在 SQLite，
聚类时加载到 FAISS 内存索引做 top-K 检索。
"""
import logging
import os
from typing import Dict, List, Tuple

import numpy as np

logger = logging.getLogger("interview-boss")

_model = None
_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
_DIMENSION = 512


def _fix_proxy_for_httpx():
    """httpx 不支持 socks5h:// 协议，需要转换为 socks5://"""
    for key in ("ALL_PROXY", "all_proxy"):
        val = os.environ.get(key, "")
        if val.startswith("socks5h://"):
            os.environ[key] = val.replace("socks5h://", "socks5://", 1)


def _get_model():
    """延迟加载模型（首次调用时下载 ~95MB）"""
    global _model
    if _model is None:
        _fix_proxy_for_httpx()
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model: %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def encode_texts(texts: List[str]) -> np.ndarray:
    """将文本列表编码为归一化的 embedding 向量。

    Args:
        texts: 中文文本列表

    Returns:
        numpy array, shape=(N, 512), dtype=float32
    """
    if not texts:
        return np.array([], dtype=np.float32).reshape(0, _DIMENSION)

    model = _get_model()
    embeddings = model.encode(texts, normalize_embeddings=True)
    return embeddings.astype(np.float32)


def build_index(vectors: np.ndarray):
    """从归一化向量构建 FAISS 内积索引。

    Args:
        vectors: shape=(N, dim) 的 float32 向量，已归一化

    Returns:
        faiss.IndexFlatIP 索引对象（可能为空索引）
    """
    import faiss

    if vectors.shape[0] == 0:
        return faiss.IndexFlatIP(_DIMENSION)

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    return index


def search_index(index, query: np.ndarray, top_k: int = 10) -> Tuple[List[int], List[float]]:
    """在 FAISS 索引中搜索 top-K 最相似的向量。

    Args:
        index: FAISS 索引
        query: shape=(1, dim) 的查询向量（已归一化）
        top_k: 返回的最大结果数

    Returns:
        (indices, scores) — 索引位置列表和对应的内积分数
    """
    if index.ntotal == 0:
        return [], []

    k = min(top_k, index.ntotal)
    scores, indices = index.search(query, k)
    return indices[0].tolist(), scores[0].tolist()


def compute_confidence_from_embeddings(emb1, emb2) -> float:
    """根据两个 embedding 向量的余弦相似度计算合并置信度。

    映射规则:
    - sim >= 0.95 → 0.95（几乎确定相同）
    - sim >= 0.85 → 0.85（高度相似）
    - sim >= 0.70 → 0.75（中等相似）
    - sim < 0.70 → 0.60（低相似度）

    Args:
        emb1, emb2: numpy float32 向量（已归一化），或 None

    Returns:
        置信度浮点数，范围 [0.0, 1.0]
    """
    if emb1 is None or emb2 is None:
        return 0.0
    sim = float(np.dot(emb1, emb2))
    if sim >= 0.95:
        return 0.95
    if sim >= 0.85:
        return 0.85
    if sim >= 0.70:
        return 0.75
    return 0.60


def prefilter_centroids(
    query_text: str,
    centroids: List[Dict],
    top_k: int = 10,
) -> List[Dict]:
    """用 embedding 相似度预筛选最可能匹配的 centroid。

    如果 centroid 没有 embedding 字段，降级返回全部（OpenClaw 式降级）。

    Args:
        query_text: 新题文本
        centroids: [{"id": int, "question": str, "embedding"?: ndarray}, ...]
        top_k: 返回的最大候选数

    Returns:
        筛选后的 centroid 列表，按相似度降序排列
    """
    # 分离有/无 embedding 的 centroid
    with_emb = [c for c in centroids if c.get("embedding") is not None]
    if not with_emb:
        return centroids

    # 构建索引并搜索
    vectors = np.array([c["embedding"] for c in with_emb], dtype=np.float32)
    index = build_index(vectors)
    query_emb = encode_texts([query_text])
    indices, scores = search_index(index, query_emb, top_k=top_k)

    # 返回 top-K，附加相似度分数
    return [
        {**with_emb[idx], "_similarity_score": score}
        for idx, score in zip(indices, scores)
    ]
