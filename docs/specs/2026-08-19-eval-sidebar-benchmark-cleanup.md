# Spec: 评测中心侧边栏导航清理 — Benchmark 功能合并修复

> 位置: `frontend/src/layouts/AuthenticatedLayout.vue` + `frontend/src/views/admin/` + `frontend/src/services/evaluationApi.js` + `backend/app/routers/admin_evaluation.py`
> 类型: 前端导航清理 + 后端 API 清理
> 日期: 2026-08-19
> 状态: 待实施
> 审计依据: tech-audit quick scan（2026-08-19）
> 方法: 最小变更 → 验证 → 提交

## 背景

评测中心现有 6 个导航项，覆盖「测评可视化 → 版本与发布 → Benchmark → 测评实验 → 评测结果 → 人工 A/B」流程。经代码审计发现以下问题：

| 问题 | 位置 | 现状 | 影响 |
|------|------|------|------|
| 侧边栏 Benchmark 导航项过时 | `AuthenticatedLayout.vue:244` | 指向 `/admin/evals/benchmarks`，但路由已重定向到 `/admin/evals/releases` | 用户点击后被重定向，造成困惑 |
| 未使用的 Benchmark 视图文件 | `EvaluationBenchmarksView.vue` | 文件存在但路由未导入 | 代码冗余，维护困惑 |
| 冗余 API 函数 | `evaluationApi.js:14` | `fetchEvaluationBenchmarks` 函数存在但未使用 | API 层冗余 |
| 冗余后端端点 | `admin_evaluation.py` | `/api/admin/evals/benchmarks` 端点存在但前端未使用 | 后端冗余 |

**根本原因**: Benchmark 功能已与版本发布合并，但前端侧边栏和相关代码未同步清理。

---

## 问题清单与改进方案

### 问题 1 — 侧边栏 Benchmark 导航项过时 🔴

**现状**（已核实源码）：
- `frontend/src/layouts/AuthenticatedLayout.vue:244` 定义了 `{ key: 'EvalBenchmarks', label: 'Benchmark', route: '/admin/evals/benchmarks' }`
- `frontend/src/router/index.js:126-127` 配置了 `path: 'admin/evals/benchmarks', redirect: '/admin/evals/releases'`
- 用户点击"Benchmark"后被重定向到"版本与发布"页面，但侧边栏仍显示"Benchmark"标签

**方案**：从侧边栏导航中移除"Benchmark"项。

- **Step 1**: 编辑 `frontend/src/layouts/AuthenticatedLayout.vue`，删除第 244 行的 Benchmark 导航项
- **Step 2**: 验证评测中心导航是否正常（剩余 5 项：测评可视化、版本与发布、测评实验、评测结果、人工 A/B）
- **Step 3**: 运行前端构建测试确保无语法错误

**风险**: 低。移除的是冗余导航项，不影响功能。

---

### 问题 2 — 未使用的 EvaluationBenchmarksView.vue 文件 🟡

**现状**（已核实）：
- `frontend/src/views/admin/EvaluationBenchmarksView.vue` 文件存在（74 行）
- 路由配置中没有导入该文件
- 该文件调用 `fetchEvaluationBenchmarks` API，但实际访问时被重定向

**方案**: 删除未使用的文件。

- **Step 1**: 删除 `frontend/src/views/admin/EvaluationBenchmarksView.vue`
- **Step 2**: 运行前端构建测试确保无依赖错误
- **Step 3**: 检查是否有其他文件引用该组件（应无引用）

**风险**: 低。文件未被使用，删除不影响功能。

---

### 问题 3 — 冗余的前端 API 函数 🟡

**现状**（已核实）：
- `frontend/src/services/evaluationApi.js:14` 定义了 `export const fetchEvaluationBenchmarks = () => get(\`\${ROOT}/benchmarks\`, { noCache: true })`
- 该函数未被任何组件调用
- 后端仍有对应的 `/api/admin/evals/benchmarks` 端点

**方案**: 清理未使用的 API 函数。

- **Step 1**: 从 `frontend/src/services/evaluationApi.js` 中删除 `fetchEvaluationBenchmarks` 函数
- **Step 2**: 运行前端构建测试确保无语法错误
- **Step 3**: 检查是否有其他文件引用该函数（应无引用）

**风险**: 低。函数未被使用，删除不影响功能。

---

### 问题 4 — 冗余的后端 API 端点 🟡

**现状**（已核实）：
- `backend/app/routers/admin_evaluation.py` 定义了 `@router.get("/benchmarks")` 端点
- 该端点返回 benchmark suites 数据
- 前端已不使用该端点（路由重定向到 releases）

**方案**: 评估是否保留或清理冗余端点。

- **Step 1**: 检查后端是否有其他地方调用该端点（如测试、脚本等）
- **Step 2**: 如果确认无其他调用，删除 `@router.get("/benchmarks")` 端点及其处理函数
- **Step 3**: 运行后端测试确保无依赖错误

**风险**: 中。需要确认无其他调用方。如果后端测试或脚本依赖该端点，删除会导致测试失败。

---

## 实施顺序

1. **M-1**: 移除侧边栏 Benchmark 导航项（🔴 问题，立即修复）
2. **M-2**: 删除未使用的 EvaluationBenchmarksView.vue 文件（🟡 问题，尽快修复）
3. **M-3**: 清理冗余的前端 API 函数（🟡 问题，尽快修复）
4. **M-4**: 评估并清理冗余的后端 API 端点（🟡 问题，计划修复）

每个里程碑独立可交付、可验收。

---

## Task M-1: 移除侧边栏 Benchmark 导航项

**目标**: 从侧边栏导航中移除过时的"Benchmark"项，避免用户点击后被重定向。

**Files:**

- Edit: `frontend/src/layouts/AuthenticatedLayout.vue`

**Step 1（编辑）**:

编辑 `frontend/src/layouts/AuthenticatedLayout.vue`，删除第 244 行：
\`\`\`
{ key: 'EvalBenchmarks', label: 'Benchmark', route: '/admin/evals/benchmarks' },
\`\`\`

**Step 2（验证）**:

- 运行 `cd frontend && npm run build` 确保构建通过
- 手动验证评测中心导航是否正常显示 5 个项

**Step 3（提交）**:

- 提交信息: `fix(frontend): remove obsolete Benchmark sidebar nav item`
- 关联审计发现: tech-audit quick scan 2026-08-19

---

## Task M-2: 删除未使用的 EvaluationBenchmarksView.vue

**目标**: 清理冗余的视图文件，减少代码维护负担。

**Files:**

- Delete: `frontend/src/views/admin/EvaluationBenchmarksView.vue`

**Step 1（删除）**:

删除 `frontend/src/views/admin/EvaluationBenchmarksView.vue` 文件。

**Step 2（验证）**:

- 运行 `cd frontend && npm run build` 确保构建通过
- 检查是否有其他文件引用该组件（应无引用）

**Step 3（提交）**:

- 提交信息: `refactor(frontend): remove unused EvaluationBenchmarksView.vue`
- 关联审计发现: tech-audit quick scan 2026-08-19

---

## Task M-3: 清理冗余的前端 API 函数

**目标**: 清理未使用的 `fetchEvaluationBenchmarks` 函数，减少 API 层冗余。

**Files:**

- Edit: `frontend/src/services/evaluationApi.js`

**Step 1（编辑）**:

从 `frontend/src/services/evaluationApi.js` 中删除第 14 行：
\`\`\`
export const fetchEvaluationBenchmarks = () => get(\`\${ROOT}/benchmarks\`, { noCache: true })
\`\`\`

**Step 2（验证）**:

- 运行 `cd frontend && npm run build` 确保构建通过
- 检查是否有其他文件引用该函数（应无引用）

**Step 3（提交）**:

- 提交信息: `refactor(frontend): remove unused fetchEvaluationBenchmarks API function`
- 关联审计发现: tech-audit quick scan 2026-08-19

---

## Task M-4: 评估并清理冗余的后端 API 端点

**目标**: 评估 `/api/admin/evals/benchmarks` 端点是否仍需要，如不需要则清理。

**Files:**

- Edit: `backend/app/routers/admin_evaluation.py`

**Step 1（评估）**:

- 检查后端测试中是否有调用 `/api/admin/evals/benchmarks` 的测试用例
- 检查是否有脚本或其他服务调用该端点
- 如果确认无其他调用，进入 Step 2

**Step 2（删除）**:

从 `backend/app/routers/admin_evaluation.py` 中删除 `@router.get("/benchmarks")` 端点及其处理函数 `list_benchmarks`。

**Step 3（验证）**:

- 运行后端测试: `docker compose --profile test run --rm test uv run pytest backend/tests/ -q`
- 确保测试通过

**Step 4（提交）**:

- 提交信息: `refactor(backend): remove unused /api/admin/evals/benchmarks endpoint`
- 关联审计发现: tech-audit quick scan 2026-08-19

---

## 验收标准

1. 侧边栏评测中心导航显示 5 个项（无 Benchmark）
2. 点击"版本与发布"导航项正常跳转，无重定向
3. 前端构建通过: `cd frontend && npm run build`
4. 后端测试通过: `docker compose --profile test run --rm test uv run pytest backend/tests/ -q`
5. 无冗余代码: `EvaluationBenchmarksView.vue` 文件不存在，`fetchEvaluationBenchmarks` 函数不存在

---

## 风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| 删除 Benchmark 导航项后用户找不到相关功能 | 低 | 低 | 功能已合并到"版本与发布"，用户可通过该入口访问 |
| 删除文件导致依赖错误 | 低 | 中 | 运行构建测试验证 |
| 删除后端端点导致测试失败 | 中 | 中 | 先检查测试依赖，确认无影响后再删除 |

---

## 后续建议

1. **信息架构优化**: 评测中心现有 5 个导航项，可考虑合并"测评实验"和"评测结果"，简化导航结构
2. **文档更新**: 更新 `frontend/CLAUDE.md` 和 `docs/specs/` 中的相关文档，记录评测中心导航变更
3. **用户反馈**: 收集用户对评测中心导航的使用反馈，评估是否需要进一步优化
