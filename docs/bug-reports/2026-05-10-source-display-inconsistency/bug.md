# Bug 详细分析报告

**Bug ID:** BUG-001
**发现日期:** 2026-05-10
**状态:** 已确认

## 问题概述
QuestionCard.vue 中来源详情有两种显示模式，用户要求统一为每条来源独立一行卡片，并提供"独立"和"合并到"操作按钮。

## 根本原因分析

### BUG-001: 来源显示布局不一致
- **位置:** `frontend/src/components/QuestionCard.vue:170-185`
- **症状:** 无 `original_questions` 的题目（单题多来源）来源以扁平标签横向排列，只提供"合并到"按钮
- **根因:** 模板使用两个 `v-if`/`v-else-if` 分支，分支 2（Single-question sources）使用了 `flex flex-wrap` 标签布局，与分支 1（Multi-question cluster）的卡片布局不一致
- **影响:** 39 个无 `original_questions` 但 `frequency > 1` 的题库条目显示不一致，管理员无法对单条来源执行"独立"操作
- **严重程度:** P2

## 复现步骤
1. 打开高频题库
2. 找到一个无 `original_questions` 但有多个 sources 的题目（如 "幻觉怎么应对" freq=3）
3. 展开"来源详情"
4. **预期：** 每个来源独占一行卡片，带"独立"和"合并到"按钮
5. **实际：** 来源以横向标签排列，仅有一个"合并到"按钮

## 修复建议
将 Single-question sources 分支的布局改为与 Multi-question cluster 一致的卡片布局，每条来源独立一行，添加"独立"按钮。
