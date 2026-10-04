# 剩余上传恢复对齐实施计划

对应规格：[闭环规格](../specs/2026-10-04-upload-alignment-closure/README.md)、[验收矩阵](../specs/2026-10-04-upload-alignment-closure/acceptance.md)、[契约](../specs/2026-10-04-upload-alignment-closure/contracts.md)。本计划只覆盖 AC-001/002/007/009/010/011/013/016/017/022/024。每个 checkbox 是独立的小步骤；实现按 TDD 先证伪旧行为，再最小修复。

## 文件职责

- 修改 `backend/app/routers/upload_imports.py`、`backend/app/routers/submit.py`、`backend/app/services/upload_lifecycle.py`、`backend/app/services/upload_queue.py`、`backend/app/services/upload_status.py`、`backend/app/services/public_contributions.py`：恢复权限/预算、队列续调、任务状态及 JD/追加贡献兼容。
- 修改相关前端 `frontend/src/components/business/UploadTaskCenter.vue`、`frontend/src/composables/useSubmitJobs.js`、`frontend/src/composables/useMasterBankData.js`、`frontend/src/views/InterviewView.vue`、`frontend/src/components/common/DataTable.vue`、`frontend/src/services/dataApi.js`：结果定位、分页、恢复操作和连接状态。
- 扩展 `backend/tests/integration/test_upload_recovery_stack.py` 与 `frontend/tests/e2e/upload-recovery-real-stack.spec.js`，并按需求扩展现有 focused backend tests；更新 `scripts/real_stack_smoke.sh` 以执行新增场景和保留 trace。
- 每阶段更新 `docs/verification/upload-recovery/` 的新验证账，不覆盖既有审计历史。

## 阶段 1：接口契约和分页/定位

- [x] 在 `backend/tests/pipeline/test_interview_server_pagination.py` 增加 P1 121 条、同时间戳稳定排序、U2/P2 隔离断言；先运行确认缺失断言能失败。
- [x] 在 `backend/app/routers/data.py` 实现/校正同授权条件下的 COUNT、items、排序、target lookup；运行 focused pagination tests。
- [x] 在 `frontend/tests/e2e/upload-task-center.spec.js` 增加点击后定位已发布公共投影的浏览器契约。
- [ ] 在 `frontend/tests/e2e/upload-recovery-real-stack.spec.js` 用真实上传、公共审核发布和列表 API 验证公共结果定位；断言路由、目标 row ID 与岗位。
- [x] 在 `frontend/src/services/dataApi.js`、`frontend/src/composables/useMasterBankData.js` 及 `backend/app/routers/data.py` 统一 page_size 默认值和 location 参数；运行 focused pagination test 确认实际 query 与响应一致。
- [ ] 首次验收用候选镜像验证真实 share→review→publish→任务点击→结果定位全链路，并将 AC-001/002 trace 与镜像 digest 落盘后再关闭 CL-001/002。当前实栈已验证真实 API/SQLite 分页和已发布公共结果点击，贡献审核流仍待接通。

## 阶段 2：队列和所有者重试

- [x] 为 rootless 私人失败项增加 API RED 用例：列表隔离、同一 queue_id 重排、并发幂等、U2/管理员跨 owner 404、公共/带 root 排除；先观察接口不存在时 4 项失败，再实现并通过 5 项服务/API 测试。
- [x] 在 `personal_analysis_recovery.py`、`personal_analysis_queue.py` 和 `UploadTaskCenter.vue` 实现 owner-only rootless 重试；服务/API 测试及最终候选栈覆盖 owner、公共贡献排除/404、带 root/错配 detail、并发幂等、完整分页和 worker 恢复；浏览器/API/worker/SQLite 证据已归档。
- [x] 修复已加载分页的刷新 fan-out 与状态移动漏项：改为 owner-scoped `loaded_count` 请求（每批最多 5000）和 `(created_at, queue_id)` 稳定游标，避免无界响应；4 页仍是单次请求，超过 5000 已加载项时按批次续取。范围移动后填补空位并重算页码；刷新失败不跳页、账号切换不受旧分页响应影响，cursor/retry ID 限于 SQLite signed-int64。后端、mock UI 和真实候选栈复验。
- [x] 以双 worker 候选栈覆盖持续公共流量下私人桶有界执行、COMMIT 后 Redis 通知丢失只补一个 job；增加“failed→pending 已提交、inline scheduler 缺席”故障窗，由周期对账创建 durable job 并处理完成。证据见候选栈验证账。
- [ ] 在 `backend/tests/pipeline/test_upload_retry_family.py` 加本人 rootless 兼容失败恢复、跨用户/管理员越权、预算耗尽、重复点击和 active attempt 返回用例。
- [ ] 在 `backend/app/services/upload_lifecycle.py` 收敛 attempt 创建/复用和预算判定，再运行 `./.venv/bin/python -m pytest -q backend/tests/pipeline/test_upload_retry_family.py backend/tests/pipeline/test_upload_queue_reconciliation.py`。
- [ ] 在 `backend/app/routers/upload_imports.py` 和 `backend/app/routers/submit.py` 让新旧 retry adapter 调用同一恢复服务；验证认证、actor、404/409 和 `created_attempt` 响应。
- [ ] 在 `frontend/src/components/business/UploadTaskCenter.vue` 对可重试终态显示所有者操作，并渲染预算/配置阻塞；验证并发点击不会产生第二条请求状态。
- [x] 增加实栈双浏览器恢复场景，核对 SQLite 的 attempt/job/checkpoint 数量；当前 AC-007 候选栈还验证了 worker 重启、rootless queue id/owner/root-null/私人题库投影、跨 owner 404 及 pending 无 job 的周期恢复。证据见候选栈验证账；A/B/C 多代 attempt 情形仍属于 AC-017 未完成范围。

## 阶段 3：并发、SSE 和跨代恢复

- [ ] 在 `backend/tests/pipeline/test_upload_stage_recovery.py` 固定同秒时间，以 U1/U2 两个输入断言根、detail、resolution 和答案归属。
- [ ] 在 `backend/tests/pipeline/test_upload_retry_family.py` 用两个连接竞争恢复，并验证 A/B 旧 attempt 都返回 C active。
- [x] 在 `frontend/tests/e2e/upload-task-center.spec.js` 写 EOF、快照 500、乱序 revision、心跳不进度和登出切 U2 场景；任务中心 26 项 mock 页面回归通过，真实边界另由下方 AC-010 候选栈验收。
- [x] 在 `frontend/src/composables/useSubmitJobs.js` 验证快照收敛、EOF 重连及身份变化清理；`cd frontend && npx playwright test tests/e2e/upload-task-center.spec.js` 通过，真实 API/SSE 行为见 AC-010 证据。
- [x] 在实栈场景启两个真实 worker、两个浏览器上下文，交错上传；固定同秒边界后检查跨用户 API 404、任务结果页、DB owner、work_key、resolution、canonical/source 和答案。证据见 `docs/verification/upload-recovery/2026-10-04-real-stack/ac009-db-trace.json`。跨代并发 retry 仍待 AC-017 场景。
- [x] 以一次性 SQLite/Redis 候选栈运行 AC-010，验证真实 SSE EOF、列表/详情 500、乱序 revision、心跳、延迟 401、登出切换 U2 与失败恢复保留；Playwright 1 passed，DB attempt/job 数未变。证据见 `docs/verification/upload-recovery/2026-10-04-real-stack/ac010-browser-result.json` 和 `ac010-db-trace.json`。

## 阶段 4：答案状态和错误预算

- [ ] 在 `backend/tests/services/test_upload_status_projection.py` 写 8/10 答案成功、2 失败的状态聚合红测和精确失败集合断言。
- [ ] 在 `backend/tests/services/test_upload_llm_accounting.py` 用本地 HTTP provider 固定 401 一次、429/结构修复合计至多三次、unknown 超时入账的调用数。
- [ ] 修正 `backend/app/services/upload_status.py`、worker answer/job 路由或 LLM accounting 中被红测指出的缺口；运行 `./.venv/bin/python -m pytest -q backend/tests/services/test_upload_status_projection.py backend/tests/services/test_upload_llm_accounting.py backend/tests/infra/test_upload_stream_contract.py`。
- [ ] 实栈跑 8/2 浏览器流程，核对任务卡、结果页、SSE snapshot、call ledger 和只重跑 2 项；同时让旧 SSE consumer 订阅并断言没有重复 graph。

## 阶段 5：追加贡献和 JD 兼容

- [ ] 在 `backend/tests/services/test_public_contribution_recovery.py` 增加同 URL A/B 两次贡献、B 失败及恢复后 A/B 投影累积断言。
- [ ] 在 `backend/tests/pipeline/test_upload_legacy_compat.py` 增加 JD legacy retry 后不进入题目 pipeline、旧 approved 数据读取不 replay 的反例。
- [ ] 修正 `backend/app/services/public_contributions.py` 与 `backend/app/routers/submit.py` 中由红测证明的 projection/legacy routing 问题；运行 `./.venv/bin/python -m pytest -q backend/tests/services/test_public_contribution_recovery.py backend/tests/pipeline/test_upload_legacy_compat.py`。
- [ ] 实栈执行两份同 URL contribution、worker stop/restart、JD legacy retry→review→publish；逐实体核对公共清单、历史记录及私人 marker。

## 阶段 6：文件拒绝和草稿保留

- [x] 在 `backend/tests/pipeline/test_upload_submit_api.py` 验证真实路由对超限和不支持 MIME 的提前拒绝，断言不读取 UploadFile、不创建 root/job 或派发预检。
- [x] 在 `frontend/tests/e2e/submit-flow.spec.js` 写坏 MIME 后正文与文件草稿保留、纠正后相同 key 首次有效接受的浏览器测试。
- [ ] 修正前后端由失败测试证明的校验/幂等行为；运行 `./.venv/bin/python -m pytest -q backend/tests/security/test_upload_size_guard.py backend/tests/pipeline/test_upload_submit_api.py`。
- [x] 在 disposable API+worker+browser 栈实际传 multipart，再用 DB/Redis 与浏览器断言没有幽灵任务及 key 污染；拒绝 key 查 404，纠正后仅一 root/attempt，重放同 hash 与不同 hash 分别为 202/409。

## 阶段 7：汇总验收与交付证据

- [ ] 将新增 real-stack 场景接入 `scripts/real_stack_smoke.sh`；每个 AC 输出独立 trace，并让任一失败使总命令非零退出。
- [ ] 运行上述 focused backend commands、受影响前端 `npx playwright test`，记录精确 pass/fail/skip；不得通过 skip/降断言清红。
- [ ] 构建 backend/worker/frontend 候选镜像，在隔离 Compose 临时 SQLite/Redis 上运行全部 11 AC；保存 image digest、场景结果和 trace。
- [ ] 逐项核对 `acceptance.md` 并更新验证账：只有 11 项都有通过证据才改为通过；生产只读检查单独记载。
- [ ] 执行 `git diff --check`、审核 task-owned diff 和 `git status --short`；只提交本计划拥有的代码、测试和验证证据，保留 baseline 中未跟踪路径不变。
