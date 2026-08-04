# Bug 预览报告

**日期:** 2026-07-12
**问题:** E2E 测试运行后，数据库中留下大量未清理的对话记录
**严重程度:** Medium

## 初步诊断

### 问题现象
每次运行 E2E 测试后，数据库 `chat_conversations` 表中会新增大量标题为 "新对话" 的记录（user_id=1，mode=free_practice）。这些对话没有被清理，导致数据库持续膨胀。

**数据证据：**
- user_id=1 累计 202 个 free_practice 对话
- 2026-07-11 当天新增 54 个标题为 "新对话" 的对话
- 对话创建时间呈批量模式：19:57:38-19:57:39（3个）、20:00:15-20:00:16（3个）、20:00:59-20:01:00（3个）

### 根本原因
有多个层面的问题导致对话未被清理：

**1. Playwright E2E 测试 mock 不完整**
- `chat-thinking-timer.spec.js` 只 mock 了特定路径：
  - `**/api/chat/conversations?status=active` (GET)
  - `**/api/chat/conversations/conv-1/messages` (GET/POST)
- 没有 mock `**/api/chat/conversations` (POST 创建对话)
- 如果测试过程中触发创建对话的操作，请求会发送到真实后端

**2. 真实 E2E 脚本清理逻辑不够健壮**
- `verify_interview_agent_real_e2e.py`、`verify_chat_tools_real_e2e.py`、`eval_framework/runner.py`
- 清理失败时只打印警告或忽略异常，不抛出异常
- 如果网络错误或权限问题导致删除失败，对话会残留

**3. 前端 ChatView preview 模式不完整**
- `loadConversations()` 在 preview 模式下返回预览数据
- 但 `handleSend()` 和 `handleCreateConversation()` 没有检查 preview 模式
- 在 preview 模式下仍会调用真实 API

### 影响范围
- **功能:** 不影响正常功能，但导致数据库膨胀
- **用户:** 所有用户（特别是测试用户 user_id=1）
- **数据:** 不影响数据完整性，但产生大量垃圾数据

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Low | 不影响正常功能 |
| 数据完整性 | Low | 不影响业务数据，但产生垃圾数据 |
| 安全风险 | Low | 无安全风险 |
| 性能影响 | Medium | 数据库膨胀可能影响查询性能 |
