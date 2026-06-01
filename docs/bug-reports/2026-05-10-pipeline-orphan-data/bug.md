# Bug 详细分析报告

**日期:** 2026-05-10
**状态:** 已修复

## BUG-002: batch_delete_master_bank 未清理 stale oqs 引用

- **位置:** `backend/app/routers/master_bank.py:956-967`
- **症状:** 批量删除 QB 题目后，其他 QB 记录的 `original_questions` 和 `original_question_sources` 中残留已删除题目的引用
- **根因:** 批量删除逻辑只做了级联清理（user_question_view、question_position、user_practice_history），完全没有清理其他 QB 记录中的 stale 引用。单条删除（`delete_master_question`）有此清理逻辑，但批量删除遗漏了。
- **影响:** 孤儿 oqs/oqs_sources 条目占用空间，干扰 LLM 聚类决策（聚类时读取 oqs 作为上下文）
- **严重程度:** P1

## BUG-003: 聚类队列 'processing' 状态无超时恢复

- **位置:** `backend/app/services/pipeline.py:60-71`
- **症状:** 如果 `cluster_batch` 执行过程中服务器崩溃，队列项永久卡在 'processing' 状态，`should_trigger_clustering()` 不会触发新的聚类
- **根因:** `should_trigger_clustering()` 只检查 pending 数量和 processing 数量，没有超时回退机制
- **影响:** 聚类流水线永久阻塞，需要手动干预数据库
- **严重程度:** P2

## 复现步骤

### BUG-002
1. 有两道 QB 题目 A 和 B，都来自同一面经的原始题目
2. 批量删除题目 A
3. 查看题目 B 的 `original_question_sources`——仍包含题目 A 的来源信息

### BUG-003
1. 提交面经触发聚类
2. 在 `cluster_batch` 执行过程中强制终止服务器
3. 重启服务器后，队列项仍在 'processing' 状态
4. 新面经入队后，`should_trigger_clustering()` 返回 False（因为 processing > 0）
