# 实验结论落地生产：实施 Spec

**日期**: 2026-08-06
**依据**: 检索/聚类实验结论（docs/analysis/2026-08-06-retrieval-clustering-integration.md + experiment_reports/ 5 份报告）
**范围**: "实验完成但未修改生产"清单的 6 项，按依赖分 4 个 Phase 实施
**验证**: 每项带 mock 测试（Docker test-runtime）+ 真实链路冒烟

## 总览

| Phase | 内容 | 收益依据 | 改动文件 |
|-------|------|---------|---------|
| P1a | 检索 rerank 升级 listwise | 3.5 → 4.2（抽题评估 C 方案） | `agents/chat/tools.py` |
| P1b | draw_questions 候选池 embedding 补充 | 消除 0 题/1 题候选灾难（2.8 分主因） | `services/question_draw_service.py` |
| P2 | 聚类标签摘要候选 + 验证层 | 准确率 88%、孤岛率 -22% | `services/clustering/matcher.py` + 相关 |
| P3 | 聚类异步化 | 单次导入 30-90s → 10-25s | `agents/submit/persist_public.py` + graph |
| P4 | 聚类候选混合信号 + llm_judge 统一 | 漏合并 -2%、工程复用 | `services/clustering/` + 抽公共模块 |

---

## P1a: 检索 rerank 升级 listwise

**现状**: `_llm_rerank_in_tool`（tools.py:449）用 pointwise 打分（0-1 JSON scores + 阈值 0.3 过滤）。实验证明：listwise（LLM 从候选中选 top-3）质量更高（抽题评估 C 方案 4.2 vs 3.5）；pointwise 分数不稳定（mimo 评分波动）。

**改动**: 保留 `_llm_rerank_in_tool` 签名（调用方不变），内部 prompt 改为 listwise 排序；阈值语义改为"选 top-N 后按原排序保序"。

- `_llm_rerank_in_tool(candidates, conversation_context, user_id, model=None)`:
  - candidates < 3 → 原样返回（不变）
  - 新 prompt：给定上下文 + 候选列表，输出 `{"selected_indices": [i1, i2, i3]}`（选择最相关的 top-3，宁缺毋滥）
  - 解析失败 → 返回 None（调用方保留原 envelope，与现状一致）
  - 选中的题目按原 candidates 顺序保序返回
- `_parse_rerank_scores` → 新增 `_parse_selected_indices(raw, max_idx)`（容错：数组/对象包裹/碎片）
- 阈值 `_RERANK_RELEVANCE_THRESHOLD` 不再使用（listwise 无分数），保留常量避免破坏 import

**测试**（backend/tests/chat/test_tools.py 追加）:
1. listwise 返回 3 道选中题（mock LLM 返回 `{"selected_indices": [0, 2, 4]}`）
2. 选中数 < 3 也接受（LLM 只选 2 道 → 返回 2 道）
3. LLM 失败/解析失败 → None（调用方保留原候选）
4. candidates < 3 → 原样返回不调 LLM
5. 索引越界容错（selected_indices 超界 → 忽略该索引）

**验证**: 单测通过 + 真实 mimo 调用冒烟（15 候选 → listwise top-3）

---

## P1b: draw_questions 候选池 embedding 补充

**现状**: `draw_questions`（question_draw_service.py）纯 SQL 过滤（cat2 LIKE + question_type 关键词映射）→ 候选池严重萎缩（实测"高并发限流"0 题、"缓存设计"1 题）→ 抽题 0 分。

**改动**: SQL 候选不足时（< min_pool，默认 5），用 bge-m3 embedding 语义补充：
- `draw_questions(...)` 内：SQL 过滤后若 `len(candidates) < min_pool`：
  - 构造查询文本 = cat2/topic 关键词拼接（如 "高并发 限流"）
  - `embedding_service.encode_texts([query])` → 与 DB 中全部向量 cosine top-K 补充
  - 补充候选去重（排除已在 SQL 候选中的 id）+ 追加到候选池
- 加权随机逻辑不变（补充的题同样参与 frequency×recency 权重）
- 新增参数 `embedding_fallback: bool = True`（可关闭）

**实现位置**: `question_draw_service.py` 新增 `_embedding_supplement(candidates, query_text, target_count, exclude_ids) -> list`；`draw_questions` 在 SQL 过滤后调用。

**测试**（backend/tests/services/ 或 tests/bank/ 下追加，mock embedding_service.encode_texts）:
1. SQL 候选 ≥ min_pool → 不触发补充
2. SQL 候选 < min_pool → 触发补充且总数达标、无重复
3. embedding 失败（异常）→ 优雅降级返回 SQL 候选（不崩）
4. 补充的题参与加权随机抽取（可抽取到）

**验证**: 单测 + 真实调用冒烟（"高并发限流"场景从 0 候选 → 有候选）

---

## P2: 聚类标签摘要候选 + 验证层（并入生产 matcher）

**现状**: `matcher.py` 增量匹配用 embedding top-30 候选 + MATCH_EXISTING_PROMPT。实验结论：标签摘要记忆（LLM-MemCluster）替代纯向量候选，验证层（两轮布尔一致）提升准确率至 88%。

**改动**（保守落地，不重写 matcher 整体）:
1. **候选增强**: `cluster_public_node`/`cluster_batch` 的候选生成保持现有 embedding top-30 + 文本预筛，**新增标签摘要列**：每个已有 cluster 维护 `label`（LLM 生成，落库 `clusters` 表新列或 `question_bank` 代表题加字段）
2. **匹配 prompt 增强**: MATCH_EXISTING_PROMPT 候选展示时带 label（`[标签] 代表题`），不改变候选生成逻辑（最小侵入）
3. **验证层**: 对低置信匹配（LLM 匹配 + 原二次验证路径）保持现状；新增可选开关 `CLUSTER_VERIFY_LAYER`（env，默认关，实验继续验证后开）

**注意**: 实验代码在 `experiments/`（memory_labels.py 等），生产并入是**增量**：先做标签生成+落库（幂等，存量 cluster 分批补生成），prompt 增强；验证层默认关闭不改变现有行为。

**测试**: matcher 现有测试全绿 + 新测试（标签落库、prompt 含 label）

---

## P3: 聚类异步化

**现状**: `cluster_public_node`（persist_public.py）在 SSE 请求内同步 `await cluster_batch`（5-30s）。

**改动**: 异步化 + 攒批：
- `cluster_public_node` 不再 await，改为调度后台任务（asyncio.create_task）
- 后台任务：`dequeue_batch → cluster_batch → mark_done/failed`（复用 worker.py 的 cluster_questions_task 逻辑，抽公共函数到 `services/pipeline/batch.py`）
- 攒批: pending ≥ BATCH_SIZE 立即聚；否则延迟 `CLUSTER_DELAY_SECONDS`（默认 300s，config 外置）再聚；模块级标志去重
- SSE 事件: cluster 阶段改为"已加入聚类队列，后台聚合中"
- 前端: SiteHeader.vue:264 完成文案改"题目已保存，聚类后台进行中"

**测试**: tests/pipeline/ 更新 cluster 同步断言为异步语义（任务调度、队列状态流转、后台最终处理）

**验证**: 单测 + 生产冒烟（提交面经 → SSE 快速 done → 后台完成聚类）

---

## P4: 聚类候选混合信号 + llm_judge 统一

**P4a 混合信号**: 聚类候选生成在 embedding 外增加关键词/标签文本信号（借鉴检索 FTS）：新题文本与 cluster 标签的字符/关键词重叠作为补充候选信号（零成本，文本预筛已有一层，扩展到标签）。若标签列未落库则延后。

**P4b llm_judge 统一**: 抽公共模块 `services/llm_judge.py`:
- `llm_json_call(prompt, system_msg, user_id, fallback=None)`（带容错解析）
- `parse_json_list/parse_json_object`（从 experiments/ 的 norm_score_list 等收敛）
- 检索 rerank 与聚类验证共用

---

## 实施顺序与提交

1. P1a（tools.py + 测试）→ commit
2. P1b（question_draw_service + 测试）→ commit
3. P2（matcher 标签 + 测试）→ commit
4. P3（异步化 + 测试）→ commit
5. P4（抽公共 + 测试）→ commit

每 Phase 独立可验证、可回滚。全量回归：`backend/tests/services/ backend/tests/chat/ backend/tests/pipeline/ backend/tests/bank/`。
