# TDD 开发计划

**功能名称:** Chat Agent Harness 上下文管理优化
**日期:** 2026-05-22
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

基于 Claude Code 设计哲学，优化 chat agent 的三个核心机制：统一预算管理、零成本压缩源、语义记忆召回。

## 验收标准

- [ ] TokenBudgetManager 能正确测量各 section 消耗并选择最低成本压缩等级
- [ ] 五级级联压缩在每级都能正确降级，零 LLM 成本路径优先
- [ ] Session notes 捕获所有记忆类型 + topics + asked questions
- [ ] LLM 语义召回替代 LIKE 匹配，每 turn 减少 1 次 LLM 调用
- [ ] 所有现有测试不回归

## 测试清单

### 优化 1: TokenBudgetManager (test_chat_budget.py)

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| B-001 | 短对话无需压缩 | 5 条消息, 2K chars | needs_compression=False | ⏳ |
| B-002 | 12K-24K 级联停在 snip | 15 条消息, 15K chars | tier="snip", 无 LLM 调用 | ⏳ |
| B-003 | >24K 用 session notes | 30 条消息, 25K chars + notes | tier="session_notes" | ⏳ |
| B-004 | >24K 无 notes 降级到 LLM | 30 条消息, 25K chars, 空 notes | tier="llm" | ⏳ |
| B-005 | 超长对话缩减 recent window | 50 条消息, 35K chars | keep_rounds 降至 3 或 2 | ⏳ |
| B-006 | 空消息列表 | [] | recent=[], tier="none" | ⏳ |
| B-007 | budget_snapshot 传入 state | 完整 pipeline | generate_response 收到 snapshot | ⏳ |

### 优化 2: Session Notes (test_chat_session_notes.py)

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| S-001 | 捕获所有记忆类型 | weakness + preference + strength | notes 包含全部三种 | ⏳ |
| S-002 | 捕获 topic 标签 | keywords=["Redis", "缓存"] | notes 包含 [topics] | ⏳ |
| S-003 | 捕获被问题目 | retrieved_questions=[...] | notes 包含 [asked] | ⏳ |
| S-004 | Tier 1 用 session notes | 15K chars + notes | compressed 包含 notes 文本 | ⏳ |
| S-005 | Tier 1 无 notes 回退到 snip | 15K chars, 空 notes | compressed 仅含 snip | ⏳ |
| S-006 | 预笔记在 classify 后插入 | keywords + interview intent | state["session_notes"] 含 [pending] | ⏳ |
| S-007 | 2000 字符上限 | 3K chars notes | 仅保留最新 2000 chars | ⏳ |

### 优化 3: LLM 语义召回 (test_chat_memory_recall.py)

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| M-001 | 正常召回 | 5 memories + interview msg | intent 有效, memory_ids 子集 | ⏳ |
| M-002 | LLM 失败降级 | Mock LLM 异常 | 规则 intent, 空 memory_ids | ⏳ |
| M-003 | 过滤无效 ID | LLM 返回 [999, 5], 仅 5 存在 | 返回 [5] | ⏳ |
| M-004 | 无记忆跳过召回 | 无 memories | intent only, memory_ids=[] | ⏳ |
| M-005 | 关键词提取 | 面试问题 about Redis | keywords 包含相关词 | ⏳ |
| M-006 | 闲聊返回空 | "你好" | intent="chat", keywords=[], ids=[] | ⏳ |
| M-007 | get_memories_by_ids 查询 | IDs [5, 7] | 返回完整内容 | ⏳ |
| M-008 | 集成: 面试路径仅 1 次 LLM | 完整 graph mock | generate_response 前恰好 1 次 LLM | ⏳ |

## 红-绿-重构循环计划

- [ ] 循环 1: Opt 1 B-001~B-007 (budget.py 红灯→绿灯→重构)
- [ ] 循环 2: Opt 3 M-001~M-008 (memory_recall_service.py 红灯→绿灯→重构)
- [ ] 循环 3: Opt 2 S-001~S-007 (session notes 红灯→绿灯→重构)
