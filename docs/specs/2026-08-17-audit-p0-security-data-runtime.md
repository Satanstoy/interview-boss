# Tech Audit P0：安全、数据完整性与运行可靠性

> 日期：2026-08-17
> 来源：`docs/internal/tech-audit-2026-08-17.md`
> 顺序：P0，完成并验证后再进入 P1
> 原则：每个代码任务遵循 RED → GREEN → REFACTOR；生产数据库迁移必须先备份，禁止直接在当前运行库上手工删除数据。

## 目标

先消除会造成密钥滥用、数据不一致、租户边界错误或后台任务静默丢失的风险。外部密钥轮换属于运维动作，仓库只提供校验、runbook 和验证命令，不自动调用供应商控制台。

## Task P0-A：密钥与管理员密码安全

> 产品决定：不把 `ADMIN_PASSWORD` 的 16 位长度作为生产启动硬门槛；启动时仍校验 JWT/OAuth 签名密钥长度，管理员密码是否为空继续由管理员初始化逻辑处理。

**Files**

- Modify: `backend/app/core/config.py`、`backend/app/db/migrations/auth.py`
- Test: `backend/tests/security/test_runtime_secret_policy.py`
- Docs: `docs/runbooks/secret-rotation.md`

- [x] RED：测试现有长度的 `ADMIN_PASSWORD` 可以启动；测试 JWT/OAuth/第三方 key 只从环境变量读取。
- [x] GREEN：增加统一 secret policy 校验，但不在启动阶段强制管理员密码长度。
- [ ] REFACTOR：将启动校验与错误信息集中到配置模块，避免各模块重复判断。
- [ ] 运维步骤：轮换并撤销旧 SiliconFlow key；用 `git filter-repo` 清理可达历史；使用 gitleaks 全史扫描。

**Done when**：签名密钥配置错误在启动时明确失败，管理员初始化仍拒绝空密码，runbook 包含轮换/历史清理/验证/回滚步骤，且仓库不写入任何真实 secret。

## Task P0-B：数据库 FK 孤儿修复与迁移保护

**Files**

- Modify: `backend/app/db/connection.py`、`backend/app/db/migrations/__init__.py`、`backend/app/db/migrations/schema_hygiene_2.py`
- Create: `backend/app/db/migrations/data_repair_2.py`
- Test: `backend/tests/infra/test_migration_091_fk_repair.py`、`backend/tests/infra/test_migration_backup.py`

- [ ] RED：构造缺失 `chat_conversations`/`question_bank` 父行的 `interview_asked_questions`，断言 migration 091 清理孤儿且保留合法行。
- [ ] RED：断言 `init_db()` 的迁移连接在迁移前启用 `PRAGMA foreign_keys=ON`。
- [ ] RED：断言 090/091 均属于 destructive migration，执行前调用整库备份。
- [ ] GREEN：新增幂等 migration 091，删除同时缺任一父引用的 asked-question 孤儿；将 090、091 纳入备份集合。
- [ ] GREEN：`init_db()` 建立连接后立即设置并断言 FK pragma。
- [ ] REFACTOR：将 FK 检查/修复统计写入日志，迁移完成后执行 `PRAGMA foreign_key_check`，发现新违规则失败。

**Done when**：迁移测试覆盖合法/非法数据、重复运行、备份失败；测试库 `foreign_key_check` 为 0；不直接修改当前生产数据库。

## Task P0-C：LLM 配额并发原子性与软删除可见性

**Files**

- Modify: `backend/app/services/llm_quota.py`、`backend/app/routers/chat.py`、`backend/app/agents/chat/memory_extract.py`
- Test: `backend/tests/services/test_llm_quota.py`、`backend/tests/chat/test_jd_visibility.py`

- [ ] RED：并发调用同一用户、limit=1 时只有一个请求返回允许；其余请求拒绝。
- [ ] RED：软删除 JD 不得进入 chat 上下文或 memory title；跨用户 JD 不得被读取。
- [ ] GREEN：使用带 `WHERE call_count < ?` 的单条 UPSERT/rowcount 判定，避免 SELECT-then-UPDATE 竞态。
- [ ] GREEN：统一 JD 可见性查询，要求 `owner_id` 与 `deleted_at IS NULL`。
- [ ] REFACTOR：抽取可复用可见性函数，清理重复 SQL，并补边界日志。

**Done when**：配额并发测试稳定通过 20 次重复运行，JD 隔离测试覆盖公共/私有/软删三类数据。

## Task P0-D：评测 worker 与后台任务可见性

**Files**

- Modify: `deploy/docker-deploy.sh`、`deploy/eval-worker-launcher.sh`、`docker-compose.yml`、`backend/app/worker.py`
- Test: `backend/tests/infra/test_eval_worker_deployment.py`、`backend/tests/services/test_worker_observability.py`
- Docs: `docs/runbooks/eval-worker.md`

- [ ] RED：部署结构测试断言 eval timer 安装/启用路径存在；queued 任务无消费者时能被诊断接口识别。
- [ ] RED：cron 执行成功、失败、未执行三种状态均有 last-run/status 记录。
- [ ] GREEN：增加 `eval-worker-install`/`eval-worker-status` 命令，安装并启用 systemd timer；运行前检查 Docker、Redis、数据库。
- [ ] GREEN：增加 worker heartbeat 和 cron execution record；为 eval run 增加 queued 超时状态提示。
- [ ] REFACTOR：把诊断输出集中到 deploy/status helper，避免脚本和 API 重复实现。

**Done when**：fresh clone 可以按 runbook 启用 timer；测试覆盖 timer 文件、启动命令、锁和失败退出码；运行态验证能区分 worker offline 与 queue empty。

## P0 验证命令

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/infra/test_migration_091_fk_repair.py \
  backend/tests/infra/test_migration_backup.py \
  backend/tests/services/test_llm_quota.py \
  backend/tests/chat/test_jd_visibility.py -q
./scripts/check.sh lineguard
python3 backend/scripts/check_secrets.py
```
