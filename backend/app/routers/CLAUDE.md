# Routers — API 路由层

> 位置：`backend/app/routers/` | 下游依赖：`services/`, `core/` | 注册：`asgi.py`
> 职责：HTTP 感知层，禁止包含业务逻辑。路由函数只负责解析请求、调用 services、格式化响应。

## 文件清单

| 文件 | 端点 | 职责 |
|------|------|------|
| `auth.py` | `/api/auth/*` | 登录/注册/刷新/登出/邮箱绑定、忘记密码重置、已登录修改密码；logout 必须幂等清除 refresh cookie |
| `submit.py` | `/api/submit-stream-v2`, `/api/submit-jobs*` | JD/面经提交（LangGraph SSE + 后台 Job），并 re-export submit service 兼容旧内部导入 |
| `data.py` | `/api/data/*` | 数据管理（JD/面经 CRUD）；面经/明细变更必须在同一事务重算 typed fact 并标记统计刷新 |
| `questions.py` | `/api/master-bank/*` | 题库 CRUD + 搜索 |
| `answers.py` | `/api/answers/*` | AI 答案生成 |
| `practice.py` | `/api/practice/*` | LeetCode 风格刷题队列、系统/自定义题单、题单题目管理与间隔复习 |
| `interview.py` | `/api/interview/*` | 模拟面试 |
| `analytics.py` | `/api/analytics/*` | 数据分析 |
| `insights.py` | `/api/insights` | 洞察工作台聚合快照 |
| `profile.py` | `/api/profile/*` | 用户配置（公共+管理员） |
| `chat.py` | `/api/chat/*` | Chatbot 对话（SSE 流式、turn status、assistant regenerate） |
| `bank_build.py` | `/api/bank-build/*` | 题库构建（Agent） |
| `admin_review.py` | `/api/master-bank/*` | 管理员审核、合并历史、聚类维护 |
| `coding.py` | `/api/coding/*` | 手撕代码练习（题目/题单/导入/提交/错误统计） |
| `audio.py` | `/api/audio/*` | 语音转文字（Deepgram） |
| `error_report.py` | `/api/error-report` | 前端错误上报 |
| `interview_distribution.py` | `/api/interview/distribution/*` | 模拟面试题型的系统默认分布与用户岗位偏好 |
| `health.py` | `/api/health` | 健康检查 |

## 子路由包

| 包 | 端点前缀 | 说明 |
|------|---------|------|
| `profile_pkg/` | `/api/profile/*` | 配置子路由（llm/taxonomy/position/email/resume） |
| `questions_pkg/` | `/api/master-bank/*` | 题库操作子路由（mutations/bulk/share：share 私有题→公共 pending、pending/mine 我的待审） |

## 核心规则

- **禁止业务逻辑**：路由函数只做 HTTP 感知（解析请求、格式化响应），业务逻辑放 services/
- **依赖注入**：用 `Depends(get_current_user)` / `Depends(get_admin_user)` 做认证
- **SSE 端点**：用 `StreamingResponse(media_type="text/event-stream")` 返回流式数据
- **Chat 回合生命周期**：`chat.py` 发送消息必须先通过 `reserve_chat_turn` 原子占用回合并写入用户消息；流式完成必须通过 `turn_id + fence + user_id` finalize，取消必须调用幂等 cancel 端点，不能退回无回合约束的消息写入。
- **Chat 重试与 revision**：发送请求应携带稳定 `client_request_id`；`GET /conversations/{id}/turns/{turn_id}` 只返回当前用户的 turn snapshot。regenerate 只能通过 assistant revision endpoint，不能把原 user message 截断后再次插入。
- **Chat SSE 元数据**：`chat.py` 用 `_metadata_events_from_done()` 将 agent 的 done metadata 拆成公开事件（如 `selected_question`、`question_plan`、`basis`），避免直接暴露完整内部 metadata；`question_plan` 必须显式白名单输出字段，禁止透传内部 plan
- **岗位隔离**：列表、统计、练习进度、导入写入等用户可见数据必须通过 `get_user_job_position(user['id'])` 获取当前岗位；不要直接用全局 `get_current_job_position()` 作为用户视图过滤或写入依据。
- **新路由注册**：在 `asgi.py` 中 `app.include_router(router)`
- **面经分布事实**：修改 `questions_detail` 的文本或分类、重处理面经、删除/恢复公共面经时，必须复用 `db.operations` 的事实同步/刷新标记辅助函数；不能只更新题库代表题。

## 修改后必做

1. 新增路由后在 `asgi.py` 注册
2. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/ -q`
3. 更新本文件
