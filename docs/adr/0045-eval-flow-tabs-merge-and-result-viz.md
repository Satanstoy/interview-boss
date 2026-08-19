# 评测流程 Tab 合并与结果可视化改版

在评测中心 UX 升级中确定：把"版本与发布"（EvaluationReleasesView）与"Benchmark"（EvaluationBenchmarksView）合并为一页（版本与发布内部分段呈现 Benchmark 题集详情），评测流程 Tab 从五步简化为四步；"测评可视化"（Overview）改为质量健康看板；"评测结果"页改为按质量排序的总览表格并接入后端分数聚合。

**背景**：版与 Benchmark 两页都展示"完整评测版本测什么"的题集映射，信息重复；Overview 只有 4 个计数卡信息量少；/runs 不返回 score 导致结果页分数横条为空。

**决策**：
1. **合并**：Releases + Benchmarks → 单页"版本与发布"，Benchmark 题集/Case 契约并入完整评测版本详情折叠区。
2. **流程 Tab 4 步**：版本与发布 → 测评实验 → 评测结果 → 人工 A/B（删独立 Benchmark Tab）。
3. **Overview → 质量健康看板**：各 Agent 通过率排名 + 失败趋势 + 待处理失败 run 清单。
4. **结果页 → 总览表格**：默认质量排序 + 状态/目标筛选 + 分数横条；/runs 扩展返回 score + target_type；/overview 增加 by_target 聚合。
5. **两个独立提交**：先"结果页可视化 + 后端分数聚合"，再"版本/Benchmark 合并 + Overview 改版"。
