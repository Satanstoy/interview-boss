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

## 单元2–4：进行中，不能宣称全部规格完成

实际公共 worker 事务已添加失效执行回归，7种上下文红→绿；合法执行与私人持久化事务正在验证。私人 queue 故障 SQLite trigger 已复现留下已提交 interview/detail，正在修复原子性。任务中心历史分页、详情动作和即时刷新6项浏览器回归已红，尚未实现。新版真实栈及 AC029 完整分类/标签和 resolution 身份断言尚未执行。

仍未验收：独立 worker 续租、私人事务全部故障点、任务中心列表/SSE 同 revision 和账号切换、面经真实分页、新版全流程真实栈。审核台两条原有整应用 mock 测试未重跑，已执行的是新增真实组件行为。不得把这些边界标成通过，也不得把历史基线的真实栈结果算作当前修改验收。
