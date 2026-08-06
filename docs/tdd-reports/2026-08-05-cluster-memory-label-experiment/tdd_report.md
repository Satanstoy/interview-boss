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
| R6 | tight | 0.8 | 中断 | — | — | mimo 服务抖动 → tenacity 无限重试（788 次请求，正常 3.3 倍），数据污染，弃用 |

## 关键发现

1. **验证层有效但 similarity 分数不可靠**：R3（0.7）质量最高，但 R5（0.6）反而全拒——LLM 打分波动大（sim=0.00 配"考察点一致"自相矛盾）。**验证层作为"两轮独立布尔判断一致"是稳的，分数门槛是脆的**。
2. **prompt 收紧效果有限**：R1→R2（42→40）证明措辞对 LLM 边界判断影响小；LLM 单次判断波动（同一题三轮三种结论）是主噪声源。
3. **漏合并很少**：187 孤岛中明确漏合并 3-4 条（~2%）；相似度预筛只找到 46 个候选对，证明大多数孤岛与已有聚类文本重叠极低（真新题）。
4. **方案能发现现有系统漏掉的合并**：R1 的 42 个合并中 18-20 个抽样判定合理（现有系统把这些留在孤岛）；R3 验证后的 14 个中 12 个合理且全部关键漏合并保留。
5. **现有数据有脏样本**：oq 混入无关题（5872 混入"研究生方向"行为面题）、cluster 含重复项（5940）——污染 LLM 判断，并入生产前需清理。

## 用量与成本（2026-08-05 实测统计）

mimo 无公开 usage API，以下为日志请求数 + prompt 结构精确估算；与用户 mimo 后台"约 10% 套餐"交叉验证吻合（按 10% ≈ 8.5M 反推套餐约 85M token/月）。

| 轮次 | 请求次数 | 估算 token | 说明 |
|------|---------|-----------|------|
| R1 (loose, 无验证) | ~194 | ~0.96M | |
| R2 (tight, 无验证) | ~194 | ~0.99M | |
| R3 (tight, 验证 0.7) | ~236 | ~1.01M | 最佳轮次 |
| R4 (loose, 验证 0.7) | 241 | ~0.98M | |
| R5 (tight, 验证 0.6) | 227 | ~1.01M | |
| R6 (中断, 重试风暴) | 788 | ~3.56M | 占总量 42%，纯浪费 |
| **总计** | ~1880 | **~8.5M** | |

**用量构成（关键）：**
- **分配阶段占 95%+**：每轮 187 次 × 每次携带全部 133 个标签（~3.5K token/次）≈ 0.96M——大头
- 标签摘要：~25K/轮（1%）；验证层：~25K/轮（1%）
- **R6 重试风暴烧掉 3.56M（42%）**：mimo 抖动时 tenacity 无限重试，纯浪费

## Embedding 候选生成验证（2026-08-05，bge-m3 via SiliconFlow）

字符相似度作为候选信号实测不可靠（top-20 召回仅 86%，漏 2 个真实合并：6033 大小写+语义无重叠、6236 字符零重叠），用户提出是否用 embedding。采用 API embedding（BAAI/bge-m3, 1024 维, SiliconFlow）离线验证：

**结果：top-20 = 100% 召回（14/14），12/14 排 top-2 内。**

| N | 字符 jaccard | bge-m3 |
|---|-------------|--------|
| top-5 | 64% | 93% |
| top-10 | 79% | 93% |
| **top-20** | **86%** | **100%** |
| top-30 | 93% | 100% |

- 6033 "rag的作用" → "RAG技术理解与选型"：字符 129 名 → **top-1**
- 6236 "实习项目介绍" → "挑一个项目介绍"：字符 35 名 → **top-1**

**图谱方案评估（用户提议"新标签建图谱关系"）：实测 8/14 = 57%，不采用。** 图检索（HNSW/GraphRAG 思路）优势需上千节点才显现；133 节点全量 embedding 排序毫秒级即可。图仅在未来"题目生态可视化"产品需求时考虑（届时 cat2 + keywords 数据已铺路）。

## 最终生产架构（实验定稿）

```
新题 → ① bge-m3 embedding 检索 top-20 候选聚类（召回 100%）
     → ② LLM 分配（tight prompt，仅带 20 个候选标签，token 4K→1K/次）
     → ③ 验证层（VERIFY_MERGE_PROMPT，same 布尔两轮一致，fail-closed）
     → ④ 文本预筛前置（规范化文本精确/包含匹配，零成本）
```

**成本核算（对比原方案）：**
- LLM 分配：0.75M/轮 → ~0.2M/轮（20 候选替代 133 全量）
- embedding：聚类向量缓存持久化（只算一次），增量仅 embed 新题（~50K token 一次全库，几分钱）
- 全程每轮 ≈ 0.2M token

## Prompt 方案（实验定稿）

```
1. CLUSTER_LABEL_PROMPT（标签摘要）
   不变。分批 20/批；label ≤20 字 + keywords 3-6 个；输出 {"clusters": [...]} 对象
   （适配 response_format=json_object）。质量已验证（"高并发场景下的限流方案设计"等准确）。

2. SINGLETON_ASSIGN_PROMPT（分配）→ tight 版定稿
   含"不应合并"五类示例（考察点不同 / 主题相近问题不同 / 介绍vs对比题 / 具体算法题vs元问题 / 考察范围不同），
   结尾强调"宁可漏合并，不可错合并"。

3. VERIFY_MERGE_PROMPT（验证）→ same 布尔为准
   独立视角复核 + similarity 0-1 评分。判定规则：same=true 即采纳；
   similarity 仅作降级参考（<0.5 时 reason 标注 sim），不做硬门槛
   （R5 证明分数波动大，两轮布尔一致才稳）。

配置参数：verify_enabled=True；sim_threshold 不设硬门槛；assign prompt = tight
```

- 预期效果：合并 ~7-14 个/187 孤岛（4-7%），准确率 ~85-90%，漏合并率 ~2%

## 生产化成本优化（将总量降 ~90%）

1. **分配只带 top-20 相似标签（embedding 信号）**：已验证 100% 召回；token 降 85-90%（0.96M → ~0.2M/轮）。字符相似度信号不可用（86%）
2. **标签摘要 + 聚类向量缓存持久化**：标签和 embedding 生成一次存 DB，增量导入/后续轮次不重生成（省 7 次/轮；R2-R6 每轮重复生成是浪费）
3. **重试上限控制**：tenacity 设 max attempts + 熔断（R6 教训：mimo 抖动时 788 次重试烧 3.56M）
4. **生产场景天然更省**：增量导入只对新题 embed + 分配 + 验证（几题/次），不做全量 187 次重扫

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
