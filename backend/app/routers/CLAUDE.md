# Routers — API 路由层

> 位置：`backend/app/routers/` | 下游依赖：`services/`, `core/` | 注册：`asgi.py`
> 职责：HTTP 感知层，禁止包含业务逻辑。路由函数只负责解析请求、调用 services、格式化响应。

## 文件清单

| 文件 | 端点 | 职责 |
|------|------|------|
| `auth.py` | `/api/auth/*` | 登录/注册/刷新/登出/邮箱绑定、忘记密码重置、已登录修改密码；logout 必须幂等清除 refresh cookie |
| `submit.py` | `/api/submit-stream-v2`, `/api/submit-jobs*` | JD/面经提交（LangGraph SSE + 后台 Job），并 re-export submit service 兼容旧内部导入 |
| `data.py` | `/api/data/*` | 数据管理（JD/面经 CRUD）；面经/明细变更必须在同一事务重算 typed fact 并标记统计刷新。删除级联严格限定 owner 范围（`owner_id IS ?`，NULL 匹配公共数据）：私有删除不碰公共/他人面经、detail、question_bank sources；`_cleanup_sources_for_url` 带 owner_scope。面经删除必须把主记录、detail、JSON 来源投影和规范化来源表放进同一个严格事务；来源清理失败必须回滚整个删除，且只有同 owner 同 URL 的最后一个活跃面经才能清理来源。**静态 `question_bank.frequency` 恒为「聚类变体数」语义**（`original_questions` 长度，下限 `max(1, ...)`）：删除/恢复时 oqs 缺失必须保守取 1，禁止用剩余来源数冒充频率（真实出现频率 = 动态来源数，由刷题/题库列表动态计算）。`update_generic_data` 编辑 interview/questions_detail/jd 的 `url` 时复用 `core.validation.validate_source_url` 校验（非空必须 http(s)，internal:// 等无效值拒绝） |
| `questions.py` | `/api/master-bank/*` | 题库 CRUD + 搜索。detail 用 all 口径可见性过滤（公共 approved OR 自己的）；编辑权限唯一矩阵 `can_edit_question`（公共题仅 admin，个人题仅本人，admin 也不能改他人个人题） |
| `answers.py` | `/api/master-bank/*` | AI 答案生成。公共参考答案（`ai_answer`）仅管理员可生成（单题/批量均 403 拦截普通用户）；批量生成 SSE 每 15 秒发送 heartbeat，单题生成超过 300 秒转为失败进度并继续收尾，确保最终发送 `done`；`generate-recitation` 为用户定制个人背诵稿（公共参考答案为基座 + 岗位/简历上下文 + 用户搜索配置），写入 `user_question_view.user_answer`；`save-user-answer` 仅允许对用户可见的题写入（all 口径可见性断言）；`use-reference-answer` 已删除；生成时联网搜索来源写入 `question_bank.answer_sources` 并在题库列表/详情 API 返回（questions.py） |
| `practice.py` | `/api/practice/*` | LeetCode 风格刷题队列、系统/自定义题单、题单题目管理与间隔复习。收藏/复习/加题单/evaluate-answer 的可见性统一 all 口径（`build_bank_where_clause(user_id, "all")`：公共题 + 自己的题），与题库列表一致。复习与自评记录复习时通过 `_user_urgency()` 按用户招聘偏好（`user_recruitment_pref` 届次 + pace）计算机会窗口 urgency 传入 `record_review`（无偏好 → 0.2 base） |
| `interview.py` | `/api/interview/*` | 模拟面试 |
| `analytics.py` | `/api/analytics/*` | 数据分析 |
| `insights.py` | `/api/insights` | 洞察工作台聚合快照 |
| `profile.py` | `/api/profile/*` | 用户配置（公共+管理员）。`active-season` 为全局配置仅 admin 可写（user_profile 是全局单例）。`/api/profile/recruitment`（GET/PUT，任意登录用户）读写 per-user `user_recruitment_pref`（届次+批次+每日容量+pace 节奏），返回全年机会窗口、当前/下一窗口与紧迫度（机会脉冲模型），供刷题「今日复习」调度与前端状态行使用 |
| `chat.py` | `/api/chat/*` | Chatbot 对话（SSE 流式、turn status、assistant regenerate） |
| `bank_build.py` | `/api/bank-build/*` | 题库构建（Agent）。`build-personal` 合并：管理员可并入公共题（现有行为），非管理员只落个人题（个人题吸收公共题来源，公共题数据绝不改动，防审核旁路） |
| `admin_quality.py` | `/api/admin/quality-issues/*` | 聚合质量审查清单生成与审批（`generate-all` 创建持久化后台任务，全量扫描公共题库误合并/漏合并；`generate-unmerged` 保留为单独即时入口；列表/单条 approve·reject/batch-approve）。业务逻辑在 `app.services.job_lifecycle` / `app.services.quality_issue_ops` / `app.services.unmerged_quality`，本路由只做 HTTP 感知 |
| `admin_assistant.py` | `/api/admin/assistant/*` | 管理员 AI 助手（聚合质量审查）：`POST /chat`（LLM tool-calling，读工具即时执行，写工具只暂存为待确认）、`POST /confirm`（确认并执行写操作，重新校验 + reviewed_by 留痕）、`GET /history`（会话日志）。全部 `Depends(get_admin_user)`；工具 schema 只在后端，前端从不持有 |
| `admin_source_health.py` | `/api/admin/source-health/*` | 来源健康（同签名重复公共面经）：`GET /duplicate-groups`（列表，`table=interview|jd`）、`POST /duplicate-groups/merge`（body `{signature, table, dry_run}`，默认 dry_run 预览；真实执行保留 MIN id 软删其余）。业务逻辑在 `services/interview_merge_service`，只处理公共面经（`owner_id IS NULL`） |
| `admin_review.py` | `/api/master-bank/*` | 管理员审核、合并历史、聚类维护 |
| `coding.py` | `/api/coding/*` | 手撕代码练习（题目/题单/导入/提交/语言与 LeetCode/ACM 模式/错误统计） |
| `audio.py` | `/api/audio/*` | 语音转文字（Deepgram） |
| `error_report.py` | `/api/error-report` | 前端错误上报（匿名）。限长防刷：最多 50 条、单字段截断 2000、超限返回 ok:false |
| `interview_distribution.py` | `/api/interview/distribution/*` | 模拟面试题型的系统默认分布与用户岗位偏好 |
| `health.py` | `/api/health` | 健康检查 |

## 子路由包

| 包 | 端点前缀 | 说明 |
|------|---------|------|
| `profile_pkg/` | `/api/profile/*` | 配置子路由（llm/taxonomy/position/email/resume） |
| `questions_pkg/` | `/api/master-bank/*` | 题库操作子路由（mutations/bulk/share：share 私有题→公共 pending、pending/mine 我的待审）。trash 回收站：admin 仅见公共题（`owner_id IS NULL`），个人题仅本人 |

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
