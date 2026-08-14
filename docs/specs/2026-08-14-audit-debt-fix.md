# Audit 债务修复 Spec — 2026-08-14 续跑（未改进项）

> 来源：三份 tech-audit 对账（`.tech-audit/work/2026-08-14/2026-08-14-audit-reconciliation.md`）的 STILL-OPEN 项，按风险排序。
> 原则：TDD（先写失败测试）→ 最小实现 → 验证 → 提交。配置类修改附静态断言测试。
> 方法：writing-plans 原子任务拆分，每个 Task 2-5 分钟；涉及数据库迁移的任务先备份。
> 状态口径：✅ 完成 / 🚧 进行中 / ⬜ 未开始

## 范围总览（按紧要度）

| 阶段 | # | 发现 | 风险 | 修复 | 状态 |
|---|---|---|---|---|:---:|
| P0 | A | 并发邮箱注册/bind → 500（应 409） | 🟡 并发数据完整性 | 捕获 IntegrityError 转 409 + API 级测试 | ⬜ |
| P0 | B | check.sh 静态检查静默失效（run_static_* 未定义） | 🟢 门禁形同虚设 | 补函数定义，ruff/eslint 真正接线 | ⬜ |
| P0 | C | verify_code 双用竞态 + email 本地时区 | 🟡 验证码可双过 | 原子门控 + UTC | ⬜ |
| P0 | D | 用户 LLM/搜索 API key 明文落库 | 🟡 敏感数据泄露 | Fernet 加密 api_key | ⬜ |
| P1 | E | 复习提交无幂等键（超时重发双写） | 🟡 数据重复+调度错乱 | 幂等键门控 | ⬜ |
| P1 | F | practice evaluate-answer 双写 user_practice_history + record_review | 🟡 口径不一致 | 统一写路径/去重 | ⬜ |
| P1 | G | 动态频率 SQL / practice_deck difficulty f-string 插值 | 🟢 潜在注入面 | 白名单+参数化兜底 | ⬜ |
| P1 | H | 软删读路径漏过滤 ×4（chat JD / profile season / data restore-batch / mutations merge-split） | 🟢 数据可见性 | 补 deleted_at 过滤 | ⬜ |
| P2 | I | CI 依赖引导 + gitleaks allowlist | 🟡 CI 必红 | ci.yml 补引导；.gitleaks.toml | ⬜ |
| P2 | J | 测试文件真实 key 字面量 | 🟡 敏感信息进仓库 | 改拼接/mock | ⬜ |
| P2 | K | LLM per-user 配额 + 成本追踪 | 🟡 预算燃烧 | 配额门禁 + llm_usage 表 | ⬜ |
| P2 | L | admin 弱口令长度校验 | 🟡 爆破风险 | 长度校验 | ⬜ |
| P3 | M | python-jose/passlib → PyJWT/argon2；uvicorn 解钉 | 🟡 弃维护+CVE | 库迁移 + 升级重测 | ⬜ |
| P3 | N | OTP 8 位码 + per-email 锁定 | 🟡 OTP 爆破 | 8 位码 + 失败锁定 | ⬜ |
| P3 | O | worker/nginx/oauth healthcheck | 🟢 运维可观测 | healthcheck + do_status | ⬜ |
| P3 | P | restore 命令/runbook/cron 可见性 | 🟢 事故就绪 | do_restore + runbook + last_run_at | ⬜ |
| P3 | Q | PIPL 合规四件套（隐私/删除/sub-processor/导出） | 🟡 合规 | 页面+接口+文档 | ⬜ |
| P3 | R | test 容器挂生产 data 卷隔离 | 🟡 污染真库 | 独立测试卷/TEST_DB_PATH | ⬜ |
| P4 | S | god-file 拆分（chat_service/nodes/ChatView/LoginModal） | 🟢 可维护性 | 逐文件拆分 | ⬜ |
| P4 | T | 依赖陈旧（Vite/uvicorn）+ Dependabot | 🟢 生态滞后 | 升级 + 接线 | ⬜ |

**不做（本轮）**：D11 合规页（含产品决策，单独 review）；gitleaks 历史清洗（破坏性，需用户确认远端后单独执行）；真全栈 E2E（大工程另行规划）。

---

## 阶段 P0 — 安全/数据完整性（本轮优先，建议先做）

### Task A: 并发邮箱注册/绑定 IntegrityError → 409
**Files**: `backend/app/routers/auth.py`、`backend/tests/security/test_email_unique.py`、`backend/tests/security/`（新）
**现状**：migration 079 加唯一索引后，并发重复 email 的第二个请求 `_create` 泛 `except Exception` → 500；`_insert_user` 裸 INSERT 无 try → 全局 500。应为 409。
- [ ] Step 1（RED）：`test_email_unique.py` 增 API 级测试——并发（或顺序两次）注册同邮箱 → 一 200 一 409（非 500）
- [ ] Step 2：跑测试确认失败
- [ ] Step 3（GREEN）：`register` 的 `_create` / `/register-with-email` 的 `_insert_user` / `bind_email_with_token` 捕获 `sqlite3.IntegrityError` → `HTTPException(409)`
- [ ] Step 4：跑 `pytest backend/tests/security/ -q` 全绿
- [ ] Step 5：提交 `fix(auth): return 409 on concurrent duplicate email`

### Task B: check.sh 静态检查真正接线
**Files**: `scripts/check.sh`
**现状**：`run_audit()` 调 `run_frontend_audit`/`run_backend_audit`（已定义）+ `run_static_backend`/`run_static_frontend`（**未定义**）→ bash 静默跳过，ruff/eslint 从不执行。
- [ ] Step 1（RED）：结构测试断言 `scripts/check.sh` 含 `run_static_backend()`/`run_static_frontend()` 函数定义（`backend/tests/infra/test_check_scripts.py`）
- [ ] Step 2：跑测试确认失败
- [ ] Step 3（GREEN）：在 check.sh 定义两函数，`run_static_backend` 调 `ruff check backend/app`（audit WARN），`run_static_frontend` 调 `npx eslint frontend/src`（`cd frontend && npm run lint`）
- [ ] Step 4：本地 `./scripts/check.sh audit`，确认 ruff/eslint 真实输出
- [ ] Step 5：提交 `fix(build): wire ruff+eslint static checks into check.sh audit`

### Task C: verify_code 原子门控 + 邮箱 UTC
**Files**: `backend/app/services/email_service.py`、`backend/tests/security/test_email_auth.py`
**现状**：`verify_code` 读 used=0 与 `_mark_code_used` 分两次连接，两 worker 并发可双过；`datetime.now()` naive。
- [ ] Step 1（RED）：`test_email_auth.py` 增异步并发调用同 code → 仅一次返回 True；增跨时区过期判断
- [ ] Step 2：跑测试确认失败
- [ ] Step 3（GREEN）：`_mark_code_used` 改 `UPDATE ... WHERE used=0`，`verify_code` 依据 rowcount 决定返回值；到期比较改 `datetime.now(timezone.utc)`
- [ ] Step 4：`pytest backend/tests/security/ -q` 全绿
- [ ] Step 5：提交 `fix(email): atomic verify_code gate + UTC expiry`

### Task D: 用户 API key Fernet 加密
**Files**: `backend/app/core/config.py`、`backend/app/routers/profile_pkg/llm.py`、`backend/app/services/`（密钥派生）、`backend/tests/security/`（新）
**现状**：`user_llm_config.api_key` / `search_api_key` 明文存储。
- [ ] Step 1（RED）：测试加密往返 + 无密钥时解密抛错 + DB 不含明文
- [ ] Step 2：跑测试确认失败
- [ ] Step 3（GREEN）：环境派生密钥 Fernet 加密写入、读取解密；存量明文迁移脚本
- [ ] Step 4：`pytest backend/tests/security/ -q` 全绿
- [ ] Step 5：提交 `fix(security): encrypt user LLM/search API keys at rest`

---

## 阶段 P1 — 正确性/数据一致性

### Task E: 复习提交幂等键
**Files**: `backend/app/routers/practice.py`、`backend/app/services/practice_review_service.py`
**现状**：前端/网络超时重发自评会双写 `practice_review_events` 并二次推进 SRS。
- [ ] Step 1（RED）：测试重复提交同 client_request_id → 仅一次生效
- [ ] Step 2-4：GREEN 实现幂等键门控（复用前端 `client_request_id` 或在请求体加 idempotency_key），全量回归
- [ ] Step 5：提交 `fix(practice): idempotent review submission`

### Task F: practice evaluate-answer 双写统一
**Files**: `backend/app/routers/practice.py`、`backend/app/services/practice_review_service.py`
**现状**：同一评估同时写 `user_practice_history` 与 `record_review`（SM-2），口径/状态可能不一致。
- [ ] Step 1：测试断言单次评估只更新一张历史表（或明确双写保持一致性的契约）
- [ ] Step 2-4：收窄写路径，明确唯一事实源
- [ ] Step 5：提交 `fix(practice): unify evaluate-answer write path`

### Task G: f-string 插值审计与参数化兜底
**Files**: `backend/app/services/practice_deck_service.py`、`backend/app/db/queries.py:89-96`（get_dynamic_frequency_sql）
**现状**：`user_id`/`table_alias`/`difficulty` 直接 f-string 插入 SQL，声明白名单但无 regex 兜底确认。
- [ ] Step 1（RED）：结构测试断言插入片段经白名单/regex 门（`get_dynamic_frequency_sql` user_id 强转 int）
- [ ] Step 2-4：加 `int(user_id)` 前置强转 + 表别名白名单 regex 断言
- [ ] Step 5：提交 `fix(db): parameterize/guard f-string in dynamic-frequency and deck queries`

### Task H: 软删读路径补 deleted_at 过滤
**Files**: `backend/app/routers/chat.py:441`、`profile.py:106,187`、`data.py:613-628,687-692`、`questions_pkg/mutations.py:44,221,225,487`、`questions_pkg/bulk.py`
**现状**：多处读软删面经/JD 未过滤 `deleted_at`。
- [ ] Step 1（RED）：每个点加回归测试——软删记录不出现在对应读路径
- [ ] Step 2-4：逐文件补 `AND deleted_at IS NULL`；JD restore 补 owner 限定
- [ ] Step 5：提交 `fix(data): filter deleted_at across chat/profile/data/mutations reads`

---

## 阶段 P2 — 工程化/成本

### Task I: CI 依赖引导 + gitleaks allowlist
**Files**: `.github/workflows/ci.yml`、`.gitleaks.toml`（新）
**现状**：fresh-clone `check.sh all` 缺 node_modules/backend.env；gitleaks 历史 key 必红。
- [ ] Step 1：ci.yml 补 `npm ci` / `uv sync` / playwright install 引导；gate 只跑 gitleaks + 结构测试
- [ ] Step 2：`.gitleaks.toml` 精确 allowlist 测试 fixture
- [ ] Step 3：提交 `ci(workflow): add dependency bootstrap + gitleaks allowlist`

### Task J: 测试文件 key 字面量改拼接
**Files**: `backend/tests/security/test_secret_scan.py:20`、`backend/tests/infra/test_check_secrets.py:27`
- [ ] Step 1：改拼接 `"sk-" + "x"*44` / mock，断言无真实字面量
- [ ] Step 2：`filter-repo` 或确认远端私有后清理历史（需用户确认）
- [ ] Step 3：提交 `test(security): remove literal api key from tests`

### Task K: LLM per-user 配额 + 成本追踪
**Files**: `backend/app/services/llm.py`、`backend/app/services/answer_enrichment.py`、`routers/answers.py`、`db/migrations/llm_usage.py`（新）
**现状**：无配额门禁、无 usage 落库。
- [ ] Step 1（RED）：测试配额耗尽 → 429；`/api/analytics/token-usage` 聚合正确
- [ ] Step 2-4：llm_usage 表 + 每次调用捕获 response.usage 落库 + per-user 每日 token 配额门禁
- [ ] Step 5：提交 `feat(llm): per-user daily quota + usage tracking`

### Task L: admin 密码长度校验
**Files**: `backend/app/core/auth.py`、`backend/tests/security/`（新）
- [ ] Step 1（RED）：测试 <16 字符 ADMIN_PASSWORD 在 env 载入时拒绝
- [ ] Step 2-4：`core/config.py`/`auth.py` 对 ADMIN_PASSWORD 加 ≥16 校验，缺失/过短报错
- [ ] Step 5：提交 `fix(security): enforce admin password minimum length`

---

## 阶段 P3 — 依赖/合规/运维

### Task M: python-jose/passlib 迁移 + uvicorn 解钉
**Files**: `pyproject.toml`、`backend/app/core/auth.py`
- [ ] Step 1（RED）：token 签发/校验改为 PyJWT（保持 HS256/issuer/require_sub），密码 verify 改用 argon2-cffi 或 bcrypt 直连
- [ ] Step 2：uvicorn 解钉 `==0.24.0` → `>=0.30`，重跑 chat/security 回归
- [ ] Step 3：提交 `refactor(auth): migrate to PyJWT + argon2; unpin uvicorn`（依赖变更走 `uv add`/`uv remove`）

### Task N: OTP 8 位码 + per-email 锁定
**Files**: `backend/app/services/email_service.py`
- [ ] Step 1（RED）：连续 5 次错误 → 第 6 次正确也拒绝
- [ ] Step 2-4：验证码改 8 位字母数字 + 按 email+purpose 失败计数锁定
- [ ] Step 5：提交 `fix(security): 8-char OTP + per-email failure lockout`

### Task O/P: healthcheck + restore/runbook + cron 可见性
**Files**: `docker-compose.yml`、`deploy/docker-deploy.sh`、`backend/app/worker.py`、`docs/runbook/`（新）
- [ ] worker/nginx/oauth-gateway 加 healthcheck；`do_worker_up` 校验真实就绪
- [ ] `do_restore <backup>` + 一页恢复 runbook；worker cron 落库 last_run_at + 只读端点
- [ ] 提交 `feat(ops): healthchecks, restore command, runbook, cron visibility`

### Task Q: PIPL 合规四件套
**Files**: `frontend/src/views/`、`backend/app/routers/profile_pkg/`、`docs/privacy/data-flow.md`（新）
> 需产品决策，单独 review 后执行。隐私政策/用户协议页 + 注册勾选、delete-account 接口、sub-processor 文档、export-data。
- [ ] 确认合规口径（PIPL；若出现 EU/付费用户升 🔴）
- [ ] 提交 `feat(compliance): privacy/agreement pages + account deletion + data export + data-flow doc`

### Task R: test 容器数据卷隔离
**Files**: `docker-compose.yml` test 服务、`backend/app/core/config.py`、`backend/tests/conftest.py`
- [ ] test 服务改挂独立 `./backend/test_data` 或 `TEST_DB_PATH` 环境覆盖
- [ ] 保留 conftest 兜底断言（拒绝真实 DB_PATH）；跑 `test_api_does_not_write_production_db`
- [ ] 提交 `fix(test): isolate test container from production data volume`

---

## 阶段 P4 — 可维护性（低优，另行排期）

### Task S: god-file 拆分
**Files**: `backend/app/services/chat_service.py`（2395）、`backend/app/agents/chat/nodes.py`（2028）、`frontend/src/components/business/ChatView.vue`（1577）、`LoginModal.vue`（1142）
- [ ] 按 line_guard_overrides 逐文件拆分，每步跑全量回归，拆分后从 allowlist 移除

### Task T: 依赖升级 + Dependabot
**Files**: `frontend/package.json`（Vite 4→8）、`pyproject.toml`（uvicorn）、`.github/dependabot.yml`（新）
- [ ] Vite 逐大版本升级（plugin-vue 同步）；依赖升级后 `npm audit`/`pip-audit` 清零高危
- [ ] 提交 `chore(deps): upgrade vite/uvicorn + add dependabot`

---

## 执行顺序与门禁

```
P0 (A→D) → P1 (E→H) → P2 (I→L) → P3 (M→R) → P4 (S→T)
每完成 1 个 Task：python: docker compose --profile test run --rm test uv run pytest backend/tests/<域>/ -q
                 frontend: cd frontend && npm run build
每阶段收尾：./deploy/docker-deploy.sh check
```

**验收标准**：P0-P2 全部完成 → 对应 🔴/🟡 安全与并发项关闭；`check.sh all`（含真正接线的 ruff/eslint）全绿；`pytest backend/tests/security/ + services/ + infra/` 无回归。

---
*Spec 由审计对账生成；逐条状态见 `.tech-audit/work/2026-08-14/2026-08-14-audit-reconciliation.md`*
