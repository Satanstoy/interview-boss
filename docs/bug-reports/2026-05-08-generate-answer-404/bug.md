# Bug 详细分析报告

**Bug ID:** BUG-010
**发现日期:** 2026-05-08
**状态:** 已确认

## 问题概述
管理员在高频题库中点击"AI生成答案"按钮时，系统返回错误"生成失败: 请求的资源不存在"。该问题的根本原因是 `generate_master_answer` 端点使用了过度严格的查询条件，导致无法找到题目。

## 根本原因分析

### BUG-010: generate_master_answer 使用过度严格的查询条件
- **位置:** `backend/app/routers/master_bank.py:781-788`
- **症状:** 点击"AI生成答案"返回404错误
- **根因:** 使用 `_build_bank_where_clause` 进行点查询，该函数会 JOIN `question_position` 表。如果题目没有在 `question_position` 表中注册，查询返回空结果。
- **影响:** AI生成功能完全不可用
- **严重程度:** P1

## 复现步骤
1. 以管理员身份登录系统
2. 进入高频题库页面
3. 点击任意题目的"AI生成答案"按钮
4. 观察错误提示"生成失败: 请求的资源不存在"

**预期行为:** 应该成功生成AI答案
**实际行为:** 返回404错误

## 修复建议
修改 `generate_master_answer` 端点，不使用 `_build_bank_where_clause` 进行点查询。改为直接根据题目ID查询，并检查用户是否有权限访问该题目。

受影响的端点:
1. `generate_master_answer` (line 779)
2. `batch_generate_answers` (line 1038)
3. `get_random_questions` (line 1219)
4. `evaluate_answer` (line 1340)
