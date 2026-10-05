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
| AC-001/002（历史运行） | 1 passed | 当次只定位预置已发布目标，未覆盖 share→review→publish 后点击任务卡；该部分缺口已由 2026-10-05 的闭环验收补齐，见文末新记录。 | [历史浏览器/接口 trace](2026-10-04-real-stack/ac001-ac002-browser-result.json) |
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

## AC-007 rootless 队列公平性与 Redis 通知恢复

- 命令：`REAL_STACK_ONLY_AC007_QUEUE=1 REAL_STACK_REUSE_BUILT_IMAGES=0 REAL_STACK_CAPTURE_FAILURE_DB=1 AC007_QUEUE_WORKER_REPLICAS=2 ./scripts/real_stack_smoke.sh`
- 结果：退出码 `0`。候选项目：`interview-boss-real-e2e-3182738-1791115817`；两个真实 worker 容器均通过 Compose health check。
- 环境：一次性 SQLite volume、真实 API、两套 Redis、ARQ dispatcher/worker；仅模型边界使用本地确定性 HTTP stub。未连接生产数据库。
- 公共持续到达公平性：U1 私人队列 7 项，初始公共队列 11 项；worker 处理期间新增 12 波、60 个公共项。9.68 秒时，U1 已完成 5 项，公共队列仍有 65 项 pending；随后两类队列均排空，rootless 活跃 job 为 0。[seed](2026-10-04-real-stack/ac007-queue-seed.json)、[公平性 trace](2026-10-04-real-stack/ac007-queue-fairness.json)、[排空 trace](2026-10-04-real-stack/ac007-queue-idle.json)。
- COMMIT 后丢通知：真实停止 disposable 队列 Redis，再调用真实 `_run_cluster_batch_in_background`。记录到一次 ARQ 连接失败；SQLite 中同一 durable job 保持 pending。Redis 重启后对真实 `scheduled_submit_job_dispatch_task` 连调两次，只得到一个 queued job/`arq_job_id`；两个 worker 恢复后完成该 job，未完成队列行数为 0。[故障种子](2026-10-04-real-stack/ac007-lost-dispatch-seed.json)、[故障后 outbox](2026-10-04-real-stack/ac007-lost-notification.json)、[dispatcher trace](2026-10-04-real-stack/ac007-dispatch-recovery.json)、[最终 worker 状态](2026-10-04-real-stack/ac007-lost-dispatch-final.json)。
- 候选镜像：backend/worker `sha256:c42aa4a1afd9b8f70ccefa2c9595b55f02dca79160d0ad5500c7fbe4ef1d048c`；frontend `sha256:46a9c7decf6a46c0f8fb27c5bf5c9a9776380715537aced6e7cc801fe43a5767`；HTTP model stub `sha256:c454e2bb1c70ef31231bd8dda2524794e00b11ba6fdaff8b05a030d64b0c1891`；OAuth gateway `sha256:8e3c05c29a50481784cb5332c4347b1793d5ec3c8b0bf889f8f3085b85d21371`。
- 上传根任务所有者重试另有真实浏览器/API/SQLite 证据：并发请求共用 attempt 2，U2 与管理员访问为 404，worker 重启后成功，checkpoint hash 保持不变，且浏览器实际打开了恢复后的私人面经。[浏览器 trace](2026-10-04-real-stack/ac007-owner-retry-browser-result.json)、[SQLite trace](2026-10-04-real-stack/ac007-owner-retry-db-trace.json)。
- 当时的部分状态仅反映 rootless 私人失败项仍未验收；该历史结论已由下面同一当前候选镜像的 rootless owner retry 实测取代。

## CL-AC-007 先前候选栈：所有者与 rootless 重试

- 所有者浏览器/API/SQLite 命令：`REAL_STACK_ONLY_AC007=1 REAL_STACK_REUSE_BUILT_IMAGES=0 REAL_STACK_CAPTURE_FAILURE_DB=1 AC007_COMPLETION_TIMEOUT_MS=120000 ./scripts/real_stack_smoke.sh`。结果：退出码 `0`，Playwright `1 passed, 0 failed, 0 skipped`；一次性候选项目 `interview-boss-real-e2e-3236536-1791118288`。该测试覆盖 upload root 恢复和私人 rootless 队列项恢复。
- rootless 浏览器实测：两个 U1 浏览器并发对同一 `queue_id=1` 重试，响应分别为 `202 created=true` 和 `200 created=false`；U2 与管理员请求均为 `404`。两个 U1 任务中心都显示原失败项，并在重试后从失败列表消失。upload root 并发恢复仍收敛到 attempt 2，worker 重启后完成，原成功 extraction checkpoint hash 保持不变，私人结果从任务卡成功打开。
- SQLite 实测：rootless 原队列行为同一行 `id=1`，owner 为 U1，`root_import_id IS NULL`，最终 `status=done`；生成的问题出现在 U1 私人题库。该行未关联 upload root 或 attempt，也没有新建重复队列行；rootless job 的 `upload_attempt_id` 为 null。rootless 记录没有 upload checkpoint 或 upload resolution，数据库验收因此检查原 queue id、owner、root-null 和私人题库投影。
- 证据：[浏览器/API trace](2026-10-04-real-stack/ac007-owner-rootless-browser-result.json)、[SQLite trace](2026-10-04-real-stack/ac007-owner-rootless-db-trace.json)、[fixture seed](2026-10-04-real-stack/ac007-owner-rootless-seed.json)。

## CL-AC-007 先前候选栈：持续公共流量公平性与 Redis 丢通知

- 命令：`REAL_STACK_ONLY_AC007_QUEUE=1 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_CAPTURE_FAILURE_DB=1 AC007_QUEUE_WORKER_REPLICAS=2 ./scripts/real_stack_smoke.sh`。结果：退出码 `0`；两个真实 worker 容器均健康；一次性候选项目 `interview-boss-real-e2e-3244753-1791118451`。此轮复用上一节的镜像 digest。
- 公平性：两 worker 处理期间追加 9 波、45 个公共项；公共队列仍有 50 项 pending 时，U1 已完成 5 个私人项；其后队列全部排空，pending 和活跃 rootless job 均为 0，观测时间 6.866 秒。
- 丢通知恢复：停止 disposable 队列 Redis 后，真实队列写入已提交，但 ARQ 通知失败；SQLite durable job 保持 pending。恢复 Redis 后 dispatcher 用原 idempotency key 恢复同一 job 一次，重复调用没有生成第二个 job；两个 worker 最终完成任务，未完成队列行数为 0。
- 证据：[公平性 fixture](2026-10-04-real-stack/ac007-current-queue-seed.json)、[公平性 trace](2026-10-04-real-stack/ac007-current-queue-fairness.json)、[排空 trace](2026-10-04-real-stack/ac007-current-queue-idle.json)、[通知丢失 trace](2026-10-04-real-stack/ac007-current-lost-notification.json)、[dispatch 恢复 trace](2026-10-04-real-stack/ac007-current-dispatch-recovery.json)、[最终 worker trace](2026-10-04-real-stack/ac007-current-lost-dispatch-final.json)、[故障 seed](2026-10-04-real-stack/ac007-current-lost-dispatch-seed.json)。
- 当前候选镜像：backend/worker `sha256:28302ff2c73e660d4a25e0c2c517e4243753e3b0fe23da80382499231189cd5f`；frontend `sha256:32daedbcf27e1b203d6bb73219b31e860f0f8c418e47a6bc50dc121ad3e29628`；本地 HTTP 模型 stub `sha256:1122700106d84200e8f63364781de818e204f0ddbb52bf93380e6bc2c3e4d4db`；OAuth gateway `sha256:fe3189121b56d653b6a886ee27ea9fe060808d9217d30c7072aa37c1253bbd0a`。
- 边界：API、鉴权、SQLite、Redis、dispatcher、worker 和浏览器均运行真实候选服务；模型供应商边界由本地确定性 HTTP stub 替代。数据只写入 disposable SQLite/Redis，没有连接生产数据库。
- 首次 rootless 候选运行发现两项验收问题：DB 断言错误地要求 rootless 队列生成 upload `question_resolutions`；runner 在 Playwright 等待逻辑后未恢复 `set -e`，导致断言失败时仍退出 `0`。该次运行不计通过。修正断言以核对 rootless 适用的 queue/owner/private projection 契约，并恢复 fail-fast 后，重新构建运行上面记录的候选栈并通过。

## CL-AC-007 首轮候选栈：所有者、公共贡献隔离与双 worker 恢复

- 所有者真实浏览器/API/SQLite 命令：`REAL_STACK_ONLY_AC007=1 REAL_STACK_REUSE_BUILT_IMAGES=0 REAL_STACK_CAPTURE_FAILURE_DB=1 AC007_COMPLETION_TIMEOUT_MS=120000 ./scripts/real_stack_smoke.sh`。结果：退出码 `0`；Playwright `1 passed, 0 failed, 0 skipped`；候选项目 `interview-boss-real-e2e-3296780-1791120557`。
- 上传 root：U1 两个浏览器并发重试收敛到 attempt 2，只有一个请求新建 attempt；U2 和管理员跨 owner 均为 `404`。worker 重启后 root 完成，成功 extraction hash 保持不变，浏览器打开同一 U1 私人结果。
- rootless 私人队列：同一 `queue_id=1` 的并发重试返回 `202 created=true` 与 `200 created=false`；U2/管理员均 `404`。worker 处理后原行到达 `done` 并在 U1 私人题库可见，没有新 root、attempt 或重复 queue row。
- 公共贡献隔离：真实浏览器打开 owner task center 后，公共贡献失败题不出现在个人失败列表；用个人 rootless retry 入口请求其 queue id 返回 `404`。SQLite 确认其 public interview owner、queue owner 和 root 均为空，queue、contribution request、item 状态仍为 `failed`。
- 双 worker 命令：`REAL_STACK_ONLY_AC007_QUEUE=1 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_CAPTURE_FAILURE_DB=1 AC007_QUEUE_WORKER_REPLICAS=2 ./scripts/real_stack_smoke.sh`。结果：退出码 `0`；候选项目 `interview-boss-real-e2e-3304523-1791120705`；两个 worker 健康。持续公共到达期间 55 个 public 项仍 pending 时，U1 已完成 5 个私人项，公平性观测为 7.477 秒；随后队列排空。
- 故障恢复：停止 disposable Redis 后，已提交 durable job 的 ARQ 通知失败；Redis 恢复后重复 dispatch 只产生同一个 job，两个 worker 完成工作。另模拟 rootless 行已提交 `failed→pending` 但 inline scheduler 未创建 job；周期 reconcile 创建/派发 job，worker 最终把原行处理为 `done`，没有 upload root/attempt。
- 最终候选镜像：backend/worker `sha256:9168352adda986471786168f45ab9f7ccaafa9d54268edc0fc2c31f8cc2d73f0`；frontend `sha256:f4d65c2637b759cca795141e1609d1cc821c71f5776fdf4ffe206ec8ae7e0eb7`；本地确定性 HTTP 模型 stub `sha256:73f50066226905bb36b303bc80801cfa766c21edb505cd213e8d6c3bc3e6f4ee`；OAuth gateway `sha256:576850588d8076d6fcaf6a71f82533df9d406703f37885c3e5e1849abc6c414c`。
- 持久证据：[所有者浏览器/API](2026-10-04-real-stack/ac007-final-owner-rootless-browser-result.json)、[所有者 SQLite](2026-10-04-real-stack/ac007-final-owner-rootless-db-trace.json)、[脱敏 fixture seed](2026-10-04-real-stack/ac007-final-owner-rootless-seed.json)、[队列公平性](2026-10-04-real-stack/ac007-final-queue-fairness.json)、[队列排空](2026-10-04-real-stack/ac007-final-queue-idle.json)、[丢通知及 dispatch 恢复](2026-10-04-real-stack/ac007-final-dispatch-recovery.json)、[最终 worker](2026-10-04-real-stack/ac007-final-lost-dispatch-final.json)、[rootless 周期对账恢复](2026-10-04-real-stack/ac007-final-rootless-reconcile-recovery.json)。
- 边界：API、鉴权、SQLite、Redis、ARQ dispatcher、worker 和浏览器都使用候选服务；模型供应商由本地确定性 HTTP stub 替代。只使用 disposable SQLite/Redis，没有连接生产数据库。一次复用旧 backend 镜像的 fixture 运行因缺少新增 seed 字段退出码 `1`，未计入通过；重建镜像后以上两轮复跑均退出码 `0`。

<a id="cl-ac-007-final"></a>
## CL-AC-007 最终复核：连续范围刷新与队列恢复

- RED→GREEN：固定每批 5000 上限前，`loaded_count=5001` 会返回 200；cursor 超出 SQLite signed-int64 时会触发 `OverflowError`；账号切换期间旧分页失败会清掉新用户的加载状态；范围刷新失败后下一次加载会跳到第 3 页；retry 超大 ID 会在 SQLite 绑定处返回 500。对应测试先复现这些失败，再由有界分页、keyset cursor、请求代次保护、失败后页码回算及 API/service 双层整数范围校验转绿。
- GREEN 行为：`POST /api/personal-analysis-queue/failed/refresh` 只返回当前认证 owner 的连续失败范围，总量大于 5000 时按 `(created_at, queue_id)` cursor 分批续取。刷新会补足已消失的失败项并重算页码；账号切换、刷新和分页响应都用 user/refresh/load-more 代次校验，旧响应不能写入新状态。普通用户重试仍使用原 `analysis_queue.id`，不得创建 upload root 或 attempt。
- 本地回归：后端 4 个相关 pipeline 文件 `34 passed, 1 warning`；任务中心完整 Playwright `32 passed`。Python compile、Node syntax check、shell syntax check、Compose config 和 `git diff --check` 均退出码 `0`。Mock UI 测试仅验证前端竞争状态，不代替以下真实候选栈证据。
- owner 真实候选栈：命令 `REAL_STACK_ONLY_AC007=1 REAL_STACK_REUSE_BUILT_IMAGES=0 REAL_STACK_CAPTURE_FAILURE_DB=1 AC007_COMPLETION_TIMEOUT_MS=120000 ./scripts/real_stack_smoke.sh`；退出码 `0`，Playwright `1 passed`；项目 `interview-boss-real-e2e-3424878-1791125059`。构建镜像实际运行浏览器/API/鉴权/worker/SQLite 流程，断言 owner 可恢复原 rootless 行、公共贡献失败项不进入个人列表、跨 owner（含管理员）retry 为 `404`，并检查私人题库投影和 root-null 状态。
- 双 worker 候选栈：命令 `REAL_STACK_ONLY_AC007_QUEUE=1 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_CAPTURE_FAILURE_DB=1 AC007_QUEUE_WORKER_REPLICAS=2 ./scripts/real_stack_smoke.sh`；退出码 `0`；项目 `interview-boss-real-e2e-3432587-1791125175`。公共队列持续有新任务时私人队列仍取得进展；Redis 通知中断后 durable job 只入队一次；已提交但未 inline 派发的 rootless pending 行由周期对账恢复并处理到 `done`，没有 upload root/attempt。
- 最终候选镜像 digest：backend/worker `sha256:1932346e2245a5296c0590f0b888bbc6ce3ae79968e23494df3e511b1dc8f84f`；nginx/frontend `sha256:6ede448cada1fc23bc721ccdd062845e1b4cd01de744953d7117dd30679e6001`；本地 HTTP 模型 stub `sha256:b095f36f87d65e2e06239ef8afe549cbe26c913a2454b48dbf0bfd6b7db75fee`；OAuth gateway `sha256:b2c0843f517be61e11b9858b9f6f2dafc0a7931114d02a420f228f8fe4d71801`。
- 证据：[owner 浏览器/API trace](2026-10-04-real-stack/ac007-range-owner-browser-result.json)、[owner SQLite trace](2026-10-04-real-stack/ac007-range-owner-db-trace.json)、[脱敏 seed](2026-10-04-real-stack/ac007-range-owner-seed.json)、[公平性](2026-10-04-real-stack/ac007-range-queue-fairness.json)、[排空状态](2026-10-04-real-stack/ac007-range-queue-idle.json)、[丢通知及派发恢复](2026-10-04-real-stack/ac007-range-dispatch-recovery.json)、[最终 worker 状态](2026-10-04-real-stack/ac007-range-lost-dispatch-final.json)、[rootless 周期对账恢复](2026-10-04-real-stack/ac007-range-rootless-reconcile-recovery.json)。
- 边界：这两次是 disposable Docker Compose 候选部署，不是生产部署。API、鉴权、SQLite、Redis、dispatcher、worker 与浏览器使用构建后的候选镜像；模型供应商由本地确定性 HTTP stub 替代。没有连接生产数据库或外部模型。

## AC-010 独立候选栈验收

- 命令：`REAL_STACK_ONLY_AC010=1 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_CAPTURE_FAILURE_DB=1 ./scripts/real_stack_smoke.sh`
- 结果：退出码 `0`；Playwright `1 passed, 0 failed, 0 skipped`。候选项目：`interview-boss-real-e2e-3122953-1791113436`。该栈使用临时 SQLite volume 和独立 Redis；没有连接、读取或写入生产数据库。
- 测试专用代理路由只存在于 `nginx/nginx.real-e2e.conf`，由 disposable Compose 只读挂载；生产 `nginx/nginx.conf` 不引用该代理。
- 使用真实 backend、浏览器和 SSE；故障代理只对真实 API/SSE 响应注入 500、延迟 401 和截断 EOF，不伪造成功任务响应。停住 worker 以固定任务快照；本地 HTTP 模型 stub 仅替代模型供应商。
- 浏览器/API 断言：U1 先收到 revision 8，再经真实重连收到 revision 7，页面保留较新状态；任务列表和详情请求 500 时卡片、状态和进度仍保留；心跳不改变状态/进度/计数。跨 owner 详情为 404。U1 登出后旧 SSE 请求被 abort，延迟列表/refresh 401 不重新打开登录遮罩；切换至 U2 后只有 U2 任务流和任务可见，通用 GET 缓存返回 U2 身份。旧用户草稿清除，U2 的恢复草稿在恢复接口 500 后保留。
- 恢复接口在 U2 自有 `partial_failed` 任务上实际返回 500；浏览器重试请求未创建第二条工作图。SQLite 证明 U1/U2 两条 running root 及 U2 recoverable root 均保持原 attempt/job 数量。
- 候选镜像 ID：backend/worker/proxy `sha256:062b341c2c4cb2e39e1538039dda6bac27d18d80aecff50ee4e5079a9c59531c`；frontend `sha256:1b73a93bff67f9dd89d79a85a3cc7341641bd5535825a27caf126fc8a20b1cf8`。本次复用已经构建的镜像。
- 持久证据：[浏览器/API/SSE trace](2026-10-04-real-stack/ac010-browser-result.json)、[SQLite attempt/job trace](2026-10-04-real-stack/ac010-db-trace.json)、[乱序 revision 7 事件](2026-10-04-real-stack/ac010-revision7.json)。

## 红绿与专项回归

| 命令 / 验证 | 结果 | 说明 |
|---|---:|---|
| `cd frontend && npx playwright test tests/e2e/upload-task-center.spec.js -g '私人结果没有岗位 ID 时不发送字面量 undefined 过滤条件'`（修复前） | 1 failed（预期红） | 捕获 location 请求把空岗位 ID 编码成字面量 `position_id=undefined`。 |
| 同上（修复后） | 1 passed | `UploadTaskCenter.vue` 现在只在岗位 ID 存在时发送该参数。AC-028 的真实候选栈随后通过。 |
| `cd frontend && npx playwright test tests/e2e/upload-task-center.spec.js --reporter=line`（本次收尾） | 32 passed | API mock 页面回归覆盖 EOF 重连、500 保留最后状态、revision 排序/心跳、账号切换、权限动作、个人 rootless retry、分页边界、旧账号分页竞态和刷新失败后不跳页；它不作为真实 API/队列证据。真实 owner/rootless API 证据见上面的 AC-007 最终候选栈验收，真实 SSE 证据见 AC-010 独立候选栈验收。 |
| `PYTHONPATH=backend uv run pytest backend/tests/pipeline/test_upload_snapshot_counts.py backend/tests/pipeline/test_upload_classify_checkpoint_recovery.py backend/tests/pipeline/test_upload_stage_recovery.py backend/tests/pipeline/test_upload_graph_recovery_regressions.py backend/tests/pipeline/test_upload_import_retry.py -q` | 35 passed, 1 warning | AC-007 checkpoint 恢复和 list/detail/by-key 答案计数回归。 |
| `PYTHONPATH=backend uv run pytest backend/tests/pipeline/test_upload_retry_family.py backend/tests/pipeline/test_upload_queue_reconciliation.py -q` | 12 passed | attempt 复用/并发、授权、work key 和调度公平性单测。 |
| `PYTHONPATH=backend uv run pytest backend/tests/services/test_upload_status_projection.py backend/tests/services/test_upload_llm_accounting.py backend/tests/infra/test_upload_stream_contract.py -q` | 49 passed | 状态投影、调用账本 helper 和 stream DTO/contract 单测。 |
| `PYTHONPATH=backend uv run pytest backend/tests/security/test_upload_size_guard.py backend/tests/pipeline/test_upload_submit_api.py -q` | 环境阻断 | 本机 `.env` 模型 host 被 SSRF/outbound guard 判为保留地址；4 个 security case fail、15 个 API case 在 app 导入时 error，均未进入业务断言。覆盖这些 API 的真实 multipart AC-022 候选栈验收已通过。占位域名也被本机解析策略拒绝，没有绕过安全检查。 |

## 尚未关闭的验收

2026-10-04 的 AC-007 验收只关闭并标记了 CL-AC-007；当时没有据此声称所有 spec 已对齐。后续 AC-011 的独立结果见下节；当前其余未闭环项见[验收矩阵](../superpowers/specs/2026-10-04-upload-alignment-closure/acceptance.md)。只有对应 Given/When/Then 的真实候选栈证据齐备后，才逐项标记通过。

## CL-AC-011 独立候选栈验收

- 日期：2026-10-05。
- 命令：`REAL_STACK_ONLY_AC011=1 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_PORT=18081 scripts/real_stack_smoke.sh`。
- 结果：脚本退出码 `0`；Playwright `1 passed, 0 failed, 0 skipped`；最终 SQLite/provider trace 交叉断言通过。候选 Compose 项目：`interview-boss-real-e2e-208242-1791200138`。
- 环境：一次性 SQLite volume 和 Redis namespace；真实前端、Nginx、FastAPI、登录鉴权、SSE、ARQ dispatcher、worker 和数据库。LLM provider 边界使用本地 HTTP stub，记录实际 HTTP 请求；业务 API、任务状态、授权、worker 和数据库没有用 mock 代替。没有连接生产数据库，也没有调用模型供应商。
- 镜像 image ID：backend/worker `sha256:8ef19693b9a52c75ab84664a90bf5622d6eb80c381133494b123bf5f2a8edda0`；frontend/Nginx `sha256:48c68ffbc5f63de6da72fd1209d0082b9e68f912c320813f2dbcd14d2bcd672a`；LLM stub `sha256:56863d8dd1d78037a98878272adf8652614b98b5cdba51440f03c2bc43dc62cf`；OAuth gateway `sha256:2c8056aae6dfef454d781aabc54e2e30a4715030c11fccec2a7ac878eafd1078`。
- 首轮实际状态：任务卡、API snapshot 和 SSE 均为 `partial_failed`，10 题中 8 答案成功、2 失败；错误为 `UPSTREAM_UNAVAILABLE` 且 `retryable=true`，所有者动作包含 `retry_failed_steps`；结果可打开。
- 恢复后实际状态：attempt 2 只为题目 ID 9、10 创建 answer job，worker 仅对此两题各新增 1 次实际 HTTP provider 请求；题目 1–8 的答案、结果 hash、job ID 均未变；10 个 detail 的 resolution ID 均保持 `1..10`。最终 snapshot 为 `completed`、10 成功、0 失败；结果页在终态 6 秒后仍能从任务历史重新打开。
- focused backend 回归：答案错误分类与进度测试 `7 passed`；resolution link 相关用例 `6 passed`；遗漏 match 时保留身份测试 `1 passed`。完整 `test_upload_resolution_link.py` 中另有一个与本 AC 无关的贡献模块导入用例被本机 `.env` 上游 URL SSRF guard 阻断；该用例未进入断言。
- 长期证据：[browser/API/SSE trace](2026-10-04-real-stack/ac011-browser-result.json)、[首轮 SQLite/provider trace](2026-10-04-real-stack/ac011-first-pass-db-trace.json)、[最终 SQLite/provider trace](2026-10-04-real-stack/ac011-final-db-trace.json)、[交叉断言结果](2026-10-04-real-stack/ac011-trace-assertion.json)。完整原始候选栈 artifacts 位于 `test-results/real-stack/interview-boss-real-e2e-208242-1791200138/`。

本次验收只关闭 CL-AC-011。CL-AC-001/002/013/016/017/022 部分验收及 CL-AC-024 未运行仍保持开放；见[验收矩阵](../superpowers/specs/2026-10-04-upload-alignment-closure/acceptance.md)。

## CL-AC-013 独立候选栈验收

- 日期：2026-10-05。
- 命令：`REAL_STACK_ONLY_AC013=1 REAL_STACK_REUSE_BUILT_IMAGES=0 REAL_STACK_CAPTURE_FAILURE_DB=1 REAL_STACK_PORT=18081 REAL_STACK_STUB_PORT=18082 scripts/real_stack_smoke.sh`。
- 结果：退出码 `0`；Playwright `1 passed, 0 failed, 0 skipped`（2.6 分钟）；浏览器/API/SSE、SQLite/provider 账本交叉断言和日志脱敏脚本均通过。候选项目：`interview-boss-real-e2e-384602-1791205420`。
- 环境：一次性 SQLite volume、独立 Redis、真实 frontend/Nginx/FastAPI/鉴权/SSE/ARQ dispatcher/worker；模型边界通过本地 HTTP stub 验证真实 provider 请求，不连接生产数据库或外部模型。
- 401 与 403：各产生 1 次标记的 HTTP 请求；提取账本各 1 次失败调用；root 分别为 `needs_action/MODEL_AUTH_INVALID` 与 `needs_action/PERMISSION_REVOKED`，每个只保留 attempt 1 和一条 submit job。API snapshot、SSE、允许动作和任务中心按钮一致。
- 429 与旧入口：首个 attempt 实际发送 3 次 HTTP 429（物理调用上限），root 显示 `partial_failed/UPSTREAM_RATE_LIMIT` 和 `retry_failed_steps`；调用旧 `/api/submit-jobs/{job_id}/retry` 后，同一 root 的 attempt 2 发送 1 次 HTTP 200 并完成。SQLite 有 2 条 submit job、attempt 历史 `failed → completed`；旧 SSE 读回同一 snapshot，没有重复入队。
- 格式失败：实际发送 3 次 HTTP 200 的格式错误响应，提取账本记录 3 次成功 HTTP 调用、阶段最终为 `MODEL_OUTPUT_INVALID`；root 为可恢复的 `partial_failed`，API action 与 `allowed_actions` 一致，只有一条 submit job。
- 超时：第一次 HTTP 请求被 stub 延迟并在模型调用期限内超时；账本保留 1 个 `unknown/APITimeoutError` 和 1 个成功调用，stub 收到两次请求，root 最终 `completed`。SQLite 只有一条 interview 与一份 detail，业务写入没有重复。
- 日志脱敏扫描 118,013 字节，结果 `passed`，未发现 provider key、Authorization header、原文、私有题干或敏感响应标记。provider access ledger 总计 22 次请求，状态为 17×200、1×401、1×403、3×429；逐场景状态见[stub HTTP 账本](2026-10-05-real-stack/ac013-stub-access.json)。
- 候选 image ID：backend/worker `sha256:4ada6281fd90b43afc3227f8b58aea698aded1ce9128966a1aa5e656affbbb19`；nginx/frontend `sha256:ba89d90a9beaf9da738ce570886fd420bce057de4af4bb1cb16648d9f3a01964`；本地 HTTP 模型 stub `sha256:176660801baf2be16c9e7e2fe18fb250491fc14bd34aab649a39ffbfe875b8bf`；OAuth gateway `sha256:474d033b80a863243f1a8ff72d56f2bab12b9044fd15908bd983be3d83a3eb84`。
- 持久证据：[浏览器/API/SSE trace](2026-10-05-real-stack/ac013-browser-result.json)、[401 SQLite trace](2026-10-05-real-stack/ac013-auth_401-db-trace.json)、[403 SQLite trace](2026-10-05-real-stack/ac013-permission_403-db-trace.json)、[429 与旧 retry SQLite trace](2026-10-05-real-stack/ac013-rate_429-db-trace.json)、[格式错误 SQLite trace](2026-10-05-real-stack/ac013-format_invalid-db-trace.json)、[超时 SQLite trace](2026-10-05-real-stack/ac013-timeout_once-db-trace.json)、[日志脱敏结果](2026-10-05-real-stack/ac013-log-redaction.json)。
- 红绿根因：实际 stack 暴露 Tenacity `RetryError` 未被统一分类、legacy retry 把 `credential_preflight` 错投到 submit worker，以及 fixture 协议自动探测调用污染了 extract 物理调用断言。三者分别以 wrapper 异常单测、legacy retry job-type 回归和显式 Chat 的隔离 provider 配置修复；最终候选栈已转绿。

## CL-AC-001/002 候选栈闭环验收

- 日期：2026-10-05。基线提交 `002ae5c0090ed8b1ed67588c7bed03b6fbb56778`；候选镜像由其上的当前工作树构建，包含 AC-001/002 E2E fixture、浏览器断言和 SQLite 关系核验改动。
- 命令：`REAL_STACK_ONLY_AC001_AC002=1 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_CAPTURE_FAILURE_DB=1 ./scripts/real_stack_smoke.sh`。
- 结果：退出码 `0`；Playwright `1 passed, 0 failed, 0 skipped`（3.5 分钟）；后端 SQLite 交叉核验通过。项目：`interview-boss-real-e2e-579948-1791209764`。
- 环境边界：候选 frontend/Nginx、FastAPI、鉴权、Redis、ARQ dispatcher、worker、SQLite 和浏览器走真实调用；SQLite volume 与 Redis namespace 一次性隔离并随 runner 清理。模型 HTTP 边界使用本地确定性 stub；未接生产数据库或外部模型。
- AC-001：U1 在 P1 第 2 页并带季节筛选时，由另一会话提交真实 share 上传；任务到达待审后由管理员真实批准，worker 发布公共投影。原会话未被后台发布改变路由；任务卡点击调用真实 target location API，定位 P2 的公共 interview `126`，页面显示 P2 并高亮目标。U2 可读公共 interview，读取私人 root 为 `404`。SQLite trace 验证 share root `f6c0c765-da38-4429-94a2-f7aa4742b659` → U1 私有 interview `125` → contribution request `2` → 已发布公共 interview `126`，task result target 与公共 interview ID 一致。
- AC-002：121 条 P1 记录经真实服务端分页，断言总数、created_at 相同记录按 ID 稳定排序、翻页不重复、季节筛选、排序切换、page size 变化回到第一页、P1/P2/U2 隔离以及 target lookup 使用相同分页大小并打开正确行。JD DataTable 保持旧客户端模式：真实接口一次返回 45 行，浏览器本地分页为 3 页，切页不产生新 API 请求。
- 隐私断言：真实私有面经保留合成公司名；管理员 review 对 company 的确认值是 null，公共投影 company 为空，U2 公共列表不包含私有公司 marker。
- 候选 image digest：backend/worker `sha256:7c1fd9dcf8c8724724405b7d8177fc6667ee5a50d8b07f6615b83d027c48a471`；nginx/frontend `sha256:07f7cf83bed49dffede4c0a681331704db8c91d69dd210d3db9989c28ff0c44d`；本地 HTTP 模型 stub `sha256:e4991a7110fe127508f9bc619421d629662258566d5f993039971cfec16e2874`；OAuth gateway `sha256:5b1d9af808104182248833ac7a4392c12c3781e9c7e983f2ecbefecf15162104`。
- 持久证据：[真实浏览器/API trace](2026-10-05-real-stack/ac001-ac002-browser-result.json)、[SQLite 关系 trace](2026-10-05-real-stack/ac001-ac002-db-trace.json)。
- 状态：CL-AC-001 和 CL-AC-002 的本补充 Given/When/Then 均有浏览器/API/SQLite 证据，验收矩阵更新为通过。其余开放 AC 仍按矩阵状态处理。
