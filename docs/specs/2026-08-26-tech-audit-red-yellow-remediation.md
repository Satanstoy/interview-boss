# Tech Audit 红/黄灯整改 Spec

> 日期：2026-08-26
> 来源：[`docs/internal/tech-audit-2026-08-26.md`](../internal/tech-audit-2026-08-26.md)
> 范围：本轮审计的 3 条 🔴 与 13 条 🟡，共 16 条整改项
> 前置状态：审计只读完成；当前仓库保留 pre-existing 的 `backups/`，不纳入本任务
> 总原则：每个行为改动遵循 RED → GREEN → REFACTOR；每个阶段独立验证、独立提交，可单独回滚

## 1. 目标与非目标

### 目标

1. 消除当前 3 条红灯：没有真实全链路 E2E、nginx/OAuth 没有健康检查、生产巨型文件越过行数红线且 line guard 当前失败。
2. 关闭 13 条黄灯：回归测试不绿、SSRF DNS rebinding 窗口、运行时用户声明、运维 runbook、OAuth gateway 依赖可复现性、类型检查门禁、schema 文档、合规部署矩阵、clear-db 审计、JWT 密钥读取错误、管理员默认值文档等。
3. 保留现有已验证的安全边界：MCP principal 覆盖、JWT refresh rotation、字段白名单、FK 检查、npm/pip audit 与 secret scan 不得回退。
4. 把“检查存在”改成“检查可阻断且可复现”：失败必须有本地命令、稳定断言和可定位日志。

### 非目标

- 本轮不处理审计中的 4 条低灯：public contributions 全表后过滤、活跃请求配额、完整 `.env.example` 变量覆盖、图表颜色 token；它们登记为下一轮债务，不得借整改之名顺手扩大范围。
- 不接入真实第三方 LLM、OAuth provider 或生产数据库；真实链路只允许使用 disposable stack 与测试替身。
- 不在当前运行中的生产数据库上手工改数据；涉及 migration 的验证只使用临时库、备份副本或 CI 数据库。
- 不通过扩大 line guard override、关闭测试、`skip`、宽泛 mock、放宽断言或 `continue-on-error` 隐藏失败。

## 2. 当前基线

| 证据 | 当前结果 | 处理要求 |
|---|---:|---|
| 全后端测试（关闭本地代理） | 37 failed / 2,799 passed / 4 skipped / 14 deselected | 先分簇定位根因，完成后关键集合与默认 suite 均为 0 failed |
| 前端 mocked Playwright | 174 failed / 250 passed | 先修 fixture/接口契约漂移；保留为快速套件，不把它冒充真实 E2E |
| `ruff check backend/app` | 通过 | 保持 blocking |
| `mypy backend/app` | 551 errors / 92 files | 分批收敛，最终成为可阻断门禁 |
| `npm run build` | 通过，有 chunk warning | 不因本 spec 扩大 bundle 重构；记录并保持 build 通过 |
| `npm run lint` | exit 0，有 38 warnings | 先确保 errors blocking，再建立 warning 清单与期限 |
| line guard | 当前 3 个文件超过冻结 cap | 先拆分/缩小文件，再更新 cap；不直接上调上限 |
| runtime health | backend/OAuth HTTP 200；nginx/OAuth Compose health 为空 | 为 nginx 与 OAuth 增加健康检查并验证 `service_healthy` |
| 数据库 | schema version 117，`foreign_key_check=0` | 文档生成到 117，迁移不能破坏当前 FK 约束 |

说明：首次后端测试运行受本机 `socks5h://127.0.0.1:7891` 代理影响，测试 fixture 清理代理发生在 collection 之后；整改时要让测试入口在 collection 前处理环境，或提供显式无代理命令，不能把环境噪声误报成代码通过。

## 3. 方案选择

### 方案 A（推荐）：分阶段关闭红灯，再收敛黄灯

- M1 先修 gate/回归与运行探针，建立真实 E2E 骨架。
- M2 修安全边界与可复现构建：SSRF、运行时用户、JWT、gateway 依赖、clear-db 审计。
- M3 修文档、schema、类型、运维和合规证据。
- 每个阶段都可部署、可验证、可回滚；CI 在相应能力完成后才提升为 blocking。

优点是风险隔离和定位成本最低；缺点是短期会经历多个阶段性提交。

### 方案 B：一次性把所有 gate 改为 blocking

不采用。当前后端和 mocked Playwright 仍有大量失败，一次性阻断会只得到长期红色 CI，无法区分产品回归、fixture 漂移和环境问题。

### 方案 C：只先做安全修复，延后测试与运行基线

不采用。安全修复没有可用回归和健康探针支撑，后续拆分/部署时容易重新引入已修问题。

本 spec 采用方案 A；用户确认后从 M1-A 开始执行。

## 4. 设计与分阶段任务

### M1：恢复发布可信度（红灯优先）

#### M1-A：nginx/OAuth healthcheck（D6 🔴）

**修改范围**

- `docker-compose.yml`
- 必要时 `nginx/nginx.conf`、`oauth-gateway/app.py`
- 新增或扩展 `backend/tests/infra/test_health_contract.py` 与 compose 结构测试

**设计**

- nginx 检查本地静态入口或代理健康路径；OAuth 使用现有 `/health`，检查 HTTP 200 和 `status=ok`。
- 两个服务都声明合理的 `interval`、`timeout`、`retries`、`start_period`，不依赖宿主机 curl；镜像内已有工具优先，否则使用 Python/BusyBox 可用能力。
- 保持 backend `service_healthy` 依赖；不把“容器进程存在”当作服务健康。

**验收**

- `docker compose config --quiet` 通过。
- `docker compose ps` 对 nginx、OAuth 显示 `healthy`。
- 故意停止 backend 或让 OAuth 健康端点失败时，依赖服务状态可被观察到。
- 结构测试阻止未来删除任一 healthcheck。

#### M1-B：line guard 与五个巨型生产文件（D1 🔴、D8 🟡）

**修改范围**

- `backend/app/routers/admin_evaluation.py`
- `backend/app/services/llm.py`
- `backend/app/worker.py`
- `frontend/src/components/business/ChatView.vue`
- `backend/app/agents/chat/react_loop.py`
- `scripts/line_guard.sh`、`scripts/line_guard_overrides.txt`
- 对应模块测试与 import/contract 测试

**设计**

- 先按稳定职责拆出纯函数、策略、schema、transport/adapter 或子 router；保持公开函数、路由、事件格式和错误语义兼容。
- 每次只拆一个职责簇，移动代码后先跑原测试，再新增边界测试；禁止机械切割导致循环依赖。
- `admin_evaluation.py`、`worker.py`、`ChatView.vue` 是当前超过冻结 cap 的首批目标；`llm.py` 与 `react_loop.py` 在 cap 附近，先冻结增长并拆出最高耦合职责。
- 只有实际减小文件后才更新 override baseline；最终移除已不需要的 override。line guard 不扩展到临时目录、生成文件或测试 fixture。

**验收**

- `./scripts/line_guard.sh` 全绿，且没有通过提高 cap 解决失败。
- 五个生产文件均不再触发红线；新增模块也受同一规则约束。
- 受影响的后端单测、前端 build/lint 与路由/worker smoke 通过。

#### M1-C：清零后端回归失败并恢复 blocking（D3 🟡、D8 🟡）

**修改范围**

- 失败簇涉及的 `backend/app/**`、`backend/tests/**`、`backend/tests/conftest.py`
- `scripts/check.sh`、`.github/workflows/ci.yml`
- 新增 `backend/tests/infra/test_check_script_contract.py`（若已有则扩展）

**设计**

- 先把 37 个失败按 bank/security/services/taxonomy/worker/clustering/infra 分簇，记录每簇首个根因和最小复现命令。
- collection 前统一清理代理或让测试 runner 显式接收 `NO_PROXY`/无代理环境；不能依赖 autouse fixture 修复 collection 阶段环境。
- 修实现/fixture 契约，而不是只改断言；每个修复必须有行为回归测试。
- 仅当一个检查的错误数清零且有稳定本地命令后，才从 non-blocking 切换 blocking。审计、静态检查和关键 pytest 不得用 `|| true` 隐藏失败。

**验收**

- 关键子集和默认后端测试 0 failed；失败时保留完整首个根因输出。
- `check.sh` 的 blocking/non-blocking 分类有结构测试保护。
- CI 任一 blocking 项失败时 workflow 失败，报告不得打印虚假的总 PASS。

#### M1-D：真实 disposable-stack E2E（D3 🔴、D3 🟡）

**修改范围**

- `frontend/tests/playwright.config.js`
- `frontend/tests/e2e/real-stack-smoke.spec.js`
- `backend/tests/infra/test_real_stack_smoke.py`（如 API/worker 端需要后端契约测试）
- `docker-compose.yml` 的 test/e2e profile 或新增最小 overlay
- `.github/workflows/ci.yml`
- 必要的测试 fixture/runbook

**设计**

- 保留现有 mocked Playwright 作为快速 UI 套件，并单独命名 real-stack job，避免两者证据混淆。
- real-stack 使用临时 Compose project：nginx → backend → SQLite 持久化卷 → Redis → worker；测试结束后清理临时卷与网络。
- 第三方 LLM 不访问真实密钥；在 provider boundary 注入可控 stub，返回与生产响应 schema 相同的成功、失败、超时样本。
- 最小链路覆盖：注册/登录、创建或提交一条业务输入、进入队列、worker 消费、持久化结果、浏览器读回并渲染完成态；至少包含一次失败可观察断言。
- 失败时上传 Compose 日志、容器状态、数据库 schema version 和 Playwright trace；成功时不上传 secret。

**验收**

- 没有后端服务时 real-stack smoke 明确失败，而不是被 mock route 接管。
- fresh checkout 能用 documented command 启动并运行；CI 有超时与清理保障。
- 该 suite 至少真正穿过 nginx、API、Redis、持久化和 worker；报告明确标注 stubbed provider。

### M2：安全与可复现运行时

#### M2-A：SSRF DNS rebinding 防护（D4 🟡）

**修改范围**

- `backend/app/core/outbound_url.py`
- `backend/app/services/llm.py`
- `backend/app/services/search_service.py`
- 新增/扩展 security tests 与 HTTP transport test double

**设计**

- URL 校验返回结构化的“允许目标”：规范化 scheme/host/port、通过 DNS 解析得到的允许地址集合和审计信息。
- 建立连接时使用已经验证的地址（例如自定义 transport/连接器 pin 地址，同时保留正确的 Host/SNI），并在重定向关闭的前提下对连接目标再次执行私网/保留地址检查。
- 明确 IPv4、IPv6、localhost、私网、link-local、metadata 地址、解析失败、DNS 变化、非默认端口的测试矩阵。
- 不依赖一次性 `resolve → 返回原 URL → 之后普通 httpx 请求` 的时间窗口；若底层库限制无法安全 pin，则采用可审查的 egress proxy/allowlist 方案并记录取舍。

**验收**

- DNS 首次解析为公网、连接时切换为私网的回归测试被拒绝。
- 正常公网 endpoint、IPv6 合法地址、超时和 redirect 行为有测试。
- LLM 与 search 两条调用路径共用同一安全边界，日志不泄露 token。

#### M2-B：声明非 root 运行用户（D4 🟡）

**修改范围**

- `Dockerfile`
- `deploy/entrypoint.sh`
- `nginx` stage/config 与 `docker-compose.yml`
- 必要的镜像结构测试

**设计**

- app image 在镜像构建阶段准备目录权限，并在最终镜像声明 `USER appuser`；entrypoint 不再依赖 root `chown` 作为正常启动路径。
- bind mount 权限由部署前置检查或一次性 host-side prepare 处理；权限不满足时 fail clearly，不静默吞错。
- nginx 采用非 root 运行方式（非 root 基础镜像或明确的非特权端口/缓存/pid/temp 路径），同时保持宿主端口映射兼容。
- OAuth 已声明 `USER oauthuser`，补充结构测试防回归。

**验收**

- `docker inspect` 显示 app/nginx/oauth 的有效 runtime user 非 root；必要的 init 进程也不能以 root 常驻。
- fresh volume、只读数据挂载、日志与临时文件写入均通过。
- 部署脚本在权限不足时返回非 0 并给出修复提示。

#### M2-C：JWT 读取失败 fail-closed（D14 🟡）

**修改范围**

- `backend/app/core/auth.py`
- `backend/tests/security/` 下 auth/restart regression tests

**设计与验收**

- 区分文件不存在、空值/格式错误、权限错误、IO 错误；只有“明确不存在且允许首次初始化”才能生成新 key。
- 已存在 key 读取失败时启动失败并保留原错误上下文，不静默生成新 key；写回失败同样不能假装持久化成功。
- 测试覆盖首次启动、正常重启 token 可验证、权限失败、损坏文件、并发初始化；确保不会无提示地使全部 session 失效。

#### M2-D：OAuth gateway 依赖锁定与独立审计（D7 🟡）

**修改范围**

- `oauth-gateway/requirements.txt` 或 gateway 的独立 lock manifest
- `oauth-gateway/Dockerfile`
- `.github/workflows/ci.yml`
- 新增 gateway dependency contract test/runbook

**设计**

- 选定一种可复现路径：优先使用独立 `pyproject.toml` + `uv.lock` 并在 Docker 中 `uv sync --frozen`；若保持 requirements，则必须 pin 精确版本并使用 hashes。
- gateway 依赖与 root `uv.lock` 分开审计；CI 对 gateway 运行独立 `pip-audit`/等效审计并阻断高危漏洞。
- 构建使用 lock 文件，不允许 Docker 在 build 时解析开放下界。

**验收**

- 两次 clean build 得到一致依赖版本清单。
- gateway lock 缺失、过期或审计失败会让 CI 失败。
- OAuth health、授权回调与 MCP proxy smoke 通过。

#### M2-E：clear-db durable admin audit（D12 🟡）

**修改范围**

- `backend/app/routers/analytics.py`
- `backend/app/db/migrations/` 新增审计表 migration 或扩展现有专用表
- admin audit service/model 与 security tests

**设计**

- 在不被 clear-db 删除的审计表中记录：admin subject/id、action、target scope、confirmation/request id、开始时间、备份路径/校验摘要、结果、失败原因摘要、完成时间。
- 审计记录不能写入 token、密码、数据库原始内容或备份敏感路径中的 secret。
- 成功、确认失败、备份失败、清理失败、重复请求都产生可查询的结果记录；清理事务不能误删审计记录。
- 保持当前“确认 token + 备份前置”不变，并补充权限、幂等和失败回归测试。

**验收**

- API 成功返回后能按 admin identity 查到 durable success event；失败也能查到明确状态。
- 审计表在 clear-db 后仍存在且记录完整；无权限用户不能写入或读取不属于其权限范围的管理审计。

### M3：文档、类型、运维与合规闭环

#### M3-A：管理员默认值与部署配置文档（D2 🟡）

- 统一 `README.md`、`backend/.env.example` 与 `backend/app/db/migrations/auth.py` 的首次管理员用户名口径。
- 明确环境变量覆盖优先级、首次登录方式和“示例值不代表实际生产值”。
- 加结构测试：文档示例与 seed fallback 不允许无意分叉。

#### M3-B：schema 文档自动生成与 freshness gate（D9 🟡）

- 以 live migration registry（当前到 117）和可重建临时库为唯一来源，更新 `docs/architecture/schema.md`。
- 生成内容至少包含 migration range、表/列/索引/FK、schema version 与生成时间/commit 信息。
- 增加生成脚本或已有脚本的可复用入口；CI 在 schema 输出与临时库不一致时失败。
- 验收：临时库 `foreign_key_check=0`，schema version 与 registry 一致，文档不再停留在 086。

#### M3-C：mypy/TypeScript/ESLint 门禁（D8 🟡）

- 后端按模块分批清零 551 个 mypy errors，禁止大范围 `ignore`；每批保留类型回归测试。
- 前端补 `type-check` 脚本，让 Vue/TS SFC 有明确检查入口；逐步启用 strict 子集，先收敛 errors 再处理 warnings。
- ESLint 从 non-blocking 变 blocking 的前提是错误数为 0、warning 有编号/owner/期限。
- CI 输出 blocking、warning、skipped 三类摘要，脚本契约测试防止结果被总 PASS 覆盖。

#### M3-D：故障 runbook（D6 🟡）

在现有 `backup-restore.md`、`eval-worker.md`、`secret-rotation.md` 之外增加或合并统一入口，覆盖：

- DB 不可用/锁、Redis 不可用、worker offline/队列积压；
- LLM 5xx、超时、rate limit 与 provider 切换；
- 磁盘耗尽、容器 OOM、日志膨胀；
- 备份校验、恢复、回滚、升级与责任升级路径。

每篇必须有症状、止损、验证命令、恢复步骤、数据影响、回滚条件和事后记录；破坏性命令必须有确认与备份前置。

#### M3-E：部署级合规证据矩阵（D11 🟡）

- 在 `docs/compliance/` 提供 deployment-specific 模板/清单，而非继续使用泛化 provider 描述。
- 每个部署实例记录 provider legal entity、处理目的、数据类别、地区/跨境传输机制、保留期、删除方式、子处理者版本和责任人。
- 明确自托管/不同 OpenAI-compatible endpoint 的责任边界；隐私政策链接到实例化配置，不把可配置项写成固定事实。
- 验收使用脱敏 fixture 验证字段完整，不提交真实供应商密钥或个人数据。

## 5. 执行规则（用户确认后生效）

1. 先把本 spec 作为设计基线固定；确认后调用 writing-plans，将当前阶段拆成 2–5 分钟可验证的小任务。
2. 每个生产代码任务先写失败测试并实际看到功能性失败，再做最小实现；配置类改动也尽量用结构测试锁定。
3. 遇到现有测试失败先按 systematic-debugging 做复现、最近变更检查、数据流定位和最小回归；不把未知失败混入新改动。
4. 每完成一个逻辑单元，检查 `git diff` 与 `git status`，只暂存 task-owned 文件；`backups/` 永远不暂存、不删除、不覆盖。
5. 每个阶段完成后做 code review、运行验证命令并提交 focused checkpoint；不 push，除非用户另行授权同步远端。
6. 任何需要扩大权限、修改生产数据、force push、真实 provider 凭据或变更不可逆数据保留策略的动作，单独停下请求确认。

## 6. 阶段验收总表

### M1 完成条件

- nginx/OAuth Compose health 为 healthy；health contract tests 通过。
- line guard 全绿，五个生产巨型文件完成拆分或有明确未完成的独立阻塞说明；不得只涨 cap。
- 后端默认 suite 0 failed；mocked E2E 的失败簇已清零或逐项登记且不冒充 real-stack 证据。
- real-stack smoke 在 CI/本地 disposable Compose 中成功跑通最小链路。

### M2 完成条件

- SSRF rebinding regression、非 root 镜像、JWT restart/error、gateway lock/audit、clear-db durable audit 全部有自动化回归。
- `docker compose config --quiet`、相关镜像 build、security tests 与 dependency audit 通过。

### M3 完成条件

- README/env/seed 默认值一致；schema 文档与 migration 117 自动校验一致。
- mypy/TS/ESLint 达到计划中的 blocking 阈值，剩余 warning 有 owner 与期限。
- 故障 runbook 与部署合规矩阵可由新运维人员按步骤 dry-run，且不含真实 secret/个人数据。

## 7. 最终验证命令

```bash
./scripts/line_guard.sh
./scripts/check.sh backend
./scripts/check.sh frontend
docker compose config --quiet
docker compose --profile test run --rm test uv run pytest backend/tests/infra backend/tests/security -q
cd frontend && npm run build && npm run lint && npm run test
docker compose --profile real-e2e up --abort-on-container-exit --exit-code-from real-e2e
```

其中 `real-e2e` profile、type-check 命令和 schema freshness 命令在对应阶段实现后才加入最终 gate；在此之前不能把它们写成已经存在的验证能力。

## 8. 延后项

以下低灯不属于本轮红/黄整改，但必须保留在下一轮 backlog：

- D5：public contributions requester SQL 过滤与 per-user active request cap；
- D13：完整运行时环境变量 reference 或收窄 README 完整性声明；
- D16：PracticeStarChart/PracticeQuadChart 统一 `chartTokens.js`。
