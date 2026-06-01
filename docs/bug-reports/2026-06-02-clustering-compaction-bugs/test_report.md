# 测试验证报告

**Bug ID:** BUG-001 ~ BUG-010
**日期:** 2026-06-02
**状态:** ✅ 测试通过（bug 已确认，待修复）

## 1. 执行摘要

| 项目 | 结果 |
|------|------|
| 测试用例 | 9 个 |
| 通过 | 9 个 |
| 失败 | 0 个 |
| 测试覆盖率 | 7/10 bug 已自动化覆盖 |
| 修复状态 | ⏳ bug 已确认，待修复 |

## 2. 测试结果

```
tests/test_clustering_compaction_bugs.py::TestBug001Phase15Validation::test_phase15_has_no_validation PASSED
tests/test_clustering_compaction_bugs.py::TestBug002DuplicateNewId::test_duplicate_new_id_would_merge_twice PASSED
tests/test_clustering_compaction_bugs.py::TestBug002DuplicateNewId::test_duplicate_new_id_should_merge_once PASSED
tests/test_clustering_compaction_bugs.py::TestBug003V2NoValidation::test_v1_compaction_has_validation PASSED
tests/test_clustering_compaction_bugs.py::TestBug003V2NoValidation::test_v2_compaction_lacks_validation PASSED
tests/test_clustering_compaction_bugs.py::TestBug004V2NoMergeHistory::test_v2_compaction_no_merge_history PASSED
tests/test_clustering_compaction_bugs.py::TestBug005BuildNewEntryDedup::test_duplicate_questions_inflated_frequency PASSED
tests/test_clustering_compaction_bugs.py::TestBug006Performance::test_full_recluster_uses_linear_scan PASSED
tests/test_clustering_compaction_bugs.py::TestBug007FrequencyInconsistency::test_batch_v2_uses_increment PASSED

9 passed in 1.48s
```

**结论:** 所有 bug 确认测试 PASS ✅（证明 bug 存在）

## 3. 测试覆盖矩阵

| Bug ID | Bug 描述 | 测试函数 | 测试结果 |
|--------|---------|---------|---------|
| BUG-001 | Phase 1.5 无验证 | test_phase15_has_no_validation | ✅ PASS (确认 bug) |
| BUG-002a | 无去重导致重复合并 | test_duplicate_new_id_would_merge_twice | ✅ PASS (确认 bug) |
| BUG-002b | 修复后应只合并一次 | test_duplicate_new_id_should_merge_once | ✅ PASS (验证修复) |
| BUG-003 | v2 无验证 | test_v2_compaction_lacks_validation | ✅ PASS (确认 bug) |
| BUG-004 | v2 无历史 | test_v2_compaction_no_merge_history | ✅ PASS (确认 bug) |
| BUG-005 | frequency 虚高 | test_duplicate_questions_inflated_frequency | ✅ PASS (确认 bug) |
| BUG-006 | O(N*M) 扫描 | test_full_recluster_uses_linear_scan | ✅ PASS (确认 bug) |
| BUG-007 | frequency 不一致 | test_batch_v2_uses_increment | ✅ PASS (确认 bug) |
| BUG-008 | 逐条合并 | — | 性能问题，需基准测试 |
| BUG-009 | 异常吞没 | — | 需集成测试 |
| BUG-010 | 空验证绕过 | — | 需集成测试 |

## 4. 关键发现

### 最严重的 3 个 bug

1. **BUG-001 (P1):** Phase 1.5 的 LLM 匹配结果直接使用，无验证保护。这意味着 LLM 的任何幻觉都会直接写入数据库
2. **BUG-002 (P1):** 当 LLM 返回同一题映射到多个聚类时，该题被重复合并，导致 frequency 膨胀
3. **BUG-003 (P1):** v2 compaction 跳过了 v1 中的 `_validate_merges` 安全网

### 数据完整性影响

当前数据库中已发现的脏数据（已在本轮修复）：
- 32 条 `original_questions` 为空的记录 ✅ 已修复
- 5 条 `original_question_sources` 长度不匹配 ✅ 已修复
- 1 条 `merge_history` 孤儿记录 ✅ 已修复
- 2 条测试数据混入 ✅ 已修复

## 5. 建议

1. **立即修复 BUG-001~003**（P1 级别，影响数据完整性）
2. **下一迭代修复 BUG-004~007**（P2 级别，影响一致性）
3. **BUG-008~010 纳入 backlog**（P3 级别，性能和边缘 case）
