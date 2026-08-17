# ADR-0044: 采用极简双版本轴与完整运行快照

**Status:** accepted

## 决策

评测系统只保留两个面向管理员的顶层版本对象：

1. **Target Release（被测对象版本）**：记录某个 Agent、Workflow 或 Pipeline 的可复现行为。
2. **Evaluation Release（完整评测版本）**：记录某一类目标“如何被测”的完整配置。

一次 **Eval Run（评测运行）** 必须绑定一个 Target Release 和一个 Evaluation Release。评测内容的内部配置仍然分组保存，但不再把 Benchmark、Judge、Harness、Candidate Simulator 和协议暴露成六类需要管理员分别维护的公开版本。

Evaluation Release 按目标类型限定作用域，例如 `interview-eval@1.0` 只能用于面试目标；同一目标类型的多个 Target Release 可以复用它。这样可以直接进行公平 A/B：两次运行使用同一个 Evaluation Release，只更换 Target Release。

## 配置归属

| 配置 | 所属版本 | 说明 |
| --- | --- | --- |
| 代码、Workflow、产品 Prompt、产品工具 | Target Release | 会改变产品正常行为 |
| 被测对象使用的模型及参数 | Target Release | 被测 Agent 自己调用的模型 |
| Benchmark Case、输入 Snapshot、质量要求 | Evaluation Release | 决定测什么 |
| Hard Assertions、Rubric、聚合与门槛 | Evaluation Release | 决定怎样判定 |
| Judge Model、Prompt、采样与结构化输出约束 | Evaluation Release | 固定裁判行为 |
| Simulator Harness、工具夹具、超时、重试和随机性 | Evaluation Release | 固定 E2E 执行器 |
| Candidate Simulator Model、Prompt、候选人画像和参数 | Evaluation Release | 固定模拟用户行为 |
| 评测侧 Embedding/Retrieval 与运行限制 | Evaluation Release | 固定评测环境 |

上述配置在 Evaluation Release Manifest 中以 `benchmark`、`protocol`、`judge`、`simulator_harness`、`candidate_simulator`、`retrieval` 和 `runtime` 等内部分组保存。分组用于前端表单和审计，不产生独立的公开版本号。

## 最小数据边界

### Target Release

至少保存：`id`、`target_id`、`target_type`、`display_name`、`version`、`status`、`source_ref`、`manifest`、`config_digest`、创建者和发布时间。`manifest` 记录代码、Workflow、Prompt、工具、被测模型及其参数。

### Evaluation Release

至少保存：`id`、`target_type`、`display_name`、`version`、`status`、`manifest`、`config_digest`、创建者和发布时间。`manifest` 包含完整 Benchmark、评测协议、Judge、Harness、Candidate Simulator、评测侧检索和运行参数。

### Eval Run

至少保存：`id`、`target_release_id`、`evaluation_release_id`、`status`、`resolved_snapshot`、`replication_policy`、批次与并发参数、随机种子策略、创建者、时间戳和结果摘要。`resolved_snapshot` 在创建时生成，包含两个 Release 的 Manifest 以及实际解析出的模型、参数、Git SHA、配置摘要和可获得的镜像摘要。

凭证只保存稳定的 `credential_ref`，不把 API Key 写入 Release、Run 或 Artifact。实际凭证由全局模型配置或运行环境提供。

## 生命周期

- Draft 可以反复编辑、校验和启动探索性 Eval Run；探索性结果标记为 Draft Run。
- Publish 时生成正式版本号并冻结 Manifest；版本号按目标或目标类型分别递增，例如 `interview-agent@1.1` 和 `interview-eval@1.1`。
- 已发布版本不可原地修改。需要调整时，从它复制出新的 Draft，再发布为新版本。
- 正式回归门禁和人工 A/B 只允许绑定 Published Release；A/B 的两侧必须使用同一个 Evaluation Release 和同一批次输入，只改变 Target Release。
- Eval Run 创建后只读取 `resolved_snapshot`，重试、恢复和重放不重新读取 Draft 或全局默认值。

## 影响

前端“版本与发布”页面只需管理两类版本；Evaluation Release 编辑页用中文配置分组呈现 Benchmark、规则、Judge、Harness 和模拟器。后端 API 和 Manifest 继续使用稳定英文键名。其他目标类型可以通过新增 Target Adapter 和对应 Evaluation Release 配置接入，但 1.0 仅开放已有适配器支持的目标。

该决策收敛并替代此前将评测组件分别公开版本化的设计；既保留历史结果可追溯性，又符合快速迭代项目不应维护一组互相漂移版本号的要求。
