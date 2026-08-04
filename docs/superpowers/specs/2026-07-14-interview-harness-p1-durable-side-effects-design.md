# 模拟面试 Harness P1：Durable Side Effects 与一致性设计

**日期：** 2026-07-14  
**状态：** 核心链路已实现（migration 045、durable handoff、worker retry、provenance/version guard）；复杂 extraction policy 与独立 poller 可继续迭代
**前置：** P0 执行边界、request fingerprint 和 revision turn 已完成

## 背景

当前 pipeline 在 assistant finalize 后通过 fire-and-forget task 做 memory
extraction，提取结果直接写 `chat_memories`，session notes 则是无版本的完整
字符串覆盖。对话 metadata 也采用 read-merge-write。turn fence 可以阻止部分
同步副作用，但无法保护后台 task 在取消、进程重启或并发更新时的写入一致性。

## 目标

1. assistant turn commit 与待处理副作用之间建立可靠的 durable handoff。
2. memory extraction 可重试、可去重、可追溯到 source turn，并不会因旧 task
   覆盖新 session notes。
3. metadata 和 session notes 使用 optimistic concurrency，冲突显式暴露或
   合并，而不是静默丢更新。
4. memory 读取只暴露有效、未过期、属于当前 user 的内容。

## 非目标

- 不在 P1 改变 ReAct 工具选择或 prompt trust boundary。
- 不把全部聊天消息改造成 event sourcing。
- 不引入 PostgreSQL、消息队列或新的 ORM；先使用 SQLite WAL + worker/定时
  poller。
- 不让 LLM 直接写 memory；LLM 只产生待校验 extraction result。

## 数据模型

### `chat_side_effect_jobs`

```sql
CREATE TABLE chat_side_effect_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    conversation_id TEXT NOT NULL,
    source_turn_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    locked_at TIMESTAMP,
    finished_at TIMESTAMP,
    last_error TEXT,
    UNIQUE(kind, source_turn_id)
);
```

`UNIQUE(kind, source_turn_id)` 保证同一 turn 的 memory extraction/session
note job 只入队一次。job payload 保存原始输入的受控摘要和 extraction schema
version，不保存不必要的完整 prompt。

### Memory provenance

`chat_memories` 增加：

```sql
source_turn_id TEXT,
source_job_id TEXT,
memory_schema_version INTEGER NOT NULL DEFAULT 1,
expires_at TIMESTAMP,
content_hash TEXT NOT NULL DEFAULT ''
```

自动提取 memory 必须经过 schema、长度、类型、去重和敏感信息策略校验；无效
条目不入库。读取默认过滤 `is_active = 1` 且未过期，并继续按 user_id 隔离。

### Versioned metadata

`chat_conversations` 增加 `metadata_version INTEGER NOT NULL DEFAULT 0` 和
`session_notes_version INTEGER NOT NULL DEFAULT 0`。更新采用：

```sql
UPDATE chat_conversations
SET metadata = ?, metadata_version = metadata_version + 1
WHERE id = ? AND user_id = ? AND metadata_version = ?;
```

更新失败返回 conflict，由服务层按字段级 merge 或重新读取重试一次；禁止
无条件覆盖整个 JSON。

## 数据流

1. P0 finalize 在同一短事务内写 assistant message，并插入 side-effect jobs。
2. SSE `done` 只表示 assistant turn 已提交；job 是否完成不影响当前回复。
3. worker/定时 poller 领取 pending job，使用 source turn fence 和 user scope
   校验后调用 memory extractor。
4. extraction result 通过 deterministic validator 后，按 content hash 幂等写入
   memory，并用 versioned append/merge 更新 session notes。
5. job 成功标记 completed；可重试异常指数退避；超过上限标记 dead-letter，
   不影响 assistant turn。

取消或失败的 turn 不创建 side-effect job。若 job 已创建但 turn 随后失效，
worker 在领取前再次校验，直接标记 skipped。

## 测试

- finalize 与 job enqueue 原子性；重试不重复 enqueue；
- cancelled/failed turn 不产生 job；
- worker 重启后 pending job 可继续；同一 job 重跑不重复 memory；
- source turn、source user、schema version 和 expiry 正确；
- 两个 metadata writer 的版本冲突不会静默覆盖；
- session notes 合并保留两个合法更新；
- 越权 source turn、过期 memory、非法 extraction 都被拒绝。

## 交付顺序

1. migration 和 service repository；
2. finalize enqueue；
3. worker/poller 和 retry policy；
4. memory validator/provenance；
5. metadata/session notes versioning；
6. backfill 与观测指标。

## 当前实现映射

- `chat_side_effect_jobs` 在 assistant finalize 同事务入队，API 进程和 ARQ worker 都可 claim。
- `chat_memories` 保存 `source_turn_id`、`source_job_id`、schema version、expiry 和 content hash；读取默认过滤过期记录。
- `chat_conversations.metadata_version` 与 `session_notes_version` 提供显式 optimistic concurrency conflict。
- `backend/tests/chat/test_p1_p2_structured_turn.py` 覆盖原子 handoff、重试去重、版本冲突、过期记忆和 provenance。

P1 完成后，P2 可以把副作用 job、coverage event 和 assistant generation 统一
接入结构化 turn ledger，但 P1 不依赖 P2 的完整 event model。
