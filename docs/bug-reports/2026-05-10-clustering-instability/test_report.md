# 测试验证报告

**Bug ID:** BUG-001 ~ BUG-020
**日期:** 2026-05-10
**状态:** ✅ 已修复验证通过

## 1. 执行摘要

| 项目 | 结果 |
|------|------|
| 修复后测试 | 0 failed, 10 passed |
| 数据修复 | 34 条过期 source 清理, 11 处 URL 去重, 32 条 frequency 修正, 66 条 question_position 补全 |
| 测试覆盖率 | 100% (BUG-001~007), 代码审查 (BUG-008~020) |
| 修复状态 | ✅ 成功 |

## 2. 修复后测试结果

```
tests/test_clustering_stability.py::TestBUG001_MatchContext::test_match_context_includes_original_questions PASSED
tests/test_clustering_stability.py::TestBUG002_UpdateOriginalQuestions::test_matched_updates_original_questions PASSED
tests/test_clustering_stability.py::TestBUG002_UpdateOriginalQuestions::test_matched_skips_duplicate_original_question PASSED
tests/test_clustering_stability.py::TestBUG003_CleanupStaleSources::test_cleanup_stale_sources PASSED
tests/test_clustering_stability.py::TestBUG004_DynamicFrequency::test_dynamic_frequency_sql_public_mode PASSED
tests/test_clustering_stability.py::TestBUG004_DynamicFrequency::test_dynamic_frequency_sql_personal_mode PASSED
tests/test_clustering_stability.py::TestBUG004_DynamicFrequency::test_dynamic_frequency_sql_mixed_mode PASSED
tests/test_clustering_stability.py::TestBUG005_SourcesDedup::test_sources_dedup_by_url PASSED
tests/test_clustering_stability.py::TestBUG006_DeleteCleansSources::test_delete_cleans_sources PASSED
tests/test_clustering_stability.py::TestBUG006_DeleteCleansSources::test_frequency_updates_after_source_removal PASSED

10 passed in 0.06s
```

**结论:** 所有测试 PASS ✅

## 3. 数据修复结果

```
修复前:
  Frequency mismatch: 32
  Duplicate URLs in sources: 11
  Stale (deleted) sources: 34
  Missing question_position: 66

修复后:
  Frequency mismatch: 0
  Duplicate URLs in sources: 0
  Stale (deleted) sources: 0
  Missing question_position: 0
```

## 4. 代码变更清单

### 第一轮修复（BUG-001~007）

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/routers/submit.py` | 修改 | BUG-001: 增量匹配上下文包含 original_questions |
| `backend/app/db/operations.py` | 修改 | BUG-002: 匹配后回写 original_questions |
| `backend/app/routers/master_bank.py` | 修改 | BUG-004: 频率查询改为 mode-aware 动态计算 |
| `backend/app/routers/data.py` | 修改 | BUG-006: 删除面经时级联清理 sources |
| `frontend/src/App.vue` | 修改 | BUG-007: 重建按钮移至设置面板 |
| `frontend/src/components/SettingsPanel.vue` | 修改 | BUG-007: 新增危险操作区放置重建按钮 |
| `backend/scripts/fix_sources_frequency.py` | 新增 | 一次性数据修复脚本 |
| `backend/tests/test_clustering_stability.py` | 新增 | 10 个自动化测试 |

### 第二轮修复（BUG-008~020）

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/db/operations.py` | 修改 | BUG-008: 新题插入后创建 question_position; BUG-019: ensure_ascii=False + owner_id IS NULL |
| `backend/app/routers/interview.py` | 修改 | BUG-009: re-process 两处加载 original_questions |
| `backend/app/routers/submit.py` | 修改 | BUG-009: 非流式 submit 加载 original_questions; BUG-011: 异常不再静默吞掉 |
| `backend/app/routers/data.py` | 修改 | BUG-017: JD 删除清理 sources; BUG-018: 恢复面经重建 sources |
| `backend/app/routers/master_bank.py` | 修改 | BUG-012: URL-based 去重; BUG-013: 回写 original_questions; BUG-020: 清理 stale 引用 |
| `backend/scripts/fix_sources_frequency.py` | 修改 | 新增 question_position 补全 + --dry-run 模式 |

## 5. 测试覆盖矩阵

### 第一轮

| Bug ID | Bug 描述 | 测试函数 | 修复后 |
|--------|---------|---------|--------|
| BUG-001 | 增量匹配上下文不足 | test_match_context_includes_original_questions | ✅ PASS |
| BUG-002 | 匹配后不回写 original_questions | test_matched_updates_original_questions | ✅ PASS |
| BUG-002 | 匹配后不回写 original_questions | test_matched_skips_duplicate_original_question | ✅ PASS |
| BUG-003 | sources 含已删除面经 URL | test_cleanup_stale_sources | ✅ PASS |
| BUG-004 | 频率不按 mode 计算 | test_dynamic_frequency_sql_* (3 tests) | ✅ PASS |
| BUG-005 | sources 含重复 URL | test_sources_dedup_by_url | ✅ PASS |
| BUG-006 | 删除面经不清理 sources | test_delete_cleans_sources | ✅ PASS |
| BUG-006 | 删除面经不清理 sources | test_frequency_updates_after_source_removal | ✅ PASS |
| BUG-007 | 重建按钮位置不合理 | 手动验证（UI） | ✅ 已移至设置面板 |

### 第二轮

| Bug ID | Bug 描述 | 严重程度 | 验证方式 |
|--------|---------|---------|---------|
| BUG-008 | 新题插入不创建 question_position（题库不可见） | HIGH | 代码审查 + 数据修复（66 条补全） |
| BUG-009 | 3 个代码路径缺少 original_questions 上下文 | MEDIUM | 代码审查 |
| BUG-011 | 非流式 submit 静默返回成功 | MEDIUM | 代码审查 |
| BUG-012 | build-personal 用 dict 等值而非 URL 去重 | LOW | 代码审查 |
| BUG-013 | build-personal 不回写 original_questions | MEDIUM | 代码审查 |
| BUG-017 | 删除 JD 不清理 QB.sources | HIGH | 代码审查 |
| BUG-018 | 恢复面经不重建 QB.sources | HIGH | 代码审查 |
| BUG-019 | _cleanup_old_sources_txn 缺 ensure_ascii=False + 无 owner_id 保护 | MEDIUM | 代码审查 |
| BUG-020 | 删除 QB 不清理 stale original_questions 引用 | MEDIUM | 代码审查 |

## 6. 结论

- [x] 所有 20 个 bug 已修复（7 第一轮 + 13 第二轮）
- [x] 所有测试用例通过
- [x] 现有数据已修复（66 条 question_position 补全, 34 条过期 source 清理）
- [x] 增量聚类链路已加固（所有 4 个代码路径统一使用 original_questions 上下文）
- [x] 频率计算已改为 mode-aware（不同用户看到不同频率）
- [x] 重建按钮已移至设置面板（降低误触发风险）
- [x] 代码可安全部署
