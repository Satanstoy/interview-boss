# 重构阶段报告

**重构时间:** 2026-05-31
**重构范围:** embedding_service.py

## 重构前代码

```python
# prefilter_centroids 中有冗余检查
has_embedding = any("embedding" in c and c["embedding"] is not None for c in centroids)
if not has_embedding:
    return centroids
centroids_with_emb = [c for c in centroids if "embedding" in c and c["embedding"] is not None]
if not centroids_with_emb:
    return centroids
```

## 重构后代码

```python
with_emb = [c for c in centroids if c.get("embedding") is not None]
if not with_emb:
    return centroids
# ...直接使用 with_emb
return [
    {**with_emb[idx], "_similarity_score": score}
    for idx, score in zip(indices, scores)
]
```

## 重构原则检查

- [x] 测试仍然通过（7/7 PASSED）
- [x] 消除冗余代码（has_embedding + centroids_with_emb → with_emb）
- [x] 使用 dict comprehension 替代循环
- [x] 使用 c.get() 替代 "key" in c

## 阶段状态
- [x] 重构完成
- [x] 测试仍然通过
