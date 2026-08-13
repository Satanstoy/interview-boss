# Tech-Audit 紧要修复 Spec — 2026-08-13

> 来源：[tech-audit-2026-08-13.md](../analysis/tech-audit-2026-08-13.md) 的 🔴 级发现
> 原则：TDD（先写失败测试）→ 最小实现 → 验证 → 提交。配置类修改附静态断言测试。
> 方法：全部遵循 writing-plans 原子任务拆分；每个 Task 2-5 分钟。

## 范围（按紧要度排序）

| # | 发现 | 风险 | 修复 |
|---|------|------|------|
| A | D4-1 SiliconFlow API key 硬编码 ×4 脚本 + 进 git 历史 | 🔴 密钥泄露，可能仍有效 | 删字面量改读 env + 历史清洗（待确认） |
| B | D13-1 JWT_SECRET 公开占位进 .env.example | 🔴 新部署共享已知密钥 | 注释化占位 + README 统一口径 |
| C | D13-2 OAUTH_SECRET_KEY 公开兜底值 | 🔴 未设变量部署令牌可伪造 | compose 移除兜底 + 触发自动生成 |
| D | D14-1 users.email 无唯一约束 | 🔴 重复 email 数据完整性 | 新增迁移：去重 + UNIQUE 索引 |
| E | D8-2 门禁无 secret 扫描 | 🔴 再犯无拦截 | check.sh 增加 secret 扫描（阻断） |
| F | D8-1 零 CI | 🔴 无集中门禁 | GitHub Actions workflow（防再犯） |

**不做（本轮）**：D1 巨型文件拆分、D3 真 E2E（大工程，另行规划）；D11 合规页（产品决策）。

---

## Task A: D4-1 删除实验脚本硬编码 API key

**Files:**
- Edit: `backend/app/services/clustering/experiments/reranker_cross_encoder_eval.py`
- Edit: `backend/app/services/clustering/experiments/vector_rerank_eval.py`
- Edit: `backend/app/services/clustering/experiments/embedding_recompute_eval.py`
- Edit: `backend/app/services/clustering/experiments/draw_questions_eval.py`
- Create: `backend/tests/security/test_secret_scan.py`

**现状**：4 个脚本第 24-26 行硬编码 `sk-hkaopkqmnstcesslqwxifjiqdffgbpljrixgyssagvgtclym`，且进入 git 历史（78c77d0/e6f4f0d/95fcf63）。

- [ ] Step 1（RED）：写 `test_secret_scan.py` 断言 experiments 目录无 `sk-` 字面量、.env.example 无实值占位、compose 无 `change-me-in-production`
- [ ] Step 2：跑测试确认失败（Docker test-runtime）
- [ ] Step 3（GREEN）：4 个脚本改为 `os.environ.get("SILICONFLOW_API_KEY")`，缺失时脚本启动即报错提示
- [ ] Step 4：跑测试确认通过
- [ ] Step 5：提交 `fix(security): remove hardcoded siliconflow api key from eval scripts`

**git 历史清洗（破坏性，需用户确认后单独执行）**：
- 安装 `git filter-repo`（当前未安装）→ `--replace-text` 替换 key → force push 到 gitee+github 双远端
- 或：确认双远端均为私有后，仅轮换 key + 删字面量（本轮已做），历史保留
- **必须**：用户在 SiliconFlow 控制台轮换该 key（报告中 key 曾用于生产 embedding）

## Task B: D13-1 JWT_SECRET 占位注释化

**Files:**
- Edit: `backend/.env.example`
- Edit: `README.md:194`（统一「自动生成」口径）

**现状**：`.env.example:19` 有 `JWT_SECRET=change_me_to_a_random_64_byte_hex_string`（40 字节，恰好通过 auth.py 的 len>=32 检查——照抄示例的部署共享同一已知签名密钥）。

- [ ] Step 1（RED）：test_secret_scan.py 断言 .env.example 中 JWT_SECRET 行为注释或空
- [ ] Step 2：确认测试失败
- [ ] Step 3（GREEN）：.env.example 改为 `# JWT_SECRET=` 注释 + 说明「不设置则系统自动生成并写回 .env」；README:194 核对口径
- [ ] Step 4：测试通过
- [ ] Step 5：提交 `fix(security): remove JWT_SECRET placeholder from .env.example`

## Task C: D13-2 OAUTH_SECRET_KEY 兜底移除

**Files:**
- Edit: `docker-compose.yml:200`
- Edit: `oauth-gateway/auth.py`（核对自动生成逻辑）
- Edit: `backend/.env.example`（补 OAUTH_SECRET_KEY 说明）

**现状**：`OAUTH_SECRET_KEY=${OAUTH_SECRET_KEY:-change-me-in-production}` 使 env 恒非空，oauth-gateway/auth.py:20 的 `secrets.token_hex(32)` 自动生成永不触发；未设变量的部署用已知密钥签 token。

- [ ] Step 1（RED）：test_secret_scan.py 断言 compose 无 `change-me-in-production`
- [ ] Step 2：确认失败
- [ ] Step 3（GREEN）：compose 改为 `OAUTH_SECRET_KEY=${OAUTH_SECRET_KEY:-}`（空则触发 auth.py 自动生成并告警）；.env.example 补注释说明
- [ ] Step 4：测试通过
- [ ] Step 5：提交 `fix(security): drop OAUTH_SECRET_KEY public fallback in compose`

## Task D: D14-1 users.email 唯一约束

**Files:**
- Create: `backend/app/db/migrations/auth.py` 新增 `_migration_079_users_email_unique`
- Edit: `backend/app/db/migrations/__init__.py` 注册 (79, ...)
- Create: `backend/tests/security/test_email_unique.py`（或并入迁移测试）

**现状**：users.email 由 `_migration_010` ALTER 添加，无 UNIQUE；应用层注册时 SELECT 查重（routers/auth.py:270）但无 DB 约束，并发/直插可产生重复。

- [ ] Step 1（RED）：test_email_unique.py —— 迁移后 PRAGMA index_list 含 email 唯一索引；插入重复 email 抛 IntegrityError；NULL email 允许多条
- [ ] Step 2：确认失败（迁移尚不存在 → 测试失败于 fixture 或断言）
- [ ] Step 3（GREEN）：迁移实现——先删除重复 email（保留最小 id，其余置 NULL 或删行），再 `CREATE UNIQUE INDEX idx_users_email_unique ON users(email) WHERE email IS NOT NULL`
- [ ] Step 4：测试通过
- [ ] Step 5：提交 `feat(db): enforce unique users.email via migration 079`

## Task E: D8-2 check.sh secret 扫描

**Files:**
- Create: `backend/scripts/check_secrets.py`（无第三方依赖，扫描常见 secret 模式；放 backend/scripts/ 因 test 容器只挂载 ./backend，且符合 check_* 运维脚本规范）
- Edit: `scripts/check.sh`（blocking 段加 secret scan）

**现状**：门禁唯一安全项是 npm audit / pip-audit 且 WARN 不拦截；API key 提交无任何工具拦截。

- [ ] Step 1（RED）：为 check_secrets.py 写测试（临时目录造 `sk-xxx` 文件断言检出；无匹配时退出 0）
- [ ] Step 2：确认失败（脚本不存在）
- [ ] Step 3（GREEN）：实现 check_secrets.py（扫描 tracked 文件 + 排除 .env/data/node_modules）；check.sh 加 `run_blocking "secret scan"`
- [ ] Step 4：测试通过 + 本机跑一次 check.sh audit 验证
- [ ] Step 5：提交 `feat(ci): add secret scan to check.sh gate`

## Task F: D8-1 GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

**现状**：仓库无任何 CI 配置；github push 远端已配置（https://github.com/Satanstoy/interview-boss.git）。

- [ ] Step 1：编写 workflow —— push/PR 触发；job 1: gitleaks secret 扫描（官方 action）；job 2: docker compose --profile test 跑 pytest 结构测试 + frontend build（复用 check.sh 的 backend/frontend 段，audit 段 WARN 不阻断）
- [ ] Step 2：本地验证 yaml 语法（python yaml.safe_load）
- [ ] Step 3：提交 `feat(ci): add GitHub Actions workflow with gitleaks + check.sh`
- [ ] 注：真实跑通依赖 GitHub 平台，push 后由远端验证（verification 阶段说明）

---

## 验证与收尾

1. 全部修改完成后：`docker compose --profile test run --rm test uv run pytest backend/tests/security/ backend/tests/infra/ -q`
2. 跑 `./deploy/docker-deploy.sh check`（或 check.sh backend 段）确认门禁不回归
3. 更新 `backend/CLAUDE.md`（如涉及测试文件规则）与 README（如需）
4. 每个 Task 独立 commit（Conventional Commits，英文）
