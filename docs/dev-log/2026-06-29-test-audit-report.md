# 测试审计报告 — 2026-06-29

## 概况（修复后）

| 指标 | 修复前 | 修复后 | 变化 |
|------|--------|--------|------|
| 总测试数 | 1386 | 1382 | -4 |
| 通过 | 1130 (81.5%) | 1216 (88.0%) | **+86** |
| 失败 | 210 (15.2%) | 154 (11.1%) | **-56** |
| 错误 | 31 (2.2%) | 0 (0%) | **-31** |
| 跳过 | 12 | 10 | -2 |
| xfailed | 5 | 2 | -3 |
| 通过率 | 81.5% | **88.0%** | **+6.5%** |

## 按目录通过率

| 目录 | 失败 | 通过 | 跳过 | 错误 | 通过率 |
|------|------|------|------|------|--------|
| bank | 25 | 46 | 35 | 0 | 65% |
| chat | 28 | 393 | 6 | 0 | 93% |
| coding | 0 | 0 | 0 | 0 | — |
| infra | 18 | 79 | 0 | 0 | 81% |
| interview | 13 | 14 | 0 | 0 | 52% |
| pipeline | 2 | 63 | 0 | 31 | 66% |
| security | 42 | 25 | 0 | 0 | 37% |
| services | 17 | 182 | 0 | 0 | 91% |
| services/clustering | 0 | 0 | 0 | 0 | — |
| taxonomy | 4 | 22 | 0 | 0 | 85% |

## 错误分类

### A. 容器内路径指向宿主机（60 个错误）

**现象**: `PermissionError: [Errno 13] Permission denied: '/root/sj/interview-boss/backend/app/routers/questions.py'`

**根因**: 测试脚本用 `open('/root/sj/interview-boss/...')` 读取源码做静态分析。Docker 容器内路径是 `/app/...`，不是 `/root/sj/...`。

**影响文件**:
- `bank/test_soft_delete_and_ux.py` (19 个)
- `bank/test_rebuild_position_filter.py` (6 个)
- `bank/test_oqs_backfill.py` (6 个)
- `bank/test_bank_mode_sql.py` (6 个)
- `bank/test_cross_category_merge.py` (5 个)
- `bank/test_per_user_answers.py` (2 个)
- `services/test_source_display.py` (7 个)
- `services/test_settings_position_switch.py` (5 个)
- `services/test_position_management.py` (2 个)
- `services/test_generate_answer_fix.py` (2 个)

**性质**: 🔧 **测试脚本问题**

**修复方案**: 将硬编码的 `/root/sj/interview-boss/...` 路径改为动态查找：
```python
# 之前
with open('/root/sj/interview-boss/backend/app/routers/questions.py', 'r') as f:

# 之后
BACKEND_ROOT = Path(__file__).resolve().parents[2]  # 或用 _find_backend_root()
with open(BACKEND_ROOT / 'app/routers/questions.py', 'r') as f:
```

**批次**: 第 1 批（最大收益，60 个错误）

---

### B. 前端文件在容器内不存在（29 个错误）

**现象**: `FileNotFoundError: [Errno 2] No such file or directory: 'frontend/src/components/QuestionCard.vue'`

**根因**: 测试读取前端 Vue/JS 源码做验证，但 Docker test-runtime 只复制了 `backend/`，没有 `frontend/`。

**影响文件**:
- `services/test_source_display.py` — 读 `QuestionCard.vue`
- `services/test_frontend_ux.py` — 读 `validate.js`
- `services/test_integration_bugs.py` — 读 `App.vue`、`index.js`
- `security/test_email_required.py` — 读 `validate.js`
- `security/test_security_audit.py` — 读 `App.vue`
- `security/test_privilege_escalation.py` — 读 `SettingsPanel.vue`

**性质**: 🔧 **测试脚本问题**

**修复方案**: 两种选择：
1. **复制 frontend/ 到 test-runtime**（简单但增大镜像）
2. **将前端源码验证改为 API 响应验证**（更健壮，推荐）

**批次**: 第 2 批

---

### C. pipeline mock 路径错误（34 个错误）

**现象**: `AttributeError: <module 'app.services.pipeline'> does not have the attribute 'get_db_connection'`

**根因**: `conftest.py` 的 `client` fixture 遍历 `sys.modules` 中所有 `app.routers.*` 模块来 patch `run_db` 和 `get_db_connection`。但 `app.services.pipeline` 不是 router 模块，它有自己的 DB 访问方式，conftest 没有覆盖到。

**影响文件**:
- `pipeline/test_langgraph_workflows.py` (19 个)
- `pipeline/test_pipeline_e2e.py` (13 个)
- `pipeline/test_two_phase_pipeline.py` (1 个)
- `pipeline/test_reprocess_cleanup_order.py` (1 个)

**性质**: 🔧 **测试脚本问题**（conftest.py 的 patch 策略不覆盖 service 模块）

**修复方案**: 扩展 conftest.py 的 patch 范围，或在 pipeline 测试中单独 mock `get_db_connection`。

**批次**: 第 1 批（34 个错误，和 A 类一起修收益最大）

---

### D. 导入路径错误（18 个错误）

**现象**: `ImportError: cannot import name 'merge_question' from 'app.routers.questions'`

**根因**: 测试导入的函数已被重命名、移动或删除。

| 导入的函数 | 来源模块 | 状态 |
|-----------|---------|------|
| `merge_question` | `app.routers.questions` | 已不存在（6 个测试） |
| `save_personal_taxonomy` | `app.routers.profile` | 已重命名（2 个测试） |
| `confirm_taxonomy` | `app.routers.profile` | 已重命名（2 个测试） |
| `switch_position` | `app.routers.profile` | 已重命名（1 个测试） |
| `delete_position` | `app.routers.profile` | 已重命名（1 个测试） |
| `split_question` | `app.routers.questions` | 已重命名（1 个测试） |
| `retag_master_question` | `app.routers.questions` | 已重命名（1 个测试） |
| `_migration_032_merge_history` | `app.db.migrations` | 已不存在（2 个测试） |
| `_insert_details` | `app.db.operations` | 已不存在（2 个测试） |

**性质**: ⚠️ **混合** — 部分是函数重构后测试未更新（测试问题），部分可能是生产代码重构后接口变了（需要验证）

**修复方案**: 逐个查找函数的新位置或确认已删除，更新测试导入。

**批次**: 第 2 批

---

### E. 未 mock 的 API 调用（11 个错误）

**现象**: `openai.AuthenticationError: Error code: 401 - Invalid API Key` / `anthropic.AuthenticationError`

**根因**: 测试调用了真实的 LLM API 但没有 mock，容器内没有有效的 API Key。

**性质**: 🔧 **测试脚本问题**

**修复方案**: 确保这些测试 mock 了 `openai.AsyncOpenai` 和 `anthropic.Anthropic`。

**批次**: 第 3 批

---

### F. 实际代码问题（10 个错误）

**现象**: 断言失败、数据库列缺失、Redis 连接失败等。

| 错误 | 数量 | 可能原因 |
|------|------|---------|
| `assert 0 == 1` | 3 | 业务逻辑不符合预期 |
| `no such column: mh.is_rolled_back` | 1 | 数据库迁移缺失列 |
| `BUG-002: 缺少 deleted_at IS NULL` | 3 | 查询条件不完整 |
| Redis 连接拒绝 | 2 | 容器内 Redis 连接配置问题 |
| `NoneType not subscriptable` | 2 | 空值未检查 |
| `list index out of range` | 2 | 空列表未检查 |

**性质**: 🐛 **实际代码问题**（需要逐一验证）

**修复方案**: 逐个分析，确认是 bug 还是测试环境问题。

**批次**: 第 4 批（需要仔细分析，不能批量修）

---

## 修复计划

### 第 1 批：路径 + mock 修复（94 个错误 → 预计修 80+）

**目标**: 修复容器内路径问题和 pipeline mock 问题

**改动范围**:
- `conftest.py` — 扩展 mock 范围覆盖 `app.services.pipeline`
- `bank/test_soft_delete_and_ux.py` — 路径动态化
- `bank/test_rebuild_position_filter.py` — 路径动态化
- `bank/test_oqs_backfill.py` — 路径动态化
- `bank/test_bank_mode_sql.py` — 路径动态化
- `bank/test_cross_category_merge.py` — 路径动态化
- `bank/test_per_user_answers.py` — 路径动态化
- `services/test_source_display.py` — 路径动态化
- `services/test_settings_position_switch.py` — 路径动态化
- `services/test_position_management.py` — 路径动态化
- `services/test_generate_answer_fix.py` — 路径动态化
- `pipeline/test_langgraph_workflows.py` — mock 修复
- `pipeline/test_pipeline_e2e.py` — mock 修复
- `pipeline/test_two_phase_pipeline.py` — mock 修复
- `pipeline/test_reprocess_cleanup_order.py` — mock 修复

**验证**: `docker compose --profile test run --rm test uv run pytest backend/tests/bank/ backend/tests/pipeline/ -q`

### 第 2 批：前端文件 + 导入修复（47 个错误 → 预计修 30+）

**目标**: 修复前端文件访问和过时导入

**改动范围**:
- 将前端源码验证改为 API 响应验证，或复制 frontend/ 到 test-runtime
- 更新所有过时的函数导入

**验证**: `docker compose --profile test run --rm test uv run pytest backend/tests/security/ backend/tests/services/ -q`

### 第 3 批：API mock 修复（11 个错误）

**目标**: 确保所有 LLM 调用都被 mock

**改动范围**: 需要逐个检查哪些测试缺少 mock

### 第 4 扥：实际代码问题（10 个错误）

**目标**: 逐一分析断言失败，确认是 bug 还是测试预期过时

**需要人工判断**:
- `mh.is_rolled_back` 列缺失 — 是迁移遗漏还是测试预期过时？
- `deleted_at IS NULL` 缺失 — 查询条件是否需要更新？
- Redis 连接 — 测试是否应该 mock Redis？

---

## 优先级建议

| 优先级 | 批次 | 预计收益 | 工作量 |
|--------|------|---------|--------|
| P0 | 第 1 批 | 80+ 错误修复 | 中（批量替换路径 + 改 conftest） |
| P1 | 第 2 批 | 30+ 错误修复 | 中（需要逐个判断前端验证策略） |
| P2 | 第 3 批 | 11 错误修复 | 低（加 mock 装饰器） |
| P3 | 第 4 批 | 10 错误修复 | 高（需要理解业务逻辑） |

## 修复记录

### 已完成的修复（86 个测试从失败变通过）

| 批次 | 修复内容 | 通过数变化 |
|------|---------|-----------|
| 1 | pipeline mock 路径 + 宿主机路径动态化 | +49 |
| 2 | 前端文件复制 + 过时导入 | +8 |
| 3 | tag_interview 参数 + 路径修复 | +14 |
| 4 | migrations 包重构 + clustering 导入 | +16 |
| 5 | chat agent mock 路径 + uv.lock | +33 |
| 6 | stream_llm_messages + execute_tool | +16 |

### 剩余 154 个失败（需要逐个分析）

| 类别 | 数量 | 修复难度 |
|------|------|---------|
| API AuthenticationError | 11 | 中（加 mock） |
| 断言失败（prompt/查询/组件变化） | ~100 | 高（需要业务分析） |
| DB 列/表缺失 | ~10 | 中（更新测试 schema） |
| 其他 | ~30 | 需要逐个分析 |
