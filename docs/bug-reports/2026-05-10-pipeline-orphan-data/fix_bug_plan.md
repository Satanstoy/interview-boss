# 修复计划

**日期:** 2026-05-10

## BUG-002: batch_delete_master_bank 添加 stale oqs 清理

**文件:** `backend/app/routers/master_bank.py`
**修改类型:** 新增

在批量删除 QB 题目前，遍历被删除题目的 question + original_questions，清理其他 QB 记录中对这些题目文本的 stale `original_questions` 和 `original_question_sources` 引用。逻辑与单条删除 `delete_master_question` 保持一致。

## BUG-003: should_trigger_clustering 添加超时回退

**文件:** `backend/app/services/pipeline.py`
**修改类型:** 新增

新增 `_recover_stuck_processing()` 函数，在 `should_trigger_clustering()` 判断前自动将超过 30 分钟的 'processing' 队列项回退为 'pending'。防止服务器崩溃后队列永久阻塞。

## 验证方法
运行 `pytest backend/tests/test_pipeline_orphan_data.py -v`

## 回滚方案
revert 两个文件的变更即可。
