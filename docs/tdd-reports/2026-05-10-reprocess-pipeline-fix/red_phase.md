# 红灯阶段报告

**测试编号:** T-001 ~ T-004
**测试描述:** 修复 cluster_batch 中清理顺序：先清理旧 QB 再聚类
**编写时间:** 2026-05-10

## 核心问题

`cluster_batch` 中 `_cleanup_old_sources_txn_v2` 在 `_atomic_write` 内执行（聚类之后），
导致旧 QB 条目参与聚类决策。修复方案：在加载 existing_rows 之前先清理。

## 测试策略

通过 mock `cluster_all_questions` 捕获其接收的 `all_items` 参数，验证其中不包含被清理的旧条目。
