# 增量代码审查 — 2026-08-07

**基线**: `docs/analysis/tech-audit-2026-08-05.md`（HEAD `b282e2cb`）
**审查范围**: `b282e2cb..HEAD`（82 commits，114 files，+9581/−1280）+ 工作区未提交改动（Tier 0/1 修复在途）
**方法**: 5 个并行对抗审查 agent（clustering / LLM compat / practice scheduler / pipeline-worker / frontend）+ 主线程逐项验证（所有 Critical/Important 结论均重读源码确认）。未跑运行态测试（生产容器中禁止 pytest）。
**审查者**: Claude Code，用户指定

---

## Executive summary

- 🟢 **修复计划在途且有效**：Tier 0 五个修复中 4 个已完成（WAL 在线备份已实测可用、PROJECT_DIR 自定位、oauth-gateway 非 root + `user nginx`、Dockerfile 基础镜像升级），fix-commit 同 commit 携带测试的比例从审计时的 0% 提升到 ~53%（8/15）。
- 🔴 **修复计划大部分未动**：Tier 1 的 14 项里只有 3 项部分完成（git hook 未提交、README 部分、a11y 部分）；Tier 2-4 全部未开始（CI、test_auth_core、OTP 限流、密钥加密、PyJWT、runbook、恢复演练、配额、合规三件套）。
- 🔴 **新代码引入的高风险缺陷集中在三个"新增功能"里**：
  1. **`question_draw_service._embedding_supplement`（抽题 embedding 补充，新代码）** — 无 owner/岗位可见性过滤（跨用户私有题泄漏给面试 agent 候选）、权重用静态 frequency（虚高回归）、把 embedding BLOB 原样塞进响应（`/api/master-bank/random` 500）。**建议合并前修复**。
  2. **聚类质量审查执行链** — `serialize_issue` 对过期 variant_index 不越界检查（整个 admin 清单接口 500，双 agent 独立确认）；`split_variant` 拆出的题**恒为公共题**（owner_id 未 select）；split/dedupe/refine 破坏 dual-write 与 cluster_id/embedding/position 不变量；issue 生成器是死代码（功能上线即空清单，缺陷暂不可达但接线即爆炸）。
  3. **async clustering 批量窗（P3）** — 每任务只处理一批不再排空（100 题队列卡 60 题 pending）；后台任务用**触发者**的 LLM 配置处理 dequeued 的**他人**桶（跨用户数据 + 配置暴露）。
- 🟡 **LLM compat 层 Responses 路径静默失效**：`stream_llm_messages` 的 responses 流式分支丢 system prompt（不设 instructions）、把 chat 格式的 `max_tokens` 原样转发给 `responses.create`（openai==1.30.0 只认 `max_output_tokens` → TypeError）。用户选了 `api_format=responses` 时功能静默降级/失效。
- 🟡 **oauth-gateway 资源绑定收紧有兼容风险**：新严格校验下旧 `aud=mcp` token 全部被拒，需要客户端在 authorize **和** refresh 都带 `resource=<public-base>/mcp`；无任何 gateway 测试。
- 🟢 **审查结论干净面**：admin 端点全部 `get_admin_user` 门控、无 IDOR；新增代码无 `eval`/代码执行、无密钥泄露、LLM 重试有界且幂等、SQL 全参数化；recruitment milestones 时区/负间隔/除零全干净；mastered 抽查桶逻辑正确；chat rerank 降级干净。

---

## 一、修复计划落实情况（对照 `security-fix-plan-2026-08-05.md`）

### Tier 0 — 已完成 4/5

| # | 修复项 | 状态 | 验证 |
|---|---|---|---|
| 1 | WAL 在线备份 | ✅ 完成（工作区） | `backup_sqlite_wal` sqlite3→python3 双通道。宿主无 sqlite3 CLI，走 python3 分支；实测 python3 `sqlite3.backup` 能拿到未 checkpoint 的已提交事务、integrity_check=ok。**注意：`deploy/docker-deploy.sh backup` 尚未实测整链路，restore 子命令未做（属 Tier 1 #6 的 D6-2）** |
| 2 | PROJECT_DIR 硬编码 | ✅ 完成（工作区） | 改为 `$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)` |
| 3 | Git hook 文档谎言 | ⚠️ 部分 | `.githooks/commit-msg` 已建、本机 `core.hooksPath=.githooks` 已配，但 **`.githooks/` 未纳入 git 跟踪**（untracked），无安装脚本/文档。新克隆无 hook → CLAUDE.md "Git hook 自动检查" 对新鲜克隆仍是谎言 |
| 4 | oauth-gateway root + DB 挂载 | ✅ 完成（工作区） | `USER oauthuser` + 命名卷 `oauth-gateway-data:/app/oauth-data`（空卷继承镜像属主，可写）；DB 挂载保留 `:ro`（合理收窄）；nginx.conf 显式 `user nginx;` |
| 5 | Dockerfile 基础镜像 EOL | ✅ 完成（工作区） | node:22-alpine / python:3.12-slim-bookworm / nginx:1.29-alpine；`.python-version` 3.12；`requires-python >=3.11` |

### Tier 1 — 未完成 11/14（完成 3 项均部分）

| # | 修复项 | 状态 |
|---|---|---|
| 6 | users.email UNIQUE（D14-1） | ❌ 未做（已 grep 确认无 UNIQUE index） |
| 7 | verify_code 原子门控（D14-3） | ❌ 未做 |
| 8 | 验证码 expires_at UTC（D14-2） | ❌ 未做 |
| 9 | FTS IDF 缓存失效（D14-4） | ❌ 未做 |
| 10 | nodes.py 裸 except（D14-5） | ❌ 未做 |
| 11 | MCP query-param 认证（D4） | ❌ 未做 |
| 12 | ruff lint | ❌ 未做 |
| 13 | eslint / tsconfig strict | ❌ 未做 |
| 14 | 5 处 catch 静默吞错 | ⚠️ SettingsAdmin 已迁移 `useConfirm`/toast 化（前端 agent 确认），其余未确认 |
| 15 | 边缘服务 healthcheck | ❌ 未做（compose 仍只有 backend/redis 两个） |
| 16 | a11y 三处 | ⚠️ SettingsAdmin aria-label + useConfirm 完成；**PracticePanel:19 仍无 aria-label、PracticeDecksView:51 仍用 window.confirm、SettingsAdmin:205/221 input 仍无 label** |
| 17 | README/CLAUDE.md 互斥 | ⚠️ clone URL（gitee.com/satanstoy/interview-boss.git）+ 分支规则已修；**仍 `http://localhost`（README:128，应 127.0.0.1:8081）、agent 框架表仍写 chat=LangGraph（README:73）** |
| 18 | JWT_SECRET .env.example 占位符 | ❌ 未做（`backend/.env.example:13` 仍在） |
| 19 | HF_CACHE_DIR 环境变量 | ❌ 未做（compose 仍硬编码 `/home/ubuntu/.cache/huggingface`） |

### Tier 2-4 — 全部未开始
CI（#25）、test_auth_core（#26）、OTP 标识级限流（#20）、API key Fernet 加密（#21）、python-jose→PyJWT（#22）、uvicorn/passlib 升级（#23/24）、answers 异步化（#27）、用户配额（#28）、合规四件套（#29-32）、真 E2E/属性测试（#33/34）、四个巨型文件拆分（#35-40）。

### 计划外完成（正收益）
- **URL 校验落地**（比计划更全）：`core/validation.py` + 两个 submit 端点 + `update_generic_data` 的 interview/questions_detail/jd.url，配套 `test_update_url_validation.py` 6 用例。唯一残留：校验是 `^https?://` 前缀（`http://` 无 host 也过，Minor）。
- **fix-commit 测试配对率提升**：审计时"30 个 fix 0 个带测试"；本区间 16 个 fix 中 8 个同 commit 携带测试（frontend 样式/实验脚本类无测试预期）。

---

## 二、新代码发现（按严重度）

### 🔴 Critical / 合并前必须修

#### C1. 抽题 embedding 补充：跨用户私有题泄漏 + 静态 frequency 虚高 + 500 崩溃
`backend/app/services/question_draw_service.py:74-78, 201-216, 286-294`

`_embedding_supplement` 的查询：
```
SELECT id, question, cat1, cat2, tags, difficulty, frequency, ai_answer, embedding
FROM question_bank WHERE deleted_at IS NULL AND status = 'approved' AND embedding IS NOT NULL
```
三个独立缺陷（均已重读代码确认）：
1. **无 owner/岗位可见性过滤**：绕过 `build_bank_where_clause`，把**其他用户的私有 approved 题**拉进 `candidates`，经面试 agent `draw_questions_tool` 的 `candidate_questions`/SSE 暴露题面（最终 `select_question` 会再校验可见性，但候选泄漏已发生）。
2. **权重用静态 `qb.frequency`**：SQL 路径用 `({dyn_freq_sql}) as frequency`（动态来源数），补充路径用静态变体数；两池汇入同一 `_weighted_sample_without_replacement`（line 452 `row["frequency"]`）。静态 8 但 0 活跃来源的题权重 ≈6.0 vs 动态 1 的 ≈2.7，被多抽 ~2.2×，卡片还显示虚高 8 — 审计修过的"虚高"在抽题路径回归。
3. **embedding BLOB 进响应**：`item = dict(row)`（line 288）把 bytes 向量拷进返回项，FastAPI `jsonable_encoder` 对 bytes 做 `o.decode('utf-8')` → float32 二进制抛 `UnicodeDecodeError` → `GET /api/master-bank/random` 在 SQL 候选 <5 时 500。单元测试直调 `draw_questions` 不 JSON 序列化所以没抓到。

> 修复方向：补充查询改走与 SQL 路径相同的 `build_bank_where_clause` + 岗位过滤；SELECT 去掉 `embedding`（或用临时别名后剔除）；`frequency` 用动态子查询或从权重中剔除静态列。

---

### 🟠 Important（新代码，建议尽快修）

#### I1. `serialize_issue` 越界 IndexError → admin 清单接口整体 500
`backend/app/services/quality_issue_ops.py:51`（调用链：`routers/admin_quality.py:36`、`admin_assistant._stage_write`、`review_issue`）

`json_loads(qb["original_questions"])[row["variant_index"]]` 无越界检查。`split_variant`/`dedupe_variant`/维护合并都会缩短 `original_questions`，任何"拆了一个 index 后重开清单"的路径都让**整个** `GET /api/admin/quality-issues` 抛 IndexError 500，阻塞全部审批/拒绝。两个独立 agent 均确认。`weak_representative`（variant_index NULL）和 qb 已删（返回 ""）不受影响——只有 stale-index 场景会爆。

#### I2. `split_variant` 拆出的题恒为公共题（owner 泄漏，接线即爆）
`backend/app/services/clustering_maintenance.py:605, 634`

re-SELECT（line 605）没选 `owner_id`，line 634 `row["owner_id"] if "owner_id" in row.keys() else None` 恒为 False → 新题恒 `owner_id IS NULL`（公共）。若源 cluster 是个人题（`generate_quality_issues`/`generate_weak_representative_issues`/`run_quality_audit` 都不带 owner 过滤，个人 frequency>1 题是合法目标），审批 mismerge 会把个人变体+完整 sources 发布成公共题。**当前不可达**：issue 生成器无任何生产调用（见 I9），但接线后即为隐私泄漏。

#### I3. split/dedupe/refine 破坏 dual-write 与聚类不变量
`backend/app/services/clustering_maintenance.py:598-696`

三个操作都不调 `_sync_normalized_tables`、不设新拆题的 `cluster_id`/`embedding`/`question_position`；`refine_representative` 改 `question` 不重算 embedding。后果：拆/去重后 `audit_clustering_state` 立即报 `normalized_mismatch` + `null_cluster_id`，拆出的题对岗位过滤查询不可见；refine 后 embedding 编码旧代表题文本，`prefilter_centroids_batch` 用旧向量预筛 → 新题匹配被过滤、反造重复 cluster。

#### I4. 精确重复合并忽略 owner_id（跨公共/个人合并）
`backend/app/services/clustering_maintenance.py:141-145, 290-302`（`audit_clustering_state` 与 `run_clustering_maintenance` 合并循环均无 owner 过滤）

用户导入的题文本与公共 cluster 完全一致时，`POST /api/master-bank/clustering-maintenance`（生产端点，`dry_run=false`）把两行并入一个：若公共幸存，个人私有 sources 折进公共（泄漏）；若个人行 frequency 更高，公共题被并进个人行（全站少一道题）。**注意：此缺陷审计时已存在**（`git show b282e2cb` 含这些函数），非本区间引入，但新的 owner-agnostic 生成器会放大它；增量审查暴露而非回归。

#### I5. async clustering：每任务只处理一批不排空 + 用触发者身份处理他人批次
`backend/app/services/pipeline/queue.py:213-224, 89-94, 217`

1. `_run()` 只 `dequeue_batch(BATCH_SIZE=40)` 一次就复位 `_cluster_task_running`；100 题的队列聚类 40 后剩 60 永远 `pending`，直到下一次提交再触发（submit 图已不调 `should_trigger_clustering()`）。
2. `pending >= BATCH_SIZE` 的"立即执行"检查只在调度时刻跑一次；已有任务睡眠时新涌入的 100 题要等满 300s 窗口。
3. `cluster_batch(user_id=触发者)` 处理 `dequeue_batch` 返回的**任意桶**（`ORDER BY cnt DESC LIMIT 1`，无 NULL-first）。Alice 提交 1 题而 Bob 40 道个人题在桶里 → 用 Alice 的 LLM 配置把 Bob 的私有题发给 Alice 的 provider。桶隔离正确，**错的是 LLM user_id**，但正是隐私/正确性问题。

#### I6. `fix_source_consistency.py`：备份是 WAL 裸 cp + UNIQUE 冲突可整体中止
`backend/scripts/fix_source_consistency.py:259-262, 142-157`

1. "自动备份"是 `shutil.copy2(DB_PATH, ...)`，无 `wal_checkpoint`/`conn.backup()`；WAL 下恢复会丢最近已提交事务（docstring 声称已 checkpoint，实际没有）。破坏性脚本的安全网失效。
2. URL 归一化 `UPDATE ... SET url=keep_url WHERE url=drop_url` 在 `keep_url` 有软删行时与 `UNIQUE(question_bank_id, url)` 冲突（SQLite 唯一索引计入软删行）→ `IntegrityError` → 整个 repair 中止。测试只走 happy path，从没软删 `keep_url` 行。

#### I7. LLM compat Responses 流式：system prompt 丢失 + `max_tokens` TypeError
`backend/app/services/llm.py:1462-1485, 1465-1467`；`agents/chat/answer.py:373`

1. Responses 流式分支 `_convert_messages_to_responses_input(messages, "")` 跳过 `role=system`，且不设 `instructions` → 面试官行为护栏被丢，静默。
2. 调用方传 chat 格式 `max_tokens=200`，`kwargs` 原样转给 `responses.create`；openai==1.30.0 该 API 只接受 `max_output_tokens` → TypeError。answer.py 的 `try/except` 兜底 → 过渡句生成静默降级为机械 fallback，功能从未生效。用户在 UI 选 `api_format=responses`（compat 层宣传的能力）即踩中。

#### I8. oauth-gateway 资源绑定：旧 token 全拒 + 无测试
`oauth-gateway/proxy.py:58-64, 75-77`；`oauth-gateway/auth.py:48-62`

proxy 现在恒以 `expected_resource = f"{_public_base_url(request)}/mcp"` 校验，token 的 `aud`/`resource` 必须等于它。旧 token（`aud="mcp"`，升级前签发）全部 401；refresh 对 legacy 行（`resource=""`）不设 requested_resource 则新 token 依旧 `aud="mcp"` → 死循环拒绝。`resource` 是客户端在 authorize query param 传入的**未校验自由值**。整个 gateway 无自动化测试（连发现端点/授权码流程都没有）。需要对着真实 ChatGPT connector 端到端验证 authorize+refresh 都带 resource，否则集成静默断。

#### I9. issue 生成器是死代码 → 质量审查功能上线即空
`backend/app/services/clustering_maintenance.py:720-871`

`generate_quality_issues`/`generate_weak_representative_issues` 只有测试调用，无路由/cron 接线 → `quality_issue` 恒空，`admin_quality`/admin assistant 恒返回空清单。**且**其幂等去重是"check-then-insert"跨连接，并发双插未门控（当前不可达）。

#### I10. SettingsQuality 清单 30s 缓存不刷新 → 审批循环失效
`frontend/src/services/adminQualityApi.js:5`；`frontend/src/components/business/SettingsQuality.vue:38-47`

`fetchQualityIssues` 用 `http.get` 不带 `noCache`，而 `http.js` GET 默认 30s 缓存。审批/拒绝/批量后 `loadIssues()` 返回过期缓存，issue 仍显示 pending；再点 404。项目约定所有变更敏感 GET 都带 `noCache`（profileApi/chatApi/interviewApi 均如此），此处漏了。**品牌新功能的核心循环直接坏。**

#### I11. PracticePanel 裸 `:href="src.url"` 绕过 safeUrl
`frontend/src/components/business/PracticePanel.vue:61`

已知的 `internal://` 防御只修了 `QuestionCard.vue`，PracticePanel 的 `[原文]` 直接 `:href="src.url"`。后端会为无链接来源合成 `internal://<id>`（interview.py:79,135,229 等），点击即坏链接；若任何非 http 协议（`javascript:`/`data:`）进入 `question.sources`（legacy/管理端编辑），就是存储型 XSS 锚点。同文件其他位置和 QuestionCard/PracticeMode 都用 `safeUrl`——此处是漏网。

#### I12. PracticeMode 自评在替代导航下被丢弃
`frontend/src/components/business/PracticeMode.vue:454-483, 492-501`

自评只写 `selfRating`，只在"下一题"按钮提交；←/→ 快捷键、看题模式、切换题单都能在 `queueSwitchBlocked()` 放开后跳过提交。用户看到"自评已记录"但实际没落库，卡片保持 due。部分抵消 fca791b 的锁定意图。（无错题 id 问题——`markAndNext` 提交时读的是当前卡。）

---

### 🟡 Minor（记录，后续处理）

**LLM compat**
- M1 `llm_judge.py:90` `_strip_fences` MULTILINE 会剥掉 JSON 字符串值里行尾的 ``` ``` ``` → 静默篡改标签/代表题。
- M2 `llm_judge.py:27,49` 贪婪 `{.*}`/`[.*]` 跨多对象 over-capture → 静默丢结果（fail-safe）。
- M3 `llm.py:1280,1285` `get_user_llm_config` 同步 SQLite 直接在事件循环上跑，每次 LLM 调用多 2 次（批量并发 3 → ~9 次阻塞读）。
- M4 `llm.py:1231` `raw_llm_call` 对 `content=None`（纯 reasoning 模型）`.strip()` → AttributeError。
- M5 `answer_enrichment.py:252` critic 恒 `thinking=True`，在 mimo 端点（thinking 即空响应原因）上 critic 输出必短 → 解析失败 → 静默 PASS → refine loop 对目标端点无效。
- M6 mimo thinking-disable 不一致：`_call_llm_with_retry` Responses 分支和 `_call_llm_with_retry_messages` 都没做（对比 `raw_llm_call:1216`/chat 路径:1327 都做了）。

**Practice / draw**
- M7 `practice_review_service.py:24-30,40-81` `record_review` SELECT→算→upsert 无 `BEGIN IMMEDIATE`，同用户双 tab 并发 → lost update（两个事件行但状态 6 非 7）。
- M8 `practice_deck_service.py:289-330` due 路径 `due_rows`/`checkin_rows` 无 LIMIT 且忽略 `limit` 参数；500 due 题请求返回全部。
- M9 `practice_deck_service.py:265-267` `total` 未封顶而 `items` 受预算 → `total:300, items:30` 契约误导（前端 `usePracticeDecks.js` 用 total 算进度）。
- M10 `insights.py:14-29` `_count_unique_sources` 无 owner/deleted 过滤（对比 `get_dynamic_frequency_sql` 有 `qs.deleted_at IS NULL` + `i.owner_id`）：用户把私有面经 share 进公共题后，他人洞察"被问次数"虚高。

**Clustering / pipeline**
- M11 `admin_quality.py:97,106-109` batch `float(body.get("min_confidence", 0.85))` 无类型检查 → `"abc"` 500；且**无 0.85 下限**（`quality_issue_ops.batch_approve` 有 `max(0.85,...)`，admin_assistant 也有）→ 三处审批策略已漂移，违背 service docstring "共用一份实现，避免行为漂移"。router 的 approve/reject/batch 是 service 同名函数的**内联复制**（已漂移的证据）。
- M12 `clustering_maintenance.py:640,667,695` 三个操作中途 commit；`execute_issue` 与状态 UPDATE 非原子 → 崩溃后 issue 卡 pending，重试 409。
- M13 `worker.py:611-625,650` 质量审计 cron 是 `hour=3,minute=30` 无 day_of_week → **每晚跑**而非文档的"每周日"；报告文件名秒级时间戳可覆盖。
- M14 `queue.py:217-224` flush 非严格幂等：`cluster_batch` commit 后 `mark_batch_done` 前崩溃 → 重置 pending 重跑 → 重复 cluster（`--workers 2` + ARQ worker 三进程 + 各自 FAISS 缓存加剧）。
- M15 `writer.py:232-241` `_dedupe_variants` 近似启发式：最长变体替换不重查其他保留项、只对新 cluster 生效而 `apply_matched` 仍追加原始重复 → frequency 语义逐行漂移。
- M16 `tools.py:540` rerank `selected_indices` 不去重 → `[0,0,2]` 产出重复题；候选展示 1..N 而提示词要 0-based → off-by-one（有界但不纠正）。
- M17 `tools.py:19,22-42` `_RERANK_RELEVANCE_THRESHOLD`/`_parse_rerank_scores` 死代码。
- M18 `batch_generate/nodes.py:95-125` `asyncio.gather` 并发写 → 3 线程独立 SQLite 连接，重载下 `database is locked` 被当单题失败。

**修复脚本**
- M19 `fix_source_consistency.py:129-137` 物理 DELETE `questions_detail` 不碰 `analysis_queue` → 孤儿 pending 条目让 `get_pending_count` 恒 >0，每次提交都跑空转后台任务。
- M20 `fix_source_consistency.py:256` 默认 sqlite3 无 `busy_timeout`，仅 `--dry-run` 挡 mutation 无确认提示。

**oauth-gateway / 杂项**
- M21 `oauth-gateway/proxy.py:26-42` + `oauth.py:35-45` 直接信任 `X-Forwarded-Host`（无代理白名单）；单资源部署下自我抵消，多资源时是配置面风险。
- M22 调试残留：`oauth-gateway/oauth.py.orig`、根 `dbg-tmp.mjs`、`frontend/dbg-tmp.mjs`、`frontend/tests/smoke/dbg-console.spec.js` — 提交前清理。
- M23 `core/validation.py:12` `^https?://` 前缀校验，`http://`（无 host）通过。
- M24 `persist_public.py:25`（既有）share 审核门未落到 cluster 写库行（默认 `approved`），async 化后流程更隐蔽 — 建议确认意图。

**前端**
- M25 `PracticeMode.vue:64` 移动端"展开题目列表"在 quiz 模式是死按钮（aside 仅 browse 模式 v-if）。
- M26 `PracticeMode.vue:503-517` "已刷过的题"弹窗首次加载后不刷新（`practicedList.length===0` 才拉）。
- M27 新 UI 大量 `text-[10px]`/`text-[11px]` 低于 text-xs 基线；SettingsQuality 状态 tab 无 `role="tab"`/`aria-selected`。

---

## 三、验证过的干净面（无需改动）

- **授权**：`admin_quality` 四个端点 + `admin_assistant` 全部 `Depends(get_admin_user)`；无 IDOR。
- **SQL**：全部参数化；`get_dynamic_frequency_sql` 内插的 user_id 来自 DB 行而非 JWT。
- **LLM 安全**：无 `eval`/`ast.literal_eval`/pickle；模型输出不进 SQL；tenacity 重试有界且幂等；`api_format`/`thinking` 写入白名单校验。
- **recruitment milestones**：无负间隔、无除零、mastered +30 天正确、时区统一 naive-UTC。
- **chat rerank 降级**：异常/空选/越界全部回退原始 envelope。
- **fix_source_consistency SQL 注入**：无（全参数化）。
- **match_new_questions 单次调用去重**：`group_matched_ids` + 每 cat2 分组保证一道题最多落一个 cluster。

---

## 四、Triage — 建议处理顺序

| 优先级 | 事项 | 归属 |
|---|---|---|
| 🔴 立即（合并前） | C1 抽题 embedding 补充（owner 过滤 + 去 embedding BLOB + 动态频率） | question_draw_service |
| 🔴 立即 | I1 serialize_issue 越界 + I2 split_variant owner + I3 dual-write/embedding 不变量 | 质量审查执行链 |
| 🔴 立即 | I7 Responses 流式 system/max_tokens | llm.py |
| 🔴 立即 | I5 async clustering 排空 + 触发者身份 | queue.py |
| 🟠 本周 | I6 fix_source_consistency 备份/UNIQUE 中止；I11 PracticePanel raw href；I10 缓存刷新 | 脚本/frontend |
| 🟠 本周 | I8 oauth-gateway resource 兼容 + 补测试 | oauth-gateway |
| 🟠 本周 | 修复计划 Tier 1 剩余：#6 email UNIQUE、#7/8 验证码、#9 IDF、#10 裸 except、#11 MCP query、#16 a11y 两处、#17 README 两处 | 认证/运维 |
| 🟡 排期 | 死代码接线前先修 I2/I3（或生成器限定 `owner_id IS NULL`）；I9 决定接线与否 | 聚类 |

---

## 附注

- 本报告所有 Critical/Important 结论均经主线程重读源码复核。复核状态分两批：
  - 写报告时已亲自重读：C1（三条全链路）、I1、I2、I3、I4、I7（含 openai 1.30.0 SDK 签名）、I8、I9、I11、M11。
  - 2026-08-07 追问后补验的 agent 结论（均亲自重读确认）：I5 队列排空/触发者身份（`queue.py:180-224` 单批 + 调度时刻一次判断 + `ORDER BY cnt DESC` 无 NULL 优先 + `cluster_batch(user_id=触发者)`）、I6 备份裸 cp + UNIQUE 软删冲突（`fix_source_consistency.py:259-262,142-157`）、I10 前端 30s 缓存（`adminQualityApi.js:5` + `http.js:303-318` + `SettingsQuality.vue` 审批后 reload）、I12 自评丢弃（`PracticeMode.vue:454-501`）、M1 `_strip_fences` MULTILINE、M5 critic 恒 `thinking=True`。
  - 另核对：I4 为既有缺陷（`git show b282e2cb` 已存在），非本区间回归；I2/I3/I9 当前因 issue 生成器未接线而**不可达**（接线后即爆），报告中已注明。
- 新增测试建议随修复走 TDD：`question_draw_service` 补充路径的 JSON 序列化回归（补 C1-3）、`serialize_issue` 越界、async queue 排空/身份、oauth-gateway token 流程（首次引入 gateway 测试）。
