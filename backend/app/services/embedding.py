import numpy as np
from typing import List
from app.core.config import SIMILARITY_THRESHOLD


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    a = np.asarray(v1)
    b = np.asarray(v2)
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(dot / norm) if norm > 0 else 0.0


def cosine_similarity_batch(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """批量计算 query 与 matrix 中每一行的余弦相似度，返回一维数组"""
    norms = np.linalg.norm(matrix, axis=1)
    query_norm = np.linalg.norm(query)
    denom = norms * query_norm
    denom[denom == 0] = 1e-10
    return matrix @ query / denom


def find_best_match(new_vec: List[float], master_vecs: list) -> tuple:
    """在 master_vecs 中找到与 new_vec 相似度最高的记录，返回 (record, score) 或 (None, 0.0)"""
    if not master_vecs:
        return None, 0.0

    query = np.asarray(new_vec)
    matrix = np.array([m['vector'] for m in master_vecs])
    scores = cosine_similarity_batch(query, matrix)
    best_idx = int(np.argmax(scores))
    best_score = float(scores[best_idx])

    if best_score >= SIMILARITY_THRESHOLD:
        return master_vecs[best_idx], best_score
    return None, 0.0
