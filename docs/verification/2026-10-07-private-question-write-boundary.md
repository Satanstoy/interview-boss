# 私人规范题写权限修复验证

日期：2026-10-07。依据 ADR-0048 和鉴权规格：私人规范题仅所有者可修改，管理员角色不能绕过所有权。

## 基线与提交范围

- 分支：`codex/frontend-ui-hierarchy-cleanup`，开始 HEAD：`534a78138eff927fa051721770c9ea55ed29b36d`，没有 upstream。
- Remote：origin 为 `https://github.com/satanstoy/interview-boss.git`；gitee 为 `git@gitee.com:satanstoy/interview-boss.git`。本任务只本地提交，不推送、不部署。
- 原有未跟踪路径完整保留并排除：`.tech-audit/work/2026-08-28/`、`.tech-audit/work/2026-09-23/`、`backups`、`docs/specs/2026-09-23-frontend-ui-hierarchy-cleanup.md`，以及 `docs/verification/upload-recovery/2026-10-04-real-stack/` 下原有 17 个 ac007 JSON 文件。

修改文件及职责：

| 文件 | 修改 |
| --- | --- |
| `backend/app/routers/questions_pkg/permissions.py` | 复用 `can_edit_question`；外人私人题返回与不存在一致的 404，普通用户写公共题仍为 403 |
| `backend/app/routers/questions_pkg/bulk.py` | 四条删除／恢复接口与删除聚类原题检查所有权；批量先授权全部已存在 ID，再筛选生命周期状态，写入前整批拒绝 |
| `backend/app/routers/questions_pkg/mutations.py` | 拆分、移动原题的源与目标、重新打标在写入／LLM 调用前检查所有权 |
| `backend/app/routers/admin_review.py` | 回滚检查当前相关题和历史快照所有者；检查先于“已回滚”响应；两个聚类维护接口仅处理公共题 |
| `backend/app/services/clustering_maintenance.py` | 为 HTTP 维护调用提供公共作用域，贯穿审计、元数据写入、精确合并候选和报告计数；其他调用的默认语义保留 |
| `backend/app/routers/analytics.py` | 分类规范化的规范题扫描仅包含公共题 |
| `backend/tests/security/test_private_question_write_boundary.py` | 55 项真实 HTTP / JWT / 隔离 SQLite 行为测试，无路由、鉴权或 SQL 写入 mock |
| `backend/tests/services/test_question_bank_integrity.py` | 旧测试直接调用管理员路由的身份补 `is_admin=1`，保留原数据一致性断言 |
| 本验证记录 | 记录命令、证据、范围与限制 |

根因：四条接口把管理员角色当作私人题所有权的例外；其他聚类写入口只检查管理员角色；全量维护 SQL 未限定题库作用域。另外，批量 SQL 原先先筛删除状态，会跳过不在目标状态的外人私人 ID，导致混合请求仍可修改其他记录。

## 红绿证据

所有命令从 `/opt/interview-boss` 执行。测试进程使用 `OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend`，避开本机 LLM 地址的初始化安全校验；未修改本地配置文件。

红阶段（先加测试，确认实际行为失败后改实现）：

- 首批 45 项：29 failed、16 passed。四接口管理员越权实际改变 SQLite 状态；混合批次也出现修改；普通用户外人访问响应与不存在响应不同。
- 回滚额外 2 项：2 failed（私人 survivor／merged 相关记录被写入）。
- 复审新增回滚检查：2 failed、3 passed（已回滚外人记录返回 400 而非 404）。
- 聚类维护：3 failed、1 passed（包含实际私人题修改和私人报告泄露）。
- 分类规范化：1 failed（私人题 cat1 被实际改写）。

执行各红阶段的命令为下列命令（首批执行时文件只含 45 项；后续逐次增加测试）：

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend \
  .venv/bin/pytest backend/tests/security/test_private_question_write_boundary.py -q --show-capture=no
# 后续定向运行在相同命令后分别追加：
# -k merge_rollback
# -k rollback
# -k maintenance
# -k normalization
```

绿阶段先后得到 47 passed、54 passed。最终完整命令：

```bash
OPENAI_API_KEY=TEST_KEY_PLACEHOLDER OPENAI_BASE_URL='' PYTHONPATH=backend \
  .venv/bin/pytest \
  backend/tests/security/test_private_question_write_boundary.py \
  backend/tests/bank \
  backend/tests/security/test_authz_unification.py \
  backend/tests/security/test_permission_audit.py \
  backend/tests/security/test_public_rebuild_answer_scope.py \
  backend/tests/security/test_question_bank_source_projection_scope.py \
  backend/tests/infra/test_question_bank_scope_invariants.py \
  backend/tests/infra/test_build_master_bank_rebuild_scope.py \
  backend/tests/services/test_question_variant_reconciliation.py \
  backend/tests/services/test_question_bank_integrity.py \
  backend/tests/services/test_cluster_review_lifecycle.py \
  backend/tests/services/clustering/test_clustering_maintenance.py \
  backend/tests/services/clustering/test_fix_lone_islands.py \
  -q --show-capture=no
```

实际输出：`264 passed, 2 warnings in 94.51s`，退出码 0；其中新增行为测试 55 项，相关回归 209 项。警告为 pydantic settings forward reference 和现有 `datetime.utcnow()` 弃用提示。本次没有修这些问题。

此前相关回归有 199 passed、1 failed，原因是旧数据一致性测试直接传入的管理员身份缺少 `is_admin`；仅补身份标志后，最终回归通过。

```bash
.venv/bin/ruff check \
  backend/app/routers/questions_pkg/bulk.py \
  backend/app/routers/questions_pkg/mutations.py \
  backend/app/routers/questions_pkg/permissions.py \
  backend/app/routers/admin_review.py backend/app/routers/analytics.py \
  backend/app/services/clustering_maintenance.py \
  backend/tests/security/test_private_question_write_boundary.py \
  backend/tests/services/test_question_bank_integrity.py
git diff --check
```

实际输出：`All checks passed!`；两个命令退出码均为 0。独立 reviewer 只读复审无阻塞发现。

## 验证范围与限制

- 四接口覆盖普通用户自己的私人题、管理员公共题、管理员自己的私人题、两类身份访问他人私人题、普通用户写公共题；混合批次覆盖请求顺序和私人题不在目标生命周期状态的情况。拒绝路径比较完整 SQLite dump，确认没有部分写入。
- 新测试通过现有 TestClient 和 SQLite migration 建表的内存数据库；现有 fixture 只替换 DB 连接和异步执行器，不替换授权决策或 SQL 写入。旧回归包含 mock 和静态测试，未把这些结果当作生产验收。
- 未运行生产部署、浏览器端到端、真实 LLM/Redis/worker、并发所有权变更或全库测试套件。
- 本次审查和修改针对规范题按 ID／聚类管理／维护入口。来源面经/JD 授权、全库清空／备份等独立运维流程未执行，未将其视为本次题目写接口验收。
- 未新增特殊支持访问授权功能；这些写入口默认拒绝外人私人题，无管理员支持绕过。
