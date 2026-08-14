# Spec: 稳定核心债务清偿 — god-file / 一致性 / 并发 / CI 专项

> **位置**: 全仓（backend/app + frontend/src + deploy + .github）
> **类型**: 技术质量 spec（tech-audit 复查 + 改进计划）
> **日期**: 2026-08-14
> **状态**: 待实施
> **审计依据**: `.tech-audit/work/2026-08-14/findings.tsv`（104 条，16 维度）
> **Repo HEAD**: 94b7806

## 背景

上一轮 tech-audit（今日）已产出 104 条分层 findings。本 spec 聚焦代码评估中标记为「上轮未修」的**高优先级稳定债务**——它们不直接破坏现有功能，但长期持有会持续制造维护阻力、数据不一致面和安全暴露面：

| 主题 | 维度 | 现状等级 |
|---|---|---|
| God-file（5 个超 1500 行核心文件） | D1 | 🔴 ×3 上轮未修 |
| 练习/答案双写不一致（两套权威源） | D9 | 🟡 |
| 并发竞态（auth / email / 复习幂等） | D14 | 🟡 3 处 |
| LLM 无 per-user 配额 | D5 | 🟡 上轮未修 |
| Redis/ARQ 关键路径纯 mock | D3 | 🟡 上轮未修 |
| CI 从零 clone 无法跑绿 | D8 | 🔴/🟡 |

本 spec 采取**「先收敛核心、再补防线」**的顺序：数据一致性 → 并发正确性 → 资源配额防滥用 → 代码规模收敛 → 真实集成验证 → CI 可复现闭环。

---

## 问题清单与改进方案

### 问题 1 — 练习/答案「两套并行权威源」数据不一致 🔴

**现状**（已核实源码）：
- `backend/app/routers/practice.py:395` 的 `/api/evaluate-answer` 对同一答案同时执行两条写路径：
  - `INSERT INTO user_practice_history (…)`（:395）
  - `record_review(…)`（:412）→ 写 `user_question_review` + `practice_review_events`
- 用户答案又由 `/save-user-answer` 写 `user_question_view.user_answer`（`answers.py:192`）
- **读取端分裂**：`practice_deck_service` base_query 读 `user_answer`；而 `insights.py:137` / `analytics` 读 `user_practice_history` → 同一问题同一用户的答案/评分存在两套源，产生双写不一致。

**方案**：统一答案存储，收敛单一路径。

- **Step 1（写收敛）**：`self_check` 评估**只写 review 体系**（`user_question_review` + `practice_review_events`），**移除对 `user_practice_history` 的 INSERT**。答案收敛到 `user_question_view.user_answer` 单列。
- **Step 2（读收敛）**：把 `insights.py` / `analytics` 的读取源从 `user_practice_history` 迁移到 review 体系或 `user_question_view`。
- **Step 3（兼容）**：`user_practice_history` 降级为只读兼容表（保留存量数据），标注 deprecated，禁止新增写入。评估是否在未来迁移中归档/删除。
- **TDD**：为每条写路径加「写后断言只落单一源」的测试；为 insights/analytics 加「数据来自唯一源」回归断言。

**风险**：insights/analytics 依赖历史数据形态，需先跑通读迁移再切写路径。

---

### 问题 2 — 并发竞态（3 处 check-then-act）🟡

**现状**（已核实源码）：
1. **注册/绑定邮箱** (`auth.py:287 _insert_user`、`:684`、`:802`)：裸 `INSERT` / `UPDATE` 无 `try/except`，迁移 079 唯一索引兜底下并发插入抛未捕获 `sqlite3.IntegrityError` → **500 而非 409**。
2. **邮箱验证码双用** (`email_service.py:195-230 verify_code`)：`SELECT used` 与 `_mark_code_used` 分属两次独立连接事务，无序列化；`WHERE used=0` 只防第二次 UPDATE，不防第二次**授权**。
3. **复习提交无幂等键** (`practice.py:216-239` / `practice_review_service.py:114-169`)：前端/网络重发会**双写 `practice_review_events` 并二次推进 SRS `review_count`**。

**方案**：

- **1a 注册/绑定**：在 `_insert_user` 与绑定/重置的 `INSERT`/`UPDATE` 处捕获 `sqlite3.IntegrityError` → 映射为 409 Conflict；或采用 `INSERT OR IGNORE` + 影响行数判定。补 **API 级并发测试**（`test_email_unique` 目前只测 DB 层，需补路由层断言 409 而非 500）。
- **1b 验证码双用**：验证 + 标记合并进**同一事务**（`BEGIN IMMEDIATE` 原子提交），或先原子 `UPDATE … SET used=1 WHERE used=0 AND …` 再按影响行数判定，失败即 return False（防二次授权）。
- **1c 复习幂等**：前端请求加幂等键；`practice_review_events` 加 `UNIQUE(user_id, question_bank_id, idempotency_key)` 唯一约束，重放去重（可重试）；SRS 推进在事务内由幂等键保护。

---

### 问题 3 — LLM 消耗无 per-user 配额（成本/滥用暴露面）🟡

**现状**（已核实）：`routers/{answers,chat,practice,coding}.py` 的 LLM 消耗端点无 per-user 每日配额，可被单用户无限调用放大成本（多租户共享后端时存在跨用户成本/滥用面；当前私有部署暴露面较低，但仍是上轮未修的已知风险）。

**方案**：
- 新增 per-user 每日配额中间件/服务：按 `(user_id, date)` 记录 LLM 消耗（token 或调用次数）。
- 在 4 个 LLM 端点上应用限额，超限返回 429 + 明确提示。
- **优先选型**：配合问题 4 的 `llm_usage` 落库（现有 `llm.py` 已能拿到 `response.usage`），同一 schema 承载配额计数。
- 若短期不做完整配额，**最小方案**为：对公开/共享 fallback 端点移除无门槛 fallback，并加每用户速率上限（`slowapi` 已有 `limiter`，可先落到每 user 维度）。

---

### 问题 4 — God-file 代码规模收敛 🔴（投入最大、收益最高）

**现状**（已核实行数）：

| 文件 | 行数 | 超红线 |
|---|---|---|
| `backend/app/services/chat_service.py` | 2395 | >1500 |
| `backend/app/agents/chat/nodes.py` | 2028 | >1500 |
| `backend/app/worker.py` | 1805 | >1500 |
| `backend/app/services/llm.py` | 1565 | >1500 |
| `frontend/src/components/business/ChatView.vue` | 1577 | >1500 |

**方案（分模块迁移，纯重构 + 行为不变，靠现有测试保真）**：

- **4a `chat_service.py`**（2395 行，`grep '^def ` 概览已有清晰边界）：
  - `conversation` 业务（create/get/archive/delete/metadata，:782-1154）→ `chat_conversation_service.py`
  - `messages` 业务（save/get/recent/count，:1172-1370）→ `chat_message_service.py`
  - `memories` 业务（save/get/deactivate/summaries，:1428-1613）→ `chat_memory_service.py`
  - `session_notes`（:1645+）→ 并入 conversation 层
  - 保留 turn 生命周期（reserve/finalize/fail/cancel）为核心模块。
- **4b `nodes.py`**（2028 行）：按 `agents/chat/` 已有子模块边界拆分布局编排函数，状态节点/决策节点/工具节点分文件，`graph.py` 只做组装。
- **4c `worker.py`**（1805 行）：cron 注册 / job handler / 队列消费 拆分，ARQ WorkerSettings 仅配置不承载逻辑。
- **4d `llm.py`**（1565 行）：LLM 调用 / 重试 / usage 追踪 / 容错 JSON 解析 拆分；顺带把 LLM 容错 JSON 解析 ×4 重复收敛到 `llm_judge.parse_json_*` 唯一实现。
- **4e `ChatView.vue`**（1577 行）：拆为 `ChatMessageList` / `ChatComposer` / `ChatSessionBar` 子组件 + composable 抽取。
- **验收铁律**：每步拆分后跑对应功能域全量测试（chat/bank 域），**行为零变化**；行数红线 1500 写入 CLAUDE.md 并进 check.sh 硬门禁（新增超过即 FAIL）。

---

### 问题 5 — Redis/ARQ worker 关键路径纯 mock、无真实集成验证 🟡

**现状**（已核实）：`tests/infra/test_arq_integration.py` + `conftest.py mock_redis` 对 Redis/ARQ worker 关键路径纯 mock-only；真实队列入队/消费从未用真实 Redis 验证，cron 静默缺跑无可见性。

**方案**：
- `conftest.py` 支持 `RUN_REAL_REDIS=1` 环境变量：置位后用 `compose` 真实 Redis 做一次完整「入队 → worker 消费 → 结果落库」集成测试。
- 默认（未置位）仍走 mock（保持无外部依赖的离线套件绿）。
- 为 ARQ cron 增加 `last_run_at` / `status` 落库（D6 现有 🟢 建议同步做），`do_status` 汇总展示，杜绝「worker 按需关闭时 compaction/quality-audit/source-health 静默缺跑」。

---

### 问题 6 — CI 从零 clone 无法跑绿 🔴/🟡

**现状**（已核实 `.github/workflows/ci.yml`）：
- `gate` job 直接跑 `./scripts/check.sh all`：fresh clone **无 `node_modules`**（`npm run build` 必失败）、**无 `backend/.env`**（`docker compose env_file` 缺失报错）、无依赖引导步骤 → 门禁大概率恒红。
- `secrets` job：gitleaks 全史扫描因历史敏感 key（SiliconFlow）每次 push 必红，且无 `.gitleaks.toml` allowlist（测试 fixture 用）。
- `check.sh` 日常门禁只跑子集（3 后端结构 + 1 前端 smoke），`backend tests` 未纳入全量。

**方案**：
- **6a 依赖引导**：gate job 在跑 `check.sh` 前补 `npm ci` + 后端 `uv sync` / 复制 `.env.example`，或拆分 job——gate 只跑「gitleaks + 结构测试 + `npm run build`（无 server 依赖）」，全量 backend 测试走独立 job。
- **6b gitleaks allowlist**：新建 `.gitleaks.toml` 精确 allowlist 测试 fixture（而非全库排除）；测试中 key 字面量改拼接/环境变量（现有 D4 finding），使 gitleaks 可绿。
- **6c 门禁范围**：`check.sh` 纳入 backend 关键子集（bank/chat/pipeline/services/security/infra）全量 pytest，或明确拆 gated 全量 job。goal：**从零 clone → CI 单次跑绿**作为硬性完成标准。

---

## 里程碑排期

| 里程碑 | 覆盖问题 | 预估 | 依赖 |
|---|---|---|---|
| **M31** 数据一致性收敛 | 问题 1（双写收敛 + 读迁移） | 1-2 天 | — |
| **M32** 并发正确性加固 | 问题 2（auth/验证码/幂等，全 API 级测试） | 1 天 | — |
| **M33** LLM 配额与 usage 落库 | 问题 3 + `llm_usage` 表 | 0.5-1 天 | — |
| **M34** chat_service 拆分 | 问题 4a（4 层子服务） | 1-2 天 | 现有 chat 测试 |
| **M35** nodes / worker / llm 拆分 | 问题 4b-d | 2-3 天 | chat 测试 |
| **M36** ChatView.vue 拆分 | 问题 4e（子组件 + composable） | 1 天 | Playwright smoke |
| **M37** 真实 Redis 集成 + cron 可见性 | 问题 5 | 0.5-1 天 | — |
| **M38** CI 可复现跑绿 | 问题 6 | 0.5 天 | M31-33 修复后 |

**建议执行顺序**：M31 → M32 → M33（收敛与防线，1-3 天）→ M37/M38（验证闭环）→ M34-M36（规模收敛，4-6 天，可并行）。

---

## 回归 / 收尾契约

- **TDD（强制）**：每个里程碑先写红测再实现，逻辑修改后必须立即 commit（Conventional Commits，英文）。
- **门禁**：每里程碑收尾跑 `./deploy/docker-deploy.sh check`；新增≥1500 行红线检查进 check.sh。
- **CLAUDE.md**：拆分后必须更新对应目录 `CLAUDE.md`（chat_service/chat 各 agent/node；worker；llm）的模块边界说明。
- **README/规格**：涉及公开接口/数据语义变更（问题 1 的 reading-source 切换、问题 3 的限额），更新 README 与相关服务 CLAUDE.md。
- **验证**：`verification`——每个里程碑以实测输出（pytest 全绿 / check.sh 通过 / CI 绿）收尾，非「应该能用」。

## 验收标准（整体）

1. 每日自检评估 `self_check` 只写单一路径，insights/analytics 读取源唯一。
2. 并发注册/绑定/验证码/复习重放均返回 409 / 幂等去重，无 500、无双写。
3. LLM 端点有 per-user 配额，超限 429。
4. 5 个 god-file 拆分后全部 ≤1500 行，行为零回归，功能域测试绿。
5. Redis worker 有真实集成测试；cron 有 last_run 可见性。
6. 从零 clone 后 CI（gitleaks + check.sh + backend 全量）单次跑绿。
