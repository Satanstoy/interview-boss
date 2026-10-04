# 2026-10-04 上传闭环候选栈验证账

## 执行边界

- 基线分支：`codex/frontend-ui-hierarchy-cleanup`；构建时工作树包含 AC-007 / AC-022 和结果定位修复。验证完成后代码仍需审查及提交。
- 部署：`scripts/real_stack_smoke.sh` 建立并清理一次性的 Docker Compose 候选栈，Compose 项目标识为 `interview-boss-real-e2e-2902267-1791107085`。
- 数据：仅使用临时 SQLite volume 与隔离 Redis；未连接、读取或写入生产数据库。
- 模型：`interview-boss-llm-stub` 是本地确定性 HTTP provider。API、鉴权、SQLite、Redis、ARQ dispatcher、worker 和浏览器使用真实候选服务；没有调用真实模型供应商。
- 结果目录：完整原始脚本输出为 `test-results/real-stack/interview-boss-real-e2e-2902267-1791107085/`；本账需要长期检查的 JSON trace 已复制至同目录下的 `2026-10-04-real-stack/`。

## 候选镜像

| 镜像 | Digest |
|---|---|
| `interview-boss-app:real-e2e`（backend/worker） | `sha256:607ba70429ccc50c725a4bb6d743825eb357af238cec33614de56e7ec09ef8b2` |
| `interview-boss-nginx:real-e2e`（frontend） | `sha256:7660bde00ffcd5eed4423fbc2f87535e46625f413eb04a7c1a20d41d94835ef3` |
| `interview-boss-llm-stub:real-e2e` | `sha256:2c6407466cd8c754f4bd503ec48949795d136dd4820c2c8f0603eddf7c1dcbf3` |
| `interview-boss-oauth-gateway:real-e2e` | `sha256:7c288caf5804aa27c6049cef82c170c3d0ad8dbd3508acb8d8f077a88838a1ee` |

## 全量隔离栈命令

```bash
bash -n scripts/real_stack_smoke.sh \
  && node --check frontend/tests/e2e/upload-owner-retry-real-stack.spec.js \
  && git diff --check \
  && REAL_STACK_REUSE_BUILT_IMAGES=0 \
     REAL_STACK_CAPTURE_FAILURE_DB=1 \
     AC007_COMPLETION_TIMEOUT_MS=120000 \
     ./scripts/real_stack_smoke.sh
```

结果：退出码 `0`；Playwright 合计 `7 passed, 0 failed, 0 skipped`。任一失败会让脚本非零退出。

| 场景 | 结果 | 关键实测断言 | Evidence |
|---|---:|---|---|
| AC-001/002 | 1 passed | 浏览器经真实 API/SQLite 检查 121 条分页、同时间排序、岗位/季节、U1/U2 隔离及 task target location。target 为预置已发布实体，故不关闭完整 share→review→publish 任务点击验收。 | [浏览器/接口 trace](2026-10-04-real-stack/ac001-ac002-browser-result.json) |
| AC-022 | 1 passed | 真实 multipart 不支持 MIME、空文件、超限均返回 `400/400/413`；草稿保留，拒绝 key 查 `404`；修正后同 key 接受一次、同 hash 重放返回同 root、异 hash `409`。SQLite 只留一个已接受 root/attempt。文件读取字节计数尚未观测。 | [浏览器/API trace](2026-10-04-real-stack/ac022-browser-result.json)、[SQLite trace](2026-10-04-real-stack/ac022-db-trace.json) |
| AC-007 | 1 passed | 两个所有者浏览器并发 retry 返回同一 attempt，仅一个 `created_attempt=true`；U2/管理员访问均 `404`；worker 重启后任务完成；SQLite 确认成功 extraction hash 不变、失败 classify checkpoint 被成功输出替换、attempt 2 的 job 全部完成。当前镜像另有针对性复跑，详情见下节。 | [浏览器 trace](2026-10-04-real-stack/ac007-browser-result.json)、[SQLite trace](2026-10-04-real-stack/ac007-db-trace.json) |
| 基础真实栈回归 | 2 passed | 真实认证、排队/持久化、浏览器渲染，以及响应丢失后通过幂等键恢复同一上传。 | Playwright 结果见原始脚本输出目录 |
| AC-028 回归 | 1 passed | worker 停机期间真实浏览器提交个人面经；worker 恢复后任务完成，点击“查看结果”成功定位同一私人 interview 并显示题目。 | [浏览器结果](2026-10-04-real-stack/ac028-browser-result.json) |
| AC-029 回归 | 1 passed（12.8 分钟） | 真实 share、管理员脱敏审核、三项首发、ordinal 40 注入失败、worker stop/restart 后管理员 retry、最终四项公开；核对私有/公共 detail、canonical/resolution 和累计的发布清单。它没有覆盖 CL-AC-016 要求的同 URL 两份 contribution + 同 URL 私人记录。 | [浏览器 trace](2026-10-04-real-stack/ac029-browser-result.json)、[SQLite 关系 trace](2026-10-04-real-stack/ac029-db-trace.json) |

## AC-009 独立候选栈验收

- 命令：`REAL_STACK_ONLY_AC009=1 REAL_STACK_REUSE_BUILT_IMAGES=0 REAL_STACK_CAPTURE_FAILURE_DB=1 ./scripts/real_stack_smoke.sh`
- 结果：退出码 `0`；Playwright `1 passed, 0 failed, 0 skipped`。候选项目：`interview-boss-real-e2e-3009178-1791109988`。
- 栈使用一次性 SQLite volume、独立 Redis 和真实 API/浏览器/ARQ worker；本地 HTTP stub 只替代模型供应商。没有连接生产数据库。
- 两个浏览器以不同账号近同时提交不同 marker 的私人面经。runner 在 worker 停机时把两条 root 固定到 `2026-10-04 12:00:00`，之后启动两个分离的 `max_jobs=1` worker。SQLite 确认两条 submit job 都从同一秒 `2026-10-04 10:34:10` 开始，两个独立 worker ID 分别执行不同 root 的凭据预检；两条任务均完成。
- 浏览器 trace 断言各用户可读自己的 snapshot 和结果页、不能读对方 snapshot（双向 `404`），并点击各自任务卡打开正确题目。DB trace 逐项核对 requester、attempt、interview owner、detail/import/ordinal、private resolution、canonical owner/source、各自答案及答案 job 归属；不同用户的 marker、question 和答案没有交叉。
- 候选镜像：backend/worker `sha256:570d7d4958da124fc653ea7fbf810ea45e24694db9bb29a1f0c6f0db6d1364cf`；frontend `sha256:0ffb07593dc78eb34c4db8fc2f7411105143808f22a22dfbaffd578ad62d4bf5`；HTTP stub `sha256:34f2fafeac3420be54fe72d6f3cb650391a803814c750ba1157f632e08e90862`；OAuth gateway `sha256:1b20e0f41f928bfdc69e6fe2cfe396f867117b9bfb14dfabb2aa6ed367468f57`。
- 持久证据：[浏览器/API trace](2026-10-04-real-stack/ac009-browser-result.json)、[同秒 root trace](2026-10-04-real-stack/ac009-same-second.json)、[SQLite 关系和 worker trace](2026-10-04-real-stack/ac009-db-trace.json)。

## AC-007 当前镜像针对性复跑

- 命令：`REAL_STACK_ONLY_AC007=1 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_CAPTURE_FAILURE_DB=1 ./scripts/real_stack_smoke.sh`
- 结果：退出码 `0`；Playwright `1 passed, 0 failed, 0 skipped`。候选项目：`interview-boss-real-e2e-3017493-1791110261`，复用上节列出的候选镜像 digest。
- 浏览器实测：U1 的两个会话并发 retry 都返回 attempt 2，恰好一个 `created_attempt=true`；U2 和管理员对 U1 root retry 均为 `404`；worker 重启后 root 到 `completed`。
- SQLite trace 确认 extraction checkpoint 的 hash 未变，失败 classify checkpoint 恢复为成功，attempt 2 的任务完成且个人结果归属 U1。
- [当前镜像浏览器/API trace](2026-10-04-real-stack/ac007-browser-result-current.json)、[当前镜像 SQLite trace](2026-10-04-real-stack/ac007-db-trace-current.json)。
- 此复跑仍未覆盖持续公共流量公平性和 COMMIT 后丢通知对账，所以 AC-007 维持部分状态。

## 红绿与专项回归

| 命令 / 验证 | 结果 | 说明 |
|---|---:|---|
| `cd frontend && npx playwright test tests/e2e/upload-task-center.spec.js -g '私人结果没有岗位 ID 时不发送字面量 undefined 过滤条件'`（修复前） | 1 failed（预期红） | 捕获 location 请求把空岗位 ID 编码成字面量 `position_id=undefined`。 |
| 同上（修复后） | 1 passed | `UploadTaskCenter.vue` 现在只在岗位 ID 存在时发送该参数。AC-028 的真实候选栈随后通过。 |
| `cd frontend && npx playwright test tests/e2e/upload-task-center.spec.js --reporter=line` | 23 passed | 页面层测试通过 API mock 覆盖 EOF 重连、500 保留最后状态、revision 排序/心跳、账号切换和权限动作；这是 mock UI 回归，不作为真实 SSE/候选栈证据。首次并行运行曾因 Vite 动态模块加载超时 1 项，停掉候选栈后独立重跑全绿。 |
| `PYTHONPATH=backend uv run pytest backend/tests/pipeline/test_upload_snapshot_counts.py backend/tests/pipeline/test_upload_classify_checkpoint_recovery.py backend/tests/pipeline/test_upload_stage_recovery.py backend/tests/pipeline/test_upload_graph_recovery_regressions.py backend/tests/pipeline/test_upload_import_retry.py -q` | 35 passed, 1 warning | AC-007 checkpoint 恢复和 list/detail/by-key 答案计数回归。 |
| `PYTHONPATH=backend uv run pytest backend/tests/pipeline/test_upload_retry_family.py backend/tests/pipeline/test_upload_queue_reconciliation.py -q` | 12 passed | attempt 复用/并发、授权、work key 和调度公平性单测。 |
| `PYTHONPATH=backend uv run pytest backend/tests/services/test_upload_status_projection.py backend/tests/services/test_upload_llm_accounting.py backend/tests/infra/test_upload_stream_contract.py -q` | 49 passed | 状态投影、调用账本 helper 和 stream DTO/contract 单测。 |
| `PYTHONPATH=backend uv run pytest backend/tests/security/test_upload_size_guard.py backend/tests/pipeline/test_upload_submit_api.py -q` | 环境阻断 | 本机 `.env` 模型 host 被 SSRF/outbound guard 判为保留地址；4 个 security case fail、15 个 API case 在 app 导入时 error，均未进入业务断言。覆盖这些 API 的真实 multipart AC-022 候选栈验收已通过。占位域名也被本机解析策略拒绝，没有绕过安全检查。 |

## 尚未关闭的验收

本次真实栈是增量证据，不代表 11 项全部对齐。当前状态表见[验收矩阵](../superpowers/specs/2026-10-04-upload-alignment-closure/acceptance.md)：AC-024 尚未运行；AC-001/002/007/010/011/013/016/017/022 仍有表中列明的验收缺口。后续只在该 AC 完整 Given/When/Then 的真实候选栈证据齐备后标记通过。
