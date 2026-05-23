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
| `nodes.py` | 节点实现（recall、build_context、stream、extract）、面试阶段判定 |
| `state.py` | ChatState TypedDict |
| `prompts.py` | 系统提示词（含面试阶段协议）、记忆提取提示词 |
| `context_builder.py` | 上下文拼接（记忆 + 简历 + JD + 历史消息） |
| `budget.py` | Token 预算管理（控制上下文长度） |

## 核心模式

- **流式输出**：通过 SSE yield 每个 chunk
- **记忆系统**：`chat_memories` 表存储用户长期记忆，每次对话自动召回
- **Token 预算**：`budget.py` 控制上下文窗口大小，优先保留最近消息
- **面试流程**：开场(自我介绍) → 提问(一次一题) → 收尾(反问)，由 `_determine_interview_phase()` 根据消息数自动切换
- **开场白**：创建对话时 `chat_service.generate_opening_message()` 自动生成，零 LLM 成本

## 修改后必做

1. 运行 `uv run pytest backend/tests/chat/ -q`
2. 更新本文件
