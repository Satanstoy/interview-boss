# 2026-10-09 公私题库与上传 spec 再核对

基线 `3bf72bf6401ecf431eb69bb8fcd39f681bf9e435`，分支 `codex/frontend-ui-hierarchy-cleanup`；origin/Gitee未变，原有未跟踪文件保留。本轮只审查、保存反例和报告，没有修改生产实现、推送或部署。

**结论：仍不能宣称所有 spec 已对齐。** 上轮确认缺口已修复、默认真实栈通过，但本轮发现另外三个 P1 和一个 P2。旧验证报告是已执行范围的证据，不是对全部入口的完整证明。本报告以实际路由、SQLite反例及当前组件行为为依据。

规格优先级按10-04闭环README：accepted ADR-0048优先，9-29恢复契约继续有效，10-04补充细化其11个AC。8-05鉴权spec曾允许管理员个人题直接合并公共题；它与后来的ADR-0048冲突，不能作为当前豁免。

## 确认未对齐

| 优先级 / 要求 | 当前实现及实际反例 | 修复边界 |
|---|---|---|
| P1 / ADR-0048管理员默认不能看外人私人题 | `backend/app/routers/admin_review.py:102`合并历史列表、`:161`详情只检查管理员身份，无历史参与题/快照的所有权过滤。真实JWT/HTTP两入口200并返回私人题marker。私人survivor、私人merged参与项各自泄露；仅历史私人快照的反例在详情泄露，列表不返回该快照（此控制项通过）。 | 列表items/total与详情采用同一授权范围，核对当前题、合并参与项及历史快照；未知/已删除身份不能据此公开私人历史。默认拒绝必须避免泄露存在性，特殊支持权限不能从admin推导。 |
| P1 / ADR-0048个人题并公共题必须显式发布 | `backend/app/routers/questions_pkg/mutations.py:236`只分别检查source/target可写。管理员本人私人source及公共target都通过，所以跨scope合并HTTP200，公共original_questions增加PRIVATE_MERGE_MARKER，promotion_requests为0。这是绕过发布流程，不是管理员操作外人私人题的旧漏洞回归。 | 通用merge不能执行私人→公共发布；禁止跨scope变异并走显式快照/审核入口，保留合法同scope操作。 |
| P1 / AC-014真实审核投影预览、编辑与排除 | `frontend/src/components/business/AdminReview.vue:164`仅发送`approvePublicContribution(id)`；API默认payload={}。真实组件浏览器探针：编辑控件0、申请详情请求0、approveBody={}，没有实际投影审核流程。后端详情/投影API已具备不等于前端已实现。 | 面经/JD按类型展示实际最终投影，支持题目排除/修正、允许来源字段和JD字段脱敏，按revision提交，确认预览与最终公开结果一致；新旧申请操作仍分别路由。 |
| P2 / ADR-0048公共规范答案使用global配置 | `backend/app/services/question_promotions.py:151`批准新canonical时直接复制snapshot.ai_answer。用户先主动提交并获批准后，另一普通用户通过真实detail API200读到PRIVATE_USER_MODEL_ANSWER。题目已获批准，这不是未经授权公开个人练习答案，而是私人模型答案直接成为公共规范答案。 | 私人答案留在私人历史；公共规范答案按global配置生成/记账，或明确标暂缺，不把私人生成结果冒充公共生成成果。 |

### 新反例验证

后端探针位于`.tech-audit/work/2026-10-09/spec-recheck/test_remaining_boundaries.py`。使用现有FastAPI TestClient、真实JWT与迁移后的隔离SQLite；不mock路由、授权或SQL写入。既有测试设施隔离LLM/Redis，并不把这些依赖结果当生产模型验收。

最初8 failed包含重复私人快照条件；复审后把三种history形态拆成各自最小反例。最终 **7 failed / 1 passed / 1 warning，6.75s，exit1**（/tmp/spec-recheck-boundaries-retained.log）：5个历史泄露反例、1个绕过发布合并、1个答案复制反例；唯一通过的是“仅私人pre_snapshot时列表不含快照正文”。这是期望的规格断言失败，证明缺口，不能计为绿灯验收。

浏览器探针`review-ui-probe.mjs`挂载实际AdminReview.vue，业务API使用模拟响应；最终保存`review-ui-observation.json`，随后以SPEC_GAP退出1。它证明前端动作/请求内容，不能代替后端授权或部署验收。最初探针误拦截`/src/api/index.js`及等待未挂载Toaster，均已修正为路径仅`/api/`及组件空列表收敛；没有把这些脚本前置错误记为产品缺陷。最终能实际点击批准并观察请求。

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend \
 .venv/bin/pytest -p tests.conftest \
 .tech-audit/work/2026-10-09/spec-recheck/test_remaining_boundaries.py -q -s --show-capture=no
# 在frontend目录自建Vite，仅服务当前UI组件探针，结束后已停止该进程
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 18481 --strictPort
# 仓库根目录
node .tech-audit/work/2026-10-09/spec-recheck/review-ui-probe.mjs
.venv/bin/ruff check .tech-audit/work/2026-10-09/spec-recheck/test_remaining_boundaries.py
node --check .tech-audit/work/2026-10-09/spec-recheck/review-ui-probe.mjs
git diff --check
```

观察JSON均为合成测试marker、ID和请求内容，不包含真实用户正文、认证token或配置secret。完整运行日志保存在`/tmp/spec-recheck-*`，日志不加入提交。

## 原AC当前证据对账

以下区分实现反例、已有已执行子集、仍缺证据。本轮未重跑整条默认smoke；最近实际运行是上轮同基线v7，命令exit0、9个浏览器行为及对应SQL断言通过，见`2026-10-07-question-upload-spec-alignment.md`和final-smoke-manifest.json。不能按测试文件存在就把整条AC标完成。

| AC | 已有证据与本次结论 |
|---|---|
| 001 / 002 | v7真实分页与公共结果定位通过；不推导所有删除/撤权/无结果子场景已完整复验。 |
| 003 / 004 | 四格policy、严格scope配置、费用服务回归已有；未重新覆盖每格缺失/401/404/超时全组合HTTP验收。 |
| 005 | mine公共canonical私人引用、归属隔离已有真实JWT/SQLite行为证据；历史私人重建完全消除副本仍未验收。 |
| 006 | 匹配错误/作用域/结构修复服务回归已有；未把这些测试当作全部provider故障真实栈证据。 |
| 007 | v7所有者/并发恢复通过；旧闭环有公平性、rootless和丢通知证据，此次未重新跑全部相应分支。 |
| 008 | 阶段checkpoint和事务回滚测试、v7worker重启通过；仍缺全部4故障点逐一真实进程中止的当前联合证据。 |
| 009 | v7两个owner、两个worker真实HTTP重叠及所有成果隔离通过；原同owner A/B也有受理测试，不能把不同owner样例替代所有同owner交错组合。 |
| 010 | 上轮定向真实SSE EOF/失败快照/账号切换通过；revision新旧/相等合并UI行为覆盖。 |
| 011 | v7真实8成功/2失败的答案选择恢复、成功hash/ID保持及历史结果通过。 |
| 012 | 上轮实际业务写fence、心跳失败取消、私人事务回滚通过；未做长期多进程故障压力验收。 |
| 013 | 错误预算服务回归和旧闭环HTTP错误账本证据；当前未重跑完整401/403/429/格式/超时组合。 |
| 014 | **未对齐：当前审核UI仍盲批，见P1。** 后端投影API及v7API脱敏成功不抵消UI缺口。 |
| 015 | v7公共单题失败选择恢复，三成功resolution身份稳定，失败项恢复通过。 |
| 016 / 017 | 上轮服务回归及旧闭环追加/在途并发证据；此次未重新跑完整两种专用真实栈场景。 |
| 018 | root/旧job正文隔离回归已有；ADR更广的私人题读取仍被合并历史入口违反。 |
| 019 | 提取schema/count守恒回归、v7私人5题/公共排除后4题通过。 |
| 020 | approve/withdraw双连接服务竞争与事务回归已有；未新增完整UI竞争验收。 |
| 021 / 022 | v7丢POST响应恢复、文件拒绝/草稿/幂等键通过；本轮未修改该实现。 |
| 023 | 迁移/backfill回归和外部迁移身份修复已有；未对生产数据执行dry-run/apply，不能推导实际旧数据已迁移。 |
| 024 | 上轮独立真实JD retry/投影/普通私人上传通过；JD投影编辑的UI仍属AC014缺口。 |
| 025 | 实际写事务输入版本、源删除/岗位失效fence回归已有；未对所有运行中状态变化逐项做完整浏览器故障验收。 |
| 026 | 任务历史分页已补并通过UI测试；保留清理回归已有，不等于生产历史payload完整性验证。 |
| 027 | 375/1440和键盘UI行为已有；真实设备读屏、完整焦点验收仍缺。 |
| 028 | v7隔离API/SQLite/Redis/worker/provider stub/浏览器默认场景通过；不代表真实模型或生产。 |
| 029 | v7逐题身份/分类标签/聚类/公共失败恢复通过；**审核编辑和排除使用API，不证明管理员能在UI完成此流程**。全scope配置失效子场景仍缺联合验收。 |

## 保留上轮修复结论

本轮另外复跑原私人写边界55项与题库spec行为43项，合计 **98 passed / 1 warning，62.93s，exit0**（/tmp/spec-recheck-existing-boundaries.log）。这些通过不反驳新入口的反例，因为旧测试没有覆盖历史读取、跨scope合并、答案来源及真实审核编辑流程。

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend \
 .venv/bin/pytest backend/tests/security/test_private_question_write_boundary.py \
 backend/tests/security/test_question_bank_spec_alignment.py -q --show-capture=no
```

上传→提取→分类→聚类→结果读取的已测试主链仍有上轮实际通过证据；任务中心分页、动作详情、刷新和revision隔离也有证据。不能把“这条主链通过”扩大为“所有入口、审核UI和所有spec完全对齐”。本次建议优先修复三个P1，再处理规范答案配置边界及逐项补齐AC证据；未修改生产代码。
