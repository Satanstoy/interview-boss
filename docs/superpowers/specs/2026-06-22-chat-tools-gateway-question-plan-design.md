# Chat Tools Gateway 与题目计划绑定设计

日期：2026-06-22

## 背景

当前 chat agent 已经通过 ReAct tools 接入 `search_questions` 和 `draw_questions`，能够在面试对话中检索题库或加权抽题。但这条链路仍有两个核心不稳定点：

1. **工具契约偏松**：LLM 传入的参数直接进入执行函数，底层服务返回裸 list/dict。调用方难以区分“没有结果”“过滤太严”“embedding 不可用”“工具异常”等不同状态，也缺少统一的耗时、fallback、debug metadata。
2. **题目绑定偏弱**：工具返回候选题后，最终是否围绕候选题发问仍依赖 LLM。当前 pipeline 主要通过 basis id、文本重合、单候选 overlap 等启发式事后推断 `selected_question`，无法保证“搜到/抽到的题一定被问到”。

本设计把工具链路收紧为可控、可验证、可降级的工程闭环：先建立统一 Tool Gateway，再在出新题场景把候选题升级为本地选定的 `selected_question` 和强约束 `next_question_plan`。

## 目标

- 为 `search_questions`、`draw_questions` 增加 Pydantic 输入模型和输出模型。
- 将工具返回统一成稳定 envelope：`ok/items/metadata/error`。
- 明确空结果和错误语义，支持 fallback 标记和 debug reason。
- 记录工具级 metrics：总耗时、检索/向量/重排/DB 等阶段耗时，先以低侵入方式实现。
- 保持现有 ReAct state、SSE retrieved 事件、basis metadata 兼容。
- 在“出新题”场景中，本地选择 `selected_question`，生成 `next_question_plan`，强约束 LLM 围绕计划题发问。
- 生成后做 adherence 校验，不符合时自动 repair。
- 补充 Docker 后端测试，覆盖工具契约、错误降级、plan 绑定和 metadata 稳定性。

## 非目标

- 不在本阶段引入 MCP adapter。MCP 可作为未来适配层，但必须建立在稳定 Gateway 契约之上。
- 不重写整条 ReAct pipeline。
- 不让所有对话都强制绑定题库题。闲聊、澄清、未答完追问、结束面试仍保持自然对话。
- 不把 embedding 或 RAG 质量一次性调到最优。本设计为后续 golden tests 和检索优化提供稳定测量面。
- 不改变前端 SSE 协议的核心字段。新增 metadata 只能向后兼容。

## 当前链路分析

### 工具定义与执行

`backend/app/agents/chat/tools.py` 定义 OpenAI function calling schema，并在 `execute_tool()` 中分发到：

- `_execute_search_questions()` → `app.services.fts_service.hybrid_search()`
- `_execute_draw_questions()` → `app.services.question_draw_service.draw_questions()`

当前行为：

- `search_questions` 将结果写入：
  - `state["candidate_questions"]`
  - `state["retrieved_questions"]`
  - `state["question_source"] = "search"`
- `draw_questions` 将结果写入同样字段，并设置 `question_source = "draw"`。
- 工具返回给 LLM 的内容是裸 list 或简单 error dict。

### ReAct 主循环

`backend/app/agents/chat/pipeline.py` 的 `_react_loop()` 已有：

- 工具 allowlist。
- max steps / max tool calls / max seconds。
- loop detection。
- tool trace 日志。
- retrieved SSE 事件。
- 输出去重。
- `end_interview` 硬路由。

但当前主循环仍把检索/抽题结果作为“参考资料”交给 LLM，最后通过 `_build_react_metadata()` 里的 `_infer_selected_question()` 事后推断题目绑定。

### 历史题目计划能力

`backend/app/agents/chat/nodes.py` 中已有可复用能力：

- `_build_next_question_plan_prompt(plan)`
- `_question_plan_adherence(response_text, plan)`
- `_repair_response_to_question_plan(...)`

这些函数目前没有接入 ReAct 主链路，可作为本设计的基础。

## 总体架构

新增一层逻辑上的 Tool Gateway，建议先放在 `backend/app/agents/chat/tools.py` 内或拆为同目录 `tool_gateway.py`。若实现阶段发现 `tools.py` 继续膨胀，则拆文件优先。

```text
LLM tool call
  → validate_tool_call() allowlist / JSON shape
  → Tool Gateway
      → Pydantic input model
      → service call with timeout/metrics
      → normalize service result
      → Pydantic output model
      → state update
      → optional selected_question plan creation
  → ReAct message receives compact tool envelope
  → final generation sees next_question_plan when applicable
  → adherence check
      → ok: emit response
      → drift: repair, then emit response
  → metadata uses planned selected_question before fallback inference
```

## Tool Gateway 契约设计

### 统一输出 envelope

所有 chat tools 返回统一结构：

```json
{
  "ok": true,
  "tool": "search_questions",
  "items": [],
  "metadata": {
    "result_count": 0,
    "fallback_used": false,
    "fallback_steps": [],
    "empty_reason": null,
    "debug_reason": "",
    "metrics": {
      "total_ms": 0,
      "fts_ms": null,
      "cjk_like_ms": null,
      "vector_ms": null,
      "rerank_ms": null,
      "db_ms": null
    }
  },
  "error": null
}
```

失败时：

```json
{
  "ok": false,
  "tool": "draw_questions",
  "items": [],
  "metadata": {
    "result_count": 0,
    "fallback_used": false,
    "fallback_steps": [],
    "empty_reason": null,
    "debug_reason": "validation_failed",
    "metrics": {"total_ms": 1}
  },
  "error": {
    "error_code": "VALIDATION_ERROR",
    "message": "Invalid tool arguments"
  }
}
```

### ToolQuestionItem

每个题目统一规范化为：

```json
{
  "id": 123,
  "question": "...",
  "cat1": "...",
  "cat2": "...",
  "source": "search",
  "score": 0.01639,
  "reason": "rrf_ranked",
  "tags": "...",
  "difficulty": "L2-中等",
  "sources": []
}
```

字段要求：

- `id`：正整数。
- `question`：非空字符串。
- `cat1/cat2`：字符串，缺失时为空字符串。
- `source`：`search` 或 `draw`。
- `score`：可选浮点，优先取 `_combined_rank_score`、`_rrf_score`、`score`、`rank`。
- `reason`：稳定短码，例如 `rrf_ranked`、`weighted_draw`、`difficulty_fallback`。
- `sources`：保持兼容，允许 list 或 JSON string 归一化为 list。

### SearchQuestionsInput

建议字段：

- `keywords: list[str]`：0-5 个，trim，过滤空字符串；全空时返回 `ok=false / NO_QUERY` 或 `ok=true / empty_reason=NO_QUERY`，实现阶段需保持测试一致。
- `question_type: Literal["project_followup", "knowledge_probe", "new_question"] | None`
- `limit: int = 5`：范围 1-10；给 LLM 的 schema 仍可只暴露 top 3 或默认 3。
- `exclude_ids: set[int] = set()`：由 state 合并，不直接信任 LLM 任意传入。
- `negative_terms: list[str]`：由 state 合并。
- `query_text/job_position/retrieval_intent`：主要从 state 注入，不鼓励 LLM 传。

### DrawQuestionsInput

建议字段：

- `count: int = 3`：范围 1-5，超出 clamp 或 validation error，推荐 validation error，让错误可见。
- `difficulty: Literal["easy", "medium", "hard"] | None`
- `cat1/cat2/topic: str | None`：trim，限制长度。
- `question_type: Literal["algorithm_coding", "project_followup", "knowledge_probe", "system_design", "hr"] | None`
- `exclude_ids: set[int] = set()`：由 state 合并。
- `seed: int | None`：本 spec 预留，第一阶段可不暴露给 LLM；测试环境后续可启用确定性抽题。

## 错误码与空结果语义

建议错误码：

| code | 含义 | 是否可降级 |
|------|------|------------|
| `VALIDATION_ERROR` | LLM 参数不符合模型 | 否 |
| `NO_QUERY` | search 缺少 keywords/query_text | 否 |
| `USER_REQUIRED` | draw 缺少 user_id | 否 |
| `NO_MATCH` | 服务正常但无候选 | 可由后续 fallback 处理 |
| `FILTER_TOO_STRICT` | cat/difficulty/topic/exclude 过滤过严 | 可放宽 |
| `EMBEDDING_UNAVAILABLE` | 向量不可用 | 是，FTS/LIKE 降级 |
| `TOOL_TIMEOUT` | 工具超时 | 是，本地 fallback |
| `SERVICE_ERROR` | 底层服务异常 | 是，本地 fallback |
| `UNKNOWN_TOOL` | 工具名不在 allowlist | 否 |

空结果不再只用 `[]` 表示。`metadata.empty_reason` 必须说明原因：

- `no_query`
- `no_match`
- `filter_too_strict`
- `all_candidates_excluded`
- `service_unavailable`

## Metrics 设计

第一阶段采用低侵入 metrics：

- Gateway 统一记录 `total_ms`。
- `question_draw_service.draw_questions()` 可记录 DB 查询和 weighted sample 粗粒度耗时，或先只返回 total。
- `fts_service.hybrid_search()` 后续可逐步拆分：
  - FTS 查询耗时
  - CJK LIKE 耗时
  - vector 搜索耗时
  - RRF/rerank 耗时

为了避免大改服务签名，建议先用可选 side-channel：

```python
hybrid_search(..., collect_metrics: bool = False) -> list[dict] | tuple[list[dict], dict]
```

或在 Gateway 内先只记录总耗时，后续另开 PR 拆服务级 metrics。第一阶段测试不应强依赖每个子指标都非空。

## selected_question plan 绑定设计

### 触发条件

只有“出新题”场景创建强制计划：

- `intent == "practice_request"`
- `intent == "interview_question" and answer_complete is True`
- `state["question_type"] == "algorithm_coding"`
- 用户明确要求：出题、来一道、换题、随机、手撕、代码题

不触发强制计划：

- `intent == "chat"`
- `intent == "follow_up"`
- `intent == "end_interview"`
- `interview_question` 但 `answer_complete is False`
- 工具结果为空且没有明确 fallback 题

### 本地选题规则

初始规则保持简单、可测：

1. 工具 envelope `items` 非空。
2. 优先选择第一个 item。
3. 若 `question_type == "algorithm_coding"`，先在候选中找 question/cat1/cat2/tags 含算法、代码、手撕、数据结构、链表、排序、二分等关键词的题。
4. 若候选都与负向词冲突，不创建强制 plan，记录 `question_plan_reason=negative_terms_filtered`。

后续可把历史相似重复保护、阶段比例控制、seed 等抽象到独立 selector。

### next_question_plan 结构

```json
{
  "must_ask": true,
  "question_id": 123,
  "question_text": "RAG 系统中如何设计召回和重排？",
  "basis_type": "interview_question",
  "source": "search",
  "strategy": "practice_request",
  "allowed_focus": ["RAG", "召回", "重排"],
  "forbidden_focus": ["HR", "算法"],
  "selection_reason": "top_ranked_search_result"
}
```

该 plan 写入：

- `state["selected_question"]`
- `state["next_question_plan"]`
- `state["question_source_reason"] = "question_plan_bound"`

### 注入方式

在 `_react_loop()` 最终生成前，将 `_build_next_question_plan_prompt(plan)` 生成的文本作为额外 system/user message 注入。建议注入为 system 或 user 中的“系统自动生成约束”，并与缓存 system prompt 分离，避免每轮动态 plan 污染缓存。

### 生成后 adherence 校验

最终文本生成后、emit chunk 前执行：

```text
response_text
  → _question_plan_adherence(response_text, plan)
  → adheres=True: 继续
  → adheres=False: _repair_response_to_question_plan(...)
```

repair 后再次做一次 adherence：

- 通过：使用 repaired response。
- 仍不通过：使用确定性 fallback 文案：
  - `我们收束到这道题：{question_text}。请你说明核心思路、关键取舍和验证方式。`

### metadata 优先级

`_build_react_metadata()` 中 selected_question 解析优先级调整为：

1. `state["next_question_plan"]` 且本轮 response adherence 通过或已 repair。
2. `state["selected_question"]`。
3. basis question id。
4. 文本匹配。
5. 单候选 overlap。
6. 无绑定。

这样 selected_question 不再主要依赖事后猜测。

## Tool governance 设计

在现有 `_build_tool_strategy()` 基础上，建议把策略从 prompt-only 升级为“prompt + runtime gate”：

| 场景 | 工具策略 |
|------|----------|
| `end_interview` | 硬路由，禁止工具 |
| `chat` | 默认禁止 search/draw |
| `follow_up` | 默认禁止 draw；必要时允许 search，但不强制 plan |
| `practice_request` | 必须 search 或 draw；无结果需明确 fallback reason |
| `interview_question + answer_complete=True` | 默认 search；如果出新题，必须有 selected_question 或 fallback reason |
| `algorithm_coding` | 优先 draw/search with `question_type="algorithm_coding"` |
| 工具连续失败 | 不继续让 LLM 猜，走本地 fallback |

第一阶段可先在 spec 和测试中覆盖策略，不一次性实现所有 runtime gate。

## SSE 与前端兼容

现有 SSE 事件保持：

- `step`
- `retrieved`
- `insight`
- `chunk`
- `basis`
- `done`

新增 metadata 可选字段：

```json
{
  "tool_result": {
    "tool": "search_questions",
    "ok": true,
    "error_code": null,
    "fallback_used": false,
    "empty_reason": null,
    "metrics": {"total_ms": 31}
  },
  "question_plan": {
    "question_id": 123,
    "source": "search",
    "selection_reason": "top_ranked_search_result",
    "adherence": {
      "adheres": true,
      "score": 0.5,
      "reason": "keyword_overlap"
    },
    "repaired": false
  }
}
```

前端无需立即消费这些字段。后续诊断面板或日志回放可以使用。

## 测试计划

### Tool Gateway 单元测试

新增或扩展：`backend/tests/chat/test_tools.py`

- `search_questions` 正常返回 envelope，items 字段稳定。
- `draw_questions` 正常返回 envelope，items 字段稳定。
- 非法 JSON 参数返回 `VALIDATION_ERROR` 或当前 validate 层错误。
- `keywords=[]` 返回明确 `NO_QUERY` / `empty_reason=no_query`。
- `count` 越界返回 validation error。
- `draw_questions` 缺 user_id 返回 `USER_REQUIRED`。
- 底层 `_hybrid_search` 抛异常时返回 `SERVICE_ERROR`，不让 pipeline 崩溃。
- 底层 `_draw_questions` 抛异常时返回 `SERVICE_ERROR`。
- 空结果区分 `NO_MATCH` 和过滤过严场景。
- 旧 state 字段 `retrieved_questions/candidate_questions/question_source` 仍更新。

### Plan 绑定测试

新增或扩展：`backend/tests/chat/test_react_loop.py`

- practice_request + search 结果 → 创建 `next_question_plan`。
- interview_question + answer_complete=True + draw/search 结果 → 创建 plan。
- chat/follow_up/end_interview 不创建强制 plan。
- algorithm_coding 候选中优先选择算法题。
- LLM final answer 符合 plan → 不 repair，metadata selected_question 来自 plan。
- LLM final answer 偏离 plan → 调用 repair。
- repair 仍偏离 → 使用确定性 fallback。
- `selected_question` metadata 优先使用 plan，而不是 `_infer_selected_question()`。

### Service 回归测试

扩展：

- `backend/tests/services/test_fts_service.py`
- `backend/tests/services/test_question_draw_service.py`

覆盖：

- metrics 可选字段不破坏旧返回。
- draw fallback metadata 可在 Gateway 层被识别。
- embedding 不可用时 search 仍可返回 FTS/LIKE 结果并标记 fallback。

### 运行命令

按项目要求，后端测试必须通过 Docker：

```bash
docker compose exec backend uv run pytest backend/tests/chat/ -q
docker compose exec backend uv run pytest backend/tests/services/ -q
docker compose exec backend uv run pytest backend/tests/ -q
```

## 分阶段实施计划

### 阶段 1：Tool Gateway 契约硬化

- 新增 Pydantic input/output models。
- Gateway 包装 search/draw 执行。
- 统一 envelope。
- 兼容旧 state 和 SSE。
- 补 chat tools 测试。
- 更新 `backend/app/agents/chat/CLAUDE.md`、`backend/app/services/CLAUDE.md`。
- 写 dev-log，运行测试，commit。

### 阶段 2：selected_question plan 绑定

- 增加本地选题函数。
- 构造 `next_question_plan`。
- 在出新题场景注入 plan。
- 接入 adherence 和 repair。
- 调整 metadata 优先级。
- 补 ReAct loop 测试。
- 更新相关 CLAUDE.md，写 dev-log，运行测试，commit。

### 阶段 3：RAG golden tests 与抽题 deterministic tests

- 为 RAG 增加 golden cases：RAG 流程、MCP tool calling 区别、中英文混合、岗位过滤、负向词过滤、embedding fallback。
- 为 draw 增加 seed、selection_reason、分层降级测试。
- 这阶段不属于本 spec 的首个 implementation commit，但依赖本 spec 的契约。

## 风险与缓解

### 风险：改变工具输出格式导致 LLM 理解下降

缓解：给 LLM 的 tool result 可以保留紧凑版，只包含 `ok/items/error/metadata.debug_reason`，避免塞入过多 metrics。完整 metrics 留在 state/log/metadata。

### 风险：强绑定让自然追问变僵硬

缓解：只在出新题场景触发 `must_ask=true`。follow_up、chat、未答完回答不强控。

### 风险：repair 增加延迟

缓解：只有 adherence 失败才 repair。repair 失败后使用确定性 fallback，最多一次额外 LLM 调用。

### 风险：工具层 Pydantic 校验过严导致可用请求被拒绝

缓解：对字符串做 trim/filter，对 count 等采用清晰错误；先不要对 cat1/cat2 语义做强枚举，只限制长度。

### 风险：metrics 侵入服务太深

缓解：第一阶段只强制 total_ms，其余子指标可空；后续逐步拆服务级 metrics。

## 回滚策略

- Gateway 可保留旧裸 list 到 state 的兼容路径。若 envelope 影响 LLM，可只对日志/metadata 使用 envelope，对 tool message 暂时返回 `items[:3]`。
- Plan 绑定可通过配置开关控制，例如 `CHAT_QUESTION_PLAN_MODE=off|observe|enforce`：
  - `off`：完全关闭。
  - `observe`：创建 plan 和记录 adherence，但不 repair。
  - `enforce`：偏离时 repair。
- 出现线上异常时先切到 `observe` 或 `off`，保留 Gateway 契约。

## 文档更新判断

实现阶段需要更新：

- `backend/app/agents/chat/CLAUDE.md`：新增 Tool Gateway、question plan、adherence/repair 说明。
- `backend/app/services/CLAUDE.md`：若改 `fts_service.py` 或 `question_draw_service.py` 职责/返回 metrics，需要更新职责说明。
- 根 `CLAUDE.md`：若架构或代码路由表发生变化再更新；单纯内部契约不一定需要。
- README：本设计不新增 API、路由、环境变量、依赖、前端入口；实现阶段通常不触发 README 更新，除非增加环境变量或对外 API。
- `docs/dev-log/`：每次开发记录。

## 推荐实施顺序

1. 先实现阶段 1：Tool Gateway 契约硬化。
2. 确认 chat tools 和 service tests 稳定后，实现阶段 2：selected_question plan 绑定。
3. 最后补阶段 3：RAG golden tests 和抽题 deterministic tests。

这样可以把风险分层：先稳定工具输入输出，再收紧 LLM 生成边界，最后用评测集持续防退化。
