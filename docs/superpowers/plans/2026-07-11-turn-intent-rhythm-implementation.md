# TurnIntent 节奏引擎实施计划

> 对应设计：[2026-07-11-interview-turn-intent-rhythm-design.md](../specs/2026-07-11-interview-turn-intent-rhythm-design.md)

## 目标

将节奏决策从 ReAct prompt 中收回，新增每轮必跑的策略引擎和 `TurnIntent`，使 `interview-rhythm`、`rhythm_profile` 与聚焦 skill 共同约束最终 writer。

## 步骤

1. 新增 `turn_intent.py`：定义 `TurnIntent`、策略枚举和纯函数策略引擎；以 RED 测试证明新会话没有 active skill 也会应用节奏 policy。
2. 将现有 rhythm profile、ledger、semantic classifier 和 active tactic skill 映射为策略引擎输入；聚焦 skill 只提供深挖层，不再由 ReAct 决定是否激活。
3. 在 pipeline 中先计算并保存 intent；ReAct 只接收 intent 的工具需求，最终 writer 接收 intent 的 writer brief。
4. 将 executed intent 写入 done metadata 和 SSE；补 contract、ReAct、API 级测试。
5. 为未回答/反问保留 assessment evidence，供收尾总结区分 `not_assessed` 与负面证据。
6. 运行 Docker chat suite、compileall、diff check，并使用 sj 账户完成真实 API 验收。

## 验收

- 没有 `active_skills`、没有 `load_skill` 时，策略引擎仍可在深挖超限且理论缺失时切题。
- 当前项目仍缺取舍证据时，策略引擎保持项目深挖，不切算法。
- writer 的最终问题可从 `turn_intent` 解释其策略、评估目标与证据锚点。
- done metadata 暴露实际 `turn_intent`。
