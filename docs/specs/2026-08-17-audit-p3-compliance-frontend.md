# Tech Audit P3：合规、用户权利与前端交互收敛

> 日期：2026-08-17
> 前置：P0 数据边界、P1 gate、P2 运行基础已稳定
> 原则：用户可见行为先写失败测试；隐私/删除/导出涉及不可逆操作时必须提供确认、审计和回滚策略。

## 目标

让隐私政策中的用户权利可执行，让注册同意可追溯，并收敛 destructive action、Tooltip 和图表设计 token 的前端遗留。

## Task P3-A：注册同意、数据导出和账号删除

**Files**

- Modify: `frontend/src/components/business/LoginModal.vue`
- Create/Modify: `backend/app/routers/account.py`、`backend/app/services/account_export.py`
- Modify: `backend/app/db/migrations/evaluation.py`、`docs/compliance/privacy-policy.md`、`docs/compliance/account-deletion.md`
- Test: `backend/tests/security/test_account_export_delete.py`、`frontend/tests/e2e/login-register-consent.spec.js`

- [ ] RED：注册未勾选政策时不能提交；导出只返回当前用户数据；删除需要重新认证和确认；重复请求幂等。
- [ ] GREEN：加入版本化政策链接和同意记录；实现带过期时间的导出下载；实现账号删除工作流和审计日志。
- [ ] GREEN：将 `eval_human_reviews.reviewer_id` 改为匿名化/SET NULL 兼容删除，不破坏评测历史。
- [ ] REFACTOR：把隐私政策版本、导出格式、保留规则集中定义并同步文档。

**Done when**：用户能查看、导出、删除自己的数据；管理员不能导出他人数据；删除不会被评测 reviewer FK 阻塞；所有操作有审计记录。

## Task P3-B：破坏性操作确认和可访问性

**Files**

- Modify: `frontend/src/components/business/CodingPractice.vue`
- Modify: `frontend/src/views/PracticeDecksView.vue`、`frontend/src/components/SiteHeader.vue`、`frontend/src/components/business/PracticeMode.vue`
- Test: `frontend/tests/smoke/destructive-actions.spec.js`、`frontend/tests/smoke/tooltip-a11y.spec.js`

- [ ] RED：移除题目、取消收藏、删除题单在未确认时不发送请求；确认、取消、ESC、键盘焦点路径均有断言。
- [ ] GREEN：统一使用 `useConfirm`/AlertDialog/AppTooltip，移除原生 `window.confirm` 和不必要的 `title`。
- [ ] REFACTOR：抽取 destructive action helper，统一文案、焦点和 loading 状态。

**Done when**：所有 destructive action 有二次确认、可键盘操作且不会重复提交。

## Task P3-C：图表 token 与死组件清理

**Files**

- Modify: `frontend/src/components/business/PracticeStarChart.vue`、`PracticeQuadChart.vue`
- Delete: `frontend/src/components/business/ExamDistribution.vue`（确认无引用后）
- Test: `frontend/tests/smoke/chart-token-contract.spec.js`

- [ ] RED：静态测试发现图表组件出现未在 `chartTokens.js` 定义的 porcelain hex；死组件有引用时删除测试失败。
- [ ] GREEN：全部颜色改为 chartTokens；删除 0 引用组件或把它移至明确的 test fixture 目录。
- [ ] REFACTOR：统一 dark/light、tooltip、ramp 和动画 token，保留 reduced-motion 行为。

**Done when**：图表组件不再内联主题色；死组件不进入生产 build；smoke/build 通过。

## P3 验证命令

```bash
cd frontend && npm run test -- --grep 'destructive|tooltip|chart'
npm run build
docker compose --profile test run --rm test uv run pytest \
  backend/tests/security/test_account_export_delete.py -q
```
