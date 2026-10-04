# 剩余对齐项接口与状态契约

属于[闭环规格](README.md)。本文件细化本轮新增或目前未由真实栈证实的契约；已接受的公共/个人权限与发布规则继续遵循 ADR-0048 和原上传恢复规格。

## 1. 所有者恢复任务

### 1.1 入口和授权

- 任务中心对本人可恢复的 `failed` 或 `partial_failed` 任务显示“重试失败步骤”。`needs_action` 只有在阻塞条件解除后才显示/允许对应恢复动作。
- 根任务优先使用 `POST /api/upload-imports/{import_id}/retry`。兼容任务使用 `POST /api/submit-jobs/{job_id}/retry`，但必须解析到同一业务根/稳定 occurrence，并调用同一恢复服务；不得由兼容入口另启 graph。
- 创建 attempt 返回 `202`；发现活跃 attempt 时返回 `200` 和 `created_attempt=false`；无权或不存在返回 `404`；终态不允许恢复、无法安全解析身份/来源或预算耗尽返回 `409` 及稳定错误 code。相同并发请求须拿到同一 attempt ID。
- 私人 rootless `analysis_queue` 项使用其原 `queue_id` 作为稳定身份：`GET /api/personal-analysis-queue/failed` 只列出当前用户本人、未删除且已批准的私人面经中的 `status='failed'`、`root_import_id IS NULL`、非公共贡献队列行；题目 detail 必须属于该 queue 行关联的同一 interview，且没有 upload `import_id`。接口支持分页，任务中心能按页加载失败列表。任务中心刷新使用 owner-scoped `POST /api/personal-analysis-queue/failed/refresh`，请求 `loaded_count`（1–5000），响应当前仍可恢复的一页、总数和可选稳定游标 `(created_at, queue_id)`；超过一批时按游标续取，服务端不得一次物化无界失败列表。前端以已加载连续范围为目标重取页面，让已完成/删除项后的失败项补位，并按合并行数重算下一页，避免跳页；请求量最多按每 5000 行一批增长，不按 UI 页数增长。分页查询按稳定游标续取，避免状态变化导致 offset 位移漏行。`POST /api/personal-analysis-queue/{queue_id}/retry` 只把该行从 `failed` 原子改回 `pending`。新建恢复返回 `202`、`created=true`；重复请求看到同一行 `pending/processing` 时返回 `200`、`created=false`。响应不创建也不返回 upload root、upload attempt 或 checkpoint。
- rootless retry 使用当前认证用户触发已有持久队列 scheduler；worker 按队列行 owner 选择个人模型配置。请求只重新排入指定 `queue_id`，不重新提交整条面经；批处理仍可按既有队列规则处理其他已经 pending 的项。本人之外（包括管理员跨 owner）、公共/贡献失败项、带 upload root 的行、已删除或未批准的面经均从 owner API 返回 `404`。公共贡献失败继续走管理员专用入口。
- `failed→pending` 的 durable queue row 是恢复事实来源；若进程在状态提交后、inline job 创建前退出，定时对账必须发现符合 rootless 个人 scope 的 pending 行，并幂等地恢复/调度一个可执行 job。不能要求用户再次点击，也不能因重复对账创建重复 active job。
- 普通用户只能恢复自己的任务。跨用户请求，包括管理员借普通用户入口请求他人私有任务，返回 404，不透露任务是否存在。操作审计中的 actor 必须是当前认证身份，不能伪装为任务 owner。
- 身份映射不唯一、原始实体已删除、源不再有效、pipeline/input 版本无法复用时返回 409 `TASK_RECOVERY_BLOCKED`，包含稳定的 `reason_code` 和 `allowed_actions`，不派发任何 job。
- 审核通过后的公共贡献失败仍由 `POST /api/admin/public-contributions/{id}/retry` 恢复失败 ordinal；所有者任务按钮不能替代管理员审核/公共处理权限，也不能改变 review projection。

### 1.2 幂等、预算和恢复范围

- upload root 恢复响应包含根任务快照、当前 attempt、`created_attempt: boolean` 和可执行/阻塞动作。活跃 attempt 已存在时返回该 attempt 和 `created_attempt=false`。rootless 响应包含原 `queue_id`、队列状态及 `created: boolean`，不伪造 attempt。
- upload root 的两个并发恢复请求在事务竞争下只能有一个新活跃 attempt。输家返回胜出的 attempt，不创建重复 attempt/job。rootless 并发请求以同一原 `queue_id` 收敛：至多一个请求做 `failed→pending`，其余观察相同 `pending/processing` 行，不插入重复队列项。
- 新 upload attempt 只含失败、缺失或已失效步骤。成功且输入版本、pipeline 版本有效的 extraction/classification/persist/resolution/answer 结果必须沿用原 ID/hash。rootless 行没有 upload checkpoint/current upload resolution；验收要求重排原失败行并在 owner 私人 scope 完成，使原问题可从该用户私人题库读取，不要求构造 upload checkpoint。
- 单步自动重试总次数、每导入调用预算、用户日配额、系统日预算跨手动恢复累计。手动点击不能重置计数或把已记为 `unknown` 的外部调用当免费成功。超预算返回 409 `RETRY_BUDGET_EXHAUSTED`，保留成果并提供 `reset_at`（若适用）；不能排 job。
- 用户模型配置修复后，恢复从正确的 user scope 重新预检。global/system 阻塞时保留 `wait_for_global_model` / `retry_after_configuration` 语义；不能改用个人 Key。
- 已完成、已拒绝、已撤回、无失败工作或明确不可重试的任务不创建 attempt，返回 409 `RETRY_NOT_ALLOWED` 和可读原因。

## 2. 结果定位和服务端分页

### 2.1 结果定位

任务快照只在目标具有合法读取权限时提供稳定结果标识和 `open_result`。增加可选 `result_target`，结构为 `{"entity_type":"interview","entity_id":123,"scope":"private|public"}`；只有 `allowed_actions` 包含 `open_result` 时该目标可打开。普通分享任务的公共投影发布后，`result_target` 指向已发布公共面经 ID 且 `scope="public"`；不得把私人暂存面经 ID 标成公共结果。等待审核、已拒绝或公共处理未完成时只能打开用户有权查看的私人结果/申请状态。该字段与原有 `result.interview_id`（私人处理结果兼容字段）并存，不能改变后者的历史含义。

任务卡上的“查看结果”使用稳定 `interview_id`（或同一公共实体的稳定 ID）定位。面经列表必须向服务端请求目标的授权页，不可只在当前页数组中查找。自动完成不强制导航；用户点击后才打开。目标被删除或当前用户不再有权访问时显示明确空状态，不跳到相似记录，也不在 URL/页面错误中泄漏题干。

### 2.2 面经分页

列表的 `items` 和 `total` 必须来自同一授权 scope、同一组服务端筛选条件及一致读快照。服务端执行排序/过滤后再做 `LIMIT/OFFSET`。排序键必须稳定：`created_at DESC, id DESC`（其他允许排序字段使用同一稳定 id 次序）。默认 `page=1`、`page_size=20`；`page_size` 可为 1..100，超过上限时响应采用并返回 100，低于 1 的值返回 422。

前端在筛选、岗位、招聘季、排序或 page_size 变化时回到第 1 页，并原样传递服务端 `total` 给表格；禁止基于当前 `items.length` 再做本地 slice。target lookup 接受与列表相同的筛选、排序和 `page_size` 参数，使用相同授权谓词及稳定排序返回该列表中的页码和目标行，不要求客户端拉取整表。JD 等共享 DataTable 页面保留它们现在的默认本地/服务端行为，除非调用方显式选择 server mode。

## 3. 流、状态和答案

- SSE 首条业务事件或紧随订阅的快照包含完整授权任务 snapshot 与单调 `revision`。客户端只有在新 revision 大于当前 revision 时才应用业务状态；心跳不增加 revision。
- 非终态连接 EOF、代理断开或事件流结束时，客户端重新订阅并 GET 根任务快照。列表/快照请求失败不得清空已有任务或显示空成功；状态标成连接中断并保留最后有效快照。
- 登录身份变化时，旧身份的 SSE、计时器、任务卡和结果缓存一并停止/清除；后台任务继续运行。新用户的列表不能短暂呈现前一用户的任务或私有正文。
- 根任务 `completed` 仅当所有当前要求的步骤已成功或有明确 skip reason。10 题中 8 题答案成功、2 题可恢复失败时为 `partial_failed`，8 个成功答案仍可读。恢复只调用剩余 2 题；任务卡持续可查。
- `401`/权限错误不自动重试；`429`、可重试网络失败、结构修复共享单步最多 3 次物理调用预算。所有实际发出的 HTTP 请求（包括响应丢失/timeout 后记为 `unknown` 的调用）占用同一预算。旧 SSE 消费者只能观察兼容状态，不能再启动一条工作图。日志不得包含 API key、Authorization、上传原文、私有题干或完整模型错误正文。

## 4. 上传和旧数据

- 文件 MIME/大小在持久化接受任务及读取完整 payload 之前校验。400/413/不支持类型不得创建 root、attempt、job 或占用幂等键。
- 前端校验失败或服务端拒绝时保留用户选择的文字/文件草稿，并标注具体文件级原因。用户修正输入后可复用被拒绝请求的幂等键；首次有效接受后，相同 key + 相同 hash 返回同一个 root，不同 hash 返回 409。不能因拒绝请求预先占用 key。
- JD legacy retry 必须从原 job 可证明地解析业务种类、owner、JD 实体和审批状态；不得将 JD 转成面经 question/detail/resolution/answer 工作。合法重试经 JD 自己的处理阶段后仍使用当前审核/发布门槛和白名单投影。
- 没有新 publish 元数据的历史 approved JD/公共数据按既有兼容读路径继续可见；读取旧记录不得触发重试或重复创建。新 JD 结果必须走有审核/发布记录的新路径。
