# Over-engineering audit — 2026-08-13

**Companion to**: [tech-audit-2026-08-13.md](tech-audit-2026-08-13.md)（D1 触发 ≥5 findings 的深度清单）
**按 D1 essentiality taxonomy 排序**（最安全的删除优先）。

## 可安全删除（delete / yagni）

1. **`backend/app/services/pipeline/batch_v2.py`（364 行）— yagni: 生产零调用**
   - 生产路径无任何 import；仅测试经 `inspect.getsource` / `from ... import compact_singletons_in_db_v2` 引用其源码断言「应该调用某个函数」。
   - 风险：旧实现漂移腐烂，测试断言的是历史行为而非当前契约。
   - 处理：把被断言的回归点固化为 fixtures/注释契约后删除模块；或先标注 deprecated 一个发布周期。

2. **三套图标库并行 — `@hugeicons/core-free-icons` + `@hugeicons/vue`（0 处 import，可删）+ `@lucide/vue` + `@tabler/icons-vue` 并存**
   - hugeicons 为未完成迁移的残留（CLAUDE.md 规定图标统一 @lucide/vue）。
   - 处理：npm rm hugeicons 两个包；评估 tabler 用量，能迁则迁（非必须）。

3. **`frontend/tsconfig.json` 空壳（仅 baseUrl/paths，无 strict，未接线）**
   - 给人「有类型检查」的错觉，实际任何 TS 检查都不跑。
   - 处理：补 `strict: true` 并接 `vue-tsc --noEmit` 进 check.sh；或删除空壳避免误导（推荐前者）。

## 合并收敛（shrink）

4. **LLM 容错 JSON 解析 ×4** — `llm.py:_extract_json` / `llm_judge.py:parse_json_object/parse_json_list` / `unmerged_quality.py:_extract_json_object` / `clustering/experiments/memory_labels.py:_extract_json_object/_extract_json_array`。
   - llm_judge 已立项为共享归宿但未迁完。处理：llm_judge.parse_json_* 成为唯一实现，其余 import 复用（含 experiments 目录，避免 eval 脚本与生产行为漂移）。

5. **迁移注册表集中化已达标（非 finding，正面记录）** — 78 个迁移按域分 15 个子模块 re-export，registry 单文件 237 行，无孤儿迁移、无单实现接口蔓延。

## 领域密集、不宜砍（保留）

6. **`chat_service.py`（2395 行）/ `nodes.py`（2028 行）/ `worker.py`（1685 行）/ `llm.py`（1554 行）/ `ChatView.vue`（1577 行）**
   - 逐一阅读确认：行数来自真实领域复杂度（回合状态机、side-effect 对账、ARQ 任务、LLM 客户端矩阵、SSE 重放），**非** LLM 样板膨胀。例外：`llm.py` 与 `ChatView.vue` 缺模块 docstring（无「为什么这么大」说明）。
   - 处理：按 D1 主报告 🔴 拆分为按职责模块（安全、纯结构移动），拆分时保持 router re-export 与测试引用稳定；`llm.py`/worker 先补 docstring。

## 观测到的 LLM 辅助代码特征（供后续审查侧重）

- 领域异常层次（chat_service 9 个异常类）设计合理，是幂等/对账契约的显式化，不是过度设计。
- services/ 20 个类中 15 个是异常/枚举/值对象，无单实现 Service 接口蔓延（无 XService+XRepository+XManager 三层样板）。
- 前端 composables 20 个 use* 为收敛模式，ChatView 拆分应复用该模式。
