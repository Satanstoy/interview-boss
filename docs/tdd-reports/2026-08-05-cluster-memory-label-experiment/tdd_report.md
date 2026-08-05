# 聚类实验：Cluster 语义标签摘要记忆（LLM-MemCluster 模式）

**日期**: 2026-08-05
**状态**: 实验完成，结论已记录，待用户决定是否并入生产
**代码**: `backend/app/services/clustering/experiments/`（独立实验模块，未碰生产聚类代码）

## 背景与动机

- 用户反馈"导入面经流程慢"，聚类（聚合）是单次导入的关键路径瓶颈
- 用户实测 embedding 效果一般（文档亦有记录：中文语义相似句 cosine 仅 0.6-0.7）
- 调研业界（LLM-MemCluster 2511.15424 / Lifecycle-Aware Clustering 2026 IJCNLP / Text-Clustering-as-Classification 2410.00927）：业界不依赖 embedding，用 LLM 语义标签摘要做增量分配（聚类转分类）
- 目标：验证"cluster 语义标签摘要记忆"方案在生产数据上的效果（合并质量、漏合并、成本）

## 实验设计

- **数据**：生产 DB `question_bank` 321 题：133 个有合并记录的 cluster（frequency>1）+ 187 个孤岛（frequency=1，58%）
- **方法**：
  1. 为每个已知 cluster 生成 LLM 语义标签摘要（`CLUSTER_LABEL_PROMPT`，分批 20）
  2. 孤岛题增量分配（`SINGLETON_ASSIGN_PROMPT`：归属已有 cluster / 独立新题，文本预筛先行）
  3. 验证层（`VERIFY_MERGE_PROMPT`：独立视角二次判断 + similarity 评分，fail-closed）
- **LLM**：用户主账号配置（mimo-v2.5，user_id=1）
- **评估**：合并数、抽样人工核验准确率、漏合并复核（相似度预筛 + LLM 复核）

## 轮次结果

| 轮次 | 分配 prompt | 验证层 | LLM 合并 | 维持孤岛 | 抽样准确率 | 备注 |
|------|------------|--------|---------|---------|-----------|------|
| R1 | loose（原始） | 无 | 42 | 145 | ~80%（4-5 偏宽 + 1 明显误合并） | 基线；漏合并复核发现真实漏合并 3-4 条 |
| R2 | tight（收紧） | 无 | 40 | 147 | ~80%（偏宽未消除，新偏宽出现） | **收紧 prompt 无效**（LLM 单次判断不稳定是主因） |
| **R3** | tight | **0.7** | **14** | 173 | **~88%**（偏宽 2 条） | **最佳**；关键漏合并（6267/6376/6279）全部保留 |
| R4 | loose | 0.7 | 1 | 186 | — | loose 分配偏宽 → 验证全拒，过度保守 |
| R5 | tight | 0.6 | 0 | 187 | — | 分配 33 → 验证全降级（含 reason 一致但 sim=0.00 的自相矛盾） |
| R6 | tight | 0.8 | 中断 | — | — | mimo 服务重试风暴（687 次调用），数据被污染，弃用 |

## 关键发现

1. **验证层有效但 similarity 分数不可靠**：R3（0.7）质量最高，但 R5（0.6）反而全拒——LLM 打分波动大（sim=0.00 配"考察点一致"自相矛盾）。**验证层作为"两轮独立布尔判断一致"是稳的，分数门槛是脆的**。
2. **prompt 收紧效果有限**：R1→R2（42→40）证明措辞对 LLM 边界判断影响小；LLM 单次判断波动（同一题三轮三种结论）是主噪声源。
3. **漏合并很少**：187 孤岛中明确漏合并 3-4 条（~2%）；相似度预筛只找到 46 个候选对，证明大多数孤岛与已有聚类文本重叠极低（真新题）。
4. **方案能发现现有系统漏掉的合并**：R1 的 42 个合并中 18-20 个抽样判定合理（现有系统把这些留在孤岛）；R3 验证后的 14 个中 12 个合理且全部关键漏合并保留。
5. **现有数据有脏样本**：oq 混入无关题（5872 混入"研究生方向"行为面题）、cluster 含重复项（5940）——污染 LLM 判断，并入生产前需清理。

## 效果最好的组合（建议生产化配置）

```
分配 prompt: tight 版（含"不合并"示例）
验证层: VERIFY_MERGE_PROMPT，same 布尔两轮一致即采纳（不依赖 similarity 分数门槛，
       或分数仅作降级参考，不做硬门槛）
文本预筛: 前置零成本确定性合并（规范化文本精确/包含匹配）
```

- 预期效果：合并 ~7-14 个/187 孤岛（4-7%），准确率 ~85-90%，漏合并率 ~2%
- 成本：133 clusters → 7 次标签摘要调用 + 187 次分配 + ~40 次验证 ≈ 234 次 LLM 调用/全量重扫（增量导入时只对新题）

## 生产化建议（待用户决策）

1. **并入 matcher**：把标签摘要列表（每 cluster 一个语义标签，增量维护）作为增量匹配候选池，替代/增强当前"embedding top-30 + 最近窗口"候选；合并决策保留"两轮独立判断一致"（与生产 VALIDATE_MERGES 设计哲学一致）
2. **标签摘要的增量维护**：新 cluster 生成时同步生成标签；合并发生时标签更新
3. **脏数据清理**：并入前清理 oq 混入项、重复项（可用 `clustering_maintenance` 的确定性修复）
4. **人工核验闭环**：保留报告抽样机制，定期核验合并质量
5. **与异步化（第一阶段）关系**：本实验结论独立于异步化；异步化（聚类移出 SSE 关键路径）另行规划

## 实验代码结构

```
backend/app/services/clustering/experiments/
├── prompts.py          # CLUSTER_LABEL_PROMPT / SINGLETON_ASSIGN_PROMPT(+_LOOSE) / VERIFY_MERGE_PROMPT
├── memory_labels.py    # load_cluster_data / text_prefilter / generate_cluster_labels / assign_singletons / verify_assignments
├── evaluate.py         # 评估入口（--round/--user-id/--no-verify/--sim-threshold/--assign-prompt）
└── review_islands.py   # 漏合并复核（相似度预筛 + LLM 复核）
backend/tests/services/clustering/experiments/test_memory_labels.py  # 16 个测试（mock LLM）
```

## 复现方式

```bash
# 全流程实验（round N）
docker compose run --rm -v $PWD/backend:/app/backend backend python -m app.services.clustering.experiments.evaluate --round 3 --user-id 1
# 漏合并复核
docker compose run --rm -v $PWD/backend:/app/backend backend python -m app.services.clustering.experiments.review_islands --round 1 --user-id 1
# 单元测试
docker compose --profile test run --rm test uv run pytest backend/tests/services/clustering/experiments/ -q
```

报告输出 `backend/experiment_reports/round<N>.md`（gitignored，含生产数据样本不提交）。
