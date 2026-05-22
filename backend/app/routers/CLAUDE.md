# Routers — API 路由层

HTTP 感知层，禁止包含业务逻辑。路由函数只负责解析请求、调用 services、格式化响应。

## 文件清单

| 文件 | 端点 | 职责 |
|------|------|------|
| `auth.py` | `/api/auth/*` | 登录/注册/刷新/登出 |
| `submit.py` | `/api/submit` | JD/面经提交（SSE 流式） |
| `data.py` | `/api/data/*` | 数据管理（JD/面经 CRUD） |
| `questions.py` | `/api/master-bank/*` | 题库 CRUD + 搜索 |
| `answers.py` | `/api/answers/*` | AI 答案生成 |
| `practice.py` | `/api/practice/*` | 练习模式 |
| `interview.py` | `/api/interview/*` | 模拟面试 |
| `analytics.py` | `/api/analytics/*` | 数据分析 |
| `profile.py` | `/api/profile/*` | 用户配置（公共+管理员） |
| `chat.py` | `/api/chat/*` | Chatbot 对话（SSE 流式） |
| `bank_build.py` | `/api/bank-build/*` | 题库构建（Agent） |
| `admin_review.py` | `/api/admin/*` | 管理员审核 |
| `health.py` | `/api/health` | 健康检查 |

## 子路由包

| 包 | 端点前缀 | 说明 |
|------|---------|------|
| `profile_pkg/` | `/api/profile/*` | 配置子路由（llm/taxonomy/position/email/resume） |
| `questions_pkg/` | `/api/master-bank/*` | 题库操作子路由（mutations/bulk） |

## 核心规则

- **禁止业务逻辑**：路由函数只做 HTTP 感知（解析请求、格式化响应），业务逻辑放 services/
- **依赖注入**：用 `Depends(get_current_user)` / `Depends(get_admin_user)` 做认证
- **SSE 端点**：用 `StreamingResponse(media_type="text/event-stream")` 返回流式数据
- **新路由注册**：在 `asgi.py` 中 `app.include_router(router)`

## 修改后必做

1. 新增路由后在 `asgi.py` 注册
2. 运行 `uv run pytest backend/tests/ -q`
3. 更新本文件
