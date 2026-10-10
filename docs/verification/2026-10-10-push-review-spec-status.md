# 2026-10-10 推送前复审与 spec 对账

## 结论与范围

本轮接续 `aad20465`（`codex/frontend-ui-hierarchy-cleanup`）的未完成审查，覆盖现有未提交产品修改、上一轮四个已确认 spec 缺口的实现和新增边界回归。初始 origin 上不存在同名分支；origin/master 到基线有 188 个本地提交。本次发布当前功能分支，不合并 master，不部署生产，不改 remote，不重写历史。

**上一轮四个主要实现缺口已落实；不能把本次结果表述为全部 spec / 全部 AC 子场景已完成验收。** 本轮又修复账号/草稿并发、规范题留存和单题合并问题。模型质量、生产迁移、完整故障组合等仍缺验收证据。仓库全局行数门禁还有既有超限，见下文。

规格以 accepted [ADR-0048](../../adr/0048-public-personal-question-bank-boundaries.md)、[9-29 恢复契约](../../superpowers/specs/2026-09-29-upload-recovery/contracts.md)、[10-04 闭环验收](../../superpowers/specs/2026-10-04-upload-alignment-closure/acceptance.md) 为依据。原四项缺口与真实栈证据见 [10-09 修复报告](2026-10-09-remaining-spec-fixes.md)，逐项历史证据见 [10-09 再核对](2026-10-09-question-upload-spec-recheck.md)。分支名仍沿用旧 UI 工作分支；不将未跟踪的 9-23 UI spec、旧审计目录、backups 和 AC007 临时证据混入提交。

## 审查与修复

由独立 reviewer 审查后台、前端与 spec，主代理核实反例并运行验证；审查结果并非依赖文件存在或旧日志就标绿。

| 问题 | 最终行为 / 对应回归 |
|---|---|
| 同账号 refresh token 被当作换账号，其他并发 GET 失败 | refresh 在原身份代次内更新 token；登录/退出仍切换代次。并发 refresh 与迟到私人响应各有浏览器回归。 |
| 摘要计算或 by-key 查询时换账号，A 草稿会用 B token 提交 | 每个异步边界核对身份代次和任务用户空间；身份变化错误不被恢复 catch 吞掉，不写 B 的摘要、不继续上传。 |
| 编辑已接受草稿的内容被本地 by-key 快捷恢复掩盖 | 已知摘要一致才直接恢复；不同或未知内容交由服务端检查幂等冲突，409 直接抛出。 |
| 旧草稿缺摘要，或同草稿不同内容并发，冲突响应丢失会误报成功 | 首次尝试只有确认键不存在才建立摘要；写前重读并保留先占摘要。不同摘要关闭恢复权限，不能把 A 任务当作 B 内容成功。 |
| 管理员来源 delete/restore/update 和混合批量删除可碰外人私人记录 | 通过耐久 interview 归属解析明细；所有写入事务内按同一权限检查，外人/不存在均 404，批量无部分修改。 |
| 规范题删除/整理遇到私人、历史 resolution 外键；硬删也会破坏练习引用 | 删除在同一事务失效当前 resolution；compaction 保留软删除的 canonical、私人明细、历史 resolution、私人答题/复习及来源/岗位引用。 |
| compaction 回滚恢复题目但来源镜像/variant 归属未恢复 | 同一回滚事务恢复 retained canonical，并同步涉及题目的 normalized 投影和公共 variant claims；不重建全库。 |
| 同 scope 单题 original_questions 为空时合并 500 | 初始化实际移动题干；公共与管理员本人私人两个合法路径通过真实 HTTP/SQLite 回归。 |
| preflight 配额预约异常仍继续外部调用；缺代次写入检查 | 预约失败拒绝探测；调用前提交预约释放 SQLite 写锁，返回后独立记账，超时记 unknown，代次失效拒绝派业务。 |
| 旧任务 backfill 归属/状态不明确 | 跨 owner、缺 parent、仍活跃和未完成旧链进入 ambiguous，不猜测映射；完成链可幂等应用。 |
| 脱敏 JD 的空 URL 导致其他申请复用同一公共来源 | 空 URL 不用于复用；岗位按审核申请冻结值物化，两个脱敏 JD 分别保留身份。 |
| worker / 公共贡献模块超大、依赖缓存跨工作树误删 | 按职责拆分并保留原导出兼容；依赖键与路径无关，保留被其他工作树引用的缓存；实际 Git worktree 测试通过。 |

## AC 对账

“实现已加入”不等于所有组合、部署数据或真实模型均已验收。下表以本轮新鲜服务/路由/浏览器回归为主，旧真实栈证据单独引用，不冒充本轮重新运行。

| AC | 当前实现 / 验证边界 |
|---|---|
| 001 / 002 | 分页和公共结果定位已实现；本轮分页/任务中心浏览器回归通过。旧真实栈 v7 已定位公共结果，未逐一重跑全部撤权/删除/无结果场景。 |
| 003 / 004 | policy scope 与配置/账本已实现；本轮补 preflight 预约、配额拒绝、unknown 和 fence。未全量覆盖每个 scope/provider 错误组合的真实栈验收。 |
| 005 | 私人明细+公共 canonical 引用及 owner 隔离已实现；本轮补公共删除/重聚类的同事务失效与留存。历史个人重建数据完整消副本仍未生产验收。 |
| 006 | 作用域/匹配异常处理回归通过；全部 provider 故障的真实栈联合证据不足。 |
| 007 | owner/rootless 恢复、队列对账实现与回归存在；公平性、丢通知、rootless 的真实栈证据来自 10-04 闭环，本轮未全量重跑。 |
| 008 | checkpoint / 事务 / 恢复回归通过；四个故障点逐一真实进程中止的当前联合验收仍缺。 |
| 009 | 多 owner / worker 隔离旧真实栈通过；本轮服务回归通过，不代替全部同 owner 交错组合。 |
| 010 | 任务中心详情、刷新、revision / SSE 与账号切换已实现；本轮浏览器实际行为回归通过，新增 HTTP / 草稿身份 fence。 |
| 011 | 逐题失败恢复与成功身份保持已有 v7 真实栈证据；本轮上传回归通过。 |
| 012 | 写入 fence 和事务回归通过，preflight 新增代次核对；长期多进程故障压力仍未验收。 |
| 013 | 错误/预算服务回归通过；完整 401/403/429/格式/超时真实栈矩阵本轮未重跑。 |
| 014 | 实际审核 UI 已获取详情、编辑/排除、默认脱敏、服务端预览、按 revision 提交；本轮面经/JD UI 回归通过，10-09 有 AC029/024 隔离真实栈证据。 |
| 015 | 公共失败题选择恢复、成功 resolution 身份保持旧真实栈通过；本轮公开贡献服务回归通过。 |
| 016 / 017 | 追加/在途并发服务回归通过；两种专用真实栈联合场景本轮未重跑。 |
| 018 | root/job 和历史读取 owner 边界已修；本轮扩展来源写边界，管理员也不能变更外人私人来源。 |
| 019 | count/schema 与排除后的逐题守恒回归通过；旧 v7 实际提取 5 题、公开 4 题。 |
| 020 | 审核/撤回服务竞争和事务回归通过；全部 UI 竞争仍未联合验收。 |
| 021 / 022 | 丢响应/幂等键/文件拒绝与草稿恢复已实现；本轮补编辑、未知摘要及并发冲突丢响应的浏览器回归。 |
| 023 | migration/backfill 回归通过，新增 ambiguous chain 拒绝；未对生产数据执行 dry-run/apply。 |
| 024 | JD 审核/恢复/私人上传旧真实栈通过；本轮验证脱敏 JD 身份与冻结岗位，UI 投影回归通过。 |
| 025 | 输入版本/源删除/岗位失效 fence 回归通过；运行中所有状态变化的浏览器故障矩阵仍未验收。 |
| 026 | 任务历史分页、详情与保留清理回归通过；生产历史 payload 完整性未验证。 |
| 027 | 375/1440 任务中心与操作回归通过；真实设备读屏和完整焦点验收仍缺。 |
| 028 | 隔离 API/SQLite/Redis/worker/provider stub/浏览器旧真实栈通过；本轮未重跑默认整栈，不代表真实模型或生产。 |
| 029 | 逐题提取/分类/聚类/审核/恢复旧 v7 和 10-09 AC029 真实栈通过；本轮保持服务和 UI 回归。所有 scope 配置失效组合仍缺联合验收。 |

另：merge-stats 返回全库数量和类别聚合，不含题干、快照或 ID；私人历史聚合元数据是否也要按用户范围过滤，尚需明确产品契约，未把它当作已确认的正文权限缺口。

## 验证记录

- 上传相关广回归：**480 passed / 1 既有 warning，331.76s，exit 0**，`/tmp/interview-push-review/upload.log`。
- 前端最终固定源码回归：**61 passed，1.7m，exit 0**，`/tmp/interview-push-review/ui-final.log`，含任务中心、面经分页、贡献审核、投影审核及 12 个请求/草稿边界用例。API 边界模拟，实际浏览器模块与组件，不代替生产/真实模型验收。
- 依赖缓存真实 worktree 回归：**2 passed，exit 0**，`/tmp/interview-push-review/cache-final.log`。
- Vite build：exit 0；保留既有 bundle size 提示。修改的前端模块/测试 ESLint 无 error，useSubmitJobs 保留 1 个已有 unused job warning。修改后台文件 Ruff 与 diff 检查通过。
- 历史 gitleaks：扫描 origin/master..候选范围 188 个既有提交，发现 9 个误报（幂等/任务 UUID、固定 AC 标记）。逐个读取历史原文核实，用 `.gitleaksignore` 的精确 commit/path/rule/line 指纹豁免，无目录级新增豁免；复扫无泄露，全部 staged checkpoint 扫描通过。原始配置新增 useDefault，生产默认规则保持开启。
- 原 `check_secrets.py` 全仓库检查仍报 9 个 e2e seed 固定本地测试密码，未报告为真实凭据泄漏、未扩大路径豁免。
- 全仓库 line guard 仍失败于既有文件：`backend/app/services/llm.py` 1550/1500，`backend/tests/chat/test_react_loop.py` 3790/3782，`backend/tests/chat/test_chat.py` 2046/2038，`backend/tests/integration/test_upload_recovery_stack.py` 1512/1500。本轮未改这些文件，故未声称全仓库门禁全绿。worker / public_contributions 拆分后分别低于 1500 行。

失败记录保留：并发 refresh 红灯 1 failed；换账号上传红灯 2 failed；旧草稿未知摘要与不同内容并发各 1 failed；standalone merge 2 failed；compaction 最初测试误将 SSE 作为 JSON、再误用事件名，均不当作业务反例，修正为 done/error 后 4 项真实外键失败；软删除后旧测试硬删除预期需改，首次 bank 广回归 414 passed / 2 failed，不算全组通过；回滚 normalized / variant 镜像扩展红灯 4 failed。首次前端广回归在修复进行中失败，固定源码的最终 61 passed 替代该失败运行。最终题库回归结果补于文末。

命令与完整输出保存在 `/tmp/interview-push-review/`（本机临时证据，不加入提交）；旧真实栈命令/JSON见上述已跟踪报告。本轮不部署，不执行生产迁移，不将 provider stub 当真实模型调用证据。

可重复运行的前端与定向命令（仓库根；前端命令在 frontend）：

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend .venv/bin/pytest \
 backend/tests/security/test_compaction_resolution_retention.py \
 backend/tests/security/test_remaining_spec_boundaries.py \
 backend/tests/security/test_standalone_question_merge.py \
 backend/tests/security/test_push_review_bank_boundaries.py \
 backend/tests/security/test_public_review_preview.py \
 backend/tests/infra/test_upload_review_boundaries.py \
 backend/tests/infra/test_frontend_dependency_cache_behavior.py -q --tb=short --show-capture=no
# bank/upload 广回归采用 10-09 报告中完整命令，bank 额外加入本轮三个 security 文件，
# upload 的 test_upload_*.py glob 会纳入新 infra/test_upload_review_boundaries.py。
npx playwright test --config=tests/playwright.config.js \
 tests/e2e/auth-upload-request-boundaries.spec.js tests/e2e/upload-task-center.spec.js \
 tests/e2e/public-contribution-review.spec.js tests/e2e/public-review-projection.spec.js \
 tests/e2e/interview-pagination.spec.js --workers=1 --reporter=list \
 --output=/tmp/interview-push-review/ui-final-artifacts
npm run build
npx eslint src/services/http.js tests/e2e/auth-upload-request-boundaries.spec.js --max-warnings=0
npx eslint src/composables/useSubmitJobs.js --max-warnings=1
/tmp/spec-review-gitleaks/gitleaks git --redact --log-opts='origin/master..HEAD'
git diff --check
```

## 最终结果与发布

最终题库/鉴权/聚类广回归：**416 passed / 2 既有 warning，228.78s，exit 0**，`/tmp/interview-push-review/bank-verified.log`。该运行在回滚投影/variant 修复后开始，覆盖全部最终后台候选。相关 compaction 子集 52 passed，回滚镜像最终断言 4 passed。

本轮产品/工具提交：`2e97f446`（前端请求/草稿边界）、`d1885c58`（依赖缓存与扫描配置）、`443bef4c`（preflight/backfill/模块拆分）、`cc374436`（来源写权限、规范题留存/回滚和单题合并）。以上提交和先前本地历史推送到 `origin/codex/frontend-ui-hierarchy-cleanup`；报告单独提交。保留原 Gitee remote，未向其同步；未合并 master、部署或生产迁移。

剩余工作区仅保留最初无关的 `.tech-audit/work/2026-08-28/`、`.tech-audit/work/2026-09-23/`、`backups`、9-23 UI spec 与 10-04 AC007 临时 JSON；它们未加入本轮提交。不能声称工作区整体干净。
