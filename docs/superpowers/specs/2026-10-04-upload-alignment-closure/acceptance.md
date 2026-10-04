# 剩余 11 项的验收矩阵

属于[闭环规格](README.md)。每个 `CL-REQ` 对应原 AC 的尚未闭环范围。以下均为验收要求，不代表目前已运行或已通过。

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

**Given** 至少 3 个独立 root：U1 私人 pending 7 项、公共 pending 11 项、另一个持续有新公共工作进入的 root；batch size=5。另准备一个 U1 自己的 rootless/兼容任务，执行后进入 `failed`，保留一个已成功检查点和一个失败步骤；再准备 U2 私人任务及公共审核申请。

**When** 两个以上 worker 和 reconciler 在隔离 Redis/真实 SQLite 上处理多个批次，期间阻断一次 COMMIT 后的 ARQ 通知；随后 U1 从浏览器重试自己的可恢复失败任务，并让两个浏览器上下文并发点击同一任务；U2 和 A 尝试使用 U1 的私有任务标识。

**Then** 每个合法 pending 桶在有界轮次内取得 job，连续公共流量不能饿死 U1 私人桶；reconciler 恰好补齐一次缺失 dispatch。所有者重试以同一稳定任务/业务身份创建最多一个新 active attempt，只排失败/缺失步骤；成功 checkpoint 和其数据库 ID/hash 不变。并发请求都观察同一个 active attempt，失败方返回 `created_attempt=false`。跨用户和管理员跨 owner 请求为 404，数据库无新增 attempt/job；actor 记当前用户。没有唯一安全根映射、配置未修复、不可重试状态或预算耗尽时返回契约中的明确阻塞，不制造新 root。

公共贡献已经批准后的失败 item 仍只能由管理员专用 retry 入口恢复；owner retry 不改 review 状态、不发未批准公共工作。实际容器重启 Redis 通知路径，确认恢复后的私有结果可打开、公共结果只有满足审核/发布门槛后才公开。

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
