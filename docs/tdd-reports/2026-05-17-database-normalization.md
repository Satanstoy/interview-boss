# 数据库结构规范化

**日期：** 2026-05-17
**类型：** TDD / 架构重构
**状态：** 完成

## 问题描述

`question_bank` 表有 3 个 JSON TEXT 列（`sources`、`original_questions`、`original_question_sources`），被 14+ 个写路径和 8 个读路径使用。每次查询频率都要跑 `json_each()` 子查询，清理/合并操作需要 JSON 解析-修改-序列化循环。

## 解决方案

### Phase 1: 重构 init_db()
- 将 863 行 `init_db()` 拆分为 18 个版本化迁移函数
- 新增 `schema_version` 表跟踪已执行的迁移
- 幂等性保证：已执行的迁移自动跳过

### Phase 2: 创建规范化表
- `question_sources` — 替代 `sources` JSON 列（339 行）
- `question_original_items` — 替代 `original_questions` JSON 列（384 行）
- `question_original_item_sources` — 替代嵌套 sources（384 行）
- 数据回填完成，一致性验证通过（0 不一致）

### Phase 3: helper 模块
- 新建 `backend/app/db/question_bank_sources.py`
- 提供读写 helper：`insert_source`、`delete_source`、`get_sources_filtered`、`build_api_shapes_batch` 等

### Phase 4: 双写（所有写路径）
- 14 个写路径全部更新，同时写入 JSON 列和规范化表
- JSON 列为源 of truth，规范化表为辅助

### Phase 5: 切换读路径
- `get_dynamic_frequency_sql()` 从 `json_each()` 改为 `question_sources` JOIN
- `get_master_bank()` 用 `build_api_shapes_batch_filtered()` 替代 JSON 解析
- 移除 `filter_sources_by_mode()`、`filter_original_question_sources_by_mode()`（保留但标注 deprecated）

## 新增索引（migration 021）
- `idx_qb_deleted_owner_status` — `question_bank(deleted_at, owner_id, status)`
- `idx_qd_question` — `questions_detail(question)`
- `idx_uph_user_date` — `user_practice_history(user_id, created_at)`
- `idx_aq_status_created` — `analysis_queue(status, created_at)`

## 涉及文件
- `backend/app/db/connection.py` — 迁移函数、频率 SQL、filter 函数
- `backend/app/db/question_bank_sources.py` — **新增** helper 模块
- `backend/app/db/operations.py` — 4 个写路径更新
- `backend/app/services/pipeline.py` — 3 个写路径更新
- `backend/app/routers/master_bank.py` — 6 写 + 2 读路径更新
- `backend/app/routers/data.py` — 2 个写路径更新

## 测试结果
- 355 passed, 61 failed（全部为预存在失败，零新增回归）
- 前端构建通过
