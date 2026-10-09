# 公私题库剩余 spec 缺口修复与验证

本轮基线为 `8693f2fb`，分支 `codex/frontend-ui-hierarchy-cleanup`，不是最初审查的 `534a7813`。确认 origin/Gitee 和各 worktree；原有未跟踪审计、spec、backups 及 AC007 文件保留。没有 push 或生产部署。

本轮处理上一份再核对报告的四个确认缺口，以及同一边界内经回归复现的 JD 薪资默认公开、公共 compaction 混入私人目标、历史回滚重建/写回跨作用域问题。实际UI验收还复现标签数组落库失败，已补对应回归修复。不能由本轮通过推导全部 AC 的所有子场景已验收。

## 文件与根因

| 文件（相对仓库根目录） | 修复 |
|---|---|
| backend/app/routers/admin_review.py | 合并历史列表与详情统一按作用域过滤，先过滤再分页/计数；无权和不存在均404。增加旧单题不可变快照的只读公开投影预览。回滚在写事务中复用历史授权，并按证明恢复owner_id、拒绝历史/当前scope不一致。 |
| backend/app/services/merge_history_visibility.py | 核对当前 survivor/merged 所有权及前后快照、已删除参与者的历史所有权证据；损坏或缺证明时隐藏，不从管理员身份推导私人访问权。 |
| backend/app/routers/questions_pkg/mutations.py | 原实现分别检查两端可写，导致管理员自己的私人题与公共题都通过；现于写入前拒绝双向跨作用域合并，409且整库不变。 |
| backend/app/services/pipeline/compact.py | 公共 compaction 的 frequency>1 候选原来漏 owner 条件，真实管理员 compact 路由可修改外人私人目标；现仅加载公共候选，在事务内重查两端当前有效公共状态。删除参与项前保存所有权证明。 |
| backend/app/services/question_promotions.py | 公共投影清空私人模型答案/答案来源；私人行和不可变提交快照仍保留答案，匹配已有公共题时不覆盖其全局答案。公开答案暂缺，沿用现有全局生成入口。提取共享构造函数供旧单题预览与批准使用。 |
| backend/app/routers/public_contributions.py | 新增管理员只读 preview 路由，必须带 revision，沿用422/409/400约定。 |
| backend/app/services/public_contributions.py | 详情返回 revision；预览与批准共用投影 builder，不写库且不返回保留的私人快照。JD salary 纳入默认隐藏的敏感字段。标签数组先规范化成SQLite文本，再预览/hash/物化，避免批准500及预览/落库类型分歧。 |
| frontend/src/components/business/AdminReview.vue | 通过按钮先取详情；面经可改题干/分类/标签/难度并排除题目，JD可改允许的结构字段。公司、轮次、来源、薪资默认空值。服务端预览后才允许确认，提交预览时的原 payload/revision；编辑使预览失效，409保留草稿并要求明确重读。旧单题只读预览后确认。 |
| frontend/src/api/index.js、frontend/src/services/masterBankApi.js | 导出贡献及旧单题预览请求。 |
| backend/tests/security/test_remaining_spec_boundaries.py、test_public_review_preview.py | 真实JWT、FastAPI客户端、路由和隔离SQLite；无路由/授权/SQL写入mock。compact路由仅stub外部模型文本，真实二次验证、事务和写入照常执行。 |
| frontend/tests/e2e/public-review-projection.spec.js、public-contribution-review.spec.js | Vue浏览器/API模拟行为：新旧ID独立、详情、编辑/排除、默认脱敏、预览失效、CAS冲突保留草稿与批准成功。此组不是部署验收。 |
| frontend/tests/e2e/public-contribution-real-stack.spec.js、upload-legacy-jd-ac024-real-stack.spec.js | 将原API编辑/批准改为实际UI操作，仍保留逐题公共/私人数据、恢复身份和revision断言。 |
| docs/superpowers/plans/2026-10-09-remaining-spec-alignment.md | 授权范围与分阶段实施计划。 |

## 红绿证据

- 边界正式回归初次：17 failed / 4 passed，17.72s，exit1，`/tmp/remaining-spec-red.log`。其中两项合法合并fixture没有原题数组，触发已有standalone路径的UnboundLocalError；改fixture覆盖有原题数组的正常合并，没有修该无关实现。随后新增真实compaction证据及答案/历史持久性断言。
- 三个后端边界修复后：121 passed，77.46s，exit0，`/tmp/remaining-spec-backend.log`，含23个新增及98个既有权限/spec行为。
- 历史快照含正文却无所有权证明：1 failed / 23 deselected，3.47s，exit1，`/tmp/history-proof-red.log`；新增拒绝规则后纳入最终通过回归。
- 贡献详情版本/预览：7 failed，6.31s，exit1 → 7 passed，6.31s，exit0。旧单题真实预览：1 failed / 8 passed，7.54s，exit1 → 合并边界/预览32 passed，21.62s，exit0。
- JD薪资：HTTP 1 failed / 2 passed，4.69s，exit1，UI 1 failed（实际初值PRIVATE_SALARY）；修复后审核/边界/投影/撤回/恢复/重试81 passed，74.36s，exit0，`/tmp/remaining-review-focused-green.log`。
- 公共compact路由及当前写作用域：4 failed，6.31s，exit1 → 新边界与已有compaction回归34 passed，64.69s，exit0，`/tmp/compaction-boundary-green.log`。
- 审核UI新增行为：2 failed（无详情直接批准）→ 2 passed；新旧审核合计5 passed，11.0s。最终任务中心/面经分页/审核49 passed，1.9m，exit0，`/tmp/remaining-spec-ui-regression.log`。
- 43fc218b代码题库/鉴权广回归：353 passed，2个既有warning，203.47s，exit0，`/tmp/remaining-spec-authz-final.log`。包含40个本轮新增行为、43个已有题库spec行为与相关鉴权/compaction回归。追加rollback/tags后最终7357d2a8再次同命令运行360 passed、2个既有warning、197.82s、exit0，`/tmp/remaining-spec-authz-latest.log`，包含47个本轮新增行为。
- 上传相关广回归初次469 passed，288.09s，exit0；最终compaction guard加入后再次运行469 passed，291.15s，exit0，`/tmp/remaining-spec-upload-final.log`。追加rollback/tags后再次运行469 passed、1个既有warning、290.67s、exit0，`/tmp/remaining-spec-upload-latest.log`。
- eslint修改文件0 warning/0 error，构建成功7.24s（既有chunk大小提示）；ruff及diff检查通过。没有修既有warning。

完整命令（根目录；前端命令在frontend）：

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend .venv/bin/pytest \
 backend/tests/security/test_remaining_spec_boundaries.py \
 backend/tests/security/test_public_review_preview.py \
 backend/tests/security/test_question_bank_spec_alignment.py \
 backend/tests/security/test_private_question_write_boundary.py backend/tests/bank \
 backend/tests/security/test_authz_unification.py backend/tests/security/test_permission_audit.py \
 backend/tests/security/test_public_rebuild_answer_scope.py \
 backend/tests/security/test_question_bank_source_projection_scope.py \
 backend/tests/infra/test_question_bank_scope_invariants.py backend/tests/infra/test_build_master_bank_rebuild_scope.py \
 backend/tests/services/test_question_variant_reconciliation.py backend/tests/services/test_question_bank_integrity.py \
 backend/tests/services/test_cluster_review_lifecycle.py backend/tests/services/clustering/test_clustering_maintenance.py \
 backend/tests/services/clustering/test_fix_lone_islands.py backend/tests/services/clustering/test_compaction_match_existing.py \
 -q --tb=short --show-capture=no
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend .venv/bin/pytest \
 backend/tests/pipeline/test_upload_*.py backend/tests/pipeline/test_public_personal_scope_contract.py \
 backend/tests/pipeline/test_interview_server_pagination.py backend/tests/services/test_upload_*.py \
 backend/tests/services/test_public_contribution*.py backend/tests/services/test_question_resolutions.py \
 backend/tests/security/test_upload_task_privacy.py backend/tests/security/test_private_question_write_boundary.py \
 backend/tests/infra/test_upload_*.py backend/tests/integration/test_upload_question_data_flow.py \
 backend/tests/integration/test_upload_question_data_flow_worker.py \
 backend/tests/integration/test_upload_acceptance_concurrency.py -q --tb=short --show-capture=no
npx playwright test --config=tests/playwright.config.js tests/e2e/upload-task-center.spec.js \
 tests/e2e/public-contribution-review.spec.js tests/e2e/public-review-projection.spec.js \
 tests/e2e/interview-pagination.spec.js --workers=1 --output /tmp/remaining-spec-ui-artifacts
npm run build
npx eslint src/components/business/AdminReview.vue src/api/index.js src/services/masterBankApi.js --max-warnings=0
npx eslint tests/e2e/public-contribution-real-stack.spec.js tests/e2e/upload-legacy-jd-ac024-real-stack.spec.js --max-warnings=0
.venv/bin/ruff check backend/app/routers/admin_review.py backend/app/routers/public_contributions.py \
 backend/app/routers/questions_pkg/mutations.py backend/app/services/merge_history_visibility.py \
 backend/app/services/pipeline/compact.py backend/app/services/public_contributions.py \
 backend/app/services/question_promotions.py backend/tests/security/test_remaining_spec_boundaries.py \
 backend/tests/security/test_public_review_preview.py
git diff --check
```

- 追加回滚红灯：3 failed / 2 passed，6.45s，exit1（`/tmp/rollback-scope-red.log`）；实际接受已删除外人私人参与项、本人私人参与项默认为公共、私人快照写回公共survivor。标签新建/复用公共来源实际HTTP批准均失败：2 failed，4.34s，exit1（`/tmp/review-tags-red.log`）。修复后7 passed / 40 deselected，6.25s，exit0（`/tmp/rollback-tags-green.log`）。追加相关全组回归196 passed、1个既有warning、169.80s，exit0（`/tmp/remaining-spec-final-boundaries.log`）。

追加回归命令：

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend .venv/bin/pytest \
 backend/tests/security/test_remaining_spec_boundaries.py backend/tests/security/test_public_review_preview.py \
 backend/tests/security/test_private_question_write_boundary.py backend/tests/security/test_question_bank_spec_alignment.py \
 backend/tests/services/test_public_contributions_materialize.py backend/tests/services/test_public_contribution_transitions.py \
 backend/tests/services/test_public_contribution_recovery.py backend/tests/services/test_admin_public_contribution_retry.py \
 backend/tests/services/clustering/test_compaction_match_existing.py -q --tb=short --show-capture=no
```

## 隔离真实栈

首次候选产品代码：43fc218b。app镜像7a5150bbeb5c，nginx镜像cddc665a6b01；本地模型stub ce4e9486ab22，gateway依赖镜像0b6f8b652e43。app从既有离线测试依赖镜像f8323beac0ab复制当前backend；nginx从已有本地nginx依赖复制本轮build产物；gateway重用既有依赖。没有改变生产容器，Compose项目独立、全新命名卷，不挂生产数据。本地stub验证链路控制及归属，不能证明真实外部模型质量、费用或生产效果。

首次AC029在补确认的compact边界前主动中断（exit130），不计通过。首次AC024新增精确菜单选择器不匹配实际按钮的头像文字；独立浏览器观察为Rreal_stack_admin、exact-count=0，改回项目已有的用户名匹配方式，保留审核动作断言。首次AC024实际在菜单精确定位失败（exit1），修正后1 passed/30.2s、SQL断言通过、整体exit0，项目`interview-boss-real-e2e-1123881-1791522778`，日志`/tmp/remaining-spec-ac024-verified.log`。首次新UI AC029确认时500，compose日志明确SQLite不支持tags list绑定，整体exit1（`/tmp/remaining-spec-ac029-verified.log`），未计通过。

```bash
REAL_STACK_PORT=18193 REAL_STACK_STUB_PORT=18194 REAL_STACK_CAPTURE_FAILURE_DB=1 \
 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_ONLY_AC024=1 bash scripts/real_stack_smoke.sh
python3 .tech-audit/work/2026-10-07/make_ac029_runner.py
REAL_STACK_PORT=18191 REAL_STACK_STUB_PORT=18192 REAL_STACK_CAPTURE_FAILURE_DB=1 \
 REAL_STACK_REUSE_BUILT_IMAGES=1 bash /tmp/spec-review-ac029.sh
```

最终产品候选代码：7357d2a8；app镜像4816d599deec，nginx仍为cddc665a6b01。AC010真实任务API/SSE断流、过期revision、读取500、恢复500、账号切换和缓存隔离：1 passed、37.8s，最终SQL断言通过、整体exit0。项目`interview-boss-real-e2e-1149220-1791523434`，日志`/tmp/remaining-spec-ac010-final.log`。数据库attempt/job计数无变化，旧revision未覆盖页面，切账号后旧草稿与缓存隔离；证据保存在[本轮JSON目录](upload-recovery/2026-10-09-remaining-spec/)。

最终7357d2a8候选AC024重新实际UI验收：1 passed、26.2s，最终SQL断言通过、整体exit0。项目`interview-boss-real-e2e-1180275-1791523769`，日志`/tmp/remaining-spec-ac024-latest.log`；本轮JSON目录保存这次最终候选结果。

AC029修复标签后第一次重跑，在审核列表仍显示加载时的5秒题干断言失败，接口返回正确5条；将等待改为目标request卡片可见（30秒），保留卡片题干及后续操作断言。该次exit1，不计通过。下一次完整恢复到4项published后，测试旧变量excludedItem未定义导致ReferenceError、整体exit1（`/tmp/remaining-spec-ac029-final-verified.log`），不计通过。修正为从detail的excludedIndex保留excludedItem；两个真实栈测试追加ESLint检查（含no-undef）和语法检查均exit0，随后全新栈完整重跑。为预查末尾数据断言，将该失败栈捕获的SQLite复制到临时目录、使用原assert_ac029_public_trace.py与第一轮resolution基线做离线SQL核对，exit0（`/tmp/remaining-spec-ac029-offline-sql.log`）；这只验证捕获快照，不改变该次浏览器测试exit1，也不替代最终完整重跑。

```bash
REAL_STACK_PORT=18195 REAL_STACK_STUB_PORT=18196 REAL_STACK_CAPTURE_FAILURE_DB=1 \
 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_ONLY_AC010=1 bash scripts/real_stack_smoke.sh
```

最终AC029完整重跑：1 passed、13.7m，末尾SQL断言通过、整体exit0。项目`interview-boss-real-e2e-1238084-1791524454`，日志`/tmp/remaining-spec-ac029-complete.log`。实际UI编辑题干、排除第50项、默认脱敏、预览后提交同revision；后台原有cron完成公开分类/聚类，保留私人5题与审核公共4题；第20项匹配既有公共canonical #1，来源/frequency不受私人上传影响；失败第40项恢复，前三成功项的detail/resolution/canonical ID保持不变。SQL与浏览器结果保存为本轮目录的ac029-* JSON。

本轮本地实现提交：18d04454、424ac6e6、43fc218b、7357d2a8。最后的测试/验证文档提交仅补证据，产品候选仍为7357d2a8对应镜像。

## 尚未覆盖/未修改

- 不是所有原AC子场景的联合证明：全部scope/provider错误组合、全部进程中止点、长期并发压力、所有approve/withdraw UI竞争未逐一重跑。
- 未实现特殊支持授权产品流程；管理员默认没有私人历史访问权。
- 老历史缺所有权证明时隐藏；没有猜测或重写生产旧历史。
- 旧单题公开答案明确暂缺；未新增全局模型调用或计费任务。
- 未对生产历史数据迁移、真实模型质量/费用、真实设备读屏做验收。
- 合法merge行为覆盖有原题数组的同scope操作；不含数组的已有standalone UnboundLocalError未顺手修复。
