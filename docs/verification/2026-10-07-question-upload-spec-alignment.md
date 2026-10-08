# 2026-10-07 规格对齐实施验证

基线：`codex/frontend-ui-hierarchy-cleanup`，HEAD `d90794d5`；origin/Gitee 与既有 worktree 未变。用户已有未跟踪审计、spec、backup 链接和 AC007 证据全部保留。不推送、不部署生产。实施计划见 `docs/superpowers/plans/2026-10-07-question-upload-spec-alignment.md`。

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

## 单元3：任务中心（实现与定向验证通过，待 checkpoint）

新增历史分页、summary/progress/review/budget内容、打开/回焦/接收任务即时刷新，严格递增revision合并并防账号旧响应。budget接口仅所有者可读，管理员他人任务与不存在均404。新UI行为9项先红后绿；预算JWT/真实路由/SQLite权限3项先红后绿。真实Vue组件及整应用API mock浏览器回归44 passed，1.5m（`/tmp/spec-align-ui-latest.log`）；eslint通过、build成功5.48s（既有chunk大小警告）。这组UI测试不等于真实栈验收。

```bash
cd frontend
npx playwright test tests/e2e/upload-task-center.spec.js tests/e2e/public-contribution-review.spec.js
npx eslint src/components/business/UploadTaskCenter.vue src/composables/useSubmitJobs.js
npm run build
```

## 单元4：真实栈复验（进行中）

当前隔离Docker/SQLite/Redis/HTTP模型stub的 AC001/002 面经分页与公共任务跳转：1 passed，1.9m。命令 `REAL_STACK_PORT=18121 REAL_STACK_STUB_PORT=18122 REAL_STACK_CAPTURE_FAILURE_DB=1 bash /tmp/spec-align-ac001.sh`，临时runner使用原smoke初始化与完整AC001/002块，跳过无关的前置AC011。证据：`test-results/real-stack/interview-boss-real-e2e-3881165-1791439855/`。本次正确发出page2、season、asc和page size请求。此前分页失败本次未复现，未凭猜测修改产品分页代码；浏览器测试增加中途响应证据保存以便下次失败定位。

公共贡献AC029正在当前镜像执行；新增公共分类/标签和恢复前成功resolution身份断言，尚不能宣称通过。当前未执行整个默认smoke与全部AC、实际外部模型及生产环境；不宣称所有spec验收完成。
