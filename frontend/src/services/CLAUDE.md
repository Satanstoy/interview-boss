# Frontend Services — API 服务层

> 位置：`frontend/src/services/` | 上游调用方：`composables/`, `components/` | 对应后端：`backend/app/routers/`
> 职责：按领域拆分的 API 服务，统一通过 `http.js` 发起请求。

## 文件清单

| 文件 | 职责 | 对应后端 |
|------|------|---------|
| `http.js` | HTTP 客户端（get/post/put/del/upload、SSE helpers、401 自动刷新、重试、GET TTL cache） | — |
| `authApi.js` | 登录/注册/刷新/登出、忘记密码、修改密码 | `/api/auth/*` |
| `chatApi.js` | 对话 CRUD + 带 request ID 的 SSE 消息、assistant regenerate | `/api/chat/*` |
| `dataApi.js` | JD/面经提交、数据管理；当前页面主路径使用后台 Job | `/api/submit-jobs*`, `/api/submit-stream-v2`, `/api/data/*` |
| `masterBankApi.js` | 题库 CRUD | `/api/master-bank/*` |
| `practiceApi.js` | 刷题题单、题单题目关联、闪卡复习/答案生成 | `/api/practice/*`, `/api/answers/*` |
| `interviewApi.js` | 模拟面试 | `/api/interview/*` |
| `analyticsApi.js` | 数据分析 | `/api/analytics/*` |
| `insightsApi.js` | 洞察工作台聚合快照、练习足迹图表数据 | `/api/insights`, `/api/insights/practice-activity` |
| `profileApi.js` | 用户配置；含保存前 LLM 接口格式探测（`validateMyLLMConfig`）和管理员全局模型配置（`fetchGlobalEmbeddingConfig`/`updateGlobalEmbeddingConfig`/`testGlobalEmbedding`/`testGlobalLLM`） | `/api/profile/*` |
| `resumeApi.js` | 简历管理 + 优化（SSE：points → delta → done） | `/api/profile/resume`, `/api/profile/resume/optimize` |
| `codingApi.js` | 手撕代码练习 | `/api/coding/*` |
| `interviewDistributionApi.js` | 系统默认分布与用户岗位偏好 | `/api/interview/distribution/*`, `/api/profile/interview-distribution-preference` |
| `adminAssistantApi.js` | 管理员 AI 助手（聚合质量审查）：发消息 / 确认执行写操作 / 会话历史。历史 GET 必须 `{ ttl: 0 }` 绕过 http.js 30s 缓存 | `/api/admin/assistant/*` |
| `adminQualityApi.js` | 管理员聚合质量审查：启动全量误合并/漏合并扫描、读取扫描 Job、清单列表与审批 | `/api/admin/quality-issues/*`, `/api/jobs/{id}` |
| `adminSourceHealthApi.js` | 来源健康（同签名重复公共面经）：列表 / 合并（dry_run 参数）。列表 GET 必须 `{ ttl: 0 }` 绕过 http.js 30s 缓存 | `/api/admin/source-health/*` |

## 核心规则

- 普通 API 调用通过 `http.js` 的 `get/post/put/del/upload` 方法；SSE 调用通过 `postSSE/uploadSSE/getSSE`
- 需要 HttpOnly cookie 的认证请求使用 `fetchWithCredentials()`，必须保留 `X-Requested-With: XMLHttpRequest`，否则后端 CSRF 检查会拒绝 logout/refresh 类请求
- 新增 API 在此目录创建对应文件，并在 `api/index.js` re-export
- SSE helper 内部用 `fetch` + `ReadableStream`，不要用 `EventSource`
- Chat SSE 重试必须复用同一个 `client_request_id`；regenerate 调用 assistant revision endpoint，不在前端伪造或追加 user message

## 修改后必做

1. 新增 API 文件后更新 `api/index.js` 的 re-export
2. `cd frontend && npm run build` 确认构建通过
3. 更新本文件
