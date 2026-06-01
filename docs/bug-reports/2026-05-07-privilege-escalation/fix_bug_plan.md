# 修复计划

**Bug ID:** BUG-006 ~ BUG-009
**日期:** 2026-05-07
**优先级:** P0

## 修复步骤

### 步骤 1: 修复 generate_master_answer (BUG-006)
**文件:** `backend/app/routers/master_bank.py`
**行号:** 767-799
**修改类型:** 修正

在 `_get()` 查询中加入 `_build_bank_where_clause` 可见性过滤，确保用户只能为其可见范围内的题目生成答案。

### 步骤 2: 修复 batch_generate_answers (BUG-007)
**文件:** `backend/app/routers/master_bank.py`
**行号:** 1017-1101
**修改类型:** 修正

在 `_load()` 查询中加入 `_build_bank_where_clause` 可见性过滤。

### 步骤 3: 修复 evaluate_answer (BUG-008)
**文件:** `backend/app/routers/master_bank.py`
**行号:** 1317-1384
**修改类型:** 修正

在评估前先校验 `question_id` 是否在用户可见范围内。

### 步骤 4: 修复 get_analytics (BUG-009)
**文件:** `backend/app/routers/analytics.py`
**行号:** 46-62
**修改类型:** 修正

对 `jd` 和 `questions_detail` 查询加入 bank_mode 过滤。

## 验证方法
运行 `pytest tests/test_privilege_escalation.py -v` 确认所有测试通过。

## 回滚方案
使用 `git checkout` 恢复修改的文件。
