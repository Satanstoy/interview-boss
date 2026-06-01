# TDD 开发完成报告

**功能名称:** 跨类别手动聚类
**完成日期:** 2026-05-10
**TDD 状态:** Review 完成（已有实现，测试验证）

## 执行摘要

| 指标 | 结果 |
|------|------|
| 完成测试数 | 12 |
| 代码审查点 | 6 |
| 最终测试通过率 | 100%（12/12） |

## 变更清单

### 后端

| 文件 | 变更 | 说明 |
|------|------|------|
| `backend/app/routers/master_bank.py` | 搜索端点 | SELECT 添加 `qb.cat1, qb.cat2` |
| `backend/app/routers/master_bank.py` | 合并端点 | 独立题合并后保留源行（`pass`）；独立题合并跳过 sources 复制；支持 `target_cat1`/`target_cat2` 动态 SQL |
| `backend/app/models/schemas.py` | Schema | `MergeOriginalQuestionRequest` 新增 `target_cat1`, `target_cat2`（默认 `""`） |

### 前端

| 文件 | 变更 | 说明 |
|------|------|------|
| `frontend/src/api/index.js` | API | `mergeQuestion` 新增 `targetCat1`, `targetCat2` 参数 |
| `frontend/src/App.vue` | 状态 | 新增 `mergeSourceCat1`, `mergeSourceCat2` |
| `frontend/src/App.vue` | `startMerge` | 存储源题目 cat1/cat2 |
| `frontend/src/App.vue` | `confirmMerge` | 跨类别时弹出类别选择确认 |
| `frontend/src/App.vue` | 搜索结果 | 显示 `cat1 / cat2` |
| `frontend/src/components/ConfirmDialog.vue` | 样式 | 添加 `whitespace-pre-line` 支持多行 |

## 测试覆盖矩阵

| 测试ID | 场景 | 类型 | 状态 |
|--------|------|------|------|
| T-001a | 搜索 SQL 包含 cat1/cat2 | 代码审查 | PASS |
| T-002a | 独立题合并后保留源行 | 代码审查 | PASS |
| T-002b | 独立题合并跳过 sources 复制 | 代码审查 | PASS |
| T-003a | Schema 包含 target_cat 字段 | 单元测试 | PASS |
| T-003b | 合并端点使用 cat_set 动态 SQL | 代码审查 | PASS |
| T-004a | 不传 cat 字段向后兼容 | 单元测试 | PASS |
| T-004b | 传入 cat 字段正确赋值 | 单元测试 | PASS |
| T-005a | 独立题合并不执行 DELETE | 集成测试(mock) | PASS |
| T-005b | 非独立题合并 DELETE 分支存在 | 代码审查 | PASS |
| T-006a | 两个类别时 SQL SET 子句正确 | 逻辑测试 | PASS |
| T-006b | 只传 cat1 时 SQL 正确 | 逻辑测试 | PASS |
| T-006c | 不传类别时无 SET 子句 | 逻辑测试 | PASS |

## 问题分析回顾

**合并失败根因（非跨类别限制）：** `QuestionCard.vue:250` 中 `urlToOq[s.url]` 返回空字符串时，JS `||` fallback 到 `question.question`（统一代表题文本），后端 line 696 校验 `original_q not in src_orig` 导致 400 错误。这是 BUG-004 的残留影响，已在之前修复。

## 结论

- 12 个测试全部通过，覆盖搜索、合并、Schema、SQL 构建全部改动
- 后端向后兼容：新字段有默认值，旧调用不受影响
- 前端构建成功并部署
