# TDD 开发完成报告 — Chatbot 核心优化

**功能名称:** Pre-compaction 记忆刷盘 + 跨对话会话搜索
**完成日期:** 2026-05-23
**TDD 状态:** 完整

## 执行摘要

| 指标 | 结果 |
|------|------|
| 完成测试数 | 18 |
| TDD 循环数 | 2 |
| 最终测试通过率 | 100% (18/18) |
| 全量回归 | 55 passed, 6 skipped, 0 failed |

## 设计哲学来源分析

### 三大系统对比

| 维度 | Claude Code | OpenClaw | Hermes | InterviewBoss (优化后) |
|------|------------|---------|--------|----------------------|
| 压缩策略 | 5 层渐进级联 | ContextEngine 插件 | 两阶段 50%/85% | 5 级级联 + pre-compaction flush |
| 记忆持久化 | 文件即记忆 (CLAUDE.md) | Markdown 文件 + SQLite 索引 | 4 层 (hot→cold→skills→modeling) | DB 记忆 + session notes + flush |
| 记忆检索 | LLM 扫描选 5 个 | BM25 + 向量混合检索 | FTS5 会话搜索 | FTS 关键词搜索 + 跨对话搜索 |
| 跨会话记忆 | 自动提取到 memdir | 文件持久化 | session_search + Honcho | **新增: search_past_sessions** |
| 刷盘机制 | 后台 agent 提取 | pre-compaction flush | compression flush | **新增: flush_session_to_memories** |

### 采纳的核心模式

1. **OpenClaw: "Flush before discard"** — 在压缩丢弃信息前，先将 session notes 中的重要记忆（weakness/strength/topics）持久化到 memories 表。触发条件：利用率 ≥ 80% + 有 session notes。

2. **Hermes: "Session search as cold recall"** — 新面试开始时，用目标岗位关键词搜索历史对话，将相关面试经验注入上下文。这实现了 L2 冷记忆层。

## 实现的功能

### O-1: Pre-compaction 记忆刷盘

```
budget.compress() 触发
    ↓ 判断 utilization_pct ≥ 80%
    ↓ 有 session_notes？
    ↓ 调用 flush_session_to_memories(user_id, notes)
    ↓ 解析 [weakness]/[strength]/[topics] 标签
    ↓ 去重检查（不重复保存）
    ↓ 保存到 chat_memories 表
    ↓ 继续压缩流程
```

新增函数:
- `flush_needed(session_notes, utilization_pct) -> bool`
- `flush_session_to_memories(user_id, session_notes) -> int`

### O-2: 跨对话会话搜索

```
build_interview_context(user_id, conversation_id)
    ↓ 获取用户目标岗位
    ↓ search_past_sessions(user_id, [position], limit=2)
    ↓ 排除当前对话
    ↓ format_session_recall(results)
    ↓ 注入到 【历史面试经验】 section
```

新增函数:
- `search_past_sessions(user_id, keywords, limit, exclude_conv_id) -> list[dict]`
- `format_session_recall(sessions) -> str`

## 文件变更

| 文件 | 变更 |
|------|------|
| `services/chat_service.py` | +4 函数: flush_needed, flush_session_to_memories, search_past_sessions, format_session_recall |
| `agents/chat/budget.py` | compress() 增加 user_id 参数 + flush 调用 |
| `agents/chat/context_builder.py` | 增加 conversation_id 参数 + 历史搜索 section |
| `agents/chat/graph.py` | 传递 conversation_id 到 build_interview_context |
| `agents/chat/nodes.py` | 传递 user_id 到 budget.compress() |
| `tests/test_memory_flush.py` | **新建** 10 个测试 |
| `tests/test_session_search.py` | **新建** 8 个测试 |

## TDD 原则遵守情况

- [x] 测试先行：18 个测试先写，全部 ImportError
- [x] 红灯验证：确认 18 个测试全部失败
- [x] 最小实现：只写让测试通过的代码
- [x] 重构：集成到现有系统（budget + context_builder）
- [x] 回归通过：55 passed, 0 failed

## 后续优化方向（P1/P2）

| 优化 | 来源 | 优先级 |
|------|------|--------|
| LLM 智能记忆选择（用 LLM 从 N 条记忆中选最相关的 5 条） | Claude Code | P1 |
| 面试表现画像（自动分析用户弱点/强项趋势） | Hermes/Honcho | P2 |
| 向量 + 关键词混合检索 | OpenClaw | P2 |
