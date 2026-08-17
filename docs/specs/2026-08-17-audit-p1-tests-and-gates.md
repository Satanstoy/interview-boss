# Tech Audit P1：测试、静态质量与 CI 门禁

> 日期：2026-08-17
> 前置：P0 已完成并通过验证
> 原则：先固定失败行为，再修实现；任何新增 gate 必须先有可读失败信息和本地复现命令。

## 目标

让 `check.sh` 的结果真实反映项目状态，收敛当前后端 72 个失败、ruff/mypy/ESLint 存量，并建立至少一条真实前后端链路。

## Task P1-A：后端失败簇清零

**Files**

- Modify: 失败测试对应的 `backend/app/**` 与 `backend/tests/**`
- Test: `backend/tests/bank/`、`chat/`、`pipeline/`、`services/`、`security/`、`infra/`

- [x] RED：按 bank/chat/pipeline/services/security/infra 分组记录当前失败数量和首个根因，不允许用 skip 掩盖。
- [x] GREEN：每个失败簇只修根因，优先处理 fixture/ContextVar、状态契约、环境依赖和测试期望漂移。
- [x] REFACTOR：删除重复 fixture，统一测试数据库、Redis mock 和外部服务边界。
- [x] 每个修复提交必须带一条固定回归行为的测试。

**Done when**：关键子集 0 failed；失败测试不通过 `pytest.skip`、宽泛 mock 或修改断言语义来消失。

## Task P1-B：静态检查债务收敛

**Files**

- Modify: `backend/app/**`、`frontend/src/**`、`pyproject.toml`、`eslint.config.js`
- Test: 对应 Python/Vue 单元测试

- [x] RED：把当前 ruff 175、mypy 436、ESLint 13 errors 固定为可比较基线。
- [ ] GREEN：按模块清理未使用导入/变量、未定义名称、TypedDict/Optional 类型错误、Vue prop mutation。
- [ ] REFACTOR：补充必要类型别名和 composable 边界，禁止通过大范围 ignore 降低检查强度。
- [x] 完成一个模块后立即运行该模块测试和对应静态检查。

### 进度记录（2026-08-17）

- P1-A 已完成：关键后端子集与完整 `backend/tests/services`、`security`、`infra` 回归通过；chat、pipeline 也已分别复验。
- 后端生产代码 `uv run ruff check backend/app` 已为 0 error；全仓初始可复现计数为 168（审计报告按旧入口记录为 175）。
- 前端 Vue prop mutation 已修复，`npm run lint` 已从 13 errors 降为 0 errors，剩余 48 条 warning 尚未清零。
- `mypy backend/app` 初始 446 errors，目前仍有 445 errors，主要集中在 Optional、TypedDict 和未标注容器；因此 P1-B 尚未完成。

**Done when**：生产代码 ruff、mypy、ESLint error 为 0；warnings 只允许有明确编号和期限的例外。

## Task P1-C：测试行数与真实 E2E

**Files**

- Modify: `scripts/line_guard.sh`、`frontend/tests/playwright.config.js`
- Create: `backend/tests/infra/test_real_stack_smoke.py`
- Create: `frontend/tests/e2e/real-stack-smoke.spec.js`
- Modify: `.github/workflows/ci.yml`

- [ ] RED：line guard 对 `backend/tests` 超过上限的文件失败；真实 smoke 在没有后端服务时明确失败。
- [ ] GREEN：补充测试目录扫描；在 Docker Compose test profile 中实现注册/登录、提交、队列消费、结果回读的最小链路。
- [ ] GREEN：保留 mock E2E 作为快速套件，真实 smoke 单独 job 运行并设置超时。
- [ ] REFACTOR：为真实链路提供 fixture 清理和失败诊断 artifact。

**Done when**：真实 smoke 至少覆盖一条跨前端/API/SQLite/Redis/worker 链路；测试文件不再绕过 line guard。

## Task P1-D：恢复 blocking CI

**Files**

- Modify: `scripts/check.sh`、`.github/workflows/ci.yml`
- Test: `backend/tests/infra/test_check_script_contract.py`

- [ ] RED：测试会失败的 ruff/mypy/ESLint/关键 pytest 必须使 gate 返回非 0。
- [ ] GREEN：将已清零的检查从 `run_nonblocking` 切换到 blocking；移除 `audit || true`。
- [ ] GREEN：CI fresh clone 明确执行 `npm ci`、创建 `.env` 和 Redis secret，再运行对应 gate。
- [ ] REFACTOR：按 job 输出结构化摘要，区分 blocking、warning、skipped，并保留日志。

**Done when**：fresh clone 的 CI 能复现；任一 blocking 检查失败时 workflow 失败；总 PASS 不再掩盖质量失败。

## P1 验证命令

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/bank backend/tests/chat backend/tests/pipeline \
  backend/tests/services backend/tests/security backend/tests/infra -q
./scripts/check.sh lineguard
./scripts/check.sh audit
cd frontend && npm run build && npm run test && npm run lint
```
