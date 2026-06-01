# Bug 详细分析报告

**Bug ID:** BUG-004
**发现日期:** 2026-05-10
**状态:** 已修复

## 问题概述
高频题库中 161/210 条题目（76.7%）的 `original_question_sources` 为空，导致展开来源时只有链接没有原始题目文本。

## 根本原因分析

### BUG-004a: 重建题库清空独立题目的 oqs
- **位置:** `backend/app/routers/master_bank.py:325-326`
- **症状:** 独立题目（未聚类合并）的 `original_question_sources` 被设为 `[]`
- **根因:** 代码对未合并的题目同时清空 `original_questions` 和 `original_question_sources`，但 oqs 的 URL → 题目文本映射即使对独立题目也有价值
- **影响:** 重建后所有独立题目的来源不显示原始文本
- **严重程度:** P2

### BUG-004b: 增量更新新建题目缺失 oqs
- **位置:** `backend/app/db/operations.py:213-216`
- **症状:** INSERT 语句未包含 `original_question_sources` 列，默认 NULL
- **根因:** 遗漏了 oqs 字段
- **影响:** 增量更新产生的新题目永远无法显示来源的原始文本
- **严重程度:** P2

### BUG-004c: 9 条 oqs 中 sources 为空数组
- **症状:** oqs 条目有 question 文本但 sources 为 `[]`
- **根因:** 可能是历史数据迁移问题
- **影响:** 这些条目的来源 URL 无法映射到原始题目文本
- **严重程度:** P3

## 复现步骤
1. 打开高频题库
2. 展开任意题目的来源
3. 观察：只有链接和公司/轮次，没有"该面经中的题目"文本

## 修复方案
1. `master_bank.py`: 保留独立题目的 `original_question_sources`
2. `operations.py`: 新建题目时 INSERT 包含 `original_question_sources`
3. `connection.py init_db()`: 启动时自动回填空 oqs + 修复空 sources 条目
