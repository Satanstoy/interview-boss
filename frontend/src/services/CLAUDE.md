# Frontend Services — API 服务层

> 位置：`frontend/src/services/` | 上游调用方：`composables/`, `components/` | 对应后端：`backend/app/routers/`
> 职责：按领域拆分的 API 服务，统一通过 `http.js` 发起请求。

## 文件清单

| 文件 | 职责 | 对应后端 |
|------|------|---------|
| `http.js` | HTTP 客户端（get/post/put/del/upload、SSE helpers、401 自动刷新、重试、GET TTL cache） | — |
| `authApi.js` | 登录/注册/刷新/登出、忘记密码、修改密码 | `/api/auth/*` |
| `chatApi.js` | 对话 CRUD + SSE 流式消息 | `/api/chat/*` |
| `dataApi.js` | JD/面经提交、数据管理；当前页面主路径使用后台 Job | `/api/submit-jobs*`, `/api/submit-stream-v2`, `/api/data/*` |
| `masterBankApi.js` | 题库 CRUD | `/api/master-bank/*` |
| `practiceApi.js` | 练习/答案生成 | `/api/practice/*`, `/api/answers/*` |
| `interviewApi.js` | 模拟面试 | `/api/interview/*` |
| `analyticsApi.js` | 数据分析 | `/api/analytics/*` |
| `insightsApi.js` | 洞察工作台聚合快照 | `/api/insights` |
| `profileApi.js` | 用户配置 | `/api/profile/*` |
| `resumeApi.js` | 简历管理 | `/api/profile/resume` |
| `codingApi.js` | 手撕代码练习 | `/api/coding/*` |

## 核心规则

- 普通 API 调用通过 `http.js` 的 `get/post/put/del/upload` 方法；SSE 调用通过 `postSSE/uploadSSE/getSSE`
- 需要 HttpOnly cookie 的认证请求使用 `fetchWithCredentials()`，必须保留 `X-Requested-With: XMLHttpRequest`，否则后端 CSRF 检查会拒绝 logout/refresh 类请求
- 新增 API 在此目录创建对应文件，并在 `api/index.js` re-export
- SSE helper 内部用 `fetch` + `ReadableStream`，不要用 `EventSource`

## 修改后必做

1. 新增 API 文件后更新 `api/index.js` 的 re-export
2. `cd frontend && npm run build` 确认构建通过
3. 更新本文件
