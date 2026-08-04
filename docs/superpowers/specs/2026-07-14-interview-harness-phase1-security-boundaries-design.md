# 模拟面试 Harness 第一阶段安全边界设计

**日期：** 2026-07-14  
**状态：** 待用户审阅  
**范围：** ToolPolicy、题目候选可信性、外部 MCP 身份边界、归档会话写入边界

## 目标

把当前依赖模型提示词的关键约束升级为服务端执行层约束，确保：

1. ReAct 只能调用当前回合实际获准的工具。
2. `select_question` 只能从服务端产生的候选集选择，不能提交或覆盖题目对象。
3. 外部 MCP 请求不能通过请求体伪造用户或跨用户读取 session。
4. archived conversation 仍可读，但不能继续产生新的可写消息。

## 非目标

本阶段不引入：

- `chat_turns`、幂等键、reserve/finalize 两阶段回合事务；
- coverage/asked-question/session notes 的完整 event sourcing；
- PostgreSQL、RLS 或新的 ORM；
- 完整 MCP OAuth authorization server；
- JD、简历和 memory 的结构化抽取重构。

这些内容保留到第二阶段，避免把几个独立的状态模型改造混在一次变更中。

## 当前架构约束

- 数据库使用线程级 SQLite WAL 连接，迁移由 `backend/app/db/migrations/` 手写维护。
- `backend/app/mcp_server/interview_tools.py` 是内部 ReAct 和外部 MCP 共享的执行层。
- `ToolStrategy` 继续负责生成 LLM 可读的策略说明，但不再被视为授权边界。
- 最终话术仍由 `TurnPlanner` 和 contract writer 负责；工具拒绝不能触发机械题目 fallback。
- 当前认证模型有 user JWT 和可选 `MCP_API_KEY`，还没有独立的 tenant principal，因此本阶段不虚构 `tenant_id` 语义。

## 设计方案

### 1. ToolPolicy 执行层授权

新增 `backend/app/agents/chat/tool_policy.py`，定义不可变的 `ToolPolicy`：

```python
@dataclass(frozen=True)
class ToolPolicy:
    user_id: int
    conversation_id: str
    bank_mode: str
    allowed_tools: frozenset[str]
    allowed_skills: frozenset[str] | None
    policy_version: str
```

其中 `allowed_skills=None` 表示当前策略允许所有已注册 skill；空集合表示不允许任何 skill。

`build_tool_policy(state)` 从 `compute_tool_strategy(state)` 派生工具集合：

- `allow_search=True` 才加入 `search_questions`；
- `allow_draw=True` 才加入 `draw_questions`；
- `allow_load_skill=True` 才加入 `load_skill`；
- 当前 state 存在 `candidate_questions` 或 `retrieved_questions` 时才加入 `select_question`；
- 工具集合为空时默认拒绝，不根据模型提交的工具名放宽权限。

策略在每次工具调用前根据当前受控 state 重建，以便搜索/抽题成功后允许下一步选择；state 只能由已授权的服务端工具修改。

`react_loop.validate_tool_call()` 改为接收 `ToolPolicy`，在任何执行前按以下顺序检查：

1. 工具名是否在全局注册表；
2. 工具名是否在当前 policy allowlist；
3. 参数是否为 object；
4. 参数是否通过严格 Pydantic schema；
5. `load_skill.skill_name` 是否在 `allowed_skills`；
6. `select_question` 是否只包含 `candidate_index`。

未知字段必须拒绝，不能静默丢弃。拒绝结果使用稳定错误码 `TOOL_NOT_ALLOWED`、`INVALID_TOOL_ARGUMENTS` 或 `SKILL_NOT_ALLOWED`，并记录 policy version、tool name 和安全摘要。拒绝工具不得进入 `chat_tools.execute_tool()`。

严格输入模型放在 `backend/app/agents/chat/tool_gateway.py`，至少覆盖：

- `SearchQuestionsInput`；
- `DrawQuestionsInput`；
- `LoadSkillInput`；
- `SelectQuestionInput(candidate_index: int)`。

`ToolStrategy.to_prompt_text()` 保留当前提示词说明，但只作为减少错误调用的 UX 优化，不作为安全控制。

### 2. 服务端 Candidate Set

内部和外部两个入口的 `select_question` 都只接受：

```json
{"candidate_index": 0}
```

不再接受 `candidates`、题目正文、dimension、tags 或 question object。未知字段直接返回参数错误。

候选题必须来自当前 state/session 中由 `search_questions` 或 `draw_questions` 产生的候选列表。选择时：

1. 校验候选索引为非负整数且不越界；
2. 从候选对象只取 question ID 和受控来源信息；
3. 按当前 user、bank mode、job position、approved、未删除条件重新查询题库；
4. 使用数据库返回的正文、分类、难度、标签构造 `selected_question`；
5. question plan、asked-question、coverage metadata 全部使用重新加载后的权威数据；
6. 候选不存在、越权、已删除或不再可用时返回明确错误，不使用模型提交的对象补齐。

外部 MCP 如果请求中仍携带 `candidates`，必须拒绝，而不是忽略。这可以尽早暴露旧客户端契约，避免调用方误以为任意题目仍然被接受。

本阶段不新增持久化 `candidate_sets` 表。候选集先沿用当前 ReAct state/MCP session，但 session 必须绑定调用用户；如果后续需要跨断线恢复和一次性 token，再单独设计持久化 candidate set。

### 3. 外部 MCP 身份和 session 边界

内部 ReAct 直接调用 Python 执行层，不经过 `/mcp` HTTP 认证；它使用已经由 chat router 校验过的 user/conversation state。

外部 `/mcp` 请求采用分层校验：

1. 没有 `MCP_API_KEY` 时，生产环境默认拒绝请求；开发/测试只有显式设置匿名开关时才允许；
2. 配置 `MCP_API_KEY` 时，要求 `X-MCP-API-Key`，不鼓励 query parameter 传 key；
3. 需要访问用户题库或 session 的工具必须同时提供有效 user JWT；
4. user ID 从 JWT subject/claims 推导，请求体中的 `user_id` 只能被校验为一致或直接拒绝；
5. `bank_mode` 从认证用户和服务端 entitlement 推导，不接受请求体覆盖；
6. session 存取 key 必须包含 user identity，错误用户不能读取或修改同一个 `session_id`；
7. session 不被视为认证凭据，猜到 session ID 也不能越过 JWT 校验。

本阶段只复用现有 JWT 认证能力，不实现 OAuth authorization server。若未来真正开放给第三方 MCP client，再单独增加 audience、scope、resource server 和 OAuth 流程。

### 4. Archived conversation 写入边界

`get_conversation()` 保持可返回 archived conversation，以支持历史查看；不要全局添加 status 过滤。

新增写入专用函数，至少覆盖用户消息：

```python
save_user_message_if_writable(
    conversation_id: str,
    user_id: int,
    content: str,
) -> int
```

该函数在单条 SQLite `INSERT ... SELECT ... WHERE user_id = ? AND status = 'active'` 中完成归属和状态检查，失败返回可区分的 `CONVERSATION_NOT_WRITABLE` 或 `CONVERSATION_NOT_FOUND`。路由不得先查询后调用普通 `save_message()` 来代替它。

assistant 持久化也增加 active 状态条件；如果生成期间会话被归档，则不写入新的 assistant message，并记录可观察的 finalize rejection。第二阶段的 turn fence 会进一步解决旧 worker 的提交问题，本阶段不假装已经解决并发回合。

HTTP 层对 archived/completed/非本人会话返回 `409 CONVERSATION_NOT_WRITABLE` 或 `404`，沿用现有资源隐藏策略，但不能静默写入。

## 错误和兼容性策略

- 旧模型传入未知 tool 参数：返回结构化工具错误，停止当前非法调用，不执行工具。
- 旧外部 MCP 客户端传入 `candidates`：返回参数错误；这是有意的破坏性契约收紧。
- 外部 MCP 没有用户 JWT：拒绝用户级题库/session 操作，不降级到请求体 `user_id`。
- 工具被策略拒绝：不启用题目文本 fallback，继续走现有 contract/error 路径。
- archived conversation：只读接口继续工作，任何新用户输入在写入点拒绝。

## 测试设计

新增或修改以下测试：

1. `backend/tests/chat/test_tool_strategy.py` / `test_tool_strategy_limit.py`
   - 允许/禁止工具集合正确映射；
   - end、deep-dive、冻结分布等策略的禁止工具无法执行。
2. `backend/tests/chat/test_react_loop.py`
   - 未知工具字段被拒绝；
   - 禁止工具不会调用 executor；
   - skill 白名单和 `candidate_index` 参数约束生效。
3. `backend/tests/chat/test_interview_mcp_tools.py`
   - `candidates` 注入被拒绝；
   - 候选正文被篡改时，最终 selected question 仍来自数据库；
   - 越权、删除、越界候选无法绑定。
4. `backend/tests/chat/test_mcp_session.py` 以及 MCP auth 测试
   - 不同用户不能读取同一 session；
   - 生产无 key 默认拒绝；
   - user JWT 与请求体 user_id 不一致时拒绝。
5. Chat router/service 测试
   - archived conversation 不能保存 user message；
   - archived 仍可读取消息；
   - 生成期间归档后不会新增 assistant message。

测试必须通过 Docker test-runtime 执行，重点先跑：

```bash
docker compose --profile test run --rm --build test uv run pytest \
  backend/tests/chat/test_tool_strategy.py \
  backend/tests/chat/test_tool_strategy_limit.py \
  backend/tests/chat/test_react_loop.py \
  backend/tests/chat/test_interview_mcp_tools.py \
  backend/tests/chat/test_mcp_session.py \
  -q
```

随后运行完整 `backend/tests/chat/`，并更新 `backend/app/agents/chat/CLAUDE.md`、`backend/app/mcp_server/CLAUDE.md`；如果没有新增 migration，不修改 DB migration 文档。

## 方案取舍

本阶段选择“执行入口硬化 + state/session 权威候选 + 原子写入检查”，而不是立即引入完整持久化 candidate set、turn 表和 OAuth。这样可以直接堵住已确认的越权路径，同时保留现有 SSE、ReAct state 和 SQLite 结构，为第二阶段回合事务改造留下清晰接口。
