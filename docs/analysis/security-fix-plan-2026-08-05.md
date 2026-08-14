# 安全/工程缺陷修复清单 — 从简单到困难

**来源**: tech audit 2026-08-05（`docs/analysis/tech-audit-2026-08-05.md`，HEAD b282e2c）
**原则**: 每个修复遵循 TDD（先写失败测试 → 最小实现 → 验证）；全部完成后跑 `./deploy/docker-deploy.sh check`
**难度分级**: Tier 0 十分钟 → Tier 4 重构级。安全类缺陷（D4/D5/D11/D14）标 🔒

> **⚠️ 状态对账（2026-08-14，HEAD e7f11b2）**：40 项经当前代码逐项复核——**FIXED 11 / MITIGATED 11 / STILL-OPEN 18**。已修：1,2,3,4,5,6,17,18,25,27（+11(修复)）；仍开放：8(时区),9(FTS),10(裸except),19(HF路径),20(OTP锁定),21(API加密),22(jose),23(uvicorn),24(passlib),26(JWT测试),28(配额),29(注销),30(隐私),31(data-flow),32(导出),34(fuzz),35(chat_service拆分),37(ChatView),38(LoginModal shadcn),40(Vite)；半修/静默失效：7,11,12,13,14,15,16,33,36,39（含 **check.sh 静态检查静默失效**：run_static_backend/run_static_frontend 未定义）。完整 TSV 见 `.tech-audit/work/2026-08-14/interaction/` 对账产物。

---

## Tier 0 — 十分钟级（配置/一行改动，无需测试）

| # | 缺陷 | 位置 | 改法 | 验证 |
|---|---|---|---|---|
| 1 | 🔒 **备份对 WAL 活库裸 cp（数据丢失向量）** | `deploy/docker-deploy.sh:401` | `cp` 改为 `sqlite3 "$DB" ".backup '$dest'"`，加 `|| echo "backup failed"` 失败退出 | 手动跑 `./deploy/docker-deploy.sh backup`，对比备份文件大小与 DB 一致；`sqlite3 "$dest" "PRAGMA integrity_check"` = ok |
| 2 | **PROJECT_DIR 硬编码家目录，新克隆即失败** | `deploy/docker-deploy.sh:9` | 改 `PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"` | `./deploy/docker-deploy.sh status` 正常输出 |
| 3 | **Git hook 文档谎言（CLAUDE.md 声称自动检查）** | `CLAUDE.md` + `.git/hooks/` | 二选一：a) 落地 `commit-msg` hook（正则校验 Conventional Commits + 安装脚本）b) 删掉 CLAUDE.md 声明。建议先 a | `git commit -m "test"` 被拒；`git commit -m "chore(x): test"` 通过 |
| 4 | 🔒 **oauth-gateway 以 root 运行且挂载生产 DB** | `oauth-gateway/Dockerfile:11` + `Dockerfile:145` | oauth-gateway 加 `USER` 非 root；nginx-runtime 显式 `user nginx;`；移除/收窄 DB `:ro` 挂载 | `docker compose config` 校验；容器内 `id -u` 非 0；`./deploy/docker-deploy.sh update` 后服务正常 |
| 5 | **Dockerfile 基础镜像 EOL** | `Dockerfile:15,30,145` | node:20→22-LTS、python:3.10→3.11/3.12-slim（同步 `pyproject.toml` requires-python）、nginx:1.27→1.29 | `./deploy/docker-deploy.sh update` + `check` |

---

## Tier 1 — 小时级（≤2h，含测试）

| # | 缺陷 | 位置 | 改法 | 验证 |
|---|---|---|---|---|
| 6 | 🔒 **users.email 无 UNIQUE 约束 → 2 worker 下重复账号** | `backend/app/db/migrations/auth.py:87` + `routers/auth.py:668` | 迁移加 `CREATE UNIQUE INDEX`（SQLite 允许多 NULL）；`_insert_user` 捕获 `IntegrityError` 返回 409 | TDD: 测试并发注册同邮箱 → 一个 201 一个 409；跑 `pytest backend/tests/security/ -q` |
| 7 | 🔒 **验证码双用竞态（并发两次都通过）** | `backend/app/services/email_service.py:112` | 改原子门控：`UPDATE ... SET used=1 WHERE id=? AND used=0`，rowcount==1 才返回 True | TDD: 测试两次并发验证同一 code → 仅一次成功；跑 chat/security 相关用例 |
| 8 | 🔒 **验证码有效期存本地时区（其余 UTC）** | `backend/app/services/email_service.py:81` | `datetime.now(timezone.utc)`，读侧统一 aware 比较 | TDD: 测试跨时区偏移下 code 过期判断正确 |
| 9 | **FTS IDF 缓存永不失效 → RRF 权重永久陈旧** | `backend/app/services/fts_service.py:73` | `sync_fts_entry`/`delete_fts_entry` 里重置 `_idf_cache`；全量扫描加行数上限 | TDD: 测试增删题后 IDF 变化；跑 `pytest backend/tests/services/ -q` |
| 10 | **裸 except 吞错（元数据启发式）** | `backend/app/agents/chat/nodes.py:1338,1352,1432,1449` | 改 `except Exception` + debug log，保留空串 fallback | TDD: mock DB 抛错 → 返回空串且日志有记录 |
| 11 | 🔒 **MCP 认证接受 query 参数 + 非恒定时间比较** | `backend/app/mcp_server/app.py:123` | 移除 `mcp_api_key` query 通道；hash token 后查表比较 | TDD: 测试 query 参数不再生效；header 认证正常 |
| 12 | **backend 无 lint 配置/步骤** | `pyproject.toml` + `scripts/check.sh` | 加 `[tool.ruff]`（F/E/I + S 精选），`ruff check backend/app` 接入 check.sh 作为阻断步骤 | `ruff check backend/app` 通过；`./deploy/docker-deploy.sh check` 含 lint 阶段 |
| 13 | **前端无 eslint/tsconfig strict** | `frontend/` | 加 eslint flat config（vue/js）+ lint script；`tsconfig.json` 开 `"strict": true` | `npm run lint` 通过；`npx vue-tsc --noEmit` 无新错误（存量按需修复） |
| 14 | **5 处 catch 静默吞错（用户看到空白）** | `SettingsAdmin.vue:34, ModelSelector.vue:168, SettingsInterview.vue:33,62, KnowledgeGraph.vue:64, NewChatModal.vue:193` | 统一 `useToast` 错误上浮 + 失败态 | Playwright smoke 触发失败路径截图/断言 toast 出现 |
| 15 | **边缘服务无 healthcheck** | `docker-compose.yml:90,133,159` | nginx `curl -f http://localhost:80/`；oauth-gateway `/healthz`；worker 存活探测 | `docker compose ps` 显示 healthy |
| 16 | **a11y 缺失（icon-only 无 label、input 无 label、原生 confirm）** | `PracticePanel.vue:19, SettingsAdmin.vue:185, PracticeDecksView.vue:52` | 补 `aria-label`/sr-only label；window.confirm 换共享 `useConfirm()` | 人工 + axe 快扫；现有 e2e 不回归 |
| 17 | **README/CLAUDE.md 多处互斥/占位符** | `README.md:272,309,317,373-406,461-462,673` + `CLAUDE.md:7,73` | 修正 clone URL、端口 8081、uvicorn 开发步骤、分支规则与 CLAUDE.md 一致、LangGraph→async harness 表述、`docker compose build` 改 `docker-deploy.sh frontend` | 通读两文档无矛盾；`docs/analysis/` 报告引用路径可达 |
| 18 | **JWT_SECRET 占位符与自动生成逻辑矛盾** | `backend/.env.example:15` | 删除该行，注释说明系统自动生成 | `backend/.env.example` 无操作员可填的集群内部密钥 |
| 19 | **compose 硬编码操作员家目录（HF 缓存）** | `docker-compose.yml:42-43` | `${HF_CACHE_DIR:-./.hf-cache}` 环境变量 + .env 声明 | 新主机 `docker compose config` 无 `/home/ubuntu` 路径 |

---

## Tier 2 — 半天级（M）

| # | 缺陷 | 位置 | 改法 | 验证 |
|---|---|---|---|---|
| 20 | 🔒 **OTP 无每邮箱限流（分布式爆破可接管账号）** | `backend/app/services/email_service.py:195` + `routers/auth.py` | verify_code 加按 email+purpose 失败计数，5 次失败即作废 code 并锁退；验证码改 8 位字母数字混合 | TDD: 测试连续 5 次错误 → 第 6 次正确也拒绝；跑 auth 全量用例 |
| 21 | 🔒 **用户 API key 明文落库** | `backend/app/core/config.py:109` + `routers/profile_pkg/llm.py:114` | 环境变量派生密钥（Fernet）加密 `api_key` 字段，读取时解密；已有明文数据加迁移脚本 | TDD: 测试加密往返 + 无 key 时解密报错；迁移后 DB 无明文 |
| 22 | 🔒 **python-jose 弃维护（token 签发/校验库）** | `pyproject.toml:17` + `backend/app/core/auth.py:7` | 迁移 PyJWT，保持 `algorithms=[HS256]/issuer/require_sub` 参数 | 全量 `pytest backend/tests/security/ -q` 通过（含既有 token 兼容性） |
| 23 | **uvicorn pin 2.5 年未动（含安全修复）** | `pyproject.toml:14` | 放开 `==0.24.0` → `>=0.30`（先 TDD: SSE/超时行为回归） | `uv lock` 重解析 + `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q` |
| 24 | **passlib 停更锁死 bcrypt** | `pyproject.toml:15-16` | 弃 passlib 直调 bcrypt（或 argon2-cffi），删 bcrypt 上界 | TDD: 密码 hash/verify 往返 + 存量 hash 兼容 |
| 25 | **零 CI** | 仓库根 | GitHub Actions：push/PR 跑 `docker-deploy.sh check`（pytest test-runtime + 前端 build/smoke + audit） | push 触发 workflow 全绿 |
| 26 | **JWT 核心零直接测试** | `backend/app/core/auth.py:162` | 新增 `test_auth_core.py`：过期/错签→401、refresh 轮转+family 失效、错误密码→登录锁、真实 `/api/auth/login` HTTP 流程 | `pytest backend/tests/security/test_auth_core.py -q` 全绿 |
| 27 | **answers.py 同步 LLM 调用（504 候选）** | `backend/app/routers/answers.py:63,138` | 改 SSE 流式或入 ARQ worker（复用 `submit.py:276` enqueue） | TDD: 端到端生成返回流式事件；长请求不阻塞其他请求 |
| 28 | 🔒 **LLM 消耗无按用户配额（预算燃烧）** | `routers/chat.py:270` + `routers/answers.py` | LLM 调用前 per-user 每日 token/次数配额门禁（复用 token_count 列聚合），或移除未配置用户全局 key fallback | TDD: 配额耗尽 → 429；`/api/analytics/token-usage` 聚合正确 |

---

## Tier 3 — 一天级（L）

| # | 缺陷 | 位置 | 改法 | 验证 |
|---|---|---|---|---|
| 29 | 🔒 **无账号注销路径（PIPL 47 条删除权）** | `backend/app/routers/profile_pkg/` | delete-account endpoint：级联硬删或匿名化（审计日志保留但脱敏 PII）；设置页入口 + 二次确认 | TDD: 注销后登录失败、数据不可查、审计日志仍可追溯但无 PII |
| 30 | 🔒 **无隐私政策/用户协议（PIPL 13/17 告知义务）** | `frontend/src/views/` + 注册流程 | 新增隐私政策 + 用户协议页面 + 路由，注册处勾选确认 | 页面可达、内容覆盖数据类别/用途/第三方；Playwright 注册流程含勾选 |
| 31 | 🔒 **无 sub-processor/数据流文档** | `docs/privacy/data-flow.md`（新建） | 映射每类数据（简历/音频/消息/提示词）→ 存储位置 → 第三方处理者（LLM/Deepgram/邮箱） | 文档存在且与代码实际调用一致 |
| 32 | **无用户数据导出（可携带性）** | `backend/app/routers/`（新增） | `/api/profile/export-data` JSON 打包 + 下载 | TDD: 导出内容覆盖 JD/面试记录/聊天/答案 |
| 33 | **零真 E2E（live_llm 被 CI 剔除）** | `backend/tests/conftest.py:36-50` + CI | CI 加 `RUN_LIVE_LLM_TESTS=1` 的 test-runtime 任务跑 chat 全链路（候选消息→SSE→工具调用→回复渲染） | CI 任务全绿且未被跳过（collect 数含 live 用例） |
| 34 | **零 property-based / 边界语料测试** | `backend/tests/` | decode_token/sanitize/chat 输入守卫加 hypothesis；固定 XSS/超长/unicode 语料表参数化注入登录/题目保存/聊天 | `pytest backend/tests/` 新增用例全绿 |

---

## Tier 4 — 重构级（需排期，1-2 天/项）

| # | 缺陷 | 位置 | 改法 | 验证 |
|---|---|---|---|---|
| 35 | **chat_service.py 2289 行巨兽** | `backend/app/services/chat_service.py` | 拆 `services/chat/{turns,messages,memories,side_effect_jobs}.py`，router 层 re-export 保持 API 不变 | 每步拆分后 `pytest backend/tests/chat/ -q` 全绿；最后全量回归 |
| 36 | **nodes.py 2028 行** | `backend/app/agents/chat/nodes.py` | prompt 构建器移入 `prompts.py`，LLM 助手移入 `services/llm.py` | 同上，`backend/tests/pipeline/` 全绿 |
| 37 | **ChatView.vue 1539 行** | `frontend/src/components/business/ChatView.vue` | 流式/会话逻辑提取 composables（已有 19 个 use* 先例） | `npm run build` + 前端 e2e 全绿 |
| 38 | **LoginModal 1142 行 + 绕过 shadcn** | `frontend/src/components/business/LoginModal.vue:82` | 按模式拆子组件；27 个裸 button/input 迁移 ui/ 组件 | 视觉对比 + 登录/注册/重置流程 e2e |
| 39 | **ECharts 硬编码 38 hex 复制 token** | `PracticeTrendChart.vue:83, KnowledgeGraph.vue:52` | `getComputedStyle` 读 CSS 变量喂 ECharts 或建共享 palette 模块 | 明暗主题下图表配色一致 |
| 40 | **Vite 4 EOL + 前端依赖落后 1+ 大版本** | `frontend/package.json:52` | Vite 7/8 逐大版本升级 + 配套插件（plugin-vue/tailwind/zod/vue-router）；vue-virtual-scroller beta→3.x stable | 每步 `npm run build` + smoke；最后 `npm audit` 清零高危 |

---

## 执行顺序建议（每日门禁始终保绿）

```
第 1 天: Tier 0 (1-5) → 立即堵住数据丢失 + 部署不可复现
第 2 天: Tier 1 (6-11) → 安全类：邮箱唯一约束/验证码竞态/时区/MCP 认证
第 3 天: Tier 1 剩余 (12-19) → lint 强制 + 文档一致性 + a11y
第 4-5 天: Tier 2 (20-24) → 认证加固三件套（OTP/密钥加密/库迁移）+ 依赖
第 6 天: Tier 2 (25-28) → CI + JWT 测试 + 配额门禁
第 7-9 天: Tier 3 (29-34) → 合规四件套 + E2E/属性测试
之后: Tier 4 (35-40) → 按 churn 热区逐个拆分巨兽
```

**验收标准**: 全部完成后 `./deploy/docker-deploy.sh check` 全绿；🔴 从 13 → 0；`docs/analysis/tech-audit-2026-08-05.md` 中每条 🔴 有对应关闭记录（在 `.tech-audit/accepted.tsv` 或报告中标注）。
