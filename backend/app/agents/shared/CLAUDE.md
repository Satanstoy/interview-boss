# Shared — Agent 共享模块

submit、build、batch_generate 共用的状态定义、事件格式化、质量评估。chat agent 有独立 `backend/app/agents/chat/state.py`，但也复用 `events.py` 的 SSE 格式化和 `skills/` 的 Agent Skill 基建。

## 文件职责

| 文件 | 职责 |
|------|------|
| `state.py` | TypedDict 状态定义（SubmitState / BuildBankState / BatchGenerateState） |
| `events.py` | SSE 事件格式化（`format_sse`, `make_progress_event`, `make_error_event`, `make_done_event`） |
| `quality.py` | 分类质量评估（`evaluate_tagging_quality`）、重试决策（`should_retry`） |
| `skills/base.py` | 标准 Agent Skill 数据结构、registry、资源索引 |
| `skills/loader.py` | 读取标准 `SKILL.md`，校验 name/description，索引 `references/`、`scripts/`、`assets/` |
| `skills/resolver.py` | 按 agent 名称加载 `agents/<agent>/skills/<skill>/SKILL.md` |
| `skills/builder.py` | 生成 agent-agnostic lightweight catalog 与 active skill instruction prompt |

## 核心规则

- 新增非 chat 的 LangGraph agent 时，在 `state.py` 中定义对应 TypedDict；chat 状态继续放 `backend/app/agents/chat/state.py`
- SSE 事件必须通过 `format_sse()` 格式化，前端依赖此格式
- `_event_queue_var` 是 `asyncio.ContextVar`，每个请求独立
- Agent Skill package 必须是目录 + `SKILL.md`；`name` 必须等于父目录名，且只能使用小写字母、数字和单个连字符
- `SKILL.md` 顶层保持标准字段；InterviewBoss 私有策略放在 `metadata.interview-boss.*`，不要新增全局 `skill-pack.yaml`
- `skills/builder.py` 是 shared 基建，禁止 import `app.agents.chat.*`，禁止写入 `search_questions` / `draw_questions` 等 chat 专属工具策略；agent-specific catalog 文案必须放在对应 agent 的 `skills/builder.py`
- `references/`、`scripts/`、`assets/` 只索引不自动注入 prompt；读取资源必须通过 `Skill.read_resource()`，防止路径越界

## 修改后必做

1. 修改 `state.py` 后确认所有引用该状态的 agent 仍然兼容
2. 修改 `events.py` 后确认前端 SSE 解析逻辑兼容
3. 修改 `skills/` 后运行 `docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_chat_skills.py backend/tests/chat/test_skill_catalog.py backend/tests/chat/test_react_prompt.py -q`
4. 更新本文件
