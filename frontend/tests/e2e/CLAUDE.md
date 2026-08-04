# E2E 测试 — Playwright

> 位置：`frontend/tests/e2e/` | 上游：`frontend/tests/` 总览 | 测试对象：前端完整用户流程
> 职责：Playwright E2E 测试，覆盖登录、题库、练习、设置等核心流程。

## 运行

```bash
cd frontend && npx playwright test                    # 全部
npx playwright test tests/e2e/login-register.spec.js  # 单文件
```

## 规则

- 常规 E2E 必须 mock API，禁止调用真实后端
- 禁止截图断言（CI 环境不稳定）
- 禁止使用真实密码
- 刷题模式测试应覆盖单卡背题路径、全局顶栏题单下拉切换、全部题与高频题库联动、无返回题库/刷题队列入口以及题单管理入口；优先使用 `data-testid` 断言稳定的业务入口。
- 洞察工作台测试必须 mock `/api/insights`，并覆盖三 Tab 路由与旧 `/knowledge-graph` 兼容入口。
- 测试规则见 `.claude/rules/test-files.md`（编辑测试文件时自动加载）

## Chat API Mock 规则

**重要：** 所有访问 `/chat` 路径或涉及 chat 功能的测试，必须使用通配符 `**/api/chat**` mock 所有 chat API请求，防止请求泄露到真实后端。

**正确示例：**
```javascript
await page.route('**/api/chat**', async route => {
  const url = route.request().url()
  const method = route.request().method()

  if (url.includes('/conversations') && url.includes('status=active') && method === 'GET') {
    // 返回对话列表
  } else if (url.includes('/messages') && method === 'GET') {
    // 返回消息
  } else if (url.includes('/conversations') && method === 'POST') {
    // 创建对话
  } else if (url.includes('/messages') && method === 'POST') {
    // 发送消息 (SSE)
  } else {
    // 默认返回
    await route.fulfill({ json: { status: 'success', data: [] } })
  }
})
```

**错误示例：**
```javascript
// ❌ 只 mock 特定路径，可能泄露其他请求
await page.route('**/api/chat/conversations?status=active', ...)
await page.route('**/api/chat/conversations/conv-1/messages', ...)
```
