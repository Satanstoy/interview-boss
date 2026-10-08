# 2026-10-07 规格对齐实施验证

基线：`codex/frontend-ui-hierarchy-cleanup`，HEAD `d90794d5`；origin/Gitee 与既有 worktree 未变。用户已有未跟踪审计、spec、backup 链接和 AC007 证据全部保留。不推送、不部署生产。实施计划见 `docs/superpowers/plans/2026-10-07-question-upload-spec-alignment.md`。

## 已确认缺口的闭合范围

| 审计缺口 | 本轮实现与证明 |
|---|---|
| 管理员跨所有者私人规范题变更 | 单条/批量删除恢复及等价写入口统一所有权拒绝；批量拒绝无部分写；55项真实路由/SQLite回归。 |
| 旧单题分享绕过审核、私人来源污染公共题 | 显式不可变申请快照、精确源ID、审核脱敏投影、同事务审计；43项新增spec行为回归。 |
| 旧申请统一列表漏条目、mine漏公共canonical引用 | 统一条目与类型ID路由；有效私人resolution接入mine；相关JWT/SQLite与Vue行为回归。 |
| 失效worker仍可提交、私人成果事务缝隙 | 实际公共/私人/JD写事务检查执行代次和输入版本，成果/关联/队列原子提交；失效/回滚/续租行为回归。 |
| 历史只有20条、任务动作空按钮 | 历史分页及摘要/进度/审核/预算内容；预算owner-only；真实Vue/API mock行为回归。 |
| 缺即时刷新、旧响应覆盖新SSE/跨账号 | 接受/打开/回焦刷新，严格递增revision合并与账号隔离；延迟响应行为回归。 |
| AC029分类标签、恢复身份断言不足 | 私人/公共明细和公共canonical分类标签精确断言；恢复前后detail/resolution/canonical ID比对，隔离真栈证据。 |

以上是本轮已确认缺口的修复范围，不等价于全部原始29项AC的每个子场景已完成。完整命令与证据、剩余边界见下文。

## 单元1：公共发布与私人引用（已验证）

根因：旧单题 share 在公共题精确命中时绕过审批；历史批准按裸文本删除私人副本；统一列表只计数但漏掉旧申请；mine 未读取私人明细指向公共 canonical 的有效 resolution。新增显式申请档案，把不可变快照、精确源身份、脱敏投影、审核人和目标放在事务内。历史来源身份不可靠时不猜测删除私人数据。来源变化后保留新版本；来源被删除后拒绝批准旧快照。

申请档案主键是历史 pending ID（question_bank AUTOINCREMENT，档案不依赖投影存活），source/target 外键 ON DELETE SET NULL，允许合法聚类删除仍保留审核记录。通用删除、恢复、拆分、合并双方、删除原题检查申请生命周期；维护候选及计数仅允许 approved 公共题。拒绝/撤回用 tombstone，不写 SQLite 不允许的 question_bank status。列表读取档案权威状态，防止旧投影恢复导致幽灵申请。审核台从统一列表加载，以类型+ID 区分旧单题与新面经贡献。

### 红绿证据

- 首批13项真实 JWT/FastAPI/隔离迁移 SQLite：9 failed / 4 passed → 13 passed。
- 撤回行为：1 failed / 2 passed → 3 passed。
- 关联删除与申请通用操作6项：6 failed → 6 passed。
- 终态投影恢复后列表：1 failed → 1 passed。
- pending/withdrawn/rejected/historical × split/merge-source/merge-target/delete-original：16 failed → 16 passed。
- 两维护入口：2 failed（pending 被直接合并删除）→ 通过完整回归。
- 最新新增 spec 行为共43项，连同55项跨所有者写回归、题库/JD贡献与 resolution 等相关测试：**175 passed，1 warning，107.25s**。日志 `/tmp/spec-align-bank-checkpoint-final-v3.log`，读取完整末尾及退出码。
- 真实 Vue 审核组件、API mock 的 Playwright：同 ID 混合列表重复展示断言失败 → **1 passed，4.7s**。这项是 UI 行为验证，不是部署、模型或生产验收。

### 执行命令

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend .venv/bin/pytest \
 backend/tests/security/test_question_bank_spec_alignment.py \
 backend/tests/security/test_private_question_write_boundary.py \
 backend/tests/security/test_question_bank_source_projection_scope.py \
 backend/tests/bank/test_bank_share_flow.py backend/tests/bank/test_bank_share_model.py \
 backend/tests/services/test_public_contributions_materialize.py \
 backend/tests/services/test_public_contribution_transitions.py \
 backend/tests/services/test_public_contribution_recovery.py \
 backend/tests/services/test_admin_public_contribution_retry.py \
 backend/tests/services/test_question_resolutions.py \
 backend/tests/infra/test_question_bank_scope_invariants.py -q --show-capture=no
cd frontend
npx playwright test tests/e2e/public-contribution-review.spec.js -g '统一列表'
```

修改的 Python 文件运行 ruff check；审核组件运行 eslint；git diff --check。精确通过结果提交前再次核对。没有 mock 被测路由、授权或数据库写入；故障场景通过实际 SQLite 实现。LLM/Redis 测试依赖由既有离线 fixture 隔离。

## 单元2：上传事务与执行边界（2026-10-08 已验证）

公共/私人/JD持久化现在在 BEGIN IMMEDIATE 内验证 job、lease generation、root、input version、来源与岗位有效性。面经、明细、导入关联、resolution、队列和公共申请在同一事务提交；公共申请服务保留默认 commit，持久化调用显式 commit=False。worker 在模型执行期间独立续租，失败取消执行；进度、答案子任务与收尾阶段应用业务 fence，收尾只更新本 job/本 input version 的检查点。

红绿：失效执行7类、私人队列/关联故障、独立续租、JD与申请事务4项、收尾3项均先复现失败再修复；复审补充输入版本变更后仍写旧进度，1 failed → 通过。原全链路fixture共用内存连接导致并发事务串扰，改成临时文件SQLite每线程真实连接；测试自建练习历史先提交再执行HTTP审核。未mock SQL写入。

最新验证：40 passed，1 warning，30.87s（`/tmp/spec-align-worker-final-v2.log`）；隔离 fullstack/leases/budget 22 passed，1 warning，24.20s（`/tmp/spec-align-fullstack-final.log`）。fullstack采用模型stub，heartbeat/finalize用受控graph流测试实际worker与SQLite，不能视作模型或生产验收。独立review确认进度/收尾边界，无高影响阻塞。ruff、git diff --check通过。

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend .venv/bin/pytest \
 backend/tests/services/test_submit_public_commit_fence.py \
 backend/tests/services/test_submit_personal_commit_atomicity.py \
 backend/tests/services/test_submit_worker_heartbeat.py \
 backend/tests/services/test_submit_worker_finalize_fence.py \
 backend/tests/pipeline/test_upload_graph_recovery_regressions.py \
 backend/tests/integration/test_upload_question_data_flow_worker.py -q
spec_test_dir=$(mktemp -d /tmp/spec-align-fullstack-final.XXXXXX)
UPLOAD_TEST_DB_PATH="$spec_test_dir/test.sqlite3" UPLOAD_TEST_REDIS_PREFIX="spec-align-$RANDOM" \
 OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend .venv/bin/pytest \
 backend/tests/integration/test_upload_recovery_fullstack.py \
 backend/tests/services/test_upload_leases.py backend/tests/security/test_upload_task_budget_scope.py -q
```

## 单元3：任务中心（已本地提交 ca454d2f）

新增历史分页、summary/progress/review/budget内容、打开/回焦/接收任务即时刷新，严格递增revision合并并防账号旧响应。budget接口仅所有者可读，管理员他人任务与不存在均404。新UI行为9项先红后绿；预算JWT/真实路由/SQLite权限3项先红后绿。真实Vue组件及整应用API mock浏览器回归44 passed，1.5m（`/tmp/spec-align-ui-latest.log`）；eslint通过、build成功5.48s（既有chunk大小警告）。这组UI测试不等于真实栈验收。

```bash
cd frontend
npx playwright test tests/e2e/upload-task-center.spec.js tests/e2e/public-contribution-review.spec.js
npx eslint src/components/business/UploadTaskCenter.vue src/composables/useSubmitJobs.js
npm run build
```

## 单元4：真实栈复验（进行中）

当前隔离Docker/SQLite/Redis/HTTP模型stub的 AC001/002 面经分页与公共任务跳转：1 passed，1.9m。命令 `REAL_STACK_PORT=18121 REAL_STACK_STUB_PORT=18122 REAL_STACK_CAPTURE_FAILURE_DB=1 bash /tmp/spec-align-ac001.sh`，临时runner使用原smoke初始化与完整AC001/002块，跳过无关的前置AC011。证据：`test-results/real-stack/interview-boss-real-e2e-3881165-1791439855/`。本次正确发出page2、season、asc和page size请求。此前分页失败本次未复现，未凭猜测修改产品分页代码；浏览器测试增加中途响应证据保存以便下次失败定位。

公共贡献AC029独立候选栈：浏览器1 passed，14.8m，最终SQLite断言exit0。核对私人/公共明细及公共canonical分类标签；worker停止后保存三项成功结果detail/resolution/canonical ID，恢复后相同。项目`interview-boss-real-e2e-3892085-1791440069`，日志`/tmp/spec-align-ac029-latest.log`。最终分类/标签断言助手复制到该明确隔离backend容器后执行；运行中的产品代码未变。首轮临时ID文件实际用于最终比对，但旧success retention未保存该文件；脚本已加入保留，完整smoke重跑会重新产生并归档。

AC010当前候选1 passed，39.2s；AC024当前候选1 passed，30.2s，均有最终DB断言exit0。项目分别`interview-boss-real-e2e-3932895-1791440459`、`interview-boss-real-e2e-3949429-1791440556`。归档DB证据位于`docs/verification/upload-recovery/2026-10-08-spec-alignment/`，仅确定性隔离fixture字段，不提交浏览器认证token。

```bash
python3 .tech-audit/work/2026-10-07/make_ac029_runner.py
REAL_STACK_PORT=18131 REAL_STACK_STUB_PORT=18132 REAL_STACK_CAPTURE_FAILURE_DB=1 bash /tmp/spec-review-ac029.sh
REAL_STACK_PORT=18151 REAL_STACK_STUB_PORT=18152 REAL_STACK_CAPTURE_FAILURE_DB=1 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_ONLY_AC010=1 bash scripts/real_stack_smoke.sh
REAL_STACK_PORT=18161 REAL_STACK_STUB_PORT=18162 REAL_STACK_CAPTURE_FAILURE_DB=1 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_ONLY_AC024=1 bash scripts/real_stack_smoke.sh
```

### 广回归与旧fixture对齐

最新题库/权限175 passed，1 warning，153.49s（`/tmp/spec-align-bank-final.log`，沿用单元1完整命令）；最新题库相关鉴权/上传/恢复广回归463 passed，1 warning，271.11s（`/tmp/spec-align-broad-green.log`）。额外服务回归75 passed/21 skipped，22.67s；21项为需要单独隔离环境的另一个Redis integration harness，未冒充通过。4项fullstack的显式隔离命令见单元2。

广回归先9 failed/454 passed，315.33s：5个restore fixture引用不存在的岗位；匹配回归缺恢复原稿/执行身份或仍断言已不调用的SQL mock；收尾fixture检查点未绑定本job。仅修这些测试条件，不放宽生产校验，移除SQL writer/入队mock改真实SQL断言。修正后相关70 passed，1 warning，47.78s（`/tmp/spec-align-fixtures-final.log`），再跑完整463全绿。该测试单元已提交`5d0a6640`。`test_upload_credential_preflight_job.py`的两个ruff错误由`git show HEAD:<file> | ruff check --stdin-filename ... -`确认预先存在，未顺手修复。其他新改动ruff、eslint、shell/Node语法与diff check通过。

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend .venv/bin/pytest \
 backend/tests/pipeline/test_upload_*.py \
 backend/tests/pipeline/test_public_personal_scope_contract.py \
 backend/tests/pipeline/test_interview_server_pagination.py \
 backend/tests/services/test_upload_*.py backend/tests/services/test_public_contribution*.py \
 backend/tests/services/test_question_resolutions.py backend/tests/security/test_upload_task_privacy.py \
 backend/tests/security/test_private_question_write_boundary.py backend/tests/infra/test_upload_*.py \
 backend/tests/integration/test_upload_question_data_flow.py \
 backend/tests/integration/test_upload_question_data_flow_worker.py -q --show-capture=no
```

### 完整smoke进展与失败证据

完整候选smoke第一次被磁盘耗尽中止；相关SQLite/容器启动失败不算产品失败。只回收本轮临时测试数据库、已退出候选镜像和按明确ID匹配的本轮BuildKit缓存，保留baseline文件、容器和镜像。后续175/463与AC010/024重跑全绿。

`/tmp/spec-align-smoke-final-v2.log`已通过AC011（2.0m）、AC001/002（1.2m）、AC022（14.1s）、AC007浏览器（28.7s），在AC007 DB assertion停止。根因是旧脚本对共享数据库全局attempt数断言2，计入AC011其他owner任务；新增真实SQLite回归1 failed（4!=2）→1 passed，0.67s；按owner root计数且额外本owner attempt仍检出3。生产代码未变。

此前分页失败中一次trace明确显示初始登录导航尚未进入面经页、无面经API请求，已等待初始/master-bank及main view就绪再点击侧栏，无固定sleep。更早page2/升序失败未在独立候选复现，不将它们全部归因于这次导航证据。完整smoke-v4在季筛选等待5秒时退出。保留的Playwright trace显示该请求尚未完成；backend同请求duration_ms=5150.0后返回200/61条，后续season-source响应正确。因此目前证据为断言先于响应超时，未证明产品丢弃响应。真实栈文件局部expect上限改为15秒（HTTP请求超时10秒），同时新增实际DOM行ID与page2/season/asc响应精确比对，不改分页产品代码或数据期望。分页API mock浏览器回归3 passed，21.1s，exit0（`/tmp/spec-align-pagination-ui.log`）。smoke-v5增强分页1 passed/49.9s，AC011/022、AC007浏览器与DB断言、通用栈2项也通过。随后AC028在导入前失败：trace确认register200→model-helper refresh200→llm配置200→goto/import后refresh429；compose日志明确同代理IP累计触发30/min限流，页面回登录，尚未接受上传或重启worker。保存AC028 trace/snapshot至该项目failure目录。runner在独立AC028边界重启本候选backend进程并等待健康，隔离内存limiter，保留SQLite/Redis/凭据/jobs，生产规则不改、不固定sleep。smoke-v6（`/tmp/spec-align-smoke-final-v6.log`）已再次通过AC011、增强分页、AC022、AC007浏览器及DB断言、通用栈2项；隔离后的AC028浏览器1 passed/12.6s，实际worker停止/重启后完成并精确定位。现执行AC029与余下并发场景，整体结果待退出码确认。

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend .venv/bin/pytest backend/tests/infra/test_ac007_trace_scope.py -q
REAL_STACK_PORT=18141 REAL_STACK_STUB_PORT=18142 REAL_STACK_CAPTURE_FAILURE_DB=1 REAL_STACK_REUSE_BUILT_IMAGES=1 bash scripts/real_stack_smoke.sh
```

当前未验收：完整默认smoke余下场景、全部原始AC的所有子场景、特殊支持访问产品流程、历史私人题重建完全收敛、实际外部模型质量/费用与生产历史脏数据、长期多进程故障与真实设备读屏。44项UI suite包含375/1440及键盘操作行为，但不能推导完整真实设备无障碍验收。未部署或推送。
