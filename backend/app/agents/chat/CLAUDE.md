# Chat Agent — 面试 Chatbot

LangGraph 状态机：记忆召回 → 上下文构建 → LLM 流式回复 → 记忆提取。

## 流程

```
START → recall_memories → build_context → stream_reply → extract_memory → END
```

## 文件职责

| 文件 | 职责 |
|------|------|
| `graph.py` | StateGraph 定义、条件路由 |
| `nodes.py` | 节点实现（recall、build_context、stream、extract） |
| `state.py` | ChatState TypedDict |
| `prompts.py` | 系统提示词、记忆提取提示词 |
| `context_builder.py` | 上下文拼接（记忆 + 简历 + JD + 历史消息） |
| `budget.py` | Token 预算管理（控制上下文长度） |

## 核心模式

- **流式输出**：通过 SSE yield 每个 chunk
- **记忆系统**：`chat_memories` 表存储用户长期记忆，每次对话自动召回
- **Token 预算**：`budget.py` 控制上下文窗口大小，优先保留最近消息

## 修改后必做

1. 运行 `uv run pytest backend/tests/chat/ -q`
2. 更新本文件
