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
- 洞察工作台测试必须 mock `/api/insights`，并覆盖三 Tab 路由与旧 `/knowledge-graph` 兼容入口。
- 测试规则见 `.claude/rules/test-files.md`（编辑测试文件时自动加载）
