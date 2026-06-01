# 孤儿数据修复 + 性能优化

**日期：** 2026-05-17
**类型：** Bug 修复 + 性能优化
**状态：** 完成

## 孤儿数据问题

### 问题 1: user_practice_history 无 CASCADE
- **现象：** 删除 question_bank 时，关联的 user_practice_history 记录不会被清理
- **影响：** 4 个删除路径都会产生孤儿记录
- **修复：** migration 019 重建表，添加 `ON DELETE CASCADE`

### 问题 2: _purge_soft_deleted 不清理 analysis_queue
- **现象：** 硬删 interview 前不清理 analysis_queue，导致 FK 违反或孤儿记录
- **修复：** 在 DELETE interview 前先 `DELETE FROM analysis_queue WHERE interview_id = ?`

### 问题 3: _cleanup_old_sources_txn v1 清理不完整
- **现象：** v1 不清理 `original_questions`、`original_question_sources`、`question_position`
- **修复：** v1 委托给 v2

### 问题 4: clear_db 不清理 analysis_queue/auth 表
- **修复：** 补充清理 `analysis_queue`、`login_failures`、`invalidated_families`、`email_verification_codes`

## 性能优化

### LIKE 全表扫描 → 索引查询
- `WHERE sources LIKE '%url%'` 改为 `question_sources WHERE url = ?`（走 idx_qs_url 索引）
- 影响文件：`operations.py`、`data.py`

### 循环内重复查询缓存
- `job_positions` 查询提到循环外（`operations.py`、`pipeline.py`）
- N 次相同查询 → 1 次

### build_api_shapes_batch_filtered 双查询优化
- 从 5-6 次查询重构为 3 次

### 新增复合索引（migration 021）
- `idx_qb_deleted_owner_status`、`idx_qd_question`、`idx_uph_user_date`、`idx_aq_status_created`

## 涉及文件
- `backend/app/db/connection.py` — migration 019 (CASCADE)
- `backend/app/db/operations.py` — 清理逻辑 + 缓存
- `backend/app/routers/data.py` — LIKE → 索引查询
- `backend/app/routers/analytics.py` — clear_db 补充
- `backend/app/services/pipeline.py` — 缓存 + 原子 dequeue
- `backend/app/db/question_bank_sources.py` — 双查询优化
