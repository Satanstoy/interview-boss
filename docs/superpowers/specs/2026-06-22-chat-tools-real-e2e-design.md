# Chat Tools Real E2E 验证脚本设计

日期：2026-06-22

## 背景

后端 chat tools 已完成 Tool Gateway、`selected_question` 计划绑定、adherence 校验与 repair。单元/集成聚焦测试已经覆盖实现逻辑，但还需要一个真实场景验证脚本，观察生产 Docker 后端 + 真实 LLM + SSE 下工具调用是否稳定。

## 目标

新增一个手动验证脚本：

```text
backend/scripts/verify_chat_tools_real_e2e.py
```

脚本通过真实 HTTP 接口调用：

1. 登录或使用已有 token。
2. 创建 chat conversation。
3. 发送多类真实用户消息。
4. 解析 SSE 事件。
5. 汇总工具调用、retrieved、selected_question、question_plan、repair/fallback、内部标记泄露等指标。
6. 输出可读报告，失败时返回非零 exit code。

## 非目标

- 不纳入 pytest 默认测试。
- 不 mock LLM。
- 不改业务逻辑。
- 不新增数据库迁移或 API。
- 不跑 Playwright。

## 运行方式

推荐：

```bash
RUN_REAL_CHAT_E2E=1 \
E2E_USERNAME=<username> \
E2E_PASSWORD=<password> \
docker compose exec backend uv run python backend/scripts/verify_chat_tools_real_e2e.py
```

可选：

```bash
--base-url http://localhost:8000
--turns 4
--model <model-name>
--keep-conversation
```

如果没有 `RUN_REAL_CHAT_E2E=1`，脚本拒绝运行，避免误触发真实 LLM 成本。

## 验证场景

### Case A: RAG 主动练习

用户：`我想练 RAG 系统设计，来一道题`

期望：触发 search/draw/retrieved 之一，并尽量有 selected_question 或 question_plan。

### Case B: 算法题

用户：`切到手撕代码，来一道中等难度的算法题`

期望：触发工具；如果有 selected_question，应与算法/代码/手撕相关。

### Case C: 完整回答后追新题

用户给出一段完整 RAG 项目回答。

期望：出新题时有工具调用或 selected_question；最终问题和 RAG/检索/重排/评估有一定重合。

### Case D: follow-up 负向测试

用户：`刚才那个问题能不能再解释一下？`

期望：不应强制 draw；不应出现硬绑定题目计划，或至少不应误判为新的随机抽题。

## 指标

每个 case 记录：

- `tool_called`
- `tool_names`
- `retrieved_count`
- `selected_question_id`
- `question_plan_id`
- `adherence_score`
- `repaired`
- `fallback_used`
- `internal_marker_leaked`
- `assistant_text_preview`
- `verdict`

总体记录：

- case 数
- pass/fail 数
- tool_call_rate
- selected_question_rate
- question_plan_rate
- repair_count
- fallback_count
- leak_count

## 判定规则

- 所有 case 必须收到 `done`，且不能有 SSE `error`。
- Case A/B/C 至少应满足：工具调用、retrieved、selected_question、question_plan 四者之一存在。
- Case B 如果存在 selected_question，应包含算法相关关键词。
- Case D 不应调用 `draw_questions`。
- 任意 case 发生内部标记泄露则失败。

## 安全与清理

- 登录凭据只从环境变量或命令行读取，禁止硬编码。
- 默认删除测试 conversation；传 `--keep-conversation` 才保留。
- 不直接修改题库或用户配置。
- 不打印 token/password。

## 文档更新

实现后更新：

- `backend/scripts/CLAUDE.md`
- `docs/dev-log/2026-06-22-chat-tools-real-e2e.md`
