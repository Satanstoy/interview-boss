# 剩余上传恢复对齐实施计划

对应规格：[闭环规格](../specs/2026-10-04-upload-alignment-closure/README.md)、[验收矩阵](../specs/2026-10-04-upload-alignment-closure/acceptance.md)、[契约](../specs/2026-10-04-upload-alignment-closure/contracts.md)。本计划只覆盖 AC-001/002/007/009/010/011/013/016/017/022/024。最终验收按 AC 的完整 Given/When/Then 结果判定；原计划建议的部分 focused-test 文件未逐一新增，已由隔离候选栈真实浏览器/API/worker/SQLite 证据覆盖的条目按实际验证方式更新，不把未执行的命令记成通过。

## 最终状态（2026-10-06）

- 本计划范围内的 11/11 AC 均通过隔离候选栈的浏览器/API/worker/SQLite 验收。AC-017 的 worker 在途 retry 交叠和 AC-024 的 bonus、重复审批、普通面经路径已补验。逐项命令、退出码、镜像 digest 和证据见[验收矩阵](../specs/2026-10-04-upload-alignment-closure/acceptance.md)及[候选栈验证账](../../verification/upload-recovery/2026-10-04-closure-real-stack.md)。
- 每个 AC 的模型供应商边界使用本地确定性 HTTP stub；浏览器、鉴权、API、SQLite、Redis、dispatcher 和 worker 为真实候选服务。结果不代表真实模型凭据或生成质量通过。
- AC-024 的 TDD 回归先复现 bonus 未物化和 published 状态重复审批冲突，再验证修复及完整候选栈；普通面经路径也由真实上传界面覆盖。AC-013 计数回归另发现并修复解析器检查点嵌套数据未进入 upload snapshot 的问题。
- 原计划中未新增的指定 focused-test 文件并非未验收 AC；最终 AC 状态只依据矩阵所列的实际测试结果和证据。

## 文件职责

- 修改 `backend/app/routers/upload_imports.py`、`backend/app/routers/submit.py`、`backend/app/services/upload_lifecycle.py`、`backend/app/services/upload_queue.py`、`backend/app/services/upload_status.py`、`backend/app/services/public_contributions.py`：恢复权限/预算、队列续调、任务状态及 JD/追加贡献兼容。
- 修改相关前端 `frontend/src/components/business/UploadTaskCenter.vue`、`frontend/src/composables/useSubmitJobs.js`、`frontend/src/composables/useMasterBankData.js`、`frontend/src/views/InterviewView.vue`、`frontend/src/components/common/DataTable.vue`、`frontend/src/services/dataApi.js`：结果定位、分页、恢复操作和连接状态。
- 扩展 `backend/tests/integration/test_upload_recovery_stack.py` 与 `frontend/tests/e2e/upload-recovery-real-stack.spec.js`，并按需求扩展现有 focused backend tests；更新 `scripts/real_stack_smoke.sh` 以执行新增场景和保留 trace。
- 每阶段更新 `docs/verification/upload-recovery/` 的新验证账，不覆盖既有审计历史。

## 阶段 1：接口契约和分页/定位

- [x] 在 `backend/tests/pipeline/test_interview_server_pagination.py` 增加 P1 121 条、同时间戳稳定排序、U2/P2 隔离断言；先运行确认缺失断言能失败。
- [x] 在 `backend/app/routers/data.py` 实现/校正同授权条件下的 COUNT、items、排序、target lookup；运行 focused pagination tests。
- [x] 在 `frontend/tests/e2e/upload-task-center.spec.js` 增加点击后定位已发布公共投影的浏览器契约。
- [x] AC-001 由真实候选栈浏览器执行上传、审核发布、任务卡定位和列表 API；断言路由、目标 row ID、岗位及 SQLite 公私实体关联，详见验收账。
- [x] 在 `frontend/src/services/dataApi.js`、`frontend/src/composables/useMasterBankData.js` 及 `backend/app/routers/data.py` 统一 page_size 默认值和 location 参数；运行 focused pagination test 确认实际 query 与响应一致。
- [x] 首次完整候选栈验收覆盖 share→review→publish→任务点击→结果定位及服务端分页，AC-001/002 trace 与镜像 digest 已归档，CL-001/002 已关闭。

## 阶段 2：队列和所有者重试

- [x] 为 rootless 私人失败项增加 API RED 用例：列表隔离、同一 queue_id 重排、并发幂等、U2/管理员跨 owner 404、公共/带 root 排除；先观察接口不存在时 4 项失败，再实现并通过 5 项服务/API 测试。
- [x] 在 `personal_analysis_recovery.py`、`personal_analysis_queue.py` 和 `UploadTaskCenter.vue` 实现 owner-only rootless 重试；服务/API 测试及最终候选栈覆盖 owner、公共贡献排除/404、带 root/错配 detail、并发幂等、完整分页和 worker 恢复；浏览器/API/worker/SQLite 证据已归档。
- [x] 修复已加载分页的刷新 fan-out 与状态移动漏项：改为 owner-scoped `loaded_count` 请求（每批最多 5000）和 `(created_at, queue_id)` 稳定游标，避免无界响应；4 页仍是单次请求，超过 5000 已加载项时按批次续取。范围移动后填补空位并重算页码；刷新失败不跳页、账号切换不受旧分页响应影响，cursor/retry ID 限于 SQLite signed-int64。后端、mock UI 和真实候选栈复验。
- [x] 以双 worker 候选栈覆盖持续公共流量下私人桶有界执行、COMMIT 后 Redis 通知丢失只补一个 job；增加“failed→pending 已提交、inline scheduler 缺席”故障窗，由周期对账创建 durable job 并处理完成。证据见候选栈验证账。
- [x] AC-007 通过服务/API 回归和真实候选栈验证本人 rootless 恢复、跨用户/管理员拒绝、预算与重复请求边界、active attempt 复用及队列对账；详见 AC-007 验收账。
- [x] AC-007 真实候选栈核对 attempt 创建/复用、owner actor、rootless queue_id、root-null、checkpoint 与私人投影；另由 AC-017 验证 A/B/C 多代 attempt 收敛。
- [x] 新旧 retry 入口的认证、owner scope、404/409 与恢复响应经候选栈和 API trace 核验，见 AC-007/017 验收账。
- [x] 任务中心可恢复终态操作及并发提交收敛由 AC-007/017 真实浏览器流程验收，预算/配置阻塞状态按对应 API contract 断言。
- [x] 增加实栈双浏览器恢复场景，核对 SQLite 的 attempt/job/checkpoint 数量；AC-007 还验证 worker 重启、rootless queue id/owner/root-null/私人题库投影、跨 owner 404 及 pending 无 job 的周期恢复。A/B/C 多代 attempt 由 AC-017 验收。证据见候选栈验证账。

## 阶段 3：并发、SSE 和跨代恢复

- [x] AC-009 候选栈固定同秒时间，以 U1/U2 两个输入断言根、detail、resolution 和答案归属；证据见 `docs/verification/upload-recovery/2026-10-04-real-stack/ac009-db-trace.json`。
- [x] AC-017 候选栈并发竞争恢复，并验证 A/B 旧 attempt 与两个 owner 浏览器请求都收敛到 C active；证据见 AC-017 browser/SQLite trace。
- [x] 扩展 AC-017 provider 在途闸门：确认两个 worker 正在 claim 同一 root 的不同答案 work key 时，两个浏览器并发 retry 仍收敛到 C；保存 SQLite/provider/浏览器重叠 trace 并在候选栈复跑，详见最终验收账。
- [x] 在 `frontend/tests/e2e/upload-task-center.spec.js` 写 EOF、快照 500、乱序 revision、心跳不进度和登出切 U2 场景；任务中心 26 项 mock 页面回归通过，真实边界另由下方 AC-010 候选栈验收。
- [x] 在 `frontend/src/composables/useSubmitJobs.js` 验证快照收敛、EOF 重连及身份变化清理；`cd frontend && npx playwright test tests/e2e/upload-task-center.spec.js` 通过，真实 API/SSE 行为见 AC-010 证据。
- [x] 在实栈场景启两个真实 worker、两个浏览器上下文，交错上传；固定同秒边界后检查跨用户 API 404、任务结果页、DB owner、work_key、resolution、canonical/source 和答案。证据见 `docs/verification/upload-recovery/2026-10-04-real-stack/ac009-db-trace.json`。跨代并发 retry 由 AC-017 实栈场景通过。
- [x] 以一次性 SQLite/Redis 候选栈运行 AC-010，验证真实 SSE EOF、列表/详情 500、乱序 revision、心跳、延迟 401、登出切换 U2 与失败恢复保留；Playwright 1 passed，DB attempt/job 数未变。证据见 `docs/verification/upload-recovery/2026-10-04-real-stack/ac010-browser-result.json` 和 `ac010-db-trace.json`。

## 阶段 4：答案状态和错误预算

- [x] AC-011 候选栈验证 8/10 答案成功、2 失败、精确失败集合与恢复后只重跑 2 项；任务、SSE、provider call ledger 和 SQLite 状态一致。
- [x] AC-013 候选栈用真实 HTTP provider stub 验证 401 单次、429/结构错误共享三次上限及 unknown timeout 入账，详见候选栈验证账。
- [x] AC-011/013 受影响的状态聚合、HTTP accounting、worker 与 SSE 回归均通过；详细实际运行命令与精确 pass/fail 记录在各自验收账中。原计划列举的每个 focused-test 文件未全部新增，不作为 AC 通过的替代证据。
- [x] AC-011 实栈跑 8/2 浏览器流程并核对任务卡、结果页、SSE snapshot、call ledger 和只重跑 2 项；AC-013 真实 HTTP 旧 SSE consumer 只读且未创建重复 graph。

## 阶段 5：追加贡献和 JD 兼容

- [x] AC-016 回归和候选栈覆盖同 URL A/B 两次贡献、B 失败及恢复后累计投影；服务测试红绿结果见 AC-016 验收账。
- [x] AC-024 候选栈覆盖 JD legacy retry 不进入题目 pipeline、旧 approved 数据读取不 replay；新增持久状态红绿断言修复审核状态落库问题。
- [x] 补齐 JD 审核 allowlist 的 bonus 物化和已发布状态重复审批幂等；服务回归证明同 revision/同投影返回原 JD、无新事件/实体、不同投影冲突，真实浏览器验证普通面经上传、owner 可读且 U2 公共列表不可见。
- [x] 在 AC-024 候选栈中重跑完整 JD retry→review→publish、普通面经上传及旧 approved 数据读取场景，Playwright、provider 和 SQLite 交叉断言通过。
- [x] AC-016/024 受影响的 contribution materialization、legacy routing 与持久状态回归通过；实际运行命令及结果见候选栈验证账。
- [x] AC-016 实栈执行两份同 URL contribution、worker stop/restart 和管理员恢复；AC-024 实栈执行 JD legacy retry→review→publish，逐实体核对公共列表、历史记录及私人 marker。

## 阶段 6：文件拒绝和草稿保留

- [x] 在 `backend/tests/pipeline/test_upload_submit_api.py` 验证真实路由对超限和不支持 MIME 的提前拒绝，断言不读取 UploadFile、不创建 root/job 或派发预检。
- [x] 在 `frontend/tests/e2e/submit-flow.spec.js` 写坏 MIME 后正文与文件草稿保留、纠正后相同 key 首次有效接受的浏览器测试。
- [x] AC-022 的限额、拒绝早停、幂等和浏览器草稿保留已由真实 API/parser/browser 候选栈验收；backend focused 回归通过，实际结果见 AC-022 验收账。
- [x] 在 disposable API+worker+browser 栈实际传 multipart，再用 DB/Redis 与浏览器断言没有幽灵任务及 key 污染；拒绝 key 查 404，纠正后仅一 root/attempt，重放同 hash 与不同 hash 分别为 202/409。

## 阶段 7：汇总验收与交付证据

- [x] 新增 AC-016/017/024 real-stack 场景已接入 `scripts/real_stack_smoke.sh`；每个场景输出独立 trace，失败时 runner 非零退出。
- [x] 已运行本计划 11 项 AC 的 focused backend/E2E 回归及隔离候选栈场景；AC-017/024 的最终重跑与镜像 digest、浏览器/API/provider/SQLite trace 已入验证账。
- [x] 已在隔离 Compose 临时 SQLite/Redis 上部署并逐项运行 AC 候选镜像。所有 11 项均有可追溯的结果和场景证据；模型边界使用本地 HTTP stub。
- [x] 独立复审发现并暂时打开 AC-017/024 缺口；实现、测试和候选栈复验后现 11 项通过。本计划未执行生产业务写入。
- [x] 对 AC-017/024 修复后重跑验证，完成独立复审与 diff check，并只提交本计划拥有的代码、测试和证据；保留 baseline 中未跟踪路径不变。
