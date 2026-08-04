# Bug 详细分析报告

**Bug ID:** BUG-001
**发现日期:** 2026-07-12
**状态:** 已确认

## 问题概述
E2E 测试运行后，数据库中留下大量未清理的对话记录。每次测试运行会创建 3-5 个标题为"新对话"的记录，这些记录没有被自动清理。

## 根本原因分析

### BUG-001: Playwright E2E 测试 chat API mock 不完整
- **位置:** `frontend/tests/e2e/chat-thinking-timer.spec.js:50-153`
- **症状:** 测试只 mock 了特定的 chat API 路径，没有 mock 创建对话的 API
- **根因:** mock 的 glob pattern `**/api/chat/conversations?status=active` 只匹配带查询参数的 GET 请求，不匹配 POST 创建对话的请求
- **影响:** 如果测试过程中触发创建对话的操作，请求会发送到真实后端
- **严重程度:** P2

### BUG-002: 真实 E2E 脚本清理逻辑不够健壮
- **位置:**
  - `backend/scripts/verify_interview_agent_real_e2e.py:486-492`
  - `backend/scripts/verify_chat_tools_real_e2e.py:364-370`
  - `backend/scripts/eval_framework/runner.py:142-149`
- **症状:** 清理失败时只打印警告或忽略异常，不抛出异常
- **根因:** `_delete_conversation()` 函数捕获所有异常并忽略，导致删除失败时无感知
- **影响:** 如果网络错误或权限问题导致删除失败，对话会残留
- **严重程度:** P2

### BUG-003: 前端 ChatView preview 模式不完整
- **位置:** `frontend/src/components/business/ChatView.vue:718-826`
- **症状:** `handleSend()` 和 `handleCreateConversation()` 没有检查 preview 模式
- **根因:** 只有 `loadConversations()` 检查了 preview 模式，其他 API 调用没有检查
- **影响:** 在 preview 模式下仍会调用真实 API
- **严重程度:** P2

## 复现步骤
1. 运行 Playwright E2E 测试：`cd frontend && npx playwright test`
2. 检查数据库：`SELECT COUNT(*) FROM chat_conversations WHERE title='新对话' AND user_id=1`
3. 观察数量增加

## 修复建议
1. 完善 Playwright E2E 测试的 chat API mock，使用通配符 `**/api/chat**` 匹配所有请求
2. 增强 E2E 脚本的清理逻辑，清理失败时抛出异常或重试
3. 在 ChatView 的所有 API 调用中检查 preview 模式
