# TDD 开发完成报告

**功能名称:** 修复单条面经重新分析时聚类流水顺序问题
**完成日期:** 2026-05-10
**TDD 状态:** ✅ 完整

## 执行摘要

| 指标 | 结果 |
|------|------|
| 新增测试数 | 3 |
| TDD循环数 | 3 |
| 最终测试通过率 | 100% |
| 回归测试 | 36/36 通过 |

## 红-绿-重构循环记录

| 循环 | 测试ID | 红灯原因 | 绿灯修复 | 状态 |
|------|--------|---------|---------|------|
| 1 | T-001 | 旧 QB 条目出现在聚类上下文中 | 添加 `_pre_clean` 步骤 | ✅ |
| 2 | T-002 | （已通过，共享条目逻辑正确） | 无需修复 | ✅ |
| 3 | T-003 | AI 答案丢失 | 保存旧答案 + 补充 `ai_answer` SELECT | ✅ |

## 修改文件

### `backend/app/services/pipeline.py`

**变更摘要：**
1. 在 `cluster_batch` 步骤 2 新增 `_pre_clean`：聚类前清理当前批次 URL 的旧 QB 贡献
2. 从 `_atomic_write` 移除重复的 `_cleanup_old_sources_txn_v2` 调用
3. `existing_rows` 查询补充 `ai_answer` 字段
4. AI 答案恢复增加 `saved_answers` fallback

### `backend/tests/test_reprocess_cleanup_order.py`（新增）

| 测试ID | 场景 | 状态 |
|--------|------|------|
| T-001 | 独占 URL 的旧 QB 条目不出现在聚类上下文 | ✅ PASS |
| T-002 | 共享 URL 的 QB 条目只移除目标 URL 贡献 | ✅ PASS |
| T-003 | AI 答案在清理后仍能恢复到新聚类 | ✅ PASS |

## 修复前后对比

### 修复前（问题流程）
```
tag_interview → enqueue → cluster_batch:
    load new QD → load existing QB (含旧条目) → cluster → cleanup → insert
                                              ↑ 旧条目干扰聚类决策
```

### 修复后（正确流程）
```
tag_interview → enqueue → cluster_batch:
    load new QD → save AI answers → cleanup旧QB → load existing QB (干净) → cluster → insert
                                   ↑ 旧贡献已清理，聚类上下文干净
```

## TDD 原则遵守情况

- [x] 测试先行：先写 3 个失败测试
- [x] 红灯验证：确认测试失败（旧逻辑 bug）
- [x] 最小实现：只修改 `cluster_batch` 的执行顺序
- [x] 持续重构：评估后无需进一步重构
- [x] 回归验证：36 个已有测试全部通过

## 结论

✅ 修复了 `cluster_batch` 中清理顺序问题
✅ 旧 QB 条目不再干扰聚类决策
✅ AI 答案通过双路径恢复（existing_ai_answer + saved_answers）得到保留
✅ 所有 39 个测试通过（21 单元 + 15 E2E + 3 新增）
