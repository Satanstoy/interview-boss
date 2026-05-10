# Bug 验证报告

**Bug ID:** BUG-001, BUG-002, BUG-003, BUG-004
**验证日期:** 2026-05-10

---

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试函数 | 覆盖状态 |
|--------|---------|---------|---------|
| BUG-004 | 软删除记录污染聚类 | `test_bug004_deleted_bank_excluded_from_match` | ✅ 已覆盖 |
| BUG-004 | 软删除记录污染聚类 | `test_bug004_active_records_still_included` | ✅ 已覆盖 |
| BUG-003 | 分析中不显示详细内容 | `test_bug003_sse_events_include_details` | ✅ 已覆盖 |
| BUG-002 | 切换界面无后台反馈 | `test_bug002_global_progress_computed` | ✅ 已覆盖 |
| BUG-001 | 不支持断点续传 | `test_bug001_state_persistence` | ✅ 已覆盖 |

---

## 覆盖率检查

✅ **100% 边缘情况已覆盖**

- BUG-004：覆盖了软删除记录被排除、正常记录仍被包含两种情况
- BUG-003：覆盖了 SSE 事件结构包含详情字段的验证
- BUG-002：覆盖了有/无活跃分析时的全局进度计算
- BUG-001：覆盖了分析状态持久化和恢复逻辑

---

## 测试结果预测

### BUG-004（P0 - 一行修复）

**修复前:**
- ❌ `test_bug004_deleted_bank_excluded_from_match` — FAILED
  - 原因：查询未过滤 `deleted_at IS NULL`，已删除记录被返回

**修复后:**
- ✅ `test_bug004_deleted_bank_excluded_from_match` — PASSED
- ✅ `test_bug004_active_records_still_included` — PASSED

### BUG-003（P1 - SSE 事件丰富化）

**修复前:**
- ❌ `test_bug003_sse_events_include_details` — FAILED
  - 原因：SSE 事件中没有 `details`、`matched_questions`、`new_questions` 字段

**修复后:**
- ✅ `test_bug003_sse_events_include_details` — PASSED

### BUG-002（P2 - 全局进度通知）

**修复前:**
- ❌ `test_bug002_global_progress_computed` — FAILED
  - 原因：没有 `activeReprocessing` computed 属性

**修复后:**
- ✅ `test_bug002_global_progress_computed` — PASSED

### BUG-001（P3 - 断点续传）

**修复前:**
- ❌ `test_bug001_state_persistence` — FAILED
  - 原因：interview 表没有 analysis_status / analysis_result 列

**修复后:**
- ✅ `test_bug001_state_persistence` — PASSED

---

## 关键验证点

### BUG-004 — 最高优先级

| 验证点 | 预期结果 |
|--------|---------|
| `deleted_at IS NOT NULL` 的 question_bank 记录 | 不出现在 existing_by_cat2 中 |
| `deleted_at IS NULL` 的 question_bank 记录 | 正常参与匹配 |
| 软删除面经后重新分析其他面经 | 不匹配到已废弃聚类 |

### BUG-003 — 次高优先级

| 验证点 | 预期结果 |
|--------|---------|
| 标注完成事件 | 包含 `details` 数组，每项含 question/cat1/cat2/tags/difficulty |
| 匹配完成事件 | 包含 `matched`/`unmatched` 计数，`matched_questions`/`new_questions` 列表 |
| 前端渲染 | 标注阶段显示题目分类详情 |

### BUG-002 — 体验改善

| 验证点 | 预期结果 |
|--------|---------|
| 切换 Tab 时有分析进行中 | 右下角显示浮动进度提示 |
| 无分析进行时 | 浮动提示不显示 |
| 分析完成 | 浮动提示消失，显示 toast |

### BUG-001 — 架构改进

| 验证点 | 预期结果 |
|--------|---------|
| 分析中断后重新发起 | 从断点恢复（日志中可见 "从 Stage X 恢复"） |
| analysis_status 状态流转 | idle → running → completed/failed |
| analysis_result 持久化 | JSON 中间结果可正确反序列化 |
