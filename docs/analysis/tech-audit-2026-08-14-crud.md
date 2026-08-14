# 数据库 CRUD 操作全盘排查 — 2026-08-14

**Auditor**: tech-audit deep cut（4 个并行层面 subagent + 主 agent 交叉验证）
**Scope**: 数据库 CRUD 操作专项（D9 数据完整性 + D14 正确性健壮性 + D4 注入 + D5 隔离交叉）
**Repo HEAD**: fe9685f + 安全修复（42cf667）
**方法**: 预扫描 1589 处 execute 调用 + 108 处 f-string SQL → 4 层面 fan-out（注入面/事务原子性/并发幂等/软删级联）→ 21 条 findings（0🔴 / 2🟡 / 19🟢）
**Findings source**: `.tech-audit/work/2026-08-14/findings.tsv`（CRUD 专项 21 条已并入）

---

## Executive summary

- 🟢 **Top strength**: SQL 注入面整体安全——108 处 f-string 拼接逐一验证：动态片段（列名/表名/排序/WHERE）全部经白名单 + regex 门后才插入，用户值一律 `?` 参数化。核心编排器（submit_interview_txn / 级联删除 / 题库变体操作）均用单连接显式 BEGIN/COMMIT/ROLLBACK；dual-write 与 ARQ outbox 设计规范；chat_side_effect_jobs 用 `BEGIN IMMEDIATE` + `UNIQUE(kind,source_turn_id)` + `INSERT OR IGNORE` + 乐观锁，是本仓并发防护的样板。
- 🟡 **Top risk（无 🔴）**: 并发竞态集中在**验证码双用**（email_service verify_code 无原子占用）与**注册/绑定邮箱 500**（migration 079 后 IntegrityError 未捕获）；事务脆弱性在**级联写依赖隐式事务**（connection.py 未设 isolation_level）；数据一致性缺口在 **JD restore 级联 owner 不对称**（可撤销他人软删）与**软删读路径漏过滤 ×3**（季节下拉/chat JD 内容）。
- 🟢 **数据丢失风险点**: 删除聚合内最后一个原始问法时物理 DELETE 用户练习/收藏记录（bulk.py:135）；迁移硬 DROP 遗留表无备份（CLAUDE.md 声称有但 run_migrations 无）。

---

## Findings（21 条，按层面）

### 层面 1 — SQL 注入面（D4）：3 条 🟢，无高危

| # | location | finding |
|---|---|---|
| 1 | queries.py:89-96 | get_dynamic_frequency_sql f-string 直插 user_id/table_alias——当前安全（调用方全传 DB 整型 + 常量），建议 int() + regex 白名单固化契约 |
| 2 | practice_deck_service.py:248-252 | difficulty LIKE 插值 deck_key——安全依赖函数内白名单门，建议插值处显式断言 |
| 3 | queries.py:72-97 + questions.py | SQL 片段 helper 入参无显式契约（table_alias/filter_mode）——建议 docstring/asserts 防未来误用 |

**已核实安全**（未列入 finding）：data.py 通用 UPDATE 三层防护（_ALLOWED_TABLES + ALLOWED_UPDATE_COLUMNS + _COL_RE + owner 校验）；interview_merge_service 动态表名双校验（router + service 白名单）；insights _scope_condition 内部构造；build_bank_where_clause 分支白名单。

### 层面 2 — 事务边界与原子性（D14）：4 条 🟢

| # | location | finding |
|---|---|---|
| 4 | questions_pkg/mutations.py + bulk.py | 拆分/合并/删除后代表题重生成在 COMMIT 之后 best-effort——失败仅 warning，代表题陈旧（部分完成路径） |
| 5 | data.py:925-937 | update_generic_data 编辑 interview 后事务外提交重处理任务——任务失败则派生状态陈旧 |
| 6 | connection.py:32 + data.py/operations.py | 级联写无显式 BEGIN，原子性依赖 Python 3.12 隐式 isolation_level=''——改配置即退化非原子 |
| 7 | questions_pkg/bulk.py:134-155 | 删除最后问法物理 DELETE 用户练习/收藏记录（不可恢复） |

### 层面 3 — 并发竞态与幂等性（D14）：2 🟡 + 4 🟢

| # | location | severity | finding |
|---|---|---|---|
| 8 | email_service.py:195-224 | 🟡 | **verify_code 双用竞态**：读 used=0 与标记已用分属两次连接事务，同一验证码可被两个并发请求消费（无原子占用） |
| 9 | auth.py:661-693,634-647 | 🟡 | **注册/绑定并发 500**：依赖唯一索引兜底但 IntegrityError 未捕获（应 409） |
| 10 | job_lifecycle.py:40-156 | 🟢 | 三类复用型 job check-then-insert 无兜底（随机 UUID 键使唯一索引失效），并发双建任务 |
| 11 | pipeline/queue.py:183-218 | 🟢 | cluster_batch 攒批 check-then-insert（重复 job 浪费） |
| 12 | practice.py + practice_review_service.py | 🟢 | 复习提交无幂等键——重发双写事件并二次推进 SRS |
| 13 | auth.py:62-85 | 🟢 | login _record_failure SELECT-then-INSERT（并发 500） |

### 层面 4 — 软删除/级联/数据完整性（D9）：8 条 🟢

| # | location | finding |
|---|---|---|
| 14 | data.py:687-692 | **JD restore 级联无 owner 限定**：会撤销其他用户同 URL 的软删记录（删除侧有 owner 限定，restore 侧没有——不对称） |
| 15 | data.py:613-628 | JD 批量删同 URL 多 owner 仅取首个 scope，级联不完整（半删态） |
| 16 | profile.py:106,187 | 季节下拉未过滤 deleted_at——软删面经污染可用季节 |
| 17 | chat.py:441 + nodes.py:1445 | chat 加载关联 JD 未过滤 deleted_at——软删 JD 仍喂 LLM |
| 18 | migrations/auth.py:175-176 | 迁移硬 DROP 遗留表无备份（run_migrations 无备份逻辑，与 CLAUDE.md 声称矛盾）；INNER JOIN 静默丢行 |
| 19 | migrations/question_bank.py:464-467 | 迁移清脏删 taxonomy 跨所有 owner 级联，无备份 |
| 20 | questions_pkg/bulk.py:135 | 按 question 文本跨 owner 硬删 questions_detail |
| 21 | questions_pkg/mutations.py:44,221,225,487 | merge/split 读源/目标未过滤 deleted_at——可对软删题簇操作 |

---

## 🔴 Refutation pass

本轮无 🔴（21 条中最高为 🟡×2，均已由 subagent 读实际代码路径验证 + 主 agent 抽样复核：verify_code 双用路径、注册 IntegrityError 路径、JD restore 对称性、隐式事务依赖、bulk 物理删除均代码确认）。

## Triage（建议里程碑）

| 优先级 | 事项 | Effort |
|---|---|---|
| P0 | verify_code 原子占用（BEGIN IMMEDIATE 或 UPDATE 先行） | M |
| P0 | 注册/绑定邮箱捕获 IntegrityError → 409（两路径） | S |
| P1 | JD restore 级联加 owner 限定（对称于删除） | S |
| P1 | connection.py 显式 isolation_level + 多写路径补显式 BEGIN | M |
| P1 | 软删读路径补过滤 ×3（profile 季节、chat JD、merge/split 读入） | S |
| P2 | 复习提交幂等键 + job 稳定幂等键 | M |
| P2 | 代表题重生成纳入事务或必达任务 | M |
| P3 | 迁移破坏性语句备份机制 | M |
| P3 | 物理删除用户数据路径改软删/确认 | M |

---
*报告由 tech-audit deep cut 生成；21 条 findings 已并入主 TSV（现 75 行）*
