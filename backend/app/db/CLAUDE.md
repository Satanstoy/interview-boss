# DB 层 — 数据库操作

SQLite 数据库层，线程安全，WAL 模式。

## 核心规则

- **线程安全**：`get_db_connection()` 返回线程本地连接，禁止跨线程传递
- **async 桥接**：async 函数必须用 `run_db()` 包装 DB 操作，禁止在 async 中直接调用 `get_db_connection()`
- **事务**：写操作用 `conn.commit()`，失败时 `conn.rollback()`
- **迁移**：新增表/列必须在 `migrations/` 对应领域文件添加 migration，并在 `migrations/__init__.py` 的 `_MIGRATIONS` 按序登记
- **依赖边界**：DB 层总体应避免业务服务依赖；当前 `operations.py` 复用 `services.utils` 的 URL 签名/分类规范化，改动时先确认调用链，不要扩大交叉依赖。

## 文件职责

| 文件 | 职责 |
|------|------|
| `connection.py` | 线程级连接管理、`run_db()`、岗位查询、动态频率 SQL |
| `migrations/` | Schema 迁移包；领域文件保存 `_migration_NNN_*`，`__init__.py` 维护 `_MIGRATIONS` 并提供 `run_migrations()` |
| `operations.py` | 可复用 CRUD（提交、去重、软删除）；面经写入时同步 `interview_id/question_type/dimension` 并标记公共统计过期 |
| `queries.py` | 跨领域查询（岗位、频率、分类体系） |
| `question_bank_sources.py` | 题库来源表 CRUD + dual-write 工具 |
| `utils.py` | DB 层工具函数（migration 辅助、SQL helpers） |
| `migrations/interview_distribution.py` | 面经题目关联/题型事实、分布统计与用户偏好表的 migration 042 |
| `migrations/chat.py` | Chat 会话、消息、工具 trace、asked question、turn fence、durable side effects 和 structured turn 的 migrations 024-046 |
| `migrations/practice.py` | 刷题题单、用户题目复习状态和复习事件的 migration 055 |
| `migrations/practice_decks.py` | 自定义题单所有者、可见性与题单题目关联的 migration 056 |
| `migrations/practice_defaults.py` | 清理旧的今日复习/高频/未刷分类，仅保留全部题和我的收藏系统题单的 migration 057 |
| `migrations/practice_performance.py` | 刷题队列切换查询的覆盖索引 migration 059 |
| `migrations/admin_assistant.py` | 管理员 AI 助手对话/操作审计日志表 migration 069：`admin_assistant_log`（session_id + admin_id 隔离，role: user/assistant/action）；migration 070：`quality_issue.target_qb_id`（误合并「并入到其他题」的目标题 ID）；migration 071：`quality_issue.new_cat2`（拆出后新题分类，LLM 判定）；migration 073：`quality_issue.source_question/source_cat2`（质量审查项原题快照，兼容已删除来源题的历史展示） |
| `migrations/clustering.py` | 聚类基础字段与质量审核迁移；migration 072 创建 `cluster_review_state`、`cluster_review_tasks`，并为 `quality_issue` 增加版本/任务/outbox 幂等字段；migration 076 创建原始题目全局 ownership claim 表 |
| `migrations/sources.py` | 来源规范化表 migration 016/023/047，以及公共面经/JD `url_signature` 唯一索引的安全启用 |
| `migrations/jobs.py` | jobs/analysis_queue/job_payloads 以及 migration 074 durable job lifecycle：ARQ 投递记录、lease、worker claim、重试与幂等键 |

## 关键模式

- **Dual-write**：`question_bank` 的 JSON 字段和 `question_sources`/`question_original_items` 表同步写入
- **软删除**：`deleted_at` 列，查询时加 `WHERE deleted_at IS NULL`
- **岗位过滤**：通过 `question_position` 关联表，fallback 到 `job_position` 列
- **模拟面试历史**：`chat_conversations.job_position` 记录会话所属岗位，列表和详情必须按用户当前岗位过滤。
- **模拟面试回合**：`chat_turns` 是进行中请求的唯一 fence；同一 conversation 只能有一个 `running` turn，旧 turn 不能绕过 `turn_id + fence` finalize。
- **手撕代码**：`coding_problems`（题库，50 道 seed 数据）+ `coding_submissions`（提交记录 + AI 评审结果），migration 030
- **刷题记忆**：`user_question_review` 记录每个用户每道题的熟练度、复习间隔和下次复习时间；`practice_review_events` 保留复习事件；`practice_deck_items` 连接自定义题单与高频题库题目。
- **刷题题单**：系统默认题单提供 `due`（今日复习）、`all` 和 `starred`；自定义题单由用户创建管理。队列按复习状态优先级排序（到期复习 → 新题 → 未来），排序使用静态 `question_bank.frequency` 作风险权重；**展示频率 = 动态来源数**（`get_dynamic_frequency_sql`，活跃面经按 URL 去重，过滤 `qs.deleted_at`），与题库列表口径一致，严禁用静态合并数（原始问法条数）作为展示频率。

## 修改后必做

1. 新增 migration → 更新 `migrations/` 对应领域文件和 `migrations/__init__.py` 的 `_MIGRATIONS` 列表
2. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/ -q` 确认不回归
3. 更新本文件（如新增文件或改变职责）
