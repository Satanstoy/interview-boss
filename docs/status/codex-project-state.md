# Codex 与项目状态唯一事实源

更新时间：2026-08-24（Asia/Shanghai）

## 为什么需要这份文件

不同设备上的 Codex 本地会话记录不保证自动合并。项目进度不得以某个 Codex 聊天侧栏为准；新会话、新设备或新 worktree 开始工作前，应先读取本文件，再检查 Git 状态。

官方说明：Codex 历史与 Chat/Work 历史分开；本地聊天留在本机，移动端 Remote 只能访问支持的桌面 Codex 会话，且不会写入普通聊天历史。

## 启动检查

```bash
cd /opt/interview-boss
sed -n '1,260p' docs/status/codex-project-state.md
git status --short --branch
git worktree list
```

## 当前 Git 事实

| 范围 | 状态 |
|---|---|
| 主 worktree | `/opt/interview-boss` |
| 当前分支 | `master` |
| 业务基线 HEAD（生成本文档前） | `afc2071d`（2026-08-24 02:51，部署存储治理） |
| 主 worktree 暂存区 | 空 |
| 主 worktree 未提交 | 53 个已跟踪文件修改、12 个未跟踪项（含空的 `backups/` 目录） |
| 本地 remote-tracking refs | `origin/master` 与 `gitee/master` 都在 `e79d2b0d` |
| `master` 相对本地 remote refs（业务基线） | ahead 16、behind 0；未执行 fetch，线上实际状态需另行确认 |
| 昨天的提交 | 不在 `master`，分散在下面的本地 `codex/*` 分支 |

主 worktree 的大批未提交改动属于公共/个人题库边界、系统岗位 taxonomy、公共贡献审核和流水线作用域改造，不能视为已经合并或已经验证。

## 本地 worktree 与分支

| 分支 | worktree | 当前状态 |
|---|---|---|
| `codex/taxonomy-v1-1` | `/home/ubuntu/.codex/worktrees/638e/interview-boss` | 干净；HEAD `8532b3ce` |
| `codex/tech-audit-2026-08-23` | `/home/ubuntu/.codex/worktrees/bcf9/interview-boss` | 4 个文件未提交修改；HEAD `70e5e6d9` |
| `codex/practice-spec-alignment` | `/home/ubuntu/.codex/worktrees/c1b1/interview-boss` | 18 个文件修改、7 个新增文件未提交；HEAD `551fdc1b` |
| `codex/uiux-tech-audit-2026-08-23` | `/home/ubuntu/.codex/worktrees/f849/interview-boss` | 干净；HEAD `41649913` |

## Spec 完成度

状态含义：

- **已实现（分支）**：代码/测试已形成提交，但不在 `master`，也不代表已推送。
- **进行中（未提交）**：工作区有实现迹象，但还不能当作已完成。
- **部分完成**：Spec 只有部分里程碑落地，仍有明确未完成项或缺少最终验证。
- **审计/设计文档**：只记录发现或方案，不等于代码已经实现。

| Spec / ADR | 当前判断 | 证据与未完成项 |
|---|---|---|
| `docs/specs/2026-08-23-taxonomy-v11-migration.md` | **已实现（`codex/taxonomy-v1-1`），未合并 master** | `fd234a8f` 完成 v1.1 taxonomy 迁移；`b0e84f30` 对齐生产 schema；`2d3e0d95` 增加 Agent taxonomy 修正与答案刷新；`8532b3ce` 加固刷新流程。 |
| `docs/specs/2026-08-23-tech-audit-remediation-spec.md` | **部分完成（主要 P0/P1 已在审计分支提交，未合并 master）** | 已有 secret bootstrap、OAuth 一次性消费、出站 PII 脱敏、隐私请求、SQLite async 边界、限流/ready、备份恢复、测试隔离和评测证据提交。大文件全面拆分、依赖漏洞、全量 CI 门禁、完整真实 E2E 和最终发布门禁仍不能标记为完成。 |
| `docs/specs/2026-08-23-uiux-operation-and-component-consistency.md` | **已实现（`codex/uiux-tech-audit-2026-08-23`），未合并 master** | `66cb0ae3` 是规范；`41649913` 是前端一致性实现。需在目标分支重新跑前端构建、lint 和渲染级 E2E 后才能标记发布完成。 |
| `docs/specs/2026-08-24-practice-optimization.md` | **进行中（未提交）** | `codex/practice-spec-alignment` 有评估幂等、评估持久化、权限前置、due offset 防绕过、历史错误态和前端拆分等改动，但仍在工作区，不能视为已完成或已验证。 |
| `docs/adr/0048-public-personal-question-bank-boundaries.md` | **进行中（主 worktree 未提交）** | 已有公共/个人作用域、快照、贡献申请和审核状态机的设计；主 worktree 同时有对应迁移、服务、路由、队列和测试草稿，尚未提交和验证。 |
| `docs/adr/0049-system-position-taxonomies.md` | **进行中（主 worktree 未提交）** | 已有系统 taxonomy、岗位 active/retired 生命周期和旧个人 taxonomy API 下线的设计；对应代码和迁移仍在主 worktree 未提交。 |
| `docs/internal/tech-audit-2026-08-23.md` | **审计记录，不是完成证明** | 记录了问题、优先级和验证结果；只有对应修复提交并通过新的验证，才能改变 Spec 状态。 |
| `.tech-audit/work/2026-08-23/report.md` | **审计记录，不是完成证明** | 刷题专项审计明确指出幂等、评估持久化、due 配额和权限校验缺口；后续实现目前位于 practice worktree 的未提交改动。 |

## 昨天的 19 个本地提交归属

- `codex/taxonomy-v1-1`：4 个。
- `codex/tech-audit-2026-08-23`：12 个。
- `codex/uiux-tech-audit-2026-08-23`：2 个。
- `codex/practice-spec-alignment`：1 个。

它们目前是本地分支历史，不是 `master` 的已合并历史。

## 工作规则

1. 新设备/新 Codex 会话先读本文件，不以聊天历史判断完成度。
2. 不在 `master` 上直接覆盖已有未提交改动；先确认目标分支和 worktree。
3. “Spec 已写”“代码存在”“已提交”“已合并 master”“已推送”“验证通过”是六个不同状态。
4. 下一步合并前，先分别为 taxonomy、tech-audit、UIUX、practice 和公共题库/岗位 taxonomy 建立验证结果，再做小范围合并。
