# 聚类与代表题质量审核生命周期设计

**日期：** 2026-08-10
**状态：** 方案已确认，待实施
**范围：** 公共题库聚类、代表题、聚合质量清单、AI 评估任务与现有数据迁移

## 1. 决策摘要

把一个聚类视为一个聚合根：

```text
聚合 = 代表题 + 原始题面变体 + 来源 + 分类 + embedding + 审核版本
```

数据库是最终事实源；ARQ 只负责异步执行 AI 评估。AI 只能产生聚合质量待审建议，不能直接覆盖代表题、拆题或合并题目。人工审核通过后，才由同步数据库事务执行变更。

不引入完整事件溯源，也不把审核状态只放在 Redis/ARQ 中。采用：

```text
聚类版本 + 审核状态表 + 持久任务表/outbox + ARQ worker + quality_issue
```

当前正在运行的聚类质量任务完成前，不执行本设计的数据迁移、重跑评估或 Worker 重启。

## 2. 目标

1. 新建聚类、已有聚类加入新题、孤岛合并、拆题、代表题修改、全量重建都进入统一的代表题审核生命周期。
2. 只挑选“当前聚类版本尚未审核”的聚类，不再固定取 frequency 前 20 条。
3. 同一聚类版本的 AI 任务、审核建议和人工操作全部幂等。
4. 旧审核清单、答案、来源、合并历史全部保留，不因迁移被覆盖。
5. Worker/LLM 超时、重复投递、进程重启和人工审批过期都可恢复或安全拒绝。
6. 审核结果稳定展示在现有“聚合质量”入口。

## 3. 非目标

- 不在本阶段自动批准 AI 建议。
- 不因代表题改写自动覆盖 `ai_answer` 或 `answer_sources`。
- 不重做现有聚类算法，不改变当前匹配阈值和分类体系。
- 不把人工单条审批强制改成 ARQ；普通人工审批保持同步事务。
- 不删除或重写现有 `quality_issue`、`quality_audit`、`merge_history` 历史数据。
- 不在当前质量任务运行期间改动共享题库或审核表。

## 4. 核心不变量

### 4.1 聚类版本是审核有效性的唯一依据

每个活跃公共聚类生成：

```text
cluster_version = hash(
  question,
  sorted(unique(original_questions)),
  cat1,
  cat2,
  job_position
)
```

以下任一变化都会生成新版本：

- 代表题变化；
- 变体增加、移除或移动；
- 分类变化；
- 聚类拆分或合并；
- 全量重建后形成新聚类。

AI 结果和人工审批必须携带 `cluster_version`。版本不一致时，旧结果不得写回当前聚类。

### 4.2 AI 建议与正式数据分离

AI 评估只写 `quality_issue`，不直接修改 `question_bank`。人工批准时重新读取当前聚类并校验版本，校验失败返回“审核建议已过期”，不强行执行。

### 4.3 所有聚类变化必须触发审核状态变化

统一调用 `mark_cluster_review_pending()`：

| 事件 | 需要复审的聚类 |
|---|---|
| 新建单题聚类 | 新聚类，使用单题规范性策略 |
| 新建多题聚类 | 新聚类，使用覆盖性/误合并策略 |
| 新题匹配已有聚类 | 目标聚类 |
| 孤岛合并到已有聚类 | survivor 聚类 |
| 多个孤岛合并 | survivor 聚类 |
| 从聚类拆出独立题 | 原聚类 + 新聚类 |
| 代表题人工修改 | 当前聚类 |
| 全量重建 | 所有新建聚类 |

## 5. 数据模型

### 5.1 `cluster_review_state`

一条活跃聚类一条状态记录，不把审核状态直接混入 `question_bank`。

```sql
CREATE TABLE cluster_review_state (
    cluster_id INTEGER PRIMARY KEY,
    current_version TEXT NOT NULL,
    reviewed_version TEXT,
    status TEXT NOT NULL DEFAULT 'needs_review',
    priority INTEGER NOT NULL DEFAULT 50,
    last_trigger_reason TEXT,
    last_reviewed_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

状态：

```text
needs_review → queued → running → passed
                              ↘ needs_human
                              ↘ failed
```

`reviewed_version = current_version` 只表示该版本评估完成且没有待人工动作；有 pending 清单时状态为 `needs_human`。

### 5.2 `cluster_review_tasks`

该表同时承担持久任务和 outbox 作用，避免数据库提交成功但 ARQ 入队失败后任务丢失。

```sql
CREATE TABLE cluster_review_tasks (
    id TEXT PRIMARY KEY,
    cluster_id INTEGER NOT NULL,
    review_version TEXT NOT NULL,
    trigger_reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    locked_until TEXT,
    arq_job_id TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE(cluster_id, review_version)
);
```

同一个聚类版本只能有一个评估任务。旧版本任务可以保留历史，但执行时必须检查当前版本并安全跳过。

### 5.3 扩展 `quality_issue`

新增可空字段，保证旧数据兼容：

```text
review_version TEXT
review_task_id TEXT
trigger_reason TEXT
variant_key TEXT NOT NULL DEFAULT ''
```

建议的幂等键：

```text
(qb_id, review_version, issue_type, variant_key)
```

现有 `pending`、`approved`、`done`、`rejected` 记录保留不动；迁移只补充可证明的版本信息。

## 6. 统一审核策略

### 6.1 单题聚类

不判断“是否覆盖多个变体”，只检查：

- 题面是否自明；
- 是否包含必要上下文；
- 分类是否合理；
- 是否存在明显口语、截断或面经上下文残留。

只有发现问题才创建 `new_representative` 清单；单题本身不强制生成待审卡片。

### 6.2 多题聚类

将代表题与全部 `original_questions` 一起评估：

- 代表题是否覆盖所有变体；
- 是否存在误合并；
- 是否存在重复变体；
- 是否需要生成新的规范代表题；
- 是否需要拆出或并入其他聚类。

### 6.3 新题加入已有聚类

至少评估新增变体与当前代表题的关系。若新增变体使原代表题覆盖不足，生成 `weak_representative`；若考察点不一致，生成 `mismerge`。

### 6.4 拆分和合并

- 拆分：原聚类和新聚类都创建新版本；独立题使用独立重写题面和分类策略。
- 合并：保留 survivor 的代表题，但合并完成后重新评估 survivor 的全部变体。
- 代表题改写：同步更新 embedding、FAISS 和 `cluster_label`，但不自动重新生成答案。

## 7. 任务执行结构

### 7.1 变更事务

聚类变化与审核任务必须在同一个短事务中完成：

```text
更新聚类及来源
→ 计算 current_version
→ 更新 cluster_review_state
→ INSERT OR IGNORE cluster_review_tasks
→ 提交事务
```

### 7.2 Dispatcher

周期性扫描：

- `status='pending'` 且 `available_at <= now` 的任务；
- `status='running'` 且 `locked_until < now` 的任务；
- 有 `arq_job_id` 但未完成的任务。

Dispatcher 投递 ARQ 后写入 `arq_job_id`。即使投递重复，任务唯一键也保证只会产生一个有效版本结果。

### 7.3 ARQ Worker

AI 评估任务使用 ARQ，负责：

- 抢占 lease；
- 调用统一评估器；
- 写入幂等的 `quality_issue`；
- 无问题时将 `reviewed_version` 更新为当前版本；
- 有问题时将状态设为 `needs_human`；
- 可重试错误指数退避；
- 超过重试次数进入 `failed`，等待补偿任务。

Worker 执行前后都检查当前 `cluster_version`。过期任务不得写回。

### 7.4 人工审批

现有聚合质量页面继续使用：

- 单条批准/拒绝：同步 HTTP + 数据库事务；
- 批量少量审批：同步执行；
- 大批量拆分、合并、embedding 刷新：才考虑使用 ARQ。

人工执行后，受影响聚类重新生成版本，并创建后续审核任务。

## 8. 现有数据迁移

迁移前必须重新生成一次只读快照，不能写死讨论期间的数量。

按当前盘点结果，迁移策略为：

1. 为全部活跃公共题建立 `cluster_review_state`，包括单题聚类。
2. 为每条聚类计算当前版本，不修改题目文本、答案、来源或频率。
3. 现有 pending 代表题问题保留为 `needs_human`，不重复创建任务。
4. `done/rejected` 历史记录保留；如果没有可证明的 `review_version`，标记为需要一次复核，不删除历史状态。
5. 没有有效审核记录的多题聚类创建基线评估任务。
6. 单题聚类创建轻量规范性评估任务，只有 AI 发现问题才进入聚合质量清单。
7. 旧 `quality_audit` 只作为历史报告保留，不用于推断当前聚类是否已审核，因为它没有逐聚类版本记录。
8. 迁移完成后，执行一致性检查：无空 cluster_id、无孤儿清单、来源双写一致、规范化表数量不下降、答案字段 checksum 不变。

迁移必须支持 dry-run、重复执行和中途停止。dry-run 不允许写入任何业务表。

## 9. 稳定性与故障恢复

| 故障 | 预期行为 |
|---|---|
| LLM 超时/限流 | ARQ 重试，题库不变 |
| Worker 崩溃 | lease 到期后任务重新进入 pending |
| ARQ 重复投递 | 聚类版本唯一键保证幂等 |
| 旧审核结果晚到 | 版本检查后丢弃 |
| 人工批准过期清单 | 返回冲突，不执行旧动作 |
| 数据库事务失败 | 聚类变化和审核任务一起回滚 |
| embedding 刷新失败 | 代表题修改保留，但聚类状态标记 failed，等待补偿 |
| 进程长期停止 | Dispatcher/补偿任务恢复 pending 和卡住任务 |

## 10. 上线顺序

### Phase 0：当前任务结束

- 等当前聚类质量 AI 任务完全结束；
- 记录最终 `quality_issue` 数量、状态和失败情况；
- 不重启 Worker，不启动第二个评估批次。

### Phase 1：只读迁移预演

- 增加 schema migration；
- 在数据库副本生成 cluster version；
- 输出待回填任务报告；
- 验证现有审核清单、答案、来源和 merge_history 不变。

### Phase 2：状态回填

- 正式写入 `cluster_review_state` 和 `cluster_review_tasks`；
- 旧 pending 清单保持原状；
- 先不接入新题触发器。

### Phase 3：接入所有聚类变更路径

- 新建聚类；
- 增量匹配；
- 孤岛整理；
- 拆题/合并；
- 代表题修改；
- 全量重建。

### Phase 4：启用 ARQ 评估和补偿

- Dispatcher 投递任务；
- Worker 执行 AI 评估；
- 聚合质量页面展示 version-aware 清单；
- 开启失败重试和 stuck lease 回收。

## 11. 验收标准

1. 现有题目、答案、来源和审核历史没有被迁移覆盖。
2. 同一个聚类版本重复触发只产生一个任务和一份清单。
3. 新题加入已有聚类后，目标聚类必然出现新的审核版本。
4. 拆分后原聚类和新聚类都进入审核任务。
5. 合并后 survivor 必须重新审核。
6. AI 评估不能直接修改代表题。
7. 旧版本 AI 结果和旧版本人工审批不能覆盖新版本。
8. Worker 被杀掉后，任务可以自动恢复。
9. 只停止 Worker 时，数据库里的 pending 任务不会丢失。
10. 聚合质量页面可以区分当前版本的 pending、已通过、已拒绝和已过期建议。
11. 单题聚类不因为 frequency=1 被静默漏掉，而是走轻量规范性策略。
12. 代表题改写后 embedding、FAISS、cluster_label 与正文一致。

## 12. 需要新增的测试

- 迁移 dry-run 不写业务数据；
- 迁移重复执行无重复状态/任务；
- pending/done/rejected 历史清单回填策略；
- 新题加入已有聚类创建新版本；
- 新建单题和多题聚类分别走正确策略；
- 拆分同时标记源聚类和新聚类；
- 合并后 survivor 重新入队；
- 相同版本任务幂等；
- Worker 崩溃后的 lease 恢复；
- 旧版本评估结果被丢弃；
- 过期人工审批返回冲突；
- 代表题改写刷新 embedding/FAISS/label；
- 现有 `quality_issue` UI 能展示新字段和过期状态。
