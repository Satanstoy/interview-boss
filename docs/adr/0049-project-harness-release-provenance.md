# ADR-0049：项目级 Harness Release 与评测运行快照

- 状态：已接受
- 日期：2026-08-20
- 相关决策：0043、0044、0047

## 背景

评测 Manifest 里原本同时描述了评测集、评分协议、模拟器和 Harness。这样会让 Harness 版本看起来像 Eval 私有字段：线上运行、Smoke、批量实验和前端展示无法共享同一个版本来源，A/B 也容易把“评测集变化”误认为“被测 Harness 变化”。

## 决策

1. 项目级 `Harness Registry` 是 Harness 版本的权威来源。每个 `target_type` 有稳定的 `harness_key`，每个版本只登记一次。
2. 一个 Harness Release 的完整身份由以下字段共同组成：
   - 管理员可读的 `harness_key@version`；
   - `source_ref` 和 `git_sha`，说明代码来源；
   - `image_digest`，说明实际运行镜像；
   - `config_digest`，说明运行配置；
   - `manifest_digest`，说明上述元数据和 Harness 配置的整体摘要。
3. `PROJECT_HARNESS_VERSION` 是项目当前默认 Harness 版本。普通评测默认绑定这个版本；不能按数据库最新 ID 猜测当前版本。
4. 创建评测 Run 时，可以显式选择某个已发布 Harness Release。选择结果写入 `eval_runs.harness_release_id`，并冻结到 `snapshot_json.harness_release`。之后 Eval Manifest 里的 `simulator_harness` 只表示评测执行器配置，不再作为项目 Harness 版本的权威来源。
5. Harness A/B 的比较规则是：
   - 允许 Harness Release A 与 B 不同；
   - Target、Evaluation Release、Case 快照、评测协议、候选模拟人、随机种子和环境必须相同；
   - A/B 人工复核必须确认两条 Run 的 Harness 身份确实不同。
6. 前端默认展示项目 Harness 版本；历史 Run 如果没有可信的项目 Harness 快照，展示“历史数据未记录”，不从 Eval Manifest 猜版本。
7. 新模拟面试 Harness 的发布身份确定为 `interview-harness@2.0`。它对应本次 redesign 的四层状态模型、可恢复 TurnRun 事件流、SSE 订阅和双层运行轨迹 UI；正式 Eval Run 必须冻结该 Release 的 Git SHA、镜像摘要、配置摘要和 Manifest digest。

## 版本变更流程

代码、依赖、镜像或关键配置发生会影响 Harness 行为的变化时：

1. 更新 `PROJECT_HARNESS_VERSION`；
2. 发布新的 Git SHA、镜像摘要和配置摘要；
3. 注册并发布新的 Harness Release；
4. 用新的默认版本执行普通评测，或在 A/B 中显式选择新旧两个版本；
5. 每条 Run 只读取自己的冻结快照，不回溯当前 Registry。

## 取舍

历史 Run 不会被强行补写当前 Harness 版本。无法证明来源的历史数据保留为空，这会降低旧数据的展示完整度，但避免把错误版本当成事实。
