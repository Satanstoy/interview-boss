# Bug 详细分析报告

**Bug ID:** BUG-003
**发现日期:** 2026-05-10
**状态:** 已确认（代码已有修复）

## 问题概述

用户反馈：在面经库删除一个面经后，高频题库中题目的来源信息未同步更新。具体案例：包含"简单介绍agent"的腾讯面经（xiaohongshu post `69ccc37a`），出现了两次（不同 xsec_token 的两条面经记录），删除后题库来源仍显示。

## 根本原因分析

### BUG-003: 面经删除后 question_bank sources 一致性
- **位置:** `backend/app/routers/data.py:139-195` (delete_data 端点)
- **症状:** 删除面经后 question_bank.sources 仍保留已删除面经的 URL
- **根因:** 代码已在 `data.py:177-182` 中添加 `_cleanup_sources_for_url()` 调用。事务一致性已保证：
  - 删除事务包含：级联软删除 questions_detail + 清理 question_bank.sources + 软删除面经 + commit
  - GET 端点通过 `filter_original_question_sources_by_mode` 自动过滤指向已删除面经的 oqs 条目
- **实际原因推测:**
  1. 同一面经被上传两次（ID 11 和 108，同一帖子不同 xsec_token），删除一条后另一条仍存在
  2. 服务运行的代码版本早于修复部署时间（服务 01:48 启动，代码 01:58 修改）
- **严重程度:** P2

## 数据验证

| 检查项 | 当前状态 |
|--------|---------|
| Interview 11 (69ccc37a, token A) | 未删除 |
| Interview 108 (69ccc37a, token B) | 未删除 |
| Question 2370 "简单介绍一下agent" | frequency=2, sources 含两个 URL |
| 删除端点是否调用 cleanup | 是（line 182） |
| GET 端点是否过滤已删除 oqs | 是（filter_original_question_sources_by_mode） |

## 代码路径验证

| 操作 | sources 清理 | oqs 过滤 | 事务一致性 |
|------|-------------|---------|-----------|
| 单条面经删除 | _cleanup_sources_for_url | GET 自动过滤 | 同一事务 |
| 批量面经删除 | _cleanup_sources_for_url | GET 自动过滤 | 同一事务 |
| JD 删除 | 级联清理关联面经 | GET 自动过滤 | 同一事务 |
| 恢复面经 | _restore_sources_for_url | 从 oqs 重建 | 同一事务 |

## 修复建议

代码已有修复。需确保：
1. 服务加载最新代码（重启服务）
2. 清理数据库中重复的面经记录（同一帖子不同 xsec_token）
