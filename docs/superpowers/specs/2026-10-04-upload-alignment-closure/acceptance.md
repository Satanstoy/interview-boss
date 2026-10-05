# 剩余 11 项的验收矩阵

属于[闭环规格](README.md)。每个 `CL-REQ` 对应原 AC 的尚未闭环范围。下表记录当前验证状态；详细证据见[2026-10-04 候选栈验证账](../../../verification/upload-recovery/2026-10-04-closure-real-stack.md)。

截至 2026-10-05，本地隔离候选栈还验证了 AC-011 的 8/2 答案部分失败、仅恢复失败题、稳定答案/resolution 身份、可恢复错误分类和最终结果历史定位。按本矩阵的完整 Given/When/Then 逐项审查后，只有已覆盖全部要求的条目才记为通过；相关路径的回归或局部真实栈场景记为部分。

| 闭环 AC | 当前状态 | 未闭环证据 |
|---|---|---|
| CL-AC-001 | 部分 | 真实栈定位了预置的已发布公共任务结果；尚未在同一浏览器流程验证 share→review→publish 后从该任务卡点击定位。 |
| CL-AC-002 | 部分 | 真实 SQLite 分页、排序、隔离和目标 lookup 已过；JD 共享 DataTable 的未启用 server mode 回归尚未验证。 |
| CL-AC-007 | 通过 | 最终候选镜像的真实浏览器/API/worker/SQLite 验收覆盖 upload root 和 rootless 私人失败行：并发请求收敛到同一 attempt/queue_id，成功 checkpoint 保留，U2/管理员越权为 404，公共贡献失败项不进入个人列表且个人 retry 为 404，rootless 行保持 root-null 并进入 owner 私人题库；分页与固定请求量刷新、双 worker 公平性、COMMIT 后 Redis 通知丢失恢复及状态提交后缺 job 的 rootless 周期对账恢复均通过。命令、最终镜像 digest 和 trace 见[AC-007 最终复核](../../../verification/upload-recovery/2026-10-04-closure-real-stack.md#cl-ac-007-final)。 |
| CL-AC-009 | 通过 | 隔离候选栈中双浏览器在同一秒提交；两条 submit job 的 durable start time 相同、两个独立 worker 各领取一个 root；真实答案、canonical/source、resolution、detail、任务结果页均按 owner 对应，跨用户 snapshot 为 404。见[AC-009 候选栈证据](../../../verification/upload-recovery/2026-10-04-real-stack/ac009-db-trace.json)。 |
| CL-AC-010 | 通过 | 隔离候选栈真实 API/SSE 和浏览器验收通过：EOF 重连、列表/详情 500、revision 8→7、心跳、登出后延迟 401、切换账号、恢复失败保留草稿；DB 确认无第二 attempt/job。证据见[AC-010 验收账](../../../verification/upload-recovery/2026-10-04-closure-real-stack.md#cl-ac-010-独立候选栈验收)。 |
| CL-AC-011 | 通过 | 独立候选栈真实浏览器/API/SSE/worker/SQLite/provider 调用账本验证了首轮 8/2、仅重试题 9/10、8 个成功答案 hash 与 10 个 resolution ID/规范映射稳定，完成后 6 秒仍可从历史打开结果。证据见[AC-011 独立验收](../../../verification/upload-recovery/2026-10-04-closure-real-stack.md#cl-ac-011-独立候选栈验收)。 |
| CL-AC-013 | 部分 | 调用预算与 stream contract 单测通过；本地 HTTP provider 的 401/429/超时真实请求计数和旧入口联测尚未运行。 |
| CL-AC-016 | 部分 | 公共审核、失败子项恢复的候选栈回归通过；相同 URL 两份 contribution 加同 URL 私人面经的完整累计投影验收尚未运行。 |
| CL-AC-017 | 部分 | 同一 active attempt 的并发恢复已过；A/B/C 三代旧 attempt 收敛和多 work_key 并行真实验收尚未运行。 |
| CL-AC-022 | 部分 | 真实 MIME/空文件/超限拒绝、草稿保留、重提和幂等已过；后端读取字节数/临时文件在超限前的断言尚未验证。 |
| CL-AC-024 | 未运行 | 尚无真实 JD 兼容 retry→审核发布和历史 approved 数据不重放验收。 |

## 1. 共享验收环境

固定主体 U1 普通用户 `101`、U2 普通用户 `102`、管理员 A `201`；岗位 P1/P2。每个场景使用新的临时 SQLite 数据库、随机 Redis namespace、真实 API/ARQ dispatcher/worker/UI 和候选容器镜像。浏览器通过真实 HTTP API；服务端 fixture 只负责可重复地种数据、控制故障和 stub 响应，不可把业务 service、授权或 DB 写入 mock 成成功。

本地模型 stub 是真实 HTTP provider 边界，按场景返回确定结果/故障。验收必须保存 `scenario → AC → browser trace → API/worker log correlation id → SQLite row trace` 映射。production DB 不接入这些 fixture、不写测试行。所有 scenario 独立运行，失败时保留该隔离项目的日志、trace、截图及必要的 DB 副本供复核。

## 2. 条目验收

<a id="cl-ac-001"></a>
### CL-AC-001（原 AC-001）：从任务卡定位已发布公共结果

**Given** U1 提交 share 任务，U1 处于面经 P1 第 2 页且有季节筛选；任务结果属于 P2。审核和公共处理完成后，公共结果有稳定面经 ID，U1 与 U2 均有权读取该发布结果。

**When** U1 不离开当前列表等待任务完成，然后点击该任务卡“查看结果”。

**Then** 页面根据任务返回的稳定结果 ID 调用真实列表/target lookup API，清除冲突的 P1/季节筛选，定位到 P2 的授权页，显示 P2 提示并高亮准确 row ID。后台完成本身不改变当前导航。测试断言最终路由、服务端请求、页码、岗位、目标 ID 和响应权限；不能只断言按钮存在或截图相似。

对未发布、审核拒绝、无结果、结果已删除和无权结果分别断言：卡片显示对应等待/拒绝/无结果状态；点击不会打开公共原文、不跳到同 URL 的别的实体、不泄漏私有字段；删除或权限撤销显示明确“结果不可用”。

<a id="cl-ac-002"></a>
### CL-AC-002（原 AC-002）：UI 使用真实服务端分页

**Given** P1 有 121 条当前用户授权记录，其中 created_at 相同的记录至少 3 条；库中另有 U2 私人记录和 P2 记录。日期、招聘季、岗位和权限元数据都由隔离数据库实际保存。

**When** 浏览器请求 P1 最近 20 条，翻到第 2 页，再切招聘季、排序和岗位；同时从 CL-001 使用 target lookup 定位一条不在当前页的记录。

**Then** 浏览器网络 trace 证明请求携带 page/page_size/filters/sort；每页最多请求数（本场景 20）条；第一页顺序按 created_at DESC、id DESC 稳定；全量 `total=121` 并与相同授权筛选一致。U2/P2 数据不出现在 items、total 推断或错误响应中。切换筛选/岗位/排序/page_size 回第 1 页。target lookup 使用相同 page_size 与列表参数，返回的页码能在真实列表中打开并准确高亮目标。

此场景须经过实际前端、API、SQL 和 SQLite；单独的 121 条后端分页测试或 mock DataTable 测试不能关闭此 AC。JD 共享表再做一次回归，证明未显式开启 server mode 的页面未变。

<a id="cl-ac-007"></a>
### CL-AC-007（原 AC-007）：公平续调与所有者恢复

**Given** 建立公平性 fixture：U1 私人 pending 7 项、公共 pending 11 项、另一个持续有新公共工作进入的 root，batch size=5。另建立两种相互独立的失败身份：一个 U1 的 upload root，含一个成功检查点和一个失败步骤；一个 U1 的 rootless 私人 `analysis_queue` 项，`root_import_id IS NULL` 且队列行处于 `failed`。再准备 U2 私人任务及公共贡献失败项。

**When** 两个以上 worker 和 reconciler 在隔离 Redis/真实 SQLite 上处理多个批次，期间阻断一次 COMMIT 后的 ARQ 通知。随后 U1 从浏览器分别重试 upload root 和 rootless 私人失败项；两个 U1 浏览器上下文并发重试同一个 rootless `queue_id`，U2 和 A 使用 U1 私有标识尝试两个 owner retry 入口。

**Then** 每个合法 pending 桶在有界轮次内取得 job，连续公共流量不能饿死 U1 私人桶；reconciler 恰好补齐一次缺失 dispatch。另将一条 rootless 失败行提交为 `pending` 后阻断 inline scheduler，确认周期对账发现该行并创建/派发一个 durable job，最终由 worker 处理完成。upload root 重试以原 root 创建至多一个 active attempt，只排失败/缺失步骤，成功 checkpoint 及其数据库 ID/hash 不变。rootless retry 以原 `queue_id` 原子执行 `failed→pending`，并发响应都指向同一行，至多一个 `created=true`；处理后该行仍 `root_import_id IS NULL`、属于 U1 私人面经并到达 `done`，原问题可在 U1 私人题库看到；数据库没有为它新建 upload root、upload attempt 或重复 queue row。任务中心对已加载个人失败页的刷新以最多 5000 项的 `loaded_count` 分页，按稳定游标续取当前失败项；4 页场景只需一个范围请求，超过一批时请求数按 5000 行批次增长而非按 UI 页增长。已完成项移出后后续行补位、下一页游标与返回范围一致；新范围刷新完成后迟到的分页/刷新响应不能恢复已消失项。U2 和管理员跨 owner 请求均为 404，且没有写入。两个入口的 actor 都是当前认证用户。

公共/公共贡献失败项不出现在个人 rootless 列表，也不能经个人 retry 入口恢复；公共贡献仍只能由管理员专用入口处理。owner retry 不改 review 状态、不发未批准公共工作。实际容器重启 Redis 通知路径，确认 upload root 恢复后的私人结果可打开、公共结果只有满足审核/发布门槛后才公开。rootless 项没有 upload attempt/checkpoint/current upload resolution；验收核对原 queue_id、owner、root-null 和最终私人题库投影，不能套用 upload root 的 attempt/hash 断言。

<a id="cl-ac-009"></a>
### CL-AC-009（原 AC-009）：并发上传不串单

**Given** U1 和 U2 分别在两个浏览器会话中近同时提交内容明显不同的 A/B 两份面经，固定服务端时间使旧的同秒碰撞边界成立；两个真实 worker 同时领取工作。模型 stub 为每个输入返回不同公司、题干、ordinal 和答案。

**When** 上传、提取、分类、面经持久化、题目 resolution 和答案工作交错执行，并在完成后分别打开两张任务卡。

**Then** 每个任务的 import/root、attempt、interview、所有 detail、resolution、canonical/source、答案和 trace 只关联对应用户及输入；没有 thread/job ID 冲突、A/B 内容串接或私有 marker 泄漏。数据库关联通过外键/owner/scope 查询断言，API 由各自会话读取；不能只断言 ID 不同。

<a id="cl-ac-010"></a>
### CL-AC-010（原 AC-010）：真实 SSE EOF、失败快照和换账号收敛

**Given** U1 有一个仍在运行的任务；stub/worker 可暂停以控制 revision 和状态。两个浏览器会话可独立登录 U1/U2。

**When** 对任务流依次施加：running 快照后正常 EOF；任务列表/快照 GET 返回 500；先收到 revision 8 再收到 revision 7；只发送心跳；U1 登出并登录 U2。

**Then** EOF 后客户端重连并 GET 快照；GET 500 时任务卡和最后有效状态仍在，显示连接中断而非空任务/成功；revision 7 不覆盖 8，心跳不改变进度/revision。账号切换立即关闭旧 SSE、清理计时器、任务和私有结果缓存；U2 从首帧起只见自己的任务。恢复接口失败不清草稿或旧 root，不触发第二条工作图。

此验收使用浏览器对真实 API/SSE，故障代理仅能截断/延迟/返回错误，不得 mock 成功 task API。捕获实际事件序列、revision、网络请求和页面状态。

<a id="cl-ac-011"></a>
### CL-AC-011（原 AC-011）：答案部分失败仍可恢复

**Given** U1 的任务已有面经和 10 个规范题；每题身份稳定。模型 stub 令 8 个答案成功、2 个以可重试技术错误失败，并允许之后对失败两题成功。

**When** worker 真实执行答案 job，中途打开任务中心和结果页，再由 U1 恢复。

**Then** 首轮最终根状态为 `partial_failed`，不是 completed；8 个答案可读，失败数精确为 2，错误类别及可恢复动作明确。恢复只对原失败两题发出物理模型调用；成功 8 题的答案、题目和 resolution ID/hash 不变。恢复后全部要求步骤成功才变为 completed。页面在完成超过 5 秒后仍可从任务历史打开结果。

数据库、API snapshot、SSE、worker 调用账本和浏览器显示数量须一致。已有可用答案的题须有明确 skip reason，不能重复生成并计为本次成功。

<a id="cl-ac-013"></a>
### CL-AC-013（原 AC-013）：真实 HTTP 错误与共享重试预算

**Given** 本地 HTTP 模型 stub 能按 request key 返回成功、401、429、超时和格式错误。一个 upload root 同时可从新任务中心 API、旧 `/api/submit-jobs/{job_id}/retry` 兼容入口和旧 SSE 消费端观察。

**When** 分别触发：401；连续 429；模型输出结构修复失败；网络超时；旧 SSE 同时订阅新 root。

**Then** 401/权限错误只发 1 次物理请求并转 `needs_action`；429 与结构修复合计每 step 不超过 3 次物理请求（含所有 helper/adapter 内部请求）；unknown 超时计入账本，后续业务写入仍幂等。旧 retry 只恢复同一 root/attempt 服务，旧 SSE 只读兼容 snapshot，不重复 enqueue。所有 API snapshot 的错误 code/retryability/allowed action 与 UI 一致。应用日志可按关联 ID 检索，但 stub key、Authorization、原文、私有题干和完整敏感响应均不出现。

通过 stub 服务 access log、`upload_llm_calls` 行、jobs/attempt 及 SSE trace 交叉核对调用总数，不以 mock 计数器替代真实 HTTP 请求。

<a id="cl-ac-016"></a>
### CL-AC-016（原 AC-016）：追加贡献累计投影

**Given** U1 已有一份 URL 为 X 的公共面经，题 A 已发布；同一来源的第二份 contribution 新增题 B；U1 还存在一个同 URL 私人面经。两次 contribution 使用不同稳定 request/item ID。

**When** 第二份 contribution 走真实 share→review→公共 worker 流程；在 B 的 resolution 前注入失败，重启 worker 后由有权管理员恢复失败 ordinal。

**Then** B 失败期间公共清单只含已发布的 A；恢复后投影含 A、B 各一次且顺序稳定，来源/统计与已发布 items 一致。重试不覆盖 A、不重复 detail/canonical/source、不将失败 B 提前公布，也不删除或改写 U1 的同 URL 私人记录。实际公开列表、题目/来源查询及 SQLite 投影一致；题目数据库关系逐项 trace 到两份 contribution。

<a id="cl-ac-017"></a>
### CL-AC-017（原 AC-017）：跨代恢复与并发 retry

**Given** 同一 root 依次产生 A failed、B failed、C active 三代 attempt；每代含稳定 failed/succeeded work key。另有两个不同答案 work key 可并行。两个浏览器和两个 worker 可同时操作同一 root。

**When** 客户端分别从旧 A、旧 B 发恢复请求，并在 C 活跃时由两客户端并发 retry 根任务；之后检查各 worker claim/complete。

**Then** 所有旧 ID 均解析到 C，不创建 D；两个并发响应都引用同一 C，至多一个报告新 attempt。每个 work key 至多一个 active job；不同合法答案 work key 可并行且不覆盖对方结果。`created_attempt=false` 对应清楚的“任务已在运行/继续现有尝试”UI 文案。attempt 历史完整，成功检查点不回滚。

<a id="cl-ac-022"></a>
### CL-AC-022（原 AC-022）：真实文件错误保留草稿

**Given** 浏览器已输入文字并选择文件；测试文件包括不支持 MIME、无内容文件、超过配置字节上限的大文件，以及修正后的有效文件。代理/API 和后端都是真实候选版本。

**When** 逐一提交错误文件，再修正 MIME/文件并使用被拒绝提交的同一幂等键重提；对服务端已接受的有效请求再以同 key/hash 重发。

**Then** 错误分别以明确 400/413 返回；拒绝发生在接受/持久化 root/完整缓冲大文件之前，不产生 root、attempt、job、预检调用或已占用幂等键。浏览器仍保留文字与未损坏文件选择并指出具体错误。纠正后同 key 的首次有效请求只建一个 root；之后同 hash 重发返回同 root，不同 hash 返回 409。断言实际读取字节计数/临时文件、数据库行、队列内容和浏览器草稿，不能只测校验函数。

<a id="cl-ac-024"></a>
### CL-AC-024（原 AC-024）：JD retry 与旧数据兼容

**Given** 临时库含一条需兼容 retry 的旧 JD job、一条没有新 publish 元数据的旧 approved JD、一条旧 approved 公共面经，以及一条普通面经上传任务。每条有独特 marker。

**When** 经真实兼容 retry API `/api/submit-jobs/{job_id}/retry` 重试 JD job，完成其领域处理，管理员检查并批准相应 JD 投影；同时刷新旧 JD/面经列表，并观察公共 worker 队列。

**Then** JD retry 解析到原 JD 实体/owner，任务结果仍是 JD；JD marker 不出现在 interview detail、question resolution、题目聚类和答案 job 中。审核投影只包含允许公开的结构化 JD 字段，敏感原文/联系人不泄漏。旧 approved JD 和面经继续按历史兼容谓词可读；列表读取不自动 replay/retry、不新增 job 或重复投影。普通面经行为保持原路径。需有 U2 越权读取和非 owner retry 的负向断言。

## 3. 闭环记录格式

每个场景运行后，验证记录必须逐项填写：`CL-REQ`、原 AC、spec version、代码 commit、backend/worker/frontend image digest、隔离 project/DB/Redis 标识、精确命令、exit code、passed/failed/skipped、浏览器 trace 和 SQLite trace 路径、结论及尚未验证边界。未运行、环境阻断、真实 provider 未测分别明确记录，不能用“测试绿”概括。
