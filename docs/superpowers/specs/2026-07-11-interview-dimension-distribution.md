# 面经驱动的模拟面试分布与质量控制系统设计

**日期**: 2026-07-11
**状态**: 已确认，待实施
**作者**: MiMoCode / Codex

## 1. 背景与目标

当前模拟面试的题型覆盖主要依赖岗位和难度的固定 phase 阈值。用户可以选择单条面经，但系统只从 `questions_list` 的关键词推断节奏，既不使用全库真实分布，也没有用户可调的题型比例或主问题总数。

本设计将模拟面试改造成一个可解释的受约束自适应测验系统：真实面经决定默认先验，用户可以调整，Agent 能根据候选人表现动态变化，但系统仍以程序化规则保证题型分布和题量不会无解释地失控。

### 1.1 目标

1. 基于真实、已审核面经生成按岗位划分的默认题型分布与默认题量。
2. 在设置页让用户查看系统默认、选择单条面经风格，或保存自定义题型比例和题量。
3. 创建会话时固化不可变的分布计划；后续统计变化不影响进行中的模拟。
4. 让分布计划实际约束 Agent 的检索、抽题、追问与收尾，而不是只作为 system prompt 文本。
5. 记录实际题量、题型分布、偏离原因和完成状态，并能由 E2E 脚本验证。

### 1.2 非目标

- 不要求每场模拟严格等于默认比例；真实面试允许合理波动。
- 不把私人面经直接并入影响所有用户的系统默认基线。
- 不把低置信度的自然澄清追问冒充为完成了一道主问题。

## 2. 当前实现与问题

### 2.1 已有能力

- `chat_conversations.metadata.interview_config` 可持久化会话级配置。
- `coverage_events`、`InterviewLedger`、`question_plan`、`tool_strategy` 与 `stop_policy` 已能追踪 phase、引导下一题并控制收尾。
- `build_react_system_prompt()` 已注入运行时 `<interview_harness>`，其中包含当前覆盖和下一优先 phase。
- `experience_id` 可选择一条可访问面经，生成 `rhythm_profile`。

### 2.2 缺口

- 没有从全库已标注题目统计默认比例与默认题量。
- `rhythm_profile` 只读取单条 `questions_list` 并以关键词猜测 phase，未读取题目分类数据。
- `CreateConversationRequest` 与前端没有分布、题量或用户偏好入口。
- 当前 `questions_detail` 只有 URL 关联，没有可靠的 `interview_id`，无法安全、准确地按面经、岗位与权限汇总。
- 当前固定覆盖阈值不等于主问题总数控制，也没有单场允许区间、偏离原因或实际结果审计。

## 3. 术语与统一题型

### 3.1 可配置题型

设置页、统计表、会话计划和 Agent 运行时必须使用同一组互斥题型。五个滑条合计为 100%。

| `question_type` | 设置页名称 | 说明 | 是否计入主问题总数 |
|---|---|---|---|
| `project_followup` | 项目深挖 | 围绕候选人的职责、设计、难点、取舍和复盘追问 | 是 |
| `knowledge_probe` | 基础知识 | 原理、框架、中间件、工程基础与技术细节 | 是 |
| `algorithm_coding` | 算法/手撕 | 算法、数据结构、编码实现与复杂度 | 是 |
| `system_design` | 系统设计 | 架构、容量、可靠性、扩展性与分布式权衡 | 是 |
| `behavioral` | 行为/HR | 协作、冲突、影响力、职业动机与稳定性 | 是 |

开场、自我介绍引导、候选人反问、收尾、纯澄清追问不属于 `question_type`，不计入主问题总数。

### 3.2 题库工具的统一契约

五类 `question_type` 是题库工具、MCP Gateway、Agent 状态与统计表共同使用的唯一枚举。现有 `new_question` 是“切换话题”意图，不是题型；现有 `hr` 是历史工具别名。新实现必须：

- 由共享 `QuestionType` 枚举定义五种题型，`hr` 只在兼容适配层归一化为 `behavioral`，不得再由 LLM 或新 API 产生；
- 让 `search_questions` 与 `draw_questions` 都接受并返回这五种题型，移除 search 只支持三类、draw 使用 `hr` 的不一致；
- 由分布控制器把本轮可行题型集合写入状态，Tool Gateway 必须覆盖或拒绝 LLM 传入的越界题型；
- 对每个检索/抽取候选题调用共享 `map_question_type` 验证。与控制器指定类型不一致的候选题不得进入 `select_question`；若候选池因此为空，按受记录的降级策略重新检索，而不是偷偷放宽约束。

这使滑条配置能够穿过工具调用边界成为实际过滤条件，而不是停留在 prompt 文本中。

### 3.3 高层分析维度

为兼容“项目深挖 vs 知识探测”的分析视图，另保留派生字段 `dimension`：

| `dimension` | 组成题型 |
|---|---|
| `project_deep_dive` | `project_followup` |
| `knowledge_probe` | `knowledge_probe`、`algorithm_coding`、`system_design` |
| `behavioral` | `behavioral` |
| `unclassified` | 无法可靠映射的题目 |

`dimension` 仅用于高层报表；设置、统计和运行时控制以五类 `question_type` 为准。

### 3.4 标注规则

新增统一服务 `app/services/interview_distribution.py`，集中定义 `map_question_type(cat1, cat2, tags, question)` 与 `map_dimension(question_type)`。所有写入和回填路径必须调用它。

- `E.*` 分类映射为 `algorithm_coding`。
- 明确的协作、冲突、复盘、职业动机等映射为 `behavioral`。
- 项目职责、项目难点、项目复盘映射为 `project_followup`。
- 明确的架构、容量、可靠性、扩展性、系统设计映射为 `system_design`。
- 其余已分类技术题映射为 `knowledge_probe`。
- 分类不足或规则无法可靠判断时写入 `unclassified`，不参与默认比例拟合。

映射规则必须有单元测试，并对分类体系变化提供显式版本号；禁止在不同模块各自使用关键词集合。

## 4. 数据模型

### 4.1 `questions_detail`：统计事实来源

`questions_detail` 是唯一的题型统计事实来源。新增字段：

```sql
ALTER TABLE questions_detail ADD COLUMN interview_id INTEGER;
ALTER TABLE questions_detail ADD COLUMN question_type TEXT NOT NULL DEFAULT 'unclassified';
ALTER TABLE questions_detail ADD COLUMN dimension TEXT NOT NULL DEFAULT 'unclassified';
CREATE INDEX idx_qd_interview_question_type
    ON questions_detail(interview_id, question_type);
```

`interview_id` 可为空，供 JD 或无法可靠关联的历史记录使用。参与面经统计的记录必须具备有效 `interview_id`。

新上传和重新分析时的顺序：

```text
创建或定位 interview
→ 获得 interview.id
→ 提取并标注题目
→ 写入 questions_detail.interview_id / question_type / dimension
→ 标记该岗位统计失效
```

历史回填只在 URL 与面经记录可唯一匹配时填写 `interview_id`；有歧义的记录保留未关联状态、记录迁移报告且不进入默认统计。不得以猜测归属污染权限和统计。

### 4.2 `interview_distribution_stats`：系统统计物化表

该表是从 `questions_detail` 重建的物化汇总，不是事实来源。系统默认的精确数据谓词为：

```sql
interview.owner_id IS NULL
AND interview.status = 'approved'
AND interview.deleted_at IS NULL
AND questions_detail.interview_id = interview.id
AND questions_detail.deleted_at IS NULL
AND questions_detail.question_type != 'unclassified'
```

也就是说，公共已审核面经才可改变所有用户的系统默认；`owner_id` 有值的私人面经只能用于其所有者的单条面经风格偏置。

```text
scope                    public_job_position | job_family | system_baseline
job_position             岗位名或岗位族名
question_type            五类题型之一
posterior_mean_ratio     设置页默认滑条值
posterior_alpha          Dirichlet 后验参数，可重建置信度
raw_question_count       原始有效题数，供审计
sample_interview_count   参与拟合的面经场数
sample_question_count    参与拟合的有效主问题数
recommended_total_count  同 scope 下有效主问题数的中位数
dispersion               面经间题型波动程度
confidence               high | medium | low
stats_version            原子发布的统计版本
calculated_at
```

唯一键为 `(scope, job_position, question_type, stats_version)`。读取默认值时只读取最新完整版本；一组五类记录必须拥有相同的 `stats_version`，防止读到半更新的比例。

### 4.3 `interview_distribution_refresh_jobs`：统计刷新作业

统计刷新是可恢复、可合并的后台作业，不能只在流程图中抽象为 `statistics_refresh_job(...)`。新增表：

```text
scope + job_position       唯一键；同一统计范围同时最多一个待处理作业
requested_source_version   已知的最新事实版本
published_source_version   当前已发布统计使用的事实版本
status                     pending | running | failed
attempt_count
claimed_by + claimed_at
last_error
next_retry_at
updated_at
```

事实写事务使用幂等 upsert 创建或合并作业：将 `requested_source_version` 提升到最新值、未运行时置为 `pending`。Worker 通过条件更新原子领取作业；完成时只在完整五类统计校验成功后发布新 `stats_version` 并更新 `published_source_version`。失败使用指数退避重试，保留上一成功统计并向 API 返回 `stale`。面经的 `owner_id`、审核状态、删除状态或题型变化都必须入队重算，并有权限边界回归测试。

### 4.4 `user_interview_distribution_preferences`：用户岗位偏好

```text
user_id + job_position   唯一键
mode                     system_default | selected_experience | custom
target_question_count    用户偏好的主问题总数，可为空
custom_distribution      JSON；仅 custom 模式必填，五类题型和为 1
selected_experience_id   仅 selected_experience 模式可填
style_strength           low | normal | strong
updated_at
```

用户设置只影响该用户后续新建会话，不修改系统统计表，也不回写已创建会话。

### 4.5 会话计划快照与执行日志

沿用 `chat_conversations.metadata.interview_config`，新增创建后不可修改的 `distribution_plan`。计划只描述会话开始时的输入和约束，绝不写入运行状态：

```json
{
  "distribution_plan": {
    "plan_id": "uuid-created-with-conversation",
    "mode": "system_default",
    "stats_version": 12,
    "source_snapshot": {
      "scope": "public_job_position",
      "job_position": "大模型开发",
      "sample_interview_count": 44,
      "sample_question_count": 548,
      "confidence": "high"
    },
    "style_source_snapshot": null,
    "target_question_count": 10,
    "expected_distribution": {
      "project_followup": 0.11,
      "knowledge_probe": 0.54,
      "algorithm_coding": 0.12,
      "system_design": 0.16,
      "behavioral": 0.07
    },
    "soft_target_counts": {
      "project_followup": 1,
      "knowledge_probe": 5,
      "algorithm_coding": 1,
      "system_design": 2,
      "behavioral": 1
    },
    "allowed_counts": {
      "project_followup": {"min": 0, "max": 2},
      "knowledge_probe": {"min": 3, "max": 6},
      "algorithm_coding": {"min": 0, "max": 2},
      "system_design": {"min": 0, "max": 3},
      "behavioral": {"min": 0, "max": 2}
    },
    "random_seed": "persisted-per-conversation"
  }
}
```

`allowed_counts` 必须覆盖所有五类题型，且上下界必须允许一个总数恰为 `target_question_count` 的解；`soft_target_counts` 的五类整数和必须严格等于 `target_question_count`。

`selected_experience` 模式的 `style_source_snapshot` 不得为空，且只保存可审计、无题目正文的快照：`experience_id`、该面经的版本/更新时间、五类有效题数、未分类率、`p_experience`、`style_strength`、最终混合权重 `w` 与混合前后比例。这样，即使偏好或源面经后续变化，历史会话仍可复现当时的计划形成过程。

执行状态不回写 `distribution_plan`。每条 assistant 消息的 `coverage_events` 以 `plan_id` 为键追加不可变的主问题事件；读取会话时通过折叠事件得到 `actual_counts`、当前剩余配额与进度。结束消息追加 `distribution_result`，其中只含 `completed` 或 `incomplete`、实际计数、偏离原因和结论。可以缓存可重建的执行摘要，但缓存与事件不一致时必须以事件为准。

## 5. 默认值估计方法

### 5.1 有效样本定义

一条面经须同时满足以下条件才参与岗位统计：

- `interview.status = 'approved'`、未软删除、公共可见；
- `interview.owner_id IS NULL`，即系统公共统计绝不包含私人面经；
- 题目未软删除且 `interview_id` 正确关联；
- 有效主问题数达到最低质量门槛；
- `unclassified` 占比未超过配置上限。

统计报告应保留被排除记录数及原因，供管理员审计。

### 5.2 默认总题数：中位数

对同 scope 的每场面经有效主问题数 `n_i`，默认题数为：

```text
recommended_total_count = median(n_i)
```

中位数比平均值更不易受异常长或异常短面经影响。前端可显示该值及样本数；用户可调整，后端再校验合理范围。

### 5.3 默认分布：分层 Dirichlet-多项式模型

对每场面经的五类题型计数 `c_i` 和总数 `n_i`，使用：

```text
c_i ~ Multinomial(n_i, θ_i)
θ_i ~ Dirichlet(κ × p_job)
p_job ~ Dirichlet(τ × p_parent)
```

- `p_job` 的后验均值是该岗位设置页的默认滑条值；五类值天然和为 1。
- `κ` 表示真实面经之间的自然波动，用于后续单场允许区间。
- `p_parent` 是岗位族或系统基线；样本稀少时会将岗位结果平滑地收缩到父级，而不是让一两条面经决定默认值。

参数采用经验贝叶斯估计，保存后验参数与版本。实现初期若尚未引入完整拟合器，可使用同一模型的共轭后验近似：

```text
p̂_job,t = (count_job,t + α × p_parent,t) / (count_job,total + α)
```

但统计表结构和会话计划接口必须保持不变，以便无数据迁移地升级至完整的分层拟合。

### 5.4 样本不足回退

按以下顺序选择先验来源：

```text
public_job_position
→ job_family
→ system_baseline
```

不以固定的“假装准确”阈值掩盖样本不足：统计服务须依据后验有效样本量和可信区间生成 `confidence`，并把来源和样本量返回前端。

### 5.5 单条面经风格模式

单条面经只能作为风格偏置，不得完全替代岗位总体先验：

```text
p_session = (1 - w) × p_job + w × p_experience
```

`w` 由选中面经的有效题数、未分类率、用户 `style_strength` 与统计置信度决定；题数少、质量低时自动减小。该机制避免极端单条面经劫持默认质量。

## 6. 设置页与接口

### 6.1 设置页

设置页提供：

- “使用系统默认 / 使用某条面经风格 / 自定义”模式切换；
- 五类题型滑条，显示百分比且严格合计 100%；
- 本场主问题总数输入；
- 系统统计来源、样本面经数、有效题数、统计时间、置信度与“恢复系统默认”操作；
- 在默认和单条面经模式下展示计算值；仅自定义模式允许编辑滑条；
- 新建会话时允许一次性覆盖，但不自动覆盖用户保存的岗位偏好。

### 6.2 API

- `GET /api/interview/distribution/default?job_position=...`：返回最新系统统计、默认题量、置信度及统计版本。
- `GET /api/profile/interview-distribution-preference?job_position=...`：读取当前用户偏好。
- `PUT /api/profile/interview-distribution-preference`：保存模式、题量、滑条和可选单条面经设置。
- 扩展 `POST /api/chat/conversations`：接收可选会话覆盖，后端计算并持久化 `distribution_plan`。
- `GET /api/chat/conversations/{id}`：返回会话计划与当前实际进度，供前端展示。

所有写接口必须校验：题型集合完整、比例和为 1、总题数为合理整数、所选面经对当前用户可访问、计划上下界可行。

## 7. 统计表刷新与一致性

以下动作会使对应岗位统计失效：上传面经、重新分析、编辑 `questions_list`、审核状态改变、软删除/恢复、题型重新标注。

```text
事务内写入事实数据
→ 幂等 upsert `interview_distribution_refresh_jobs`
→ 后台重算完整五类统计
→ 校验比例、样本数与版本
→ 单事务发布新的 stats_version
```

读取端只能看到上一个完整版本或新完整版本。刷新失败时保留最后成功版本并标记 `stale`，不得返回部分聚合结果。

## 8. 会话运行时质量控制

### 8.1 计划转换

创建会话后，根据 `target_question_count`、后验均值和题型波动生成：

- `soft_target_counts`：最近似的整数期望值；
- `allowed_counts`：Dirichlet-多项式后验预测的中心区间；
- `random_seed`：用于可复现的平局打破和 E2E；
- 题型最小/最大边界与每类剩余缺口。

因此总题数为 10、项目深挖先验为 11% 时，可能得到软目标 1、允许区间 0–2；不强制每一场恰好问 1 道，也不允许无解释地连续问 5 道。

### 8.2 约束式自适应选题控制器

在每次产生新的有效主问题前，`question_plan` 调用分布控制器：

```text
输入：已问计数、剩余题数、允许区间、候选题池、候选人回答质量与能力缺口
输出：可行题型集合、首选题型、禁止题型、选择理由
```

规则：

1. 若选择某题型后无法在剩余题数内满足其他题型下限，禁止该题型。
2. 若选择后超过该题型上限，禁止该题型。
3. 在可行题型中，先根据候选人的能力缺口与上一轮回答选题，再按距软目标的缺口排序；使用 `random_seed` 处理同分情况。
4. 连续同题型主问题超过配置上限时，除非其余类型不可行或有明确风险信号，否则禁止继续该类型。
5. 候选人项目材料不足、回答暴露重大风险、用户选择的风格偏置等可使策略偏离软目标，但必须记录结构化原因。
6. 达到主问题总数后进入行为反馈、反问和收尾；候选人提前结束时标记 `incomplete`，不宣称已完成计划。

该控制器必须同时接入 `question_plan`、`tool_strategy`、`tool_gateway.py`、`tools.py`、`mcp_server/app.py`、`mcp_server/interview_tools.py`、`fts_service.py`、`question_draw_service.py` 与 `stop_policy`。它在工具 Gateway 处强制覆盖/验证 LLM 的题型参数，在候选题归一化处验证实际题型，在 `select_question` 前再次检查可行性。system prompt 只展示计划和当前进度，不能作为唯一控制机制。

### 8.3 Prompt 与事件记录

`build_react_system_prompt()` 注入：

```text
本场主问题目标、各题型已问/软目标/允许区间、下一优先题型、禁止题型、候选人适应理由。
```

每个主问题写入扩展后的 `coverage_event`：

```json
{
  "plan_id": "uuid-created-with-conversation",
  "question_type": "project_followup",
  "dimension": "project_deep_dive",
  "counts_toward_target": true,
  "question_id": 123,
  "selection_reason": "target_deficit",
  "constraint_status": "within_range"
}
```

自然澄清追问可以保留在事件日志中，但 `counts_toward_target` 必须为 `false`，不得影响题量与分布完成判定。

## 9. 迁移与改造范围

当前迁移已使用至 041。本功能使用下一个可用版本（预期 042），并在 `backend/app/db/migrations/__init__.py` 的注册表中登记；禁止创建旧 spec 所写的独立 `migration_040_*` 文件。

改造范围：

- `backend/app/db/migrations/`：题目关联、题型字段、统计表、用户偏好表和回填。
- `backend/app/db/operations.py`：插入、替换题目时写入 `interview_id/question_type/dimension` 并标记统计刷新。
- `backend/app/services/interview_distribution.py`：映射、统计拟合、计划生成、运行时约束与审计工具。
- `backend/app/services/chat_service.py`：读取偏好、生成会话快照。
- `backend/app/models/schemas.py`、`backend/app/routers/chat.py`、profile 路由：请求模型与 API。
- `backend/app/agents/chat/question_plan.py`、`tool_strategy.py`、`tool_gateway.py`、`tools.py`、`coverage_events.py`、`stop_policy.py`、`nodes.py`：控制器、统一枚举、事件与 prompt。
- `backend/app/mcp_server/app.py`、`backend/app/mcp_server/interview_tools.py`、`backend/app/services/fts_service.py`、`backend/app/services/question_draw_service.py`：Gateway 参数强制、候选题型验证和检索/抽题过滤。
- 前端 Settings 和创建模拟入口：模式、滑条、题量、数据来源及进度展示。

原 `rhythm_profile` 保留为“话题衔接顺序和单条面经风格”的辅助信息，不再单独决定分布或覆盖阈值。

## 10. 测试与验收

### 10.1 单元与集成测试

1. 题型与高层维度映射，含未分类和分类体系版本变更。
2. 历史 `interview_id` 回填仅关联唯一匹配记录。
3. 统计表重建结果、版本原子性、失效/刷新和权限边界。
4. 刷新作业的幂等合并、原子领取、重试、失败 stale 行为，以及 `owner_id/status/deleted_at` 变化的统计失效。
5. 中位数题量、Dirichlet 后验比例、样本不足回退、单条面经混合权重与完整的风格来源快照。
6. 统一工具枚举、`hr` 兼容归一化、Gateway 对越界 LLM 参数的覆盖/拒绝，以及候选题型验证。
7. 不可变计划与从 append-only `coverage_events` 派生的执行状态、结束结果的一致性。
8. 用户偏好与会话覆盖校验，五类比例总和、总题数与可行区间。
9. 约束控制器：上限、下限、剩余可行性、连续题型、候选人风险偏离与提前结束。
10. prompt、工具策略、实际事件和 stop policy 使用同一 `distribution_plan`。

### 10.2 E2E 验证脚本

新增 `backend/scripts/verify_interview_distribution_e2e.py`。脚本使用显式环境开关，输出可存档 JSON 报告，包含来源统计、会话快照、每题事件、实际计数、偏离原因和结论。

必须验证：

1. 系统默认统计与从事实表完整重算的结果一致。
2. 用户自定义滑条和题量会覆盖默认值，并被固化进新会话快照。
3. 单条面经模式为受可信度约束的混合偏置，而非完全覆盖总体默认。
4. HTTP/SSE 主链路中，只有 `counts_toward_target=true` 的事件计入题量。
5. 每场已完成会话的实际题型计数位于计划允许区间；超出时必须有合法结构化原因。
6. 固定随机种子的大量确定性模拟中，总体实际比例在预设容差内收敛到会话计划的后验均值。
7. 提前结束场次标记为 `incomplete`，不参与“分布达标”结论。

### 10.3 完成标准

- 设置页显示的默认题量、默认比例、样本量、置信度和统计版本均来自统计表最新完整版本。
- 修改设置会影响后续会话的 `distribution_plan`、程序化题型选择和 system prompt。
- Agent 无法仅凭生成文本绕过题型上限、剩余可行性和主问题总数控制。
- 全部统计与 E2E 输出可追溯到事实题目、统计版本与会话事件。

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 题型标注错误污染默认值 | 保留 `unclassified`、映射版本、回填报告、管理员重标与统计重算 |
| 样本过少导致极端比例 | 分层 Dirichlet 平滑、置信度展示和岗位族/系统基线回退 |
| 单条极端面经影响模拟 | 受质量和题数约束的混合权重，不能完全替换总体先验 |
| LLM 不遵守 prompt | 用约束控制器、工具过滤和 stop policy 强制执行；prompt 仅为辅助 |
| 统计读到半更新数据 | 完整版本原子发布、失败保留上一成功版本、标记 stale |
| 候选人提前结束或回答需要追问 | 区分主问题与澄清追问，记录 `incomplete` 与偏离原因 |
| 私人数据泄漏到系统默认 | 系统统计仅使用公共已审核面经；私有数据仅在所有者会话内使用 |

## 12. 参考方法

- NIST Engineering Statistics Handbook：在存在尾部极端值时，中位数可作为比均值更稳健的位置估计。
- Thomas P. Minka, *Estimating a Dirichlet Distribution*：用于从比例向量估计 Dirichlet / Dirichlet-multinomial 参数。
- Wim J. van der Linden, *A Comparison of Item-Selection Methods for Adaptive Tests with Content Constraints*：内容蓝图约束与自适应选题。
