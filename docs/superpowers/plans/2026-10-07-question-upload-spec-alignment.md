# 公私题库与上传规格对齐实施计划

状态：实施中。用户于2026-10-07明确要求开始修改，对齐既有accepted ADR-0048、上传恢复contracts/acceptance与10-04闭环spec。基线d90794d5，分支codex/frontend-ui-hierarchy-cleanup；保留全部原有未跟踪文件，只本地提交，不部署、不推送。

依据审计：docs/verification/2026-10-07-upload-spec-review.md。目标为关闭已确认缺口、用行为测试裁定未确认边界、补真实栈验证断言。设计沿用既有作用域、审核和durable job流程。比较禁用旧share、把规范题伪装成面经申请、保留显式旧单题申请三种办法：选择第三种，保留兼容API，不制造不存在的面经事实。旧单题提交建立不可变快照和精确源ID；审核后形成默认隐藏来源的投影，批准只重定向实际提交的私人规范题，不按裸文本猜测其他私人副本。

每个任务先添加行为测试、执行确认红，再改最小实现并复跑；每个已验证领域形成独立checkpoint。测试中禁止mock路由、权限和SQL写入；UI交互mock API与真实栈证据分开记录。

## 单元1：题库发布与私人引用（已验证：175后端回归、1审核组件行为）

1. 创建backend/tests/security/test_question_bank_spec_alignment.py：真实JWT、FastAPI client、迁移SQLite，覆盖公共精确命中仍需pending、无提前写入、重复提交幂等、快照稳定、外人及管理员拒绝、统一审核列表、mine引用/删除/失效/所有者/岗位隔离。运行 `OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend .venv/bin/pytest backend/tests/security/test_question_bank_spec_alignment.py -q --show-capture=no`，确认期望行为断言失败。
2. 创建backend/app/db/migrations/question_promotions.py并注册126：创建question_promotion_requests，pending_question_id主键、source_question_id可空、requester_id、snapshot_json、review_projection_json、target_question_id、status、reviewer_id、审核时间；只加表，不猜测回填旧源ID。为source_question_id的pending状态加唯一索引。迁移双跑不增记录。
3. 修改backend/app/routers/questions_pkg/share.py：所有者检查统一404；BEGIN IMMEDIATE；重复pending返回同pending_id；创建pending规范题及同事务promotion快照，提交前不写approved公共题或删除源。
4. 修改backend/app/routers/admin_review.py：明确pending→approved/rejected，只处理提交快照；默认清空私人来源投影，使用精确source_question_id并核对owner和快照版本后退休源，历史无精确源关联的pending不猜测私人清理；同事务记录审核与目标canonical，重复批准不追加写入。
5. 修改backend/app/db/queries.py：mine通过EXISTS纳入有效private resolution指向的approved公共canonical，验证明细/面经未删除且owner一致；无外人来源、无重复canonical、岗位过滤仍生效。
6. 修改backend/app/routers/public_contributions.py统一返回规范化legacy条目及正确total；修改frontend/src/components/business/AdminReview.vue使用统一列表、按类型+ID路由操作避免ID碰撞。行为测试验证混合新旧申请与题库/JD过滤。
7. 更新旧backend/tests/bank/test_bank_share_flow.py中立即发布和文本猜测清理的错误期望，补真实批准回归。运行新增security、bank share、public contributions、question resolutions、private write boundary全部相关测试，ruff、git diff --check，独立review后本地提交。

## 单元2：实际业务事务的worker边界（已提交4b20c83c，40+22回归通过）

8. 添加真实SQLite持久化节点回归：generation失效、lease过期、job结束、root取消/源状态变化时零成果；合法代次完整提交；公共和私人事务故障回滚所有实体/关联/队列。
9. 修改backend/app/db/operations.py、backend/app/agents/submit/persist_public.py：job_id/generation传入实际写事务，BEGIN IMMEDIATE内验证fence和root输入有效性；rooted job不能缺执行身份。并调查私人persist_personal.py事务缝隙，以崩溃/rollback测试决定原子修复。
10. 检查backend/app/worker.py执行租约续期，添加独立续租与失效取消行为测试，只修确认缺口。运行job fence、upload recovery、data-flow worker集成回归，修复有效岗位fixture/跨测试污染根因，不削弱岗位失效保护。本地提交验证单元。

## 单元3：任务中心可达性与快照一致性（已提交ca454d2f，44浏览器回归通过）

11. frontend/tests/e2e/upload-task-center.spec.js添加当前组件行为回归：25条历史访问第2页、summary/progress/review/budget动作内容、接受任务/打开/回焦即时刷新、延迟列表与同revision不能覆盖较新SSE、账号切换拒绝旧响应、错误保留旧快照。使用现有Playwright启动方式，逐项确认红。
12. 修改frontend/src/components/business/UploadTaskCenter.vue及提交事件对应模块：增加可达历史分页、实现allowed_actions展示、接入即时刷新、统一严格递增revision合并和账号隔离；375/1440键盘按钮和焦点核对。只改任务中心相关流。
13. 定位真实面经分页失败，通过实际请求/按钮事件证明根因后修复或修正测试等待，不用增加固定sleep掩盖断路。运行相关浏览器、frontend build和lint。本地提交验证单元。

## 单元4：完整证据复验

14. 补backend/e2e/assert_ac029_public_trace.py公共分类/标签与成功resolution ID不变断言；在候选栈重建当前镜像，完整运行scripts/real_stack_smoke.sh及AC010/024/029相关场景；模型用本地HTTP stub，独立Compose/SQLite/Redis，不连接生产。读取实际退出码、数据库trace、浏览器输出。
15. 更新docs/verification/2026-10-07-question-upload-spec-alignment.md逐项记录红绿、命令、已关闭/仍未验证边界；保留历史审计结论，不把未执行AC标成通过。独立code-review、verification检查后提交报告。

单元1复审扩展：通用题库变异与公共维护须排除申请投影；source/target外键SET NULL，pending ID作为独立不可变档案标识，无FK。新增43项spec行为回归。具体命令与红绿证据见 docs/verification/2026-10-07-question-upload-spec-alignment.md。

2026-10-08复验：463项广回归全绿；旧恢复fixture已提交5d0a6640。AC001/002、AC010、AC024、增强分类/标签及resolution身份的AC029独立当前栈通过。完整smoke继续执行，不提前标全AC完成。已发现并纠正共享栈AC007全局attempt计数与分页初始导航测试前置条件，保留行为断言。
