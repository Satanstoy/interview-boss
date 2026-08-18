# 刷题页面打开性能优化 — 设计 Spec

> 日期:2026-08-19 · 状态:已达成共识(grill-me 确认 M1–M5 决策,ADR 0046) · 范围:后端(worker/practice 读端)+ 前端(冷启动)
> 关联:docs/analysis/2026-08-18-practice-page-performance.md(审计证据链)

## 1. Problem

打开刷题界面(`/practice`,今日复习 due 队列)时,用户感知"每次打开都慢"。生产日志与离线实测证据:

| 证据 | 数值 |
|---|---|
| `GET /api/practice/decks/due/questions` 生产耗时 | 25ms ↔ **268–504ms**(同接口冷热差 20 倍) |
| `GET /api/practice/decks` | 75–96ms |
| `GET /api/profile/recruitment` | 12–30ms |
| `GET /api/master-bank` 缓存命中 vs miss | **27ms vs 160–544ms** |
| 离线复算 due 队列整套 SQL(约 10 条查询) | **~15ms** |
| 离线复算 master-bank 完整流水线(含 159KB JSON) | **~7ms** |
| worker 48h 日志 `database is locked` | **1009 次(≈每 3 分钟一次)** |
| 实时探测写锁(300 次连续获取) | **0% 冲突(当前空闲)** |

**结论**:慢的形态 = "读路径撞上间歇性写竞争 + 冷启动冗余 + 高频自审写噪声",**不是"读得太慢"**(SQL 毫秒级)。因此修复方向是把"读"从"写"中摘出去、砍掉无谓写、砍掉冷启动空转。

## 2. Goals / Non-Goals

**目标**
1. 刷题页打开链路 P95 明显下降(基线:生产日志 25–504ms;目标:≥80% 请求 <150ms,无 500ms 档)。
2. worker 无谓写锁获取显著减少(`database is locked` 日志 <100 次/48h)。
3. 全部改动带回归测试,现有测试不红。

**非目标(本期不做)**
- 不做 due 队列的 Redis 长缓存(正确性:SRS 状态每复习一次即变,缓存易旧)。
- 不换掉 SQLite(单用户/轻负载规模下 SQLite 合理;换 PG 是另一个决策)。
- 不重构 chat 完整记忆系统,只做"每轮抽取 → 收口抽取"最小改动(R4,标注为边界项可后置)。
- 不重排 worker 大批量写任务的整体调度时段;M5 只做"重活接入 backpressure 限流 + WAL checkpoint 纪律",不做全调度错峰。

## 3. 现状事实(对齐代码,行号以审计当日为准)

- **cron 观察记账写库**:`worker.py:107-153`(`record_cron_execution` 每次 upsert `worker_cron_runs`)+`worker.py:167-182`(`observed_cron_task` 每次跑写 running+succeeded 两笔)+ `worker.py:1574-1581`(8 个 cron 全部被包装)。写锁 48h 1009 次冲突的主力。
- **cron 频率**:`worker.py:1615-1624` —— heartbeat/submit dispatch 每分钟、cluster review dispatch 每 5 分钟、chat 副作用每 10 分钟(后两者是兜底调度,平时空转)。
- **记账表读端**:`get_cron_status`(worker.py:155)、`record_worker_heartbeat`(68) 目前**仅在 worker 内被读写,无路由/前端消费**(审计已确认),挪 Redis 低风险。
- **practice 读端无缓存**:`GET /api/practice/decks`(routers/practice.py:72)、`/decks/{key}/questions`(:181)、`/profile/recruitment` 均未接入 `app/core/cache.py`。
- **master-bank 缓存已存在但 TTL 15s**:`core/config.py:115-117`(`MASTER_BANK_CACHE_TTL_SECONDS=15`),命中率低。
- **前端冷启动**:`AuthenticatedLayout.vue:304-313` `initAuthSingleton` 重复注册两遍(可能重复 loadAllData);`http.js:210-213` 每次 401 自动刷新重试一次 (access token 15min)。
- **记忆抽取每轮调 LLM**:`chat_turn_service.py:612-623` 每回合 finalize 入队 `memory_extraction` 任务 → `pipeline.py` `_step_extract_memory` 当场 claim + `memory_extract.py:259-260` 调 `_call_llm_with_retry(MEMORY_EXTRACT_PROMPT)`。cron 兜底(worker.py:740+)只在捡到遗留任务时才调 LLM。

## 4. Architecture(改动后数据流)

```
打开 /practice(冷)
  1. auth 初始化(合并后的单次 initAuthSingleton)──> 不再 401→refresh 重复链
  2. loadDecks    ──> GET /api/practice/decks        ── Redis per-user 缓存(60s,写路径失效)
  3. due/questions──> GET /api/practice/decks/due/questions(不缓存,但读端已不受写噪声拖累)
  4. recruitment  ──> GET /api/profile/recruitment   ── Redis per-user 缓存(60s,PUT 时失效)

worker(无谓写治理)
  - heartbeat / cron running 记账 ──> Redis key(ex/ttl),失败仍回退 SQLite(保留失败可查)
  - submit dispatch 每分钟→每 5 分钟;cluster dispatch / chat 副作用兜底 → 30–60 分钟

chat(二期边界)
  - 记忆抽取:每轮 → 面试收口时一次(整场对话提炼)
```

## 5. 方案设计

### R0 — 观测先行(第 0 步,独立)

- 在请求日志中间件追加两个字段:`db_busy_ms`(SQLite busy 等待时间,可选)与 `request_duration_ms` 分位统计。
- 目的:验证 R1–R3 前后 500ms 归属变化;若 R1–R3 后服务器处理已 <50ms,剩余优化转前端首帧。
- 变更:`app/middleware/` 日志字段 + 部署观测。无行为风险。

### R1 — 观察性记账挪出 SQLite

- **心跳**:`record_worker_heartbeat` 写入改为 Redis key `interview-boss:worker:hb:<worker_name>`(ttl 90s)+ 保留异常路径写 SQLite。
- **cron 运行记账**:`observed_cron_task` 包装改为:开始时写 Redis(`interview-boss:cron:<name>:run`),**结束时仅在状态变化/失败时写 SQLite** `worker_cron_runs`(`succeeded` 结果无变化则不写)。
- **降频**:heartbeat cron 每分钟→每 5 分钟;`scheduled_submit_job_dispatch_task` 每分钟→每 5 分钟;`scheduled_cluster_review_dispatch_task` 每 5 分钟→每 30 分钟;`process_chat_side_effects_task` 每 10 分钟→每 30 分钟。
- 变更面:`worker.py`、`worker_scheduled.py`(降频率用 cron 参数)、`core/cache.py`(追加 worker 记账 helper,复用现有 `_cache_client`)。
- 一致性:worker 的 `ctx["redis_cache"]` 已有(worker.py:378-384);Redis 不可用时 fail-open 回退 SQLite,行为与现状一致。

### R2 — practice 读端 per-user Redis 缓存

- **`GET /api/practice/decks `**:per-user 缓存,TTL 60s。失效:crate/update/delete deck、add/remove item 后 `invalidate(user_id)`。
- **`GET /api/profile/recruitment`**:per-user 缓存,TTL 60s。失效:PUT `/api/profile/recruitment` 后失效。
- **复用**:`app/core/cache.py` 的 epoch 模式(全局 epoch 或 per-user epoch),新增 `get_practice_decks_cache/set/...` 三个小 helper;key 带 `user_id + filter`。不加新依赖。
- **due/questions 不缓存**(非目标,理由见上),但受益于 R1(读端不被高频写撞)。

### R3 — 前端冷启动瘦身

- 合并 `AuthenticatedLayout.vue:304` 与 `:310` 两次 `initAuthSingleton` 注册为一次(消除可能重复的 loadAllData/JD/面经/master-bank 拉取)。
- 冷启动鉴权完成后开一个后台预取:auth ready 即触发 loadAllData,避免 401→refresh→重试链吃掉首帧(维持 http.js 401 自动刷新作为兜底)。
- PracticeView 首帧:维持 `serverReady ? deckQuestions : filteredMasterBank` 兜底渲染(已有,确保 due 未返回前先有卡片)。

### R4 — 记忆抽取收口一次性(边界,可在 M2 后独立评估)

- 把 `chat_turn_service.py:612-623` 的"每回合入队"改为"仅面试结束/收口轮次入队一次 (`intent==end_interview` 或 stop_policy 收口时)",payload 带整场历史。
- `extract_memory` 保持同一提示词;cron 兜底逻辑不变(频率已按 R1 降)。
- 收益:每场面试 LLM 记忆抽取调用从 ~N 次(轮数)降到 1 次;同时减少 SSE 收尾延迟。
- 风险:收口前崩溃仍由兜底 cron 承接;记忆从"逐轮增量"变"整场一次",去重逻辑(按 source turn/hash)需保持兼容。

### M5(已确认)· 写端健康(WAL checkpoint + 限流 + 备份修正)

用户在 2026-08-19 grill-me 确认决策 D1–D8(见 ADR 0046):

- **WAL checkpoint 纪律(D2)**:worker 新增每日 4:10 定时任务 `scheduled_wal_checkpoint_task`(紧贴 retention 4:00 之后),执行 `PRAGMA wal_checkpoint(PASSIVE)` 循环至 busy=0(或固定轮数上限)再 `TRUNCATE`;失败仅记日志、幂等、次日重跑,不做重试。挂 `WorkerSettings.cron_jobs`(D7)。
- **观测闭环(并 R0,D4)**:该任务每次上报 busy、回写页数、耗时;M5 验收 = `interview-boss.db-wal` 回落 + 48h `database is locked` 计数下降。
- **备份工具修正(P3)**:`build_master_bank_task` 的 `shutil.copy2(DB_PATH,...)` 替换为 `sqlite3.Connection.backup()`(WAL 下 `copy2` 漏掉 `-wal` 未合并帧,是不一致备份;`migrations/__init__.py:32` 已是正确 API)。
- **批量写限流(D3)**:重活任务接入 `services/backpressure.py` 的 `AdaptiveSemaphore`,控同刻批量写并发;不做调度错峰。
- **`busy_timeout=10000` 不动(D5)**:fail-open,慢优于报错;撞车根源由 R1+M4+M5 消掉。
- 连接层**暂不抽** `wal_autocheckpoint`/`page_size` 常量(D8,YAGNI)。

## 6. 测试计划(TDD 强制)

| 修复 | 测试文件(backend/tests/) | 用例 |
|---|---|---|
| R1 | `infra/test_worker_observability_redis.py`(mock_redis) | ① heartbeat 写入 Redis key 且 SQLite 不写;② Redis 不可用回退 SQLite;③ cron 记账:同状态重复运行不重复写库(run_count 不变);④ 失败路径仍写 SQLite |
| R2 | `services/test_practice_cache.py`(client + mock_redis) | ① `/api/practice/decks` 命中缓存不再落库(可断言 mock sqlite 调用/二次请求 <阈值);② PUT recruitment 后失效;③ 建/删 deck、增删 item 后失效;④ 缓存 miss 回退 SQLite 且结果正确 |
| R3 | 前端 Playwright(`frontend/tests/`) | ① 冷加载不出现重复 XHR(同一数据接口只请求一次);② 首帧有 fallback 卡片渲染;③ 无 401 循环 |
| R4 | `chat/test_memory_extraction_consolidation.py` | ① 普通轮次不再入队 memory_extraction;② 收口轮次入队一次且 payload 含整场历史;③ 遗留任务兜底路径不回归 |

回归门槛:改后跑 `./deploy/docker-deploy.sh test -q` 全量 + `./deploy/docker-deploy.sh check backend`;前端 `cd frontend && npm run build && npm run test`。

## 7. 验收标准(可量化)

1. 生产日志:48h 内 `database is locked` ≤ 100(N 天前基线 1009)。
2. `GET /api/practice/decks`、`/api/profile/recruitment` 冷请求走 Redis,日志 P95 < 50ms。
3. `/api/practice/decks/due/questions` 无 >300ms 抖动(配合 R0 观测确认)。
4. 前端冷启动:同一数据接口在 shell mount 阶段只请求一次。
5. 全量测试通过,无回归。

## 8. 里程碑与实施顺序

- **M1(R1)** — 观测性记账挪 Redis + cron 降频。后端独立,先做(收益最大、风险最低)。
- **M5(写端健康)** — 与 M1 同批后端独立交付:每日 4:10 checkpoint、copy2→backup、重活接入 backpressure。
- **M2(R2)** — practice 读端 per-user 缓存。
- **M3(R3)** — 前端冷启动瘦身。
- **M4(R4)** — 记忆抽取收口(可选)。
- 每里程碑按 writing-plans 拆 2–5 分钟任务,逐任务 TDD 红-绿-重构 + 提交。
