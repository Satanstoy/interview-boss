# Bug 详细分析报告

**日期:** 2026-05-27
**状态:** 已修复

## BUG-004: 第三次提示过于直白

- **位置:** `backend/app/core/prompts.py` CODING_HINT_PROMPT
- **症状:** 第 3 次提示直接给出伪代码，不像真实面试
- **根因:** prompt 中第 3 次提示描述为"直接揭示"，LLM 理解为可以直接给代码
- **修复:** 重新定义三层提示逻辑，严禁给出代码/伪代码，保持面试官口吻

## BUG-005: hint 无次数限制

- **位置:** `frontend/src/components/business/CodingPractice.vue`
- **症状:** 可以无限次请求提示
- **根因:** 没有前端次数限制逻辑
- **修复:** 前端追踪 hintCount，3 次后禁用按钮 + 显示引导提示

## 需求: 清空记录 + 功能说明

- 添加"清空本题记录"按钮，重置所有状态
- 按钮 hover 显示功能说明 tooltip
