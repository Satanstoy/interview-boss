# TDD 开发计划 — Chatbot 核心优化（基于 Claude Code / OpenClaw / Hermes 设计哲学）

**日期:** 2026-05-23
**TDD 状态:** 需求分析完成，准备进入红灯阶段

---

## 一、三大系统设计哲学对比分析

### Claude Code — "渐进降级 + 可检查记忆"

| 设计理念 | 实现方式 | InterviewBoss 现状 |
|---------|---------|------------------|
| 5 层渐进压缩 | Budget→Snip→Microcompact→Context Collapse→Auto-Compact | ✅ 已有 5 级级联，但缺少"Context Collapse"（可逆读时投影） |
| 文件即记忆 | CLAUDE.md 纯文本，可检查/可编辑/可版本控制 | ✅ 记忆存 DB，结构化但不可用户编辑 |
| LLM 选记忆 | 用 Sonnet 扫描记忆文件头选最相关的 5 个，异步预取隐藏延迟 | ❌ 用规则+最近 3 条，无语义选择 |
| 异步提取 | 每轮对话后 fork 后台 agent 提取记忆 | ✅ 有 extract_memory，但是同步等待 |
| 上下文 = 运行时组装 | 每次 API 调用前动态组装 9 个来源 | ✅ 有 graph.py 动态组装 |

**核心洞察：** Claude Code 的记忆检索不用向量数据库，而是用 LLM 推理选择。对 20-100 条记忆的规模，LLM 的语义理解 > 向量相似度。延迟通过异步预取隐藏。

### OpenClaw — "刷盘先于丢弃 + 混合检索"

| 设计理念 | 实现方式 | InterviewBoss 现状 |
|---------|---------|------------------|
| Pre-compaction flush | 上下文溢出前，静默触发一轮 agent 写入持久记忆 | ❌ 压缩时直接丢弃/摘要，无刷盘机制 |
| 混合检索 | BM25 + 向量 = 加权并集（非交集） | ⚠️ 只有 FTS5 关键词检索 |
| ContextEngine 插件化 | 4 个生命周期点：ingest→assemble→compact→after-turn | ⚠️ 硬编码，但流程相似 |
| 文件即真相 | Markdown 文件是源，SQLite 索引是派生 | ✅ DB 是源，FTS5 是索引 |

**核心洞察：** "flush before discard" 是最重要的不变量。在上下文压缩触发前，先让模型把重要信息写入持久存储。这保证了信息不会在压缩中丢失。

### Hermes — "分层缓存 + 冻结快照"

| 设计理念 | 实现方式 | InterviewBoss 现状 |
|---------|---------|------------------|
| 4 层记忆层次 | L1 热提示 → L2 会话搜索 → L3 技能 → L4 用户建模 | ⚠️ 只有 L1（memory_summaries 注入 prompt） |
| 冻结快照 | 会话开始时冻结系统 prompt，中途写入不改变当前 prompt | ❌ 每轮重建 prompt |
| FTS5 会话搜索 | 跨历史对话搜索，LLM 总结结果 | ❌ 无跨对话搜索能力 |
| 两阶段压缩 | 50% 预检 + 85% 激进压缩 | ⚠️ 有阈值但只有一级触发 |
| Honcho 辩证推理 | 多轮 LLM 推理用户偏好/模式/目标 | ❌ 无用户建模 |

**核心洞察：** 记忆是分层缓存层次结构。系统 prompt 是 L1（保护到底），SQLite + FTS5 是 L2/L3（按需检索）。不要把所有东西塞进一个存储。

---

## 二、优化方案评估（影响 vs 工作量）

| # | 优化项 | 来源 | 影响 | 工作量 | 优先级 |
|---|--------|------|------|--------|--------|
| O-1 | **Pre-compaction 记忆刷盘** | OpenClaw | 🔴 高 — 防止压缩丢失关键面试信息 | 中 | **P0** |
| O-2 | **跨对话会话搜索** | Hermes | 🔴 高 — "上次面试的问题"回忆 | 中 | **P0** |
| O-3 | **LLM 智能记忆选择** | Claude Code | 🟡 中 — 更精准的记忆召回 | 小 | **P1** |
| O-4 | **面试表现画像** | Hermes/Honcho | 🟡 中 — 深度用户建模 | 大 | P2 |

**P0 优先实施：O-1 + O-2**，这两个功能相互独立，可以并行 TDD。

---

## 三、TDD 测试清单

### O-1: Pre-compaction 记忆刷盘

核心思想：在压缩触发前，检测是否有重要信息需要先持久化（session notes 已有但未保存的记忆、关键面试话题等）。

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-101 | flush_needed 在高利用率时返回 True | budget_snapshot.utilization_pct > 80 | True | ⏳ 待写 |
| T-102 | flush_needed 在低利用率时返回 False | budget_snapshot.utilization_pct < 50 | False | ⏳ 待写 |
| T-103 | flush_needed 无 session notes 时返回 False | 空 session_notes, 高利用率 | False | ⏳ 待写 |
| T-104 | flush_to_memories 从 session notes 提取并保存 | session_notes 含 [weakness]/[strength] 标签 | memories 表新增记录 | ⏳ 待写 |
| T-105 | flush_to_memories 幂等性 | 重复 flush 相同 notes | 不重复保存 | ⏳ 待写 |
| T-106 | 集成：summarize_context 触发 flush | 高利用率 + 有 session notes | notes 提取到 memories + 压缩继续 | ⏳ 待写 |

### O-2: 跨对话会话搜索

核心思想：用户开始新面试时，自动搜索历史对话，提取相关面试经验注入上下文。

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-201 | search_past_sessions 按用户+关键词搜索 | user_id + "Redis" | 返回包含 Redis 的历史对话摘要 | ⏳ 待写 |
| T-202 | search_past_sessions 无结果时返回空 | 搜索不存在的话题 | [] | ⏳ 待写 |
| T-203 | search_past_sessions 限制结果数 | limit=3 | 最多 3 条结果 | ⏳ 待写 |
| T-204 | format_session_recall 格式化输出 | 搜索结果列表 | 可读的上下文字符串 | ⏳ 待写 |
| T-205 | 空结果时 format 返回空字符串 | [] | "" | ⏳ 待写 |
| T-206 | 集成：build_interview_context 包含历史搜索 | user_id + 有历史对话 | context 包含历史面试信息 | ⏳ 待写 |

---

## 四、实现文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/services/chat_service.py` | 修改 | 新增 `search_past_sessions()` + `flush_session_to_memories()` |
| `backend/app/agents/chat/budget.py` | 修改 | `compress()` 中添加 flush 调用 |
| `backend/app/agents/chat/context_builder.py` | 修改 | `build_interview_context()` 包含历史搜索 |
| `backend/tests/test_memory_flush.py` | **新建** | TDD 测试 O-1 |
| `backend/tests/test_session_search.py` | **新建** | TDD 测试 O-2 |

---

## 五、红-绿-重构循环计划

- [ ] 循环 1: T-101 ~ T-103 — flush_needed 判断逻辑
- [ ] 循环 2: T-104 ~ T-105 — flush_to_memories 实现
- [ ] 循环 3: T-106 — 集成到 summarize_context
- [ ] 循环 4: T-201 ~ T-203 — search_past_sessions 实现
- [ ] 循环 5: T-204 ~ T-205 — format_session_recall
- [ ] 循环 6: T-206 — 集成到 context_builder
