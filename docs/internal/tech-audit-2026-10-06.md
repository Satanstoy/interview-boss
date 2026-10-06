# Tech audit — 2026-10-06

**审查者**：tech-audit skill，在项目所有者指示下执行
**范围**：全仓库审查，覆盖 D1–D16；D10 属 release-only，本轮没有发布任务，标记 N/A
**审查基线**：`codex/frontend-ui-hierarchy-cleanup`，HEAD `c54520fd8e9ebba5c91f92c51a4c7501d7c35c70`
**发现台账**：[findings.tsv](../../.tech-audit/work/2026-10-06/findings.tsv)；7 条 🔴 均已回读具体实现或复现路径
**对比审计**：[2026-10-02 上传验收审计](../verification/upload-recovery/2026-10-02-spec-audit.md)

---

## 执行摘要

- 🔴 **最高风险**：迁移 012 在复制不完整时仍会删除两张旧表；隔离 SQLite 复现确认旧题目和练习记录可全部丢失。
- 🟢 **当前较强处**：上传恢复补充规格记录的 11/11 AC 使用真实候选应用栈、浏览器、SQLite、Redis、ARQ 和 worker 验收；模型边界由本地确定性 HTTP stub 替代。
- 🟡 **最大差距**：验收结果没有形成全仓规范追踪；权限、读快照、密钥存储、迁移与文档状态仍存在可复现冲突或缺少反例。

## 本轮结论

**整体 Spec 目前没有全对齐。** 可以确认上传恢复补充规格的 11 个闭环 AC 在其验收文档中均标记通过；这不等于所有 ADR/spec 对齐，也不代表一次部署验证覆盖了全部 29 个上传 AC。11 项闭环测试是隔离候选栈，实际服务栈跑浏览器/API/SQLite/Redis/ARQ/worker，模型供应商被本地 stub 替代；没有调用真实模型供应商，也没有对生产环境重新部署或执行验收。

本轮审查检查了仓库状态、代码和规范中的高风险行为，索引覆盖 2,224 个 tracked files，并审阅 D1–D16。`docs/adr` 与 `docs/superpowers/specs` 共 97 份 Markdown 文件；这个数字是文档库存量，不是 97 份规范逐条建立了“条款—代码—测试—候选/生产证据”矩阵。因此不能把本报告解读成所有历史设计文档每一条需求都已独立验收。需要的全仓可追踪矩阵仍是一个缺口。

## 维度概览

| 维度 | 主题 | 状态 | 🔴 | 🟡 | 🟢 |
|---|---|---:|---:|---:|---:|
| D1 | 代码必要性 | ❌ | 2 | 0 | 0 |
| D2 | 文档完整性 | ❌ | 2 | 2 | 0 |
| D3 | 对抗测试 | ⚠️ | 0 | 1 | 0 |
| D4 | 安全态势 | ❌ | 1 | 4 | 0 |
| D5 | 多租户隔离 | ⚠️ | 0 | 1 | 0 |
| D6 | 运维准备 | ✅ | 0 | 0 | 0 |
| D7 | 依赖卫生 | ⚠️ | 0 | 2 | 0 |
| D8 | 构建、CI 与开发循环 | ❌ | 1 | 4 | 0 |
| D9 | 数据完整性 | ❌ | 1 | 0 | 0 |
| D10 | 性能与成本 | N/A | — | — | — |
| D11 | 法律与合规 | ✅ | 0 | 0 | 0 |
| D12 | 管理员界面 | ✅ | 0 | 0 | 0 |
| D13 | 部署可复现性 | ⚠️ | 0 | 4 | 0 |
| D14 | 正确性与健壮性 | ⚠️ | 0 | 2 | 0 |
| D15 | UX 与交互 | ⚠️ | 0 | 7 | 0 |
| D16 | UI 与设计系统 | ⚠️ | 0 | 1 | 0 |
| **合计** | | | **7** | **28** | **0** |

### 如何理解这轮测试证据

- 本轮实际执行的定向分页回归：`backend/tests/pipeline/test_interview_server_pagination.py`，**8 passed**。它验证分页基本行为，没有验证并发写入期间 COUNT/items/rank 的一致快照。
- 本轮执行 `scripts/line_guard.sh`：**失败**，列出 6 个超限文件，与 D1 两条红项对应。
- 在临时内存 SQLite 上调用真实 migration 012：目标表非空、旧表仍有独立数据时，旧题目与旧练习历史均未迁移，源表随后被删除。该探针没有触碰仓库数据库。
- 在内存 SQLite 上直接调用题库删除/恢复路由函数，管理员对其他用户私人题目的单条/批量删除与恢复均被允许。该探针验证了路径，不是正式回归测试。
- 10/04 的闭环实测记录来自隔离候选 Compose 栈。此次审查读取了验收表及 evidence ledger，**没有重跑完整候选栈**。因此本文没有把“候选栈记录通过”写成“本轮真实部署通过”。
- 本次没有读写生产数据库，也没有向生产部署。

### 对齐问题的根因

这轮证据更支持“执行与状态治理有缺口”，不是证明所有 spec 要求彼此矛盾：上传恢复 11 个补充 AC 有具体 Given/When/Then 和候选栈证据；同时，迁移 012 丢数据、管理员跨 owner 写私有题、分页读快照等仍有独立实现缺口。确有少数文档层冲突，例如 9/29 的 Draft 生命周期与 10/04 的验收声明并存、两个决策复用 ADR-0049 编号，但它们不能解释或抵消代码中的数据/权限问题。

反复偏离的共同原因是：旧入口没有统一走已加固的新服务（密钥明文写入）；实现行为与迁移备份分类分开维护（迁移 012）；并发正确性依赖非原子多语句（分页与评测 retry）；完成记录分散在状态文档、AC 矩阵和候选栈证据中，没有一个按版本绑定 commit/image/test 的全局门禁。

## D1 — 代码必要性

**状态：❌** · 源码及集成测试文件超过项目 1,500 行上限；line guard 当前失败。

- 🔴 `backend/app/services/public_contributions.py:1`、`backend/app/worker.py:1`、`backend/app/services/llm.py:1` 分别为 2,041、1,867、1,550 行。按领域拆分，保留现有行为契约。
- 🔴 `backend/tests/chat/test_react_loop.py:1`、`backend/tests/chat/test_chat.py:1`、`backend/tests/integration/test_upload_recovery_stack.py:1` 分别为 3,790、2,046、1,512 行。拆分测试文件并维持行数门禁。

## D2 — 文档完整性

**状态：❌** · 状态源过期、验收链接失效，并有 ADR 与 spec 生命周期歧义。

- 🔴 `docs/status/codex-project-state.md:3,25,56,59-60` 自称唯一事实源，但仍记载 2026-08-24 的 `master` 状态、指向不存在的 `2026-08-23-tech-audit-remediation-spec.md`，并把已 accepted 的 ADR-0048 标成进行中。
- 🔴 `docs/verification/upload-recovery/2026-10-04-closure-real-stack.md:139,153` 的验收矩阵链接少退一级，目标文件不存在。
- 🟡 两份文档都使用 ADR-0049：Harness release provenance 与 system position taxonomies。按编号引用无法唯一定位决策。
- 🟡 9/29 上传恢复 spec 仍禁止执行者自行将 Draft 改为 Accepted；10/04 补充 spec 已宣告 11/11 验收完成，并规定原 spec 非冲突条款继续有效。需要明确规范批准/实施/验收三种状态。

## D3 — 对抗测试

**状态：⚠️** · 核心路径有测试，但认证归一化边界测试不足。

- 🟡 `backend/tests/security/test_auth_normalization.py:26-98` 覆盖大小写和普通空白，没有 NUL、Unicode 空白/大小写折叠和输入长度边界。文件头还保留与当前测试相矛盾的旧缺陷说明。增加边界或属性测试，并修正文档。

## D4 — 安全态势

**状态：❌** · 密钥有可复现的明文落库路径；备份和 OAuth scope 也有高风险缺口。

- 🔴 `backend/app/routers/profile.py:266-274` 与 `backend/app/routers/profile_pkg/embedding.py:98-119` 直接写 `user_profile`，绕过 Fernet；审计时 DB 文件权限是 0644，且 DB 中存在明文敏感配置。所有写入入口应统一加密，并迁移现存值。
- 🟡 `deploy/docker-deploy.sh:848-853` 生成普通 SQLite 备份；审计时最新可识别备份为未加密、0644 权限。使用独立密钥加密并验证隔离恢复。
- 🟡 `oauth-gateway/proxy.py:65-87` 验证 OAuth JWT 后未检查 scope，就用该用户完整 MCP token 转发请求。落实 read/write 方法授权，缺失或未知 scope 默认拒绝。
- 🟡 OAuth 登录失败限制依赖进程内 IP 状态，多实例/重启会削弱限制。将状态放到共享存储并增加多实例验收。
- 🟡 `backend/app/services/llm.py:1192-1196` 在非上传重试路径记录完整 provider exception；只记录稳定错误码、异常类型和状态码。

## D5 — 多租户隔离

**状态：⚠️** · 普通用户 scope 有较多测试；管理员跨 owner 的私人写操作边界仍不清楚。

- 🟡 `backend/app/routers/questions_pkg/bulk.py:275-284,322-345,396-413,428-457` 允许管理员删除、批量删除和恢复他人私人规范题。ADR-0048 默认不让管理员访问他人私人题；若允许受控支持例外，需明确权限、审计和验收，否则默认拒绝。内存探针确认四条路径目前放行。

## D6 — 运维准备

**状态：✅** · 备份恢复、数据库、Redis、worker backlog、LLM 故障、磁盘和 OOM 有 runbook；记录了隔离恢复演练和 RPO/RTO。此结论基于仓库文档审查，不是本轮生产运维演练。

## D7 — 依赖卫生

**状态：⚠️** · 有锁文件、Dependabot 和扫描，但 license 与 SBOM 治理未闭环。

- 🟡 `@mapbox/jsonlint-lines-primitives@2.0.2` 的许可证未能从当前锁定/声明元数据确认；需核对上游许可证及分发义务。
- 🟡 CI 没有生成 SBOM，也没有依赖许可证准入门禁。前端/Python 锁文件和扫描已存在；本项不重复 D4/D8 的漏洞结果。

## D8 — 构建、CI 与开发循环

**状态：❌** · 到期的类型债务没有转成 CI 阻断；容器扫描仍允许已知 HIGH/CRITICAL 结果通过。

- 🔴 `.tech-audit/debt.tsv:3` 的 mypy baseline 为 551 项，到期日 2026-09-30；当前 Ruff/mypy blocking 检查只走本地 audit 模式，CI 未执行。`frontend/tsconfig.json:12` 仍关闭 strict。将门禁接入 CI，并制定逐步降债基线。
- 🟡 `npm audit` 使用 `continue-on-error: true`，Trivy 使用 `exit-code: 0`；当前已知高危依赖仍不会阻断构建。
- 🟡 ShellCheck 配置存在但未在 CI 执行。
- 🟡 commit-msg hook 需要本地手动启用，CI 没有等效提交格式校验。
- 🟡 Docker 基础镜像未按 digest 固定，重建不保证使用同一镜像内容。

## D9 — 数据完整性

**状态：❌** · 已在隔离数据库复现迁移数据丢失。

- 🔴 `backend/app/db/migrations/auth.py:128-173` 只在目标 `question_bank` 完全为空时迁移旧题目，只在目标历史表完全为空时迁移旧记录；之后无条件删除旧表。混合状态会跳过未迁移数据。`backend/app/db/migrations/__init__.py:17` 又没有把版本 12 列入破坏性迁移备份集合。应逐行幂等搬迁、核对关系与数量后删源表，并先自动备份。

## D10 — 性能与成本

**状态：N/A** · 本轮不是发布审查；没有做负载压测或成本预测。

## D11 — 法律与合规

**状态：✅** · 隐私政策披露模型/转写/embedding 等子处理器，删除流程与实例化部署矩阵有文档；人工删除流程仍由有效 debt register 接受。本轮未做法律意见或生产配置核验。

## D12 — 管理员界面

**状态：✅** · 本轮未确认独立于 D5 的管理员界面阻断项；跨租户权限问题列在 D5。

## D13 — 部署可复现性

**状态：⚠️** · 文档、环境变量与 Compose 实际配置在首次部署和自托管 OAuth 地址上不一致。

- 🟡 README 建议填入固定 JWT 占位字符串，而部署脚本只在值为空时生成密钥；照抄会绕过自动生成。说明应与 `.env.example` 一致，留空并让脚本生成持久密钥。
- 🟡 Compose 强制 `EMBEDDING_BACKEND=siliconflow`，示例未提供 `SILICONFLOW_API_KEY`，embedding 首次调用会失败；README 却称其余配置均有默认值。
- 🟡 `GATEWAY_BASE_URL` 使用 Compose 根环境插值，默认公共生产域名；将值写入 `backend/.env` 不会给 Compose 插值变量赋值。自托管 OAuth discovery 可能返回错误地址。
- 🟡 deploy status 仅显示 `compose ps` 和资源统计，并吞掉 `docker stats` 错误；增加统一 health/worker/backlog 检查。

## D14 — 正确性与健壮性

**状态：⚠️** · 文档有同快照要求，但 SQL 查询未提供一致读边界；评测重试也缺并发 claim 证明。

- 🟡 `backend/app/routers/data.py:511-523,1084-1107` 分开执行 COUNT/items 和目标/rank 查询。当前 8/8 分页回归通过，但没有覆盖并发写入；在同一读事务执行并加真实 SQLite 并发验收。
- 🟡 `admin_evaluation.py` 的 retry 是 select-then-act；worker 对 Run/Item 没有原子 claim。并发 retry 或重复投递可能重复工作；增加幂等 claim 与两个请求/重复投递并发测试。

## D15 — UX 与交互

**状态：⚠️** · 7 个源码级交互/可访问性问题；本轮没有浏览器渲染级复核。

- 🟡 面经页读取未注入的 `isDataLoading`，错误态没有页面级恢复动作。
- 🟡 设置页加载岗位/招聘偏好失败后只记 console，默认值仍可保存。
- 🟡 简历删除没有确认。
- 🟡 聊天会话行用 click-only `div`。
- 🟡 上传拖放区无法键盘激活，隐藏文件 input 和文本输入 label 缺关联。
- 🟡 密码字段 label 未关联 input。
- 🟡 API Key 显隐按钮没有可访问名称。

## D16 — UI 与设计系统

**状态：⚠️** · `PracticeStarChart.vue` 重复并偏离共享 PORCELAIN 颜色 token。改为引用共享 token 后还需做渲染级核验；本轮未启动浏览器视觉验收。

## 与 2026-10-02 的变化

前一份 findings TSV 只有一条 D3：AC-029 缺少真实栈证据。本轮全仓审计没有继续把它列为开放项，因为现有 evidence ledger 记录了候选栈的 share、管理员审核、worker 重启/重试和 SQLite 关系断言。按 TSV 机械比较：旧记录 1 条不再出现，本轮为 7 🔴、28 🟡。两轮范围不相同——10/02 文件只记录上传链路，不能据数量判断仓库总体回归。

## 建议的后续里程碑

M-1 到 M-7 是 findings-to-milestones 脚本按红项生成的顺序；黄色项按维度合并成后续小批次。

| 里程碑 | 工作 | 估算 |
|---|---|---:|
| M-1 | 拆分 3 个超限生产模块，保持接口和回归 | 3–5 天 |
| M-2 | 拆分 3 个超限测试模块，保持 line guard | 2–4 天 |
| M-3 | 修正文档唯一事实源、失效链接、ADR 编号和 spec 生命周期状态 | 1–2 天 |
| M-4 | 加密密钥、迁移现存明文、收紧 DB 权限 | 1–2 天 |
| M-5 | 到期静态类型债务进入 CI blocking gate | 3–5 天 |
| M-6 | 修复 migration 012 的行级迁移、备份和混合状态保护 | 2–4 天 |
| M-D3/D4/D5 | 认证对抗测试、OAuth scope/限流、密钥备份和管理员 owner 权限 | 3–5 天 |
| M-D8/D13 | CI 扫描门禁、容器 pin、首启配置与自托管 OAuth 地址 | 3–5 天 |
| M-D14 | 分页读快照和评测工作原子 claim | 3–5 天 |
| M-D15/D16 | loading/error、确认/键盘/a11y、图表 token 修正与渲染验收 | 3–5 天 |

---

**限制**：这是代码、测试结构和仓库记录的全仓审查；没有部署生产、调用真实模型、进行完整 29-AC 单次套件复跑、跨全部 97 份规范文档建立逐条 traceability，也没有做 D15/D16 渲染级验收。具体发现、代码位置、修复建议和置信度以 findings TSV 为准。
