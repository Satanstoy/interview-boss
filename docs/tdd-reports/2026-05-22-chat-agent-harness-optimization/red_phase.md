# 红灯阶段报告

**测试编号:** B-001~B-007, S-001~S-007, M-001~M-008
**测试描述:** Chat Agent Harness 优化 — 三个模块的 TDD 红灯测试
**编写时间:** 2026-05-22

## 编写的测试代码

### test_chat_budget.py (7 tests + 5 helper tests)
- B-001: measure() 短对话无需压缩
- B-002: 级联停在 snip 层（12K-24K）
- B-003: 用 session notes 替代（>24K + notes）
- B-004: 降级到 LLM（>24K 无 notes）
- B-005: 缩减 recent window（超长对话）
- B-006: 空消息列表
- B-007: budget_snapshot 传入 state

### test_chat_session_notes.py (7 tests)
- S-001: 捕获所有记忆类型
- S-002: 从 keywords 生成 topic 标签
- S-003: 记录被问到的题目
- S-004: Tier 1 用 session notes
- S-005: Tier 1 无 notes 回退
- S-006: 预笔记插入
- S-007: 2000 字符上限

### test_chat_memory_recall.py (8 tests)
- M-001: 正常召回返回有效 intent + IDs
- M-002: LLM 失败降级
- M-003: 过滤无效 ID
- M-004: 无记忆跳过召回
- M-005: 关键词提取
- M-006: 闲聊返回空
- M-007: get_memories_by_ids 查询
- M-008: 面试路径仅 1 次 LLM

## 预期失败原因

- [ ] `app.agents.chat.budget` 模块尚未编写（BudgetSnapshot, TokenBudgetManager）
- [ ] `app.services.memory_recall_service` 模块尚未编写（classify_and_recall）
- [ ] `nodes.py` 的 extract_memory 尚未增强

## 阶段状态
- [x] 测试代码已编写
- [ ] 测试运行失败（红色）← 等待确认
- [ ] 进入绿灯阶段
