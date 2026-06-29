# InterviewBoss 日常质量门禁设计

**日期**：2026-06-29
**状态**：已批准
**范围**：开发日常验证入口、Docker 后端测试环境、前端验证脚本、audit 报告基线

## 背景

当前项目已经有 Docker test-runtime、前端 Vite 构建、Playwright 配置和较多后端测试，但日常验证入口仍然分散，并且部分结构测试在推荐的 Docker 测试环境中会天然失败。

这会带来三个问题：

1. **测试信号不可信**：项目要求 pytest 走 Docker test-runtime，但 test-runtime 镜像没有包含部分结构测试需要读取的根目录文件；个别测试路径解析也依赖脆弱的相对层级。
2. **日常验证成本偏高**：前端只有 `dev/build/preview` 脚本，缺少统一的 `test` 和 `audit` 入口；开发者需要记住多组命令。
3. **依赖安全债不可见**：npm audit 和 Python 依赖审计能暴露问题，但第一阶段不适合让历史漏洞直接阻断所有开发。

本设计先建立可信、可重复、可日常使用的质量门禁。依赖大升级、后端 service 分层、前端状态重构另行设计。

## 目标

- 提供一个统一日常入口：`./deploy/docker-deploy.sh check`。
- 保持项目现有习惯：后端验证继续走 Docker test-runtime，不在宿主机直接跑 pytest。
- 让当前关键结构测试在 Docker 测试环境中稳定运行。
- 给前端补齐标准脚本：`test`、`test:e2e`、`audit:prod`。
- 将 audit 作为第一阶段的非阻塞报告，明确展示风险但不阻断日常开发。
- 输出清晰汇总，区分 blocking checks 和 audit warnings。

## 非目标

- 不在本轮修复所有 npm 或 Python 依赖漏洞。
- 不引入新的前端测试框架、TypeScript 或 ESLint。
- 不重构后端业务 router/service 边界。
- 不拆分 `AuthenticatedLayout.vue` 或重写前端状态流。
- 不把完整 1419 个后端测试设为每次日常门禁的默认必跑项。
- 不改动生产部署流程的语义；`check` 是开发验证入口，不是部署动作。

## 设计决策

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| 门禁入口 | `./deploy/docker-deploy.sh check` | 延续项目已有脚本入口，降低记忆成本 |
| 编排位置 | 新增 `scripts/check.sh` | 避免 `docker-deploy.sh` 继续膨胀 |
| 后端验证 | Docker test-runtime | 遵守项目手册，避免宿主机环境噪声 |
| 前端验证 | `npm run build` + `npm run test` | 使用 npm scripts 作为标准接口 |
| audit 策略 | 报告但不拦截 | 先建立基线，再单独处理依赖债 |
| 默认范围 | 日常快速门禁 | 适合频繁运行，发布前全量验证另行保留 |

## 命令接口

新增统一入口：

```bash
./deploy/docker-deploy.sh check
```

支持局部模式：

```bash
./deploy/docker-deploy.sh check backend
./deploy/docker-deploy.sh check frontend
./deploy/docker-deploy.sh check audit
```

命令职责：

- `check`：运行默认日常门禁，包含后端、前端和非阻塞 audit 报告。
- `check backend`：只运行后端阻塞检查。
- `check frontend`：只运行前端阻塞检查。
- `check audit`：只运行 audit 报告，不拦截。

`docker-deploy.sh` 只负责识别 `check` 子命令并转发到 `scripts/check.sh`。`scripts/check.sh` 负责参数解析、检查执行、状态记录和结果汇总。

## 后端测试环境

### test-runtime 文件布局

`test-runtime` 继续保持轻量镜像，但需要补齐结构测试读取的项目根文件：

- `Dockerfile`
- `docker-compose.yml`
- `nginx/`
- `deploy/` 中结构测试需要读取的脚本和配置

这样 infra 测试可以在推荐 Docker 环境中真实验证部署文件，而不是因为容器文件缺失失败。

### 测试路径定位

结构测试不得依赖脆弱的 `Path(__file__).parent.parent / "app"` 这类相对层级推断。

路径定位规则：

- 后端应用源码统一定位到 `backend/app`。
- 项目根文件统一从 repo root 定位。
- 测试可通过向上查找包含 `backend/app` 和 `docker-compose.yml` 的目录来确定 repo root。

这保证本地、Docker、CI 的路径语义一致。

### 默认后端阻塞检查

日常后端门禁包含：

```bash
docker compose --profile test run --rm test uv run pytest --collect-only -q
docker compose --profile test run --rm test uv run python -m compileall -q backend/app
docker compose --profile test run --rm test uv run pytest \
  backend/tests/bank/test_master_bank_syntax.py \
  backend/tests/infra/test_docker_config.py \
  backend/tests/services/test_router_refactor.py \
  -q
```

第一版关键结构测试集合覆盖当前已知失败且代表测试基础设施可信度的 bank syntax、infra Docker config、router refactor 测试。

### 测试数据隔离

日常门禁默认使用内存 DB、mock fixture 或非真实 data 路径。需要真实 `backend/data` 的测试不进入日常默认门禁，保留给专项命令或发布前验证。

## 前端脚本

在 `frontend/package.json` 中补齐标准脚本：

```bash
npm run test
npm run test:e2e
npm run audit:prod
```

脚本语义：

- `build`：保持当前 Vite 生产构建。
- `test`：运行稳定、轻量的 smoke/diagnosis Playwright 子集。若现有测试目录已有合适分组，优先复用现有配置。
- `test:e2e`：运行完整 Playwright 测试入口。
- `audit:prod`：固定使用官方 npm registry 跑生产依赖审计。

示例：

```bash
npm audit --registry=https://registry.npmjs.org --omit=dev
```

本轮不引入新的 test runner。后续如要加入 Vitest、ESLint 或 TypeScript，需要单独设计。

## Audit 报告策略

第一阶段 audit 是非阻塞报告。

前端 audit：

```bash
cd frontend
npm run audit:prod
```

后端 audit：

- 优先基于 `uv.lock` 导出的生产依赖运行 `pip-audit`。
- 如果当前环境缺少工具、网络失败或 registry 暂时不可用，统一标记为 `WARN` 或 `SKIPPED`。
- audit 工具失败不导致 `check` 整体失败。

汇总中必须明确写出：

```text
AUDIT: reported only, non-blocking in this phase
```

后续依赖升级完成后，可以把策略从“只报告”提升为“high/critical 阻塞”。

## 失败规则

以下情况使统一门禁失败：

- 后端 pytest collect 失败。
- 后端 compileall 失败。
- 后端关键结构测试失败。
- 前端 build 失败。
- 前端 test 失败。
- Docker、npm 或必要 shell 工具缺失。
- `scripts/check.sh` 收到未知模式或内部命令异常退出。

以下情况不使统一门禁失败：

- npm audit 发现漏洞。
- pip-audit 发现漏洞。
- audit 工具因为网络、registry 或本地工具缺失无法完成。

非阻塞项必须出现在最终汇总里，不能静默忽略。

## 汇总输出

`scripts/check.sh` 最后输出简短结果表：

```text
InterviewBoss daily check

PASS backend collect
PASS backend compile
PASS backend structure tests
PASS frontend build
PASS frontend tests
WARN frontend audit: vulnerabilities reported
WARN backend audit: vulnerabilities reported

Blocking checks: PASS
Audit checks: WARN only
```

如果阻塞检查失败，汇总示例：

```text
InterviewBoss daily check

PASS backend collect
FAIL backend compile
SKIP backend structure tests
PASS frontend build
PASS frontend tests
WARN frontend audit: vulnerabilities reported

Blocking checks: FAIL
Audit checks: WARN only
```

脚本应在阻塞失败时返回非零退出码。

## 文档更新范围

实现时必须同步更新：

- `CLAUDE.md`：把 `./deploy/docker-deploy.sh check` 加到开发测试命令。
- `backend/CLAUDE.md`：说明日常后端门禁继续使用 Docker test-runtime。
- `backend/tests/CLAUDE.md`：记录测试路径定位规则。
- `frontend/CLAUDE.md`：记录新增 npm scripts 和 audit 非阻塞策略。
- `README.md`：同步开发测试命令，不重写架构章节。

## 验收标准

实现完成后，以下命令行为必须清晰：

```bash
./deploy/docker-deploy.sh check
./deploy/docker-deploy.sh check backend
./deploy/docker-deploy.sh check frontend
./deploy/docker-deploy.sh check audit
```

验收要求：

- 默认 `check` 在阻塞项全部通过时返回 0。
- 任一阻塞项失败时返回非零退出码。
- audit 有漏洞时输出 WARN，但不改变默认门禁退出码。
- audit 工具不可用时输出 SKIPPED/WARN，并给出手动运行提示。
- Docker 后端 collect、compileall、关键结构测试可单独从 `check backend` 跑通。
- 前端 build 和 test 可单独从 `check frontend` 跑通。
- README 和相关 CLAUDE.md 与实际命令保持一致。

## 后续增强

- 将 audit 策略升级为 high/critical 阻塞。
- 在依赖升级分支中消化当前 npm 和 Python 漏洞。
- 引入更细的前端 lint 或单测框架。
- 增加发布前全量检查入口，例如 `check release`。
- 将质量门禁接入 CI 或可选 git hook。
