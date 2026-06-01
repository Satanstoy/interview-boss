# 修复计划

**Bug ID:** BUG-001, BUG-002
**日期:** 2026-05-10

## 修复步骤

### 步骤 1: 删除 frequency=0 的孤立题目
直接在数据库中删除 23 条 frequency<=0 的题目及其关联的 question_position 记录。

### 步骤 2: 清理 5 条 oqs 中的孤立 URL
从 original_question_sources 中移除已软删除面经的 URL。

### 步骤 3: 添加启动自动修复
**文件:** `backend/app/db/connection.py` init_db() 函数
在现有 frequency 修复之后，新增 original_question_sources 孤立 URL 清理逻辑。

## 验证方法
数据库完整性检查：frequency == len(sources)、无 frequency<=0、oqs URLs 是 sources URLs 的子集。

## 回滚方案
从数据库备份恢复。
