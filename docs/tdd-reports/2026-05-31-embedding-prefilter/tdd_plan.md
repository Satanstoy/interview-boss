# TDD 开发计划

**功能名称:** Embedding 预筛优化
**日期:** 2026-05-31
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

在 LLM 聚类匹配前引入 Embedding 向量预筛选，将 prompt 中的已有聚类从 O(N) 缩减到 O(K=10)。

## 验收标准

- [ ] encode_texts 输入中文文本列表返回 numpy array (N, 512)
- [ ] FAISS 索引从向量列表构建，top-K 查询返回正确 indices 和 scores
- [ ] 空输入/边界情况优雅处理
- [ ] prefilter_centroids 端到端：centroid 列表 + query → top-K IDs
- [ ] 无 embedding 时降级返回全部 centroid

## 测试清单

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-001 | encode_texts 返回正确维度 | 3 条中文文本 | numpy array, shape=(3, 512), dtype=float32 | ⏳ |
| T-002 | encode_texts 空输入 | [] | shape=(0,) 的空 array | ⏳ |
| T-003 | build_index + search 基本功能 | 5 个 centroid + 1 query, K=3 | top-3 indices 和 scores | ⏳ |
| T-004 | search K > N | 3 个 centroid, K=10 | 返回全部 3 个 | ⏳ |
| T-005 | 空索引 search | 空索引 + query | 返回空结果 | ⏳ |
| T-006 | prefilter_centroids 端到端 | centroid 列表 + query text | 返回 top-K 候选 | ⏳ |
| T-007 | 无 embedding 降级 | centroids without embedding | 返回全部 centroid | ⏳ |

## 红-绿-重构循环计划

- [ ] 循环 1: T-001 + T-002 (encode_texts)
- [ ] 循环 2: T-003 + T-004 + T-005 (FAISS index + search)
- [ ] 循环 3: T-006 + T-007 (prefilter_centroids 端到端)
