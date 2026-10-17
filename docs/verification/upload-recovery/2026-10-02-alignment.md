# 上传公共题库 / 个人题库 spec 对齐验证

**日期：** 2026-10-02
**验收依据：** [`2026-09-29-upload-recovery`](../../superpowers/specs/2026-09-29-upload-recovery/README.md)，重点核对个人/公共 scope、题目 resolution、审核投影和发布门槛、恢复与逐题追踪，以及 AC-028/AC-029。
**实施计划：** [`2026-10-02-upload-spec-alignment`](../../superpowers/plans/2026-10-02-upload-spec-alignment.md)

## 结论

个人题库写入、普通用户申请公共化、审核后公共投影、按题关联与恢复、scope 预检/账本、旧 worker 写 fencing 已有代码和回归覆盖；stage 记录也统一为 spec 中的阶段名。本轮另修复管理员 reprocess/SSE、通用回收站、个人 rebuild、legacy retry 和分析状态的私人 scope，并增加逐题既有公共 canonical 命中及 resolve checkpoint 测试。

**全量结论：尚未完全对齐。** 修复提交 `3a2020b6` 已部署；生产 root/health 探针为 200，backend 与 worker 同镜像。部署镜像在隔离 `real_stack_smoke.sh` 中通过通用 smoke 与 AC-028 个人上传停启恢复（各 1 passed），上传/审核 mock Playwright 子集 16 passed，管理员/上传后端组合回归 86 passed。AC-028 和 AC-029 仍为 partial，因为真实浏览器公共申请、管理员审核和公共 worker 恢复还没有贯通。详见[全量 spec 审计](2026-10-02-spec-audit.md)。该记录保留初审发现作为历史，当前活动 finding 仅是 AC-029 公共活体腿；更广泛的前端 E2E debt 另列。

## 本轮修复与 TDD 证据

- 在 provider 请求边界按每次物理调用预留、结算上传调用账本，重试使用独立 call key；把内部阶段别名迁移、归一到 spec 阶段名，并保留 `unit_key`。迁移编号 124。
- 为聚类/答案 worker 增加 generation 与 scope lease fencing；过期或失效持有者不能提交结果，公共队列恢复按 root 隔离。
- 管理员公共直导持久化 actor、明确批准动作、脱敏投影及关联审计信息；未发布投影仍受公共读取门禁约束。
- AC-029 增加逐 ordinal trace，将 stage result、私人 detail/resolution、审核 item/projection、公共 detail/resolution/canonical 串联；本轮另覆盖既有公共 canonical 命中、不改公共字段，并确保这类直接命中有 succeeded `resolve` checkpoint。
- 用例先在缺少物理调用账本、旧阶段词汇、过期 lease 写入、缺少审批事件或 trace 关系时失败，再实现修复并运行回归。恢复 fullstack 测试的旧顺序假设也已改为符合“预检通过后才派发业务 job”的契约。
- AC-004 额外发现：预检 worker 虽然已持久化创建 `submit_import` job，但没有立即执行 dispatcher handoff，只能等每 5 分钟的 cron。新增真实隔离 Redis 回归先红（`arq_job_id` 缺失），再在成功预检提交事务后触发现有 durable dispatcher，测试转绿。

## 验证结果

### 后端 spec 相关套件（历史记录）

使用隔离 SQLite 路径和 Redis 前缀运行：

```bash
docker compose --profile test run --rm \
  -e UPLOAD_TEST_DB_PATH=/tmp/upload-spec-suite-final.sqlite \
  -e UPLOAD_TEST_REDIS_PREFIX=codex-upload-spec-suite-final-20261002 \
  test uv run pytest \
  backend/tests/infra/test_upload*.py \
  backend/tests/pipeline/test_upload*.py \
  backend/tests/pipeline/test_submit_job_retry.py \
  backend/tests/pipeline/test_public_personal_scope_contract.py \
  backend/tests/pipeline/test_interview_server_pagination.py \
  backend/tests/services/test_upload*.py \
  backend/tests/services/test_public_contribution*.py \
  backend/tests/services/test_admin_public_contribution_retry.py \
  backend/tests/security/test_upload*.py \
  backend/tests/integration/test_upload*.py \
  -q --tb=short --show-capture=no
```

结果：**361 passed, 2 skipped, 14 warnings**（188.17 秒）。跳过的是两个大文件安全限制用例。Warnings 是既有 Pydantic settings 字段定义和 ARQ Redis `.close()` 弃用提示。

### 前端与静态核对（初审记录）

- Playwright：`./node_modules/.bin/playwright test --config tests/playwright.config.js tests/e2e/upload-task-center.spec.js tests/e2e/public-contribution-review.spec.js` → **14 passed**。这些用例使用 mock API，不作为活体后端/worker 验收。
- 前端构建：`npm run build` → **通过**；Vite 有 CSS 兼容、Browserslist 过期和 chunk 体积提示。
- Python 源文件：只读 AST 解析 `backend/app`、`backend/tests` 的 **688 个 Python 文件**，全部成功。`compileall` 因测试容器以只读方式挂载源码、无法写 `__pycache__` 而未能执行；不把它记为通过。
- `git diff --check` → **通过**。
- 新增 AC-004 dispatcher 集成回归：红灯确认业务 job 创建但没有 ARQ handoff；修复后 **1 passed, 4 warnings**（2.07 秒），验证成功预检立即将 `submit_import_task` 写入隔离 Redis 队列。

## 本轮新增复核与边界

- 管理员 scope/个人公共边界组合：**86 passed, 2 warnings, 79.11s**；具体命令和红绿先后见[全量 spec 审计](2026-10-02-spec-audit.md)。
- 上传任务、公共贡献审核、逐题数据流前端 mock 子集：**16 passed, 32.4s**。
- 已执行生产 `update` 和 `worker-restart`；生产 root 与 health 均 200。业务验收使用与部署一致的 backend/nginx 镜像运行 disposable `real_stack_smoke.sh`：**2 passed**（通用 smoke 22.7s，AC-028 个人恢复 26.7s）。临时 SQLite/Redis/volume 在 runner 结束后清理。

## 未运行与边界

- AC-028 完整浏览器验收：**partial**。个人上传→queued→同一 worker 停/启→浏览器打开正确结果已在隔离 disposable Compose 栈通过；公共申请/审核的浏览器流程仍未覆盖。完整 `real_stack_smoke.sh` 现已通过，修复前 Playwright response body 读取错误作为历史记录保留。
- AC-029：已在真实 submit/review HTTP 与 worker 函数测试中覆盖既有公共 canonical hit、逐题 trace、失败 item 恢复和公共读取；仍未通过 live Redis/ARQ/browser 验证公共 share → admin review → 公共处理/恢复。
- 没有调用真实模型供应商；provider 相关测试使用确定性 stub，不验证供应商可用性、模型质量或真实费用。
- 管理员公共直导的审计测试覆盖持久化节点边界，没有单独从管理员直导 HTTP 入口跑完整公共导入链路。
