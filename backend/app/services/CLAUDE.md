# Services 层 — 业务逻辑

> 位置：`backend/app/services/` | 上游调用方：`routers/`, `agents/` | 下游依赖：`core/`, `db/`
> 职责：所有业务逻辑实现。路由层禁止包含业务逻辑。

## 文件职责

| 文件 | 职责 | 依赖 |
|------|------|------|
| `llm.py` | LLM 调用（OpenAI Chat / OpenAI Responses / Anthropic Messages 三格式）、重试、流式输出；**协议解析优先级**：用户/环境显式 `api_format` → endpoint/path hint → 10 分钟探测缓存 → 未知网关最小请求探测（仅 404/405/415 才尝试下一格式）→ Chat 默认，避免把认证/限流/参数错误误判成协议不兼容；`_PROVIDER_CAPABILITIES` 矩阵（json_mode/max_output_tokens/api_formats，按 endpoint hostname 匹配）+ `LLM_JSON_MODE_OVERRIDE`/`LLM_API_FORMAT` 应急开关；json_object 不可靠的端点自动降级为 prompt 指令 + 容错解析兜底；三格式完整参数支持（流式/工具调用/tool_choice/参数映射：messages→input、system→instructions、max_tokens→max_output_tokens、response_format→text.format、tools 扁平化、tool_choice 转换）；所有调用显式下发 `max_tokens`（默认 4096）避免服务端默认值截断；**格式转换器已抽到 `llm_converters.py`**（re-export 兼容） | `core/config`, `llm_converters` |
| `llm_converters.py` | 消息/工具格式转换器（从 llm.py 抽出）：`_convert_tools_to_anthropic`/`_convert_messages_with_tools_to_anthropic`/`_extract_tool_calls`/`make_tool_result_message` 等，纯格式转换 | — |
| `answer_enrichment.py` | 答案/背诵稿提示词构建：联网搜索（best-effort，失败回退纯模型）+ 来源格式化；`sources_json()` 序列化来源供落库；`refine_answer()` 生成后质量 loop（critic 对照参考资料+硬性 checklist，结构化 JSON verdict，PASS 提前停；revise 仅在有 issues 时执行；LLM 异常/JSON 解析失败回退草稿；单题 max_rounds=2、批量/流水线/agent max_rounds=1；无搜索来源跳过 loop） | `search_service`, `core/prompts`, `llm` |
| `search_service.py` | 用户可配置联网搜索（Tavily/Brave/Bocha/Exa 等多 provider）；`search_web()` 返回规范化结果 `[{title, url, snippet, published_at}]`，未配置返回空列表不抛错 | `core/config` |
| `pipeline/` | 批处理流水线（增量聚类、完整重建、队列、清洗、写库）与 `compact.py` 孤岛碎片整理 | `clustering`, `db` |
| `clustering/` | LLM 聚类去重包（matcher、clusterer、full_recluster、prompts），`__init__.py` 保持旧导入兼容；`experiments/` 为独立实验模块（语义标签摘要记忆：`load_cluster_data` + `text_prefilter` + LLM 标签生成 `generate_cluster_labels` + 孤岛增量分配 `assign_singletons` + 合并二次验证 `verify_assignments`（fail-closed，验证层默认开启，`evaluate.py --no-verify` 可关），`evaluate.py` 为评估入口，跑全流程并输出 Markdown 报告到 `backend/experiment_reports/`；评估通过才并入生产） | `llm`, `embedding_service` |
| `clustering_maintenance.py` | 聚类元数据审计/确定性修复（frequency、cluster_id、normalized tables、精确重复）+ 聚合质量审查清单生成：`generate_quality_issues`（两轮确认 + 置信度分级；误合并确认后先 `FIND_MERGE_TARGET_PROMPT` 判断**并入 or 拆出**——跨 cat2 允许并入，用同大类候选 + LLM 语义判定，目标存 `target_qb_id`；拆出走 `SPLIT_REWRITE_PROMPT` 预生成重写题面 + **LLM 判定新题分类** `cat2`，存 `suggested_value`/`new_cat2`，用岗位分类体系 `get_taxonomy_for_position` 作候选不发明新类）、`generate_weak_representative_issues`（代表题不规范 → 建议规范题面；全量评估时将每个聚类的全部原始变体交给 LLM，不截断为前 N 条）、`split_variant`（可选 `new_representative`/`new_cat2`：新题用重写题面+新分类，原问法降为新题问法，未传则用原文/继承）、`merge_variant`（来源题移除问法 + 目标题加问法，目标已含则仅移除）、`dedupe_variant`、`refine_representative`；质量审查候选统一限定公共题库（`owner_id IS NULL`） | `db/question_bank_sources`, `pipeline/batch` |
| `submit_service.py` | 提交业务逻辑：题目标注、答案生成、增量更新题库 | `llm`, `db`, `pipeline` |
| `embedding_service.py` | 向量编码（双后端：SiliconFlow bge-m3 1024维 + 本地 ONNX bge-small-zh 512维）+ FAISS 预筛选 + hash fallback；**生产已切 SiliconFlow bge-m3**（`EMBEDDING_BACKEND=siliconflow`，2026-08-06 全量重算 320 题，DB 记录 `embedding_model/embedding_dim`）；配置支持 **DB 热加载覆盖 env 常量**（`reload_embedding_config()` 从 `user_profile` 读 `embedding_*` key 覆盖模块级变量，重建 session/client/FAISS，asgi/worker 启动时同步调用保证重启后配置保持）；`EMBEDDING_BACKEND=auto` 时 onnx 优先、siliconflow 次之、hash 兜底（hash 无语义，仅防崩） | `openai`, `onnxruntime`, `tokenizers`, `faiss-cpu` |
| `embedding_recompute.py` | 全量 embedding 重算 job（模型更换后由 admin 端点自动触发）：遍历 `question_bank` 全部未删除题重编码，更新 `embedding/embedding_model/embedding_dim`，重建 FAISS；**失败回滚已更新行（全成功或全不动）**，避免新旧模型向量混库导致 FAISS 维度不一致崩溃；`run_recompute` 开头从 DB reload 目标配置（worker 进程独立加载）；`jobs` 表 + `/api/jobs/{id}/stream` 推送进度 | `embedding_service`, `faiss_index_manager`, `db/connection` |
| `faiss_index_manager.py` | Per-cat2 centroid 缓存 + FAISS 索引管理器，消除 cluster_batch 全表扫描；singleton 实例通过 `get_index_manager()` 访问 | `embedding_service`, `faiss-cpu` |
| `backpressure.py` | 自适应并发限制器（RateLimitError 自动降并发、成功后恢复）；matcher/compact 共享 singleton | — |
| `chat_service.py` | **facade**（104 行）：从 7 个子模块 re-export，向后兼容 router/agent 的既有 import；职责见下列子模块 | — |
| `chat_common.py` | 共享原始块：会话/回合/副作用异常类、`ChatTurn`、`_safe_json_loads`、`build_turn_request_fingerprint`、`SIDE_EFFECT_MAX_ATTEMPTS`、`FLUSH_UTILIZATION_THRESHOLD` | — |
| `chat_turn_service.py` | 回合生命周期：reserve/revision/cancel/finalize/fail + 开场白（会话 fence、幂等、side-effect 入队） | `chat_common` |
| `chat_conversation_service.py` | 会话 CRUD：create/list/get/title/archive/delete/metadata | `chat_common`, `chat_message_service` |
| `chat_message_service.py` | 消息写入（active 校验）/读取/分布事件/关联题目 id | `chat_common` |
| `chat_memory_service.py` | 用户长期记忆：memory、主题记忆、简历记忆 | `chat_common` |
| `chat_session_service.py` | session notes、刷盘触发、跨会话召回与格式化 | `chat_common`, `chat_memory_service` |
| `chat_durable_service.py` | durable side-effect job、记忆抽取 job、CandidateSet、interview event/generation read model | `chat_common` |
| `worker.py`（`app/worker.py`） | ARQ worker：任务执行 + 定时任务；`scheduled_db_retention_task`（每日 4:00）按龄清理过期邮箱验证码/完成队列/失败登录/陈旧 jobs（`run_db_retention`，保留期 30-90 天，父任务血缘保护） | |
| `fts_service.py` | FTS5 全文搜索 | `db/connection` |
| `memory_recall_service.py` | 用户长期记忆召回 | `db/connection` |
| `title_service.py` | 对话标题自动生成 | `llm` |
| `resume_service.py` | 简历 PDF 解析、存储、查询，优化结果存取（`save_optimization`/`get_optimization`） | `db/connection` |
| `email_service.py` | 邮箱验证码发送/验证（注册、登录、绑定邮箱、重置密码）；`verify_code` 用单条原子 UPDATE 完成「校验+标记已用」（audit D14，防并发双消费）；每邮箱连续失败达 `LOCKOUT_THRESHOLD`(5) 作废该码（audit D4，账本复用 `email_verification_codes` 表的 `code='__lockout__'` 保留行，不新增表列） | `core/config` |
| `taxonomy_suggest.py` | 分类建议 | `llm` |
| `utils.py` | 图片编码、URL 签名、分类规范化 | — |
| `question_draw_service.py` | 加权随机抽题（difficulty 映射、fallback 降级）；`behavioral` 过滤必须复用分布统计的统一信号词表（HR、人力资源、行为面、软技能、冲突、协作、失败、复盘、STAR、职业规划、影响力）；英语缩写 HR 必须按独立 token 匹配，不能误命中 `thread` 等技术词 | `db/connection`, `routers/questions` |
| `practice_scheduler.py` | SM-2-lite 间隔复习调度：根据 again/hard/good/easy 更新熟练度、间隔和下次复习时间；`schedule_review` 支持 `urgency`（0..1 缩放间隔，最多 -40%，`again` 不受调制）；`mastered` 卡 30 天固定抽查间隔，不受 urgency 缩放 | — |
| `recruitment_milestones.py` | 招聘季机会窗口纯函数：`get_season_windows(届次)` 生成全年 4 窗口（暑期实习/提前批/秋招正式批/春招主批，含相对权重）；`compute_urgency(windows, 今天, pace)` 机会脉冲模型——紧迫度 = clamp(base 0.2 + Σ 窗口脉冲 + 节奏偏移，0..1)，返回当前窗口与下一窗口；无窗口 → 恒 base（社招/日常实习节奏） | — |
| `practice_review_service.py` | 持久化刷题评分、复习状态与复习事件；`record_review` 透传 `urgency` 给 `schedule_review`（招聘季间隔调制）；`record_review` 接受可选 `idempotency_key`（audit D14），同 `(user_id, question_bank_id, idempotency_key)` 已存在事件时跳过重发，不重复写事件也不二次推进 SRS review_count（部分唯一索引 DB 层兜底） | `practice_scheduler`, `db/connection` |
| `practice_deck_service.py` | 今日复习（due）题单 + 系统/收藏题单与自定义题单管理。due 队列四桶排序（到期复习 → mastered 抽查「保持手感」→ 新题 → 未来），复习风险权重 = **真实出现频率（动态来源数）× (5 - proficiency)**，新题按动态来源频率降序并受预算约束（`max_new` 参数显式传入，或自动取 `user_recruitment_pref.daily_capacity − 到期复习 − 抽查`，下界 0）；题卡 `frequency` 展示与全部排序均用动态来源数（与题库列表口径一致），静态 `question_bank.frequency`（聚类变体数）仅为聚类元数据，不参与展示/排序（SQLite ORDER BY 不支持别名参与表达式，需显式内联动态频率子查询）；item 带 `is_checkin`（state=mastered）标记。**自定义题单纯私有**：owner-only 可见与增删（`visibility` 字段保留但不再产生 public 可见路径） | `db/queries` |
| `interview_distribution.py` | 模拟面试题型的唯一枚举、确定性分类、公共统计物化与分层默认值 | `core/interview_distribution_config` |
| `insights.py` | 洞察工作台聚合：当前岗位题库覆盖、个人练习证据、JD/面经计数和面试复盘摘要；**岗位高频待练**（`high_frequency`：面经 `questions_detail` 按 cat2 聚合被问频次降序 Top10，供无练习数据时「从高频开始刷」；**JOIN interview iv 并按 `_scope_condition`（owner 或公共 approved + 未删除）过滤调用者作用域**，他人私有面经不泄漏进聚合）；**readiness.items 含 `proficiency`**（SRS 熟练度聚合，练过才有值，供技能星图/双线雷达）；练习足迹聚合（365 天周历热力/连击/30 天趋势/雷达/难度/最近刷题，口径为答题记录 + 闪卡复习事件）：雷达严格限定当前目标岗位并优先返回最薄弱主题，难度统计以 score≥60 算对且返回精确 `correct_count` / `needs_work_count` | `db/queries`, `db/connection` |
| `quality_issue_ops.py` | 聚合质量审查清单业务逻辑（`quality_issue` 表）：`serialize_issue`/`execute_issue`（从 admin_quality 抽出，管理员助手确认路径与 admin_quality 路由共用同一份实现，避免行为漂移）、`list_issues`/`review_issue`/历史合并文本回退、`approve_issue`（`min_confidence=None` 保留单条审批不过滤语义；给值则 SQL 加置信度下限）、`reject_issue`、`batch_approve`（置信度下限强制 `max(0.85, 传入)`）。**展示 label 人话化**：`ISSUE_TYPE_LABELS`（mismerge→误合并、duplicate→重复问法、weak_representative→代表题不规范）与 `ACTION_LABELS`（split→拆成独立题、dedupe→移除重复问法、refine_representative→换成规范代表题、merge→并入到其他题），标识符保持英文不变。`serialize_issue` 透出 `target_qb_id` + `target_question`/`target_cat2`（并入目标，迁移 070）、`new_cat2`（拆出新分类，迁移 071）、`source_question/source_cat2`（迁移 073 原题快照）、`original_questions`（面经原题列表）供卡片「当前→操作后」对照；过期 `variant_index` 安全返回 `variant=null/variant_stale=true`；拆分/代表题修订前拒绝已被其他题簇占用的原始题目 | `clustering_maintenance`, `db/connection` |
| `question_variant_reconciliation.py` | 公共题库原始题目的规范化扫描、显式 canonical 归属修复、来源/规范化表同步、重复待审卡关闭，以及 pipeline 写入时的全局 ownership claim 防护；不替人工决定语义归属 |
| `unmerged_quality.py` | 漏合并质量审查：复用孤岛题的字符相似度预筛 + LLM 二次判断，只将公共题库中应并入已有聚类的候选写入 `quality_issue` pending；管理员审批时复用现有合并实现和 `merge_history`，不在扫描阶段自动改库 | `clustering/experiments/memory_labels`, `pipeline/compact`, `db/connection` |
| `cluster_review_lifecycle.py` | 聚类版本哈希、审核状态/持久 outbox、迁移回填、dispatcher lease、ARQ worker 抢占、重试退避、旧版本丢弃与完成状态回写；数据库事务负责事实，ARQ 只执行 AI 评估 | `db/connection`, `llm`, `clustering_maintenance` |
| `job_lifecycle.py` | 长任务 durable outbox/lease：上传 Job、逐题答案 Job、管理员全量聚合质量扫描 Job 的 dispatcher 预占、ARQ 投递记录、worker 原子 claim、心跳续租、失败退避与完成状态；数据库是事实源 | `db/connection` |
| `admin_assistant_service.py` | 管理员 AI 助手编排：5 个 OpenAI 风格 tool schema + 简体中文系统提示词 + `run_assistant_turn`（LLM tool 循环 ≤8 次，读工具即时执行、写工具只读暂存返回 `requires_confirmation`）、`confirm_and_execute`（**唯一执行点**：单线程单事务重新校验 + reviewed_by 留痕）、`get_assistant_history`（按 session_id+admin_id 隔离）。对话与操作写入 `admin_assistant_log`（role: user/assistant/action）；action 回执以 `[已执行操作]` user 消息喂回 LLM（Anthropic 会把 system 消息合并到顶部，中段回执必须用 user 消息保序）。批量置信度下限 0.85 服务端强制 | `llm`, `quality_issue_ops`, `db/connection` |
| `source_health.py` | 来源健康检查（只读 + 更新 internal 基线文件）：`run_source_health_checks()` 扫同签名重复面经（interview/jd 按 url_signature 分组，**只统计公共面经 `owner_id IS NULL`**）、internal:// 现状与相对基线的增长、question_bank JSON 双写列（sources/original_questions/original_question_sources）与规范化表不一致。供 weekly cron（`worker.scheduled_source_health_task`）与脚本 `backend/scripts/check_source_health.py` 复用同口径；`ok` 为 False 时 worker 记 warning、脚本 `--exit-code` 返回 1 | `db/connection` |
| `interview_merge_service.py` | 同签名重复公共面经的列表与合并（**仅 `owner_id IS NULL`，私有面经绝不触碰**）：`list_duplicate_groups`（signature/count/keep_id/records）、`merge_duplicate_group`（dry_run 只读预览不写库；真实执行保留 MIN id 软删其余，重挂 questions_detail + 去重、question_sources/qois URL 归一、question_bank JSON 双写列同步，全部 owner 限定）、`merge_all_duplicate_groups`（运维脚本复用）。admin 路由 `admin_source_health` 与脚本 `fix_source_consistency` 共用此实现 | `db/connection` |
| `interview_reprocess.py` | 面试重处理 durable job 提交：`submit_interview_reprocess_job()` 持久化请求并 best-effort 投递 ARQ，Redis 不可用时返回 `pending` 而非在 web 进程执行 LLM 调用 | `db/connection`, `job_lifecycle` |
| `job_position_service.py` | 岗位标准化与别名解析：复用 `interview_distribution_config.JOB_FAMILY_BY_POSITION` 的岗位族映射，提供精确的岗位发现、canonical name 解析和别名归一（连续空格/首尾空格/英文大小写/斜杠空格归一化）；未知岗位返回 `UNKNOWN_JOB_POSITION` | `core/interview_distribution_config` |
| `llm_judge.py` | LLM 结构化判断统一工具（聚类验证层与检索 rerank 共用）：`parse_json_object()` / `parse_json_array()` 容错提取 JSON（容忍 markdown 代码块/前后文字/对象包裹），整体解析失败时逐个提取对象/数组元素 | — |
| `mcp_token_service.py` | 账户级 MCP Token 生命周期：`generate_mcp_token()` 生成 opaque token（HMAC-SHA256 派生）、`validate_mcp_token()` 验证、`revoke_mcp_token()` 吊销；Token 与账户一一对应，轮换后旧 Token 立即失效 | `core/auth`, `db/connection` |

## 核心规则

- LLM 调用必须通过 `llm.py` 的函数，禁止直接实例化 OpenAI client
- OpenAI-compatible reasoning 模型（MiMo/DeepSeek 类）使用 `reasoning_content` 字段；`llm_with_tools()` 必须把非流式 `message.reasoning_content` 透出，`stream_llm_messages(yield_thinking=True)` 必须读取流式 `delta.reasoning_content`
- 重试逻辑用 tenacity，不要手写 retry 循环
- 错误处理：捕获异常后记录日志，向上抛出业务异常
- 聚类维护禁止用 embedding 阈值自动合并；embedding 最多作为候选排序/预筛信号
- 模拟面试会话必须写入并按 `job_position` 过滤，跨会话召回也只召回同岗位历史。
- Chat 消息写入必须在 SQL 内校验会话归属与 `status = 'active'`；归档会话保留只读，不允许新增 user 或 assistant 消息。
- Chat turn 必须先通过 `reserve_chat_turn()` 原子获取 conversation fence；assistant finalize、取消和 turn-owned 副作用必须校验 `turn_id + fence + user_id + status = 'running'`，不能只按 conversation 写入。
- Durable side effects 必须从 `chat_side_effect_jobs` claim；memory extraction 按 source turn/job 与 content hash 去重，metadata/session notes 更新必须支持 expected version conflict。
- CandidateSet 只保存题目引用；消费后必须从权威 `question_bank` reload，不能信任客户端或候选集中的自然语言题面。
- **题卡频率口径（唯一权威 = 动态来源数）**：展示 `frequency`、复习风险权重（`frequency × (5 - proficiency)`）、新题排序、排序 tiebreak 全部用动态来源数（活跃面经按 URL 去重、过滤 `deleted_at`，公共+本人 all 口径），与题库列表一致。`question_bank.frequency` 是聚类合并的原始问法条数（同一面经多个问法也计数），仅为聚类元数据，**禁止**参与展示/排序（历史教训：MAX 展示虚高 1 来源显示 6；风险权重用静态列导致显示高频却不靠前）。
- **SQLite ORDER BY 别名陷阱**：ORDER BY 不支持别名参与表达式——`frequency * (5 - proficiency)` 中的 `frequency` 会**静默解析为真实列** `qb.frequency`（静态列），而非 SELECT 别名；别名只允许整体引用（如裸 `frequency DESC`，同样解析为列名）。要按动态频率排序必须显式内联相关子查询 `({frequency_sql})`（无自动 CSE，单用户题量级开销可忽略）。

## 修改后必做

1. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/services/ -q`
2. 更新本文件（如新增文件或改变职责）
