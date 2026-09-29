# 2026-09-28 上传批次清理记录

日期：2026-09-29 · 执行方式：备份 → 副本演练 → 单事务应用 · 数据库：`backend/data/interview-boss.db`

## 背景

用户要求清除 2026-09-28 上传的面经批次，避免其影响数据一致性。当天三次提交中：

- 两次成功入库：小鹏多轮面经（interview `5029`）、蔚来一面面经（interview `5030`）
- 一次返回 HTTP 400，未创建任务或记录，无需清理

该批次留下 14 个任务（其中 11 个答案生成任务因模型 API Key 401 全部 `failed`）、18 条聚类队列记录、11 道仅来自该批次的公共题，以及共享私人题 `6304` 上的一条来源。

## 清理对象与保留对象

| 对象 | 处理 | 结果 |
|---|---|---|
| interview `5029`、`5030` | 软删除（走 `_delete_interview_txn`，与管理端删除同一代码路径） | `deleted_at` 已置 |
| questions_detail（两篇面经下） | 软删除 | 24 条 |
| question_bank `6488`–`6498`（仅来自蔚来） | 软删除 + 来源/原题投影清理 | 11 条 |
| question_position 上述 11 题的行 | 删除 | 11 行 |
| question_sources / question_original_items / question_original_item_sources | 目标来源行软标记 | 各 12 行 |
| analysis_queue（interview 5029/5030） | 删除（与 `db/operations.py` 的删除行为一致） | 18 行 |
| jobs `342`–`355` | `status='cancelled'`，保留 `result`/`job_payloads` 作审计 | 14 个 |
| **question_bank `6304`（用户 1 的私人题）** | **保留**，仅移除小鹏面经来源 | 来源 2→1，frequency 2→1 |

`6304` 的另一来源 `internal://5ildmcA5aKMt3W5UeGHkzQ` 与另一篇面经未被触碰；其它任何 interview、题目、任务、发布申请均无变化（与清理前快照逐行比对一致）。

## 执行步骤

1. **备份**：`backend/data/backups/upload-cleanup-20260929/before.db`（sqlite backup API，`integrity_check=ok`，清理前状态：2 篇面经存活、14 个任务均未 `cancelled`）。
2. **副本演练**：在 `dry-run.db` 上执行同一脚本，全部断言通过，结果见 `dry-run-result.json`。
3. **正式应用**：单事务 `BEGIN IMMEDIATE` 内重跑全部安全断言后提交，结果见 `applied-result.json`。
4. **缓存失效（补做并验证）**：脚本里的 `invalidate_master_bank_cache()` 是空操作——缓存客户端只在应用启动时由 `asgi.py:294` 注入，一次性进程里 `get_cache_client()` 返回 `None`。随后直接对 `REDIS_CACHE_URL` 执行 `INCR interview-boss:cache:v2:master-bank:epoch`，值 `1 → 2`，已缓存的 4 条 master-bank 载荷因 key 含 epoch 而全部失效，下次读取回源 SQLite。

演练阶段暴露并修复的脚本缺陷：`jobs.available_at` 是 NOT NULL 列，原脚本 `available_at=NULL` 触发 `IntegrityError`，改为 `CURRENT_TIMESTAMP`（取消状态的任务不会被调度器扫描，调度器只认 `pending/queued/running`）。

安全断言（任一失败即整体回滚）：目标记录必须仍处于清理前的预期状态、目标任务不得处于活动状态、11 道公共题必须各自只有该批次的一个来源、共享题必须有 2 个来源、无关联发布申请、目标集合之外的全部数据逐行不变。

## 验证结果

- interview `5029`/`5030`：`deleted_at = 2026-09-29 08:36:44`；active 明细 0、active 目标题 0。
- 面经库列表查询（与 `data.py:407` 同款）：不再返回 5029/5030，最新记录回到 `4649` 拼多多。
- 公共题 6488–6498 可见数 0；活跃题总数 290。
- 上传任务查询（与 `submit.py:355` 同款，用户 1）：无 pending/queued/running/failed 记录。
- 与备份逐行比对：`interview`、`questions_detail`、`question_bank`（目标外）、`jobs`（目标外）、`analysis_queue`（目标外）、`public_contribution_requests` 完全一致；三张归一化来源表仅目标行的 `deleted_at` 被置位；`question_position` 减 11、`question_fts*` 同步更新、`interview_distribution_refresh_jobs` 新增一条分发刷新标记。
- 两个目标 URL 的活跃来源链接均为 0；`pragma integrity_check = ok`。
- 全库引用扫描（按 `interview_id` / `question_id` / `cluster_id` 等列 + JSON 字段搜目标 URL）：剩余引用全部是预期的审计残留——软删明细 24 行、软删题的 `cluster_id`/归一化来源各 11 行、复核 state/tasks、`job_payloads` 里两条上传 payload，以及 `question_variant_owners` 的 11 条 claim。claim 表按 `PUBLIC_QB_WHERE`（含 `deleted_at IS NULL`）判定活跃归属，且下一次写入会接管指向已删题的过期 claim，`rebuild_variant_ownership` 也只从活跃题重建，因此无需手工清理。
- 运行时冒烟：`/health` 200（42 ms），backend/worker/nginx/redis 容器均 healthy。

## 残留与后续

- 清理产生了 11 条 `cluster_review_tasks`（`trigger_reason='source_removed'`，pending）。调度器在每小时 :00/:30 投递，`run_cluster_review_task` 发现聚类已非 active 后会直接把任务置为 `superseded`，不调用模型、不产生费用。
- 该批次原有 10 条 `failed` 复核任务（401 Invalid API Key）仍保留：属于 Key 配置问题的审计记录，且无后台入口按失败任务列出聚类复核任务；修好 Key 后由后续 `mark_cluster_review_pending` 自然重置。
- `cluster_review_state` 中 6488–6498 的 `needs_review` 行保留：回填与派发只遍历 active 聚类，这些行不会被处理，也无调用方汇总展示。
- jobs `342`–`355` 为 `cancelled`，不属于 90 天 `completed/failed` 清理策略，作为审计记录长期保留。

## 回滚

```bash
# 停写后用备份覆盖，再按需重启 backend/worker
cp backend/data/backups/upload-cleanup-20260929/before.db backend/data/interview-boss.db
```

备份目录含 `before.db`（清理前完整快照）、`dry-run.db`（演练副本）、`dry-run-result.json`、`applied-result.json`。演练与应用结果一致，回滚后应回到清理前状态。
