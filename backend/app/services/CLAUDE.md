# Services 层 — 业务逻辑

> 位置：`backend/app/services/` | 上游调用方：`routers/`, `agents/` | 下游依赖：`core/`, `db/`
> 职责：所有业务逻辑实现。路由层禁止包含业务逻辑。

## 文件职责

| 文件 | 职责 | 依赖 |
|------|------|------|
| `llm.py` | LLM 调用（OpenAI/Anthropic 双格式）、重试、流式输出 | `core/config` |
| `pipeline/` | 批处理流水线（增量聚类、完整重建、队列、清洗、写库）与 `compact.py` 孤岛碎片整理 | `clustering`, `db` |
| `clustering/` | LLM 聚类去重包（matcher、clusterer、full_recluster、prompts），`__init__.py` 保持旧导入兼容；`experiments/` 为独立实验模块（语义标签摘要记忆：`load_cluster_data` + `text_prefilter` + LLM 标签生成 `generate_cluster_labels` + 孤岛增量分配 `assign_singletons`，评估通过才并入生产） | `llm`, `embedding_service` |
| `clustering_maintenance.py` | 聚类元数据审计/确定性修复（frequency、cluster_id、normalized tables、精确重复） | `db/question_bank_sources`, `pipeline/batch` |
| `submit_service.py` | 提交业务逻辑：题目标注、答案生成、增量更新题库 | `llm`, `db`, `pipeline` |
| `embedding_service.py` | 向量编码（双后端：SiliconFlow bge-m3 1024维 + 本地 ONNX bge-small-zh 512维）+ FAISS 预筛选 + hash fallback | `openai`, `onnxruntime`, `tokenizers`, `faiss-cpu` |
| `faiss_index_manager.py` | Per-cat2 centroid 缓存 + FAISS 索引管理器，消除 cluster_batch 全表扫描；singleton 实例通过 `get_index_manager()` 访问 | `embedding_service`, `faiss-cpu` |
| `backpressure.py` | 自适应并发限制器（RateLimitError 自动降并发、成功后恢复）；matcher/compact 共享 singleton | — |
| `chat_service.py` | 对话管理、消息存储、durable side-effect jobs、memory provenance/version guard、CandidateSet、interview event/generation read model | `llm`, `memory_recall_service` |
| `fts_service.py` | FTS5 全文搜索 | `db/connection` |
| `memory_recall_service.py` | 用户长期记忆召回 | `db/connection` |
| `title_service.py` | 对话标题自动生成 | `llm` |
| `resume_service.py` | 简历 PDF 解析、存储、查询 | `db/connection` |
| `email_service.py` | 邮箱验证码发送/验证（注册、登录、绑定邮箱、重置密码） | `core/config` |
| `taxonomy_suggest.py` | 分类建议 | `llm` |
| `utils.py` | 图片编码、URL 签名、分类规范化 | — |
| `question_draw_service.py` | 加权随机抽题（difficulty 映射、fallback 降级）；`behavioral` 过滤必须复用分布统计的统一信号词表（HR、人力资源、行为面、软技能、冲突、协作、失败、复盘、STAR、职业规划、影响力）；英语缩写 HR 必须按独立 token 匹配，不能误命中 `thread` 等技术词 | `db/connection`, `routers/questions` |
| `practice_scheduler.py` | SM-2-lite 间隔复习调度：根据 again/hard/good/easy 更新熟练度、间隔和下次复习时间 | — |
| `practice_review_service.py` | 持久化刷题评分、复习状态与复习事件 | `practice_scheduler`, `db/connection` |
| `practice_deck_service.py` | 今日复习（due）题单 + 系统/收藏题单与自定义题单管理。due 队列复习优先（到期复习 → 新题 → 未来），复习按 `frequency × (5 - proficiency)` 风险加权，新题按 frequency 降序并受 `max_new` 容量预算约束。**自定义题单纯私有**：owner-only 可见与增删（`visibility` 字段保留但不再产生 public 可见路径） | `db/queries` |
| `interview_distribution.py` | 模拟面试题型的唯一枚举、确定性分类、公共统计物化与分层默认值 | `core/interview_distribution_config` |
| `insights.py` | 洞察工作台聚合：当前岗位题库覆盖、个人练习证据、JD/面经计数和面试复盘摘要；练习足迹聚合（打卡热力图/连击/趋势/雷达/难度/最近刷题，口径为答题记录 + 闪卡复习事件，score≥60 算对） | `db/queries`, `db/connection` |

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

## 修改后必做

1. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/services/ -q`
2. 更新本文件（如新增文件或改变职责）
