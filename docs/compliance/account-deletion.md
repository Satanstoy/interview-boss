# 账号删除（Account Deletion）

> 最后更新：2026-08-15

本文档说明用户如何请求删除账号，以及系统在删除账号时级联清理哪些数据、哪些数据因法律/安全需要保留及保留期。

## 1. 当前状态说明

截至本版本，账号删除由运营者协助完成，暂未提供一键自助删除。注销入口只清除登录态（清空刷新令牌与 HttpOnly Cookie），不删除账户数据。完整删除账号及其关联数据需通过联系运营者的方式发起。

## 2. 如何请求删除账号

1. 通过设置页了解流程：登录后在「设置 → 账户安全」页可查看隐私与账号删除说明及联系渠道。
2. 联系运营者发起：通过部署方公布的联系方式（若配置了 SMTP 支持邮箱，可用该邮箱）提交删除请求，并附上你的账号标识（邮箱或用户名）以核实身份。
3. 核实与执行：运营者核实身份后，按第 3 节级联删除你的数据，并触发第 4 节的保留规则。
4. 确认反馈：删除完成后运营者向你反馈结果。

## 3. 系统级联删除哪些数据

删除账号时，以下按用户（user_id / owner_id / submitted_by / conversation 归属）关联的数据应一并删除。以下表结构来自实际后端迁移（backend/app/db/migrations/），子表随父表 ON DELETE CASCADE 删除。

### 3.1 账户与认证

| 表 | 内容 | 说明 |
|------|------|------|
| users | 账户主记录 | 删除触发下游级联的依赖表 |
| refresh_tokens | 登录刷新令牌 | 删除账号的令牌，防止沿用 |
| login_failures | 登录失败记录 | 按用户名清理 |
| mcp_tokens / mcp_sessions | MCP 账户 Token 与会话 | 吊销并删除 |
| email_verification_codes | 邮箱验证码及锁定账本 | 清理该邮箱的验证码 |

### 3.2 配置

| 表 | 内容 |
|------|------|
| user_profile | 用户偏好 / 配置 |
| user_llm_config | 用户 LLM 配置（Base URL / 模型 / API Key） |
| user_search_config | 用户联网搜索配置（provider / API Key） |
| user_interview_distribution_preferences | 面试题型分布偏好 |
| user_recruitment_pref | 招聘季偏好（届次 / pace / 每日容量） |

### 3.3 提交内容与题库

| 表 | 内容 | 说明 |
|------|------|------|
| jd / interview | 用户提交的 JD 与面经 | owner 归本人的记录删除；公共（owner_id IS NULL）记录不删 |
| questions_detail / question_sources / question_original_items / question_original_item_sources | 面经题目明细与来源 | owner 归本人的删除 |
| question_bank / master_question_bank | 题库题目 | owner_id / submitted_by 归本人的私人题删除；公共题保留 |
| user_question_view | 用户查看记录 | 删除 |
| interview_imports / interview_import_chunks | 导入记录 | 删除 |
| practice_history | 历史练习 | 删除 |

### 3.4 练习 / 复习

| 表 | 内容 |
|------|------|
| user_practice_history | 练习作答记录 |
| user_question_review | 每道题的熟练度、间隔、下次复习时间 |
| practice_review_events | 复习事件 |
| practice_decks / practice_deck_items | 用户自定义题单及关联 |
| practice_deck_defaults | 系统/默认题单 | 保留（非个人数据） |

### 3.5 模拟面试 Chat

| 表 | 内容 | 级联 |
|------|------|------|
| chat_conversations | 会话 | 删除即级联 chat_messages / chat_turns 等 |
| chat_messages | 消息 | 随会话 ON DELETE CASCADE |
| chat_turns / chat_side_effect_jobs / chat_candidate_sets | 回合与副作用 | 随会话清理 |
| chat_memories | 长期语义记忆 | 随用户 ON DELETE CASCADE |
| chat_tool_traces | 工具调用痕迹 | 随会话清理 |
| interview_asked_questions / interview_events | 面试抽题与事件 | 随会话清理 |
| assistant_generations | 生成记录 | 随会话清理 |

### 3.6 手撕代码

| 表 | 内容 |
|------|------|
| user_resumes | 简历文件与解析文本（ON DELETE CASCADE） |
| coding_submissions | 代码提交与 AI 评审（关联用户） |
| coding_problem_favorites | 收藏 |
| coding_playlists / coding_playlist_items | 自定义题单及条目 |

### 3.7 其他

| 表 | 内容 |
|------|------|
| llm_usage | 每日 LLM 调用用量（user_id） |
| jobs / job_payloads / analysis_queue / pipeline_metrics | 任务记录 | 用户相关任务删除，公共/系统任务保留 |
| question_variant_owners | 原始题归属 claim | 本人 claim 清理 |

## 4. 因法律 / 安全需要保留的数据及保留期

以下数据在账号删除后仍需按安全/审计要求保留一段时间，或因其为公共/聚合数据而保留：

| 数据 | 保留理由 | 建议保留期 |
|------|---------|---------|
| 公共题库（owner_id IS NULL）与公共面经 | 非个人私有数据，属于平台共享内容，不随单一用户删除 | 长期保留 |
| 审计 / 管理员日志（admin_assistant_log 等） | 记录管理员写操作与审计留痕 | 建议 1-6 个月（或按运营者合规制度） |
| 聚合统计（interview_distribution_stats 等） | 去除个人标识后的聚合数据 | 长期保留（不含可识别个人信息） |
| 邮箱验证码 / 登录失败账本 | 反滥用；随每日保留期清理 | 30-90 天（由 run_db_retention 控制） |
| 请求 / 结构化日志 | 故障排查与安全 | 按日志轮转（Docker max-size / max-file） |

凡是删除后仍保留的数据，均会去除对该用户的个人可识别关联；聚合或审计数据不影响不可再识别到个人。

## 5. 操作入口

- 设置页：「设置 → 账户安全」页展示隐私/账号删除说明，是发起请求的入口（联系运营者）。
- 邮件：通过部署方公布的 SMTP 支持邮箱（SMTP_FROM / SMTP_USERNAME）提交删除请求。
- 后续建议（未实现）：为提供完整的自助删除体验，后续可在设置页提供「删除账号」按钮 + 二次确认 + 联立删除接口，并将操作写入审计日志。当前版本以本流程为准。