# 公私题库、上传流水线与任务中心规格复核（2026-10-07）

## 结论与范围

不能认定全部规格已实现。新上传/审核流水线具备主要能力，若干当前隔离栈路径已通过；旧兼容入口、本人题库查询、旧 worker 写入隔离及任务中心完整操作仍有缺口。本次审计没有修改产品实现，没有连接真实模型供应商，也没有部署生产。

审查产品代码基线：`dce70f24d16d89eb889726b2ab5a972621c9cf85`，分支 `codex/frontend-ui-hierarchy-cleanup`。这是刚完成私人规范题跨所有者写入修复后的代码；该修复不代表 ADR-0048 全部闭合。此前修复的文件、红绿过程和264项回归结果见[所有权修复验证](2026-10-07-private-question-write-boundary.md)。origin/gitee remote 已核对，现有未跟踪审计目录、backups、UI spec 与 AC007 JSON 均保留，不纳入本次提交。

依据：ADR-0048、2026-08-05-authz-unification、2026-09-29-upload-recovery 的 README/contracts/acceptance、2026-10-04-upload-alignment-closure 的三份规格及实施计划。10-06 记录的闭环 11/11 仅覆盖所列十一项和当时镜像，不能推导原始 29 项、全部领域要求或当前 HEAD 全部通过。

## 已确认缺口

| 优先级 | 规格/现象 | 位置 | 证据与边界 |
|---|---|---|---|
| 高 | 私人题发布必须先申请快照并审核；旧 share 精确命中公共题直接合并，写公共来源/频次并软删私人题 | `backend/app/routers/questions_pkg/share.py:107,155` | 真实 JWT + FastAPI 路由 + migrated SQLite，200 merged，公共 sources 含私人 URL/company，申请数不增。证明数据库污染，未额外证明普通用户 UI 可看到该 URL。 |
| 高 | AC-012 旧 worker 不可写；失效 generation 仍提交公共上传成果 | `backend/app/agents/submit/persist_public.py:70` / `backend/app/db/operations.py:879` | SQLite 中实际 job generation=2，assert_job_fence(gen1) 拒绝；调用真实 persist_public_node(gen1) 后 interview/detail/analysis_queue 各新增一条。实际持久化事务无 fence。未证明生产中发生过此竞争。 |
| 中 | AC-005 私人出现命中公共 canonical 后，“我的题库”应包含该题 | `backend/app/db/queries.py:174` | 真实 HTTP mine=[]，public/all 返回公共题；有效 owner 私人 resolution 已存在，list_mine_canonical_ids 能找到该题但未接入查询。 |
| 中 | 旧 pending 应出现在统一审核台题库标签 | `backend/app/routers/public_contributions.py:123,143` | 用户旧分享生成 pending；管理员真实 GET 返回 total=1、items=[]，仅计数未返回旧条目。 |
| 中 | 上传 root 历史只有第一页，无法访问第 21 条之后 | `frontend/src/components/business/UploadTaskCenter.vue:136` | 当前真实 Vue 组件浏览器探针：API total=25，20 卡，无分页/更多入口，第25条不可达。这里业务 API 为 mock，不是端到端验收。rootless 失败列表有分页，不受此结论影响。 |
| 中 | allowed_actions 的部分按钮没有行为 | `frontend/src/components/business/UploadTaskCenter.vue:290` | 浏览器确认“查看摘要”点击无请求、导航或文本变化；源码同样缺 view_progress/review_status/budget 分支。只实际点击了 summary，未把其余三项说成浏览器复现。 |
| 低 | 新任务接受、打开中心、回焦缺即时刷新 | `frontend/src/components/business/UploadTaskCenter.vue:246` / `StagingPanel.vue:238` | 源码确认提交事件未接到中心 refresh，打开未 GET、无焦点监听；15秒轮询存在，因此是即时性缺口，不是永远无任务。 |

根因：旧单题分享仍存在绕过新发布申请的独立写流程；canonical 所有权筛选未与私人 occurrence/resolution 查询合并；部分 worker 只在进度更新检查 fence，实际业务写事务没有同一约束；任务中心 action 渲染和 history 数据请求缺少完整交互。

## 需要继续验证的边界

- task center 列表响应可能覆盖更高 revision 的 SSE 快照；SSE 接受相同 revision，而契约要求业务状态严格递增。源码风险已记录，尚未用延迟列表响应动态复现。
- 私人持久化、下游入队和 import 关联分属不同事务，崩溃窗口可能产生缺关联成果及重试重复。尚未注入进程崩溃验证。
- build-personal 的历史重建路径与唯一公共 canonical 的完全收敛仍需要数据样本验证。
- 不声称已实现特殊支持访问的完整授权/审计产品流程；默认拒绝管理员访问私人内容与支持访问是不同验收项。
- AC029真实栈脚本虽然执行了分类/聚类，但未逐项断言全部公共分类和标签及resolution ID稳定性；完整规格验收还需补齐这些断言，不能把流程跑通当成全部字段正确。
- 真实供应商模型质量、实际凭据和费用、生产已有脏数据、多进程长时间故障、375/1440完整无障碍验收，均不在本轮已通过声明内。

## 规格覆盖判定

以下“服务回归覆盖”指本轮选定套件中的相关测试有执行，不能替代完整 AC Given/When/Then；套件整体不是全绿。历史通过不标为本轮通过。

| 原始 AC | 本轮判断 |
|---|---|
| 001 结果定位、002 分页 | 当前真实栈分页用例失败，在 total61 季筛选后的升序响应断言超时；后续结果定位未执行。失败 SQLite 恰有61条，不能认定数量夹具错；源码排序链完整，根因未定位。 |
| 003 四格策略、004 配置费用 | 服务回归覆盖；没有本轮全四格真实模型/费用验收。 |
| 005 私人引用归属 | 确认 mine 缺公共 canonical，不符合。 |
| 006 判断失败非新题 | 服务回归覆盖，非全部故障点当前栈证明。 |
| 007 队列续调、008 故障恢复、009 并发不串单 | 服务回归覆盖；默认栈被分页失败中断，未完成本轮这些完整浏览器场景。 |
| 010 连接恢复 | 独立当前栈复验，结果见下方运行账。 |
| 011 真实完成 | 当前栈完整部分答案失败恢复通过，SQLite/provider账本验证8个成功不重跑，仅题9/10各重试一次。 |
| 012 旧 worker 不可写 | 真实 SQLite 反例确认不符合。 |
| 013 错误预算 | 服务回归覆盖；未重跑完整 HTTP provider 错误场景。 |
| 014 审核投影 | 新流程服务测试覆盖；旧单题 share 存在明确绕过。 |
| 015 失败子项 | 答案部分失败当前栈通过；公共聚类逐题恢复见 AC029。 |
| 016 追加贡献、017 跨代并发 | 服务回归覆盖，未重跑完整追加并发栈。不能用合法并发通过反驳 AC012 失效代次写入。 |
| 018 私人正文隔离 | 本轮 security/privacy 回归覆盖；旧 share 对公共 canonical 数据污染另列高优先级。 |
| 019 不漏题 | 服务回归覆盖；mine 漏展示不等于 extraction丢题，单份逐题追踪见AC029。 |
| 020 审批撤回互斥 | public contribution transition 回归覆盖，无本轮全浏览器竞争验收。 |
| 021 幂等提交、022 文件错误、023 迁移回填 | 服务/infra回归覆盖；未执行当前完整超限浏览器与全部迁移双跑验收。 |
| 024 JD与旧数据 | 当前栈真实浏览器/API/worker/SQLite通过旧JD retry、审核投影、普通面经私人上传及读取不重放。 |
| 025 源状态变更 | 服务回归覆盖，六个失败与缺有效岗位的 fixture/恢复状态有关，不绕过现有岗位失效保护来宣称通过。 |
| 026 历史保留 | root 历史超过20条UI不可达；保留清理服务测试覆盖不抵消该缺口。 |
| 027 可访问性 | 本轮未做完整宽度/键盘/读屏验收。 |
| 028 完整隔离集成 | 新建独立Compose/SQLite/Redis/provider stub，部分真实场景通过；默认全栈命令失败，不标整体通过。 |
| 029 逐题数据流 | 独立当前栈复验主数据链场景见运行账；不据此宣称规格全部配置失效子场景均已验收。worker集成测试单独复跑2项通过，但大套件出现classify次数断言失败，存在顺序/隔离问题待定位。 |

## 实际命令与结果

工作目录 `/opt/interview-boss`。OPENAI_API_KEY 均为测试占位符，base URL置空；本地 pytest 并非生产验收。

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend .venv/bin/pytest \
 backend/tests/pipeline/test_upload_*.py \
 backend/tests/pipeline/test_public_personal_scope_contract.py \
 backend/tests/pipeline/test_interview_server_pagination.py \
 backend/tests/services/test_upload_*.py \
 backend/tests/services/test_public_contribution*.py \
 backend/tests/services/test_question_resolutions.py \
 backend/tests/security/test_upload_task_privacy.py \
 backend/tests/security/test_private_question_write_boundary.py \
 backend/tests/infra/test_upload_*.py \
 backend/tests/integration/test_upload_question_data_flow.py \
 backend/tests/integration/test_upload_question_data_flow_worker.py -q --show-capture=no
```

结果：exit1，456 passed、7 failed、1 warning，261.27秒。失败五项 restore 报 POSITION_RETIRED，另一个 matching retry 变为 resubmit_source；相关fixture未建立有效岗位，需要逐项修正测试隔离后复验，不能把它们直接当成六个产品bug。另 worker data-flow 断言 classify_calls=0；单独命令复跑该文件 **2 passed、1 warning、4.31秒，exit0**，因此无法据大套件失败断言正常分类必定坏。

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend \
 .venv/bin/pytest backend/tests/integration/test_upload_question_data_flow_worker.py -q -s
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend \
 .venv/bin/python -m pytest -q -p tests.conftest .tech-audit/work/2026-10-07/probes
node /tmp/task-center-d15-probe.mjs # 脚本已归档 .tech-audit/work/2026-10-07/task-center-component-probe.mjs
```

持久化缺陷探针 **4 passed、1 warning、6.18秒，exit0**：这里“通过”是反例成功复现，不是规格通过，不能当成绿灯验收。源文件位于 `.tech-audit/work/2026-10-07/probes/`；任务中心mock API探针 JSON 已保留到同目录上级，node exit0，pageErrors=[]。

```bash
REAL_STACK_PORT=18431 REAL_STACK_STUB_PORT=18432 REAL_STACK_CAPTURE_FAILURE_DB=1 ./scripts/real_stack_smoke.sh
REAL_STACK_PORT=18431 REAL_STACK_STUB_PORT=18432 REAL_STACK_CAPTURE_FAILURE_DB=1 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_ONLY_AC024=1 ./scripts/real_stack_smoke.sh
REAL_STACK_PORT=18435 REAL_STACK_STUB_PORT=18436 REAL_STACK_CAPTURE_FAILURE_DB=1 REAL_STACK_REUSE_BUILT_IMAGES=1 REAL_STACK_ONLY_AC010=1 ./scripts/real_stack_smoke.sh
```

- 默认命令重建当前代码全部候选镜像：AC011 1 passed、2.0分钟，逐题 DB账本passed；随后分页1 failed，整体exit1。项目 `interview-boss-real-e2e-2698443-1791354055`。
- AC024：浏览器1 passed、16.8秒，最终数据库断言通过，整体exit0。项目 `interview-boss-real-e2e-2722431-1791354538`。
- 一次AC010启动复用了正在清理的18432端口而失败，仅基础设施端口冲突；随后改18435/18436重跑，不计成产品缺陷。
- AC010：浏览器1 passed、33.9秒，最终DB断言 attempt/job 数未增，整体exit0。项目 `interview-boss-real-e2e-2729224-1791354621`。真实EOF/500/旧revision/换账号覆盖不等于所有并发快照时序覆盖。
- AC029主数据链：浏览器1 passed、11.8分钟，最终SQLite逐题trace断言通过，整体exit0。项目 `interview-boss-real-e2e-2739733-1791354770`；保留5题私人原稿、审核排除ordinal50、最终公共4题，ordinal20命中唯一已存在公共canonical，ordinal40失败后在worker重启恢复。已成功public detail ID稳定，私人明细cat1/cat2、审核脱敏/编辑投影核对通过。该栈断言没有逐项检查所有公共cat1/cat2/tags或稳定resolution ID，不能据此认定这些AC029细项全部通过。最终DB trace已归档 `.tech-audit/work/2026-10-07/ac029-db-trace.json`。

候选栈使用独立项目/临时卷、隔离Redis和本地确定性HTTP模型stub；实际鉴权、API、worker、数据库及浏览器是当前服务。首次镜像重建后，后续复用同一产品代码镜像。AC029未辅助调用dispatcher：实际观察到公共预检及worker重启后的工作等待五分钟周期调度，属于本轮主数据链的分钟级排队现象；通过不代表处理立即完成或吞吐性能验收。`test-results/real-stack/<project>/`为本机忽略的详细产物，不纳入提交；默认分页截图/trace被后续Playwright输出覆盖，仅保留错误日志及失败SQLite，故分页根因证据有限。

### 定向 AC029 runner 与组件探针重放

仓库默认 runner 在分页失败后停止，因此在 `/tmp` 提取了其初始化段和原样 AC029 段；没有修改仓库脚本、浏览器测试、鉴权或业务数据库写入逻辑。构造文件已保留：

```bash
python3 .tech-audit/work/2026-10-07/make_ac029_runner.py
bash -n /tmp/spec-review-ac029.sh
REAL_STACK_PORT=18437 REAL_STACK_STUB_PORT=18438 REAL_STACK_CAPTURE_FAILURE_DB=1 REAL_STACK_REUSE_BUILT_IMAGES=1 bash /tmp/spec-review-ac029.sh
```

组件探针要求先在独立终端执行 `cd /opt/interview-boss/frontend && node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 18441 --strictPort`，再从仓库执行 `node .tech-audit/work/2026-10-07/task-center-component-probe.mjs`。结束时只停止该自建 Vite。它将业务 API mock 为25项、挂载当前组件；不要把结果解释成真实 worker 或生产验证。

独立 reviewer 只读核对规格解读、命令输出和证据边界，无阻塞发现；探针 Python ruff check、组件脚本 node --check、git diff --check 均通过。提交仅包含本报告、findings 和审计证据，不包含产品实现。

## 后续修复顺序（建议，未执行）

1. 阶段8：关闭旧share直接合并公共题路径，以发布快照和审核流程接管；补mine引用与legacy pending统一列表行为回归。
2. 阶段9：把job fence/source版本检查放入实际写事务，补失效worker真实竞争与崩溃恢复测试；先验证私人事务间窗口再决定实现。
3. 阶段10：补root历史分页、action执行与事件即时刷新；动态验证revision合并竞争。定位并修复当前测试隔离/分页验收失败后，重新执行完整AC矩阵。

上述阶段由审计findings生成的里程碑建议归并而来，不改写既有spec的验收状态，也不代表用户已要求实施这些修复。
