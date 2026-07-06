# 模拟面试测试设计审查报告

**日期:** 2026-07-06
**问题:** 模拟面试测试基础设施存在多个设计层面的结构性缺陷
**严重程度:** Medium（不影响生产，但影响测试可信度和维护效率）

---

## 总体评价

**覆盖率：8/10** — 35+ 测试文件，覆盖了几乎所有纯函数和集成路径。
**设计合理性：6/10** — 存在几个结构性问题，导致部分测试"看起来通过了但实际上没测到"。

### 做得好的地方

1. **纯函数测试扎实** — `test_basis_parser.py`、`test_routing.py`、`test_output_dedup.py` 等对边界情况覆盖全面
2. **错误恢复测试完备** — `test_error_recovery.py` 覆盖了工具失败、LLM 失败、循环检测等场景
3. **Mock 策略合理** — 在服务边界 mock（`_hybrid_search_for_tool`、`llm_with_tools`），保留 ReAct 循环真实逻辑
4. **Envelope 模式测试充分** — 工具返回的标准化信封格式在 `test_tools.py` 和 `test_interview_mcp_tools.py` 中被充分验证
5. **评测框架设计周全** — 8 个场景矩阵、智能候选人、自动评分，架构设计合理

---

## BUG-001: Multi-turn 测试工具的状态隔离问题

- **位置:** `backend/tests/chat/multi_turn_helpers.py:194-286`
- **症状:** `run_multi_turn_interview()` 的每个 turn 都从空白状态开始
- **根因:** `mock_load_context()` 硬编码返回空 `message_history: []` 和 `recent_messages: []`
- **影响:** 跨 turn 行为（stop policy 触发、去重、coverage 推进、token 压缩）无法被真实测试
- **严重程度:** P2

### 详细分析

`run_single_turn()` 每次调用都创建全新的 mock 环境：

```python
async def mock_load_context(state):
    state.update({
        "message_history": [],      # ← 永远为空
        "recent_messages": [],      # ← 永远为空
        "compressed_context": None,
        "session_notes": "",
        ...
    })
```

这意味着：
- **Stop policy 测试**：`test_interview_stop_policy.py` 测试了 `evaluate_interview_stop()` 的纯函数逻辑，但无法验证"经过 16 轮对话后 stop policy 是否真的触发"
- **Output dedup 测试**：`test_output_dedup.py` 测试了 `OutputDeduplicator` 的单元逻辑，但无法验证"跨 20 轮对话后是否真的不再重复输出"
- **Coverage 推进**：无法验证"覆盖度从 warmup → project_followup → knowledge_probe 的真实推进"
- **Token 压缩**：`test_chat_budget.py` 测试了 `TokenBudgetManager` 的级联逻辑，但无法验证"30 轮对话后压缩是否真的生效"

### 为什么这不算 Critical

纯函数测试已经覆盖了每个组件的逻辑正确性。multi-turn 测试的目标是验证组件间的**集成行为**，而当前的 mock 策略让集成测试退化成了"多次独立的单元测试"。真正的跨 turn 集成需要依赖 `eval_interview_agent.py`（真实 HTTP/SSE）来验证。

---

## BUG-002: 评分引擎的关键词匹配过于脆弱

- **位置:** `backend/scripts/eval_interview_agent.py:111-121`
- **症状:** `_check_error_corrected()` 依赖硬编码中文关键词匹配
- **根因:** 没有使用语义匹配或正则表达式，纯字符串 `in` 检查
- **影响:** 误判率高 — 面试官可能用不同措辞纠正错误但被判定为"未纠正"
- **严重程度:** P3

### 详细分析

```python
def _check_error_corrected(metrics: dict, error_type: str) -> bool:
    correction_keywords = {
        "bert": ("encoder", "判别式", "不是生成式"),
        "faiss": ("不支持事务", "不支持ACID", "向量索引库"),
    }
    # 纯字符串包含检查
    return any(keyword in text for text in recent_assistant_texts for keyword in keywords)
```

问题：
- 面试官说 "BERT 属于 encoder 架构" → 不匹配 "encoder"（因为大小写和上下文）
- 面试官说 "Faiss 本身不具备事务特性" → 不匹配任何关键词
- 面试官说 "向量数据库不保证 ACID" → 匹配 "ACID"（但这是泛指，不一定是纠正 BERT 错误）

### 建议

至少改用正则表达式或增加更多同义词。理想方案是用 LLM 做语义判断（但会增加成本和延迟）。

---

## BUG-003: 评测场景缺少负面测试和压力测试

- **位置:** `backend/scripts/eval_interview_agent.py` SCENARIOS 矩阵
- **症状:** 8 个场景都是"正常路径"，缺少异常/边界场景
- **根因:** 设计时聚焦于"功能验证"，忽略了"破坏性测试"
- **影响:** 无法发现系统在极端条件下的退化行为
- **严重程度:** P2

### 缺失的场景

| 场景 | 测什么 | 为什么重要 |
|------|--------|-----------|
| `rapid_fire_short` | 候选人每轮只回 2-3 个字 | 面试官是否能处理极短回答 |
| `off_topic_loop` | 候选人连续 5 轮说完全无关内容 | off_topic_streak 是否真的触发话题切换 |
| `candidate_repetition` | 候选人连续 3 轮给出相同回答 | repetition_streak 检测和强制切换 |
| `very_long_answer` | 候选人每轮回复 2000+ 字 | token 预算管理、压缩触发 |
| `tool_failure_cascade` | 模拟连续 3 次工具调用失败 | fallback 链是否健壮 |
| `concurrent_skill_load` | 候选人同时请求多个 skill | skill 切换冲突处理 |

---

## BUG-004: test_chat.py 过于庞大，违反单一职责

- **位置:** `backend/tests/chat/test_chat.py`
- **症状:** 单个文件测试了 CRUD、FTS 搜索、路由、元数据持久化、推理追踪、完整面试流程
- **根因:** 历史累积，没有及时拆分
- **影响:** 维护困难，定位失败测试慢，文件超过 3000 行
- **严重程度:** P3

### 建议拆分

```
test_chat.py                    → 保留 chat_service CRUD
test_chat_metadata.py           → done event metadata、reasoning trace
test_chat_fts.py                → FTS5 搜索相关
test_chat_integration.py        → 完整面试流程集成
```

---

## BUG-005: SmartCandidateAgent 缺少上下文窗口管理

- **位置:** `backend/scripts/eval_interview_agent.py` SmartCandidateAgent
- **症状:** 候选人 agent 的 messages 列表无限增长
- **根因:** `respond()` 只 append 不 compress
- **影响:** 16-20 轮长程面试中，候选人可能超出 LLM context window
- **严重程度:** P2

### 详细分析

```python
async def respond(self, interviewer_message: str) -> str:
    self.messages.append({"role": "user", "content": interviewer_message})
    response = await llm_with_tools(messages=self.messages, ...)
    reply = response["content"]
    self.messages.append({"role": "assistant", "content": reply})
    return reply
```

MID_LEVEL_PERSONA 的 resume_text + ability_profile ≈ 500 tokens。每轮对话 ≈ 200-400 tokens。16 轮后总 tokens ≈ 500 + 16 × 400 = 6900 tokens。如果面试官追问详细，单轮可达 800+ tokens，16 轮 → 13300+ tokens。

对于 `mimo-v2.5` 模型，这可能接近或超出 context window。

### 建议

添加滑动窗口或摘要压缩：

```python
async def respond(self, interviewer_message: str) -> str:
    self.messages.append({"role": "user", "content": interviewer_message})
    if len(self.messages) > 20:  # 保留 system + 最近 18 条
        self.messages = [self.messages[0]] + self.messages[-18:]
    ...
```

---

## BUG-006: 覆盖度事件的端到端测试缺失

- **位置:** `backend/tests/chat/test_interview_stop_policy.py` 和 `test_react_loop.py`
- **症状:** coverage_events 的生成和消费分别被测试，但"生成 → 持久化 → 加载 → 影响 stop policy"的完整链路未被端到端验证
- **根因:** 测试边界恰好在 coverage_events 的"写入"和"读取"之间断开
- **影响:** 可能存在 coverage events 丢失但测试通过的情况
- **严重程度:** P3

### 详细路径

```
_react_loop() → _record_coverage_event() → DB 写入
                    ↓ (测试断点)
evaluate_interview_stop() → DB 读取 coverage_events → 决策
```

当前测试分别验证了两端，但没有验证 DB 中间层的完整性。

---

## BUG-007: 测试文件命名和分类不一致

- **位置:** `backend/tests/chat/` 目录
- **症状:** 部分测试文件前缀不一致，难以快速定位
- **根因:** 历史演进，不同时间点的命名风格不同
- **影响:** 新开发者难以找到正确的测试文件
- **严重程度:** P3

### 当前命名模式

| 模式 | 文件 | 数量 |
|------|------|------|
| `test_chat_*.py` | test_chat.py, test_chat_budget.py, ... | 9 |
| `test_interview_*.py` | test_interview_rhythm.py, test_interview_stop_policy.py, ... | 7 |
| `test_react_*.py` | test_react_loop.py, test_react_e2e.py, test_react_prompt.py | 3 |
| `test_*` (无前缀) | test_basis_parser.py, test_routing.py, test_tools.py, ... | 16 |

建议统一为：`test_chat_*`（pipeline 相关）、`test_interview_*`（面试行为相关）、`test_tool_*`（工具相关）、`test_util_*`（纯函数工具）。

---

## 评测框架设计评审（docs/superpowers/specs/2026-07-03-interview-eval-framework-design.md）

### 设计亮点

1. **8 场景矩阵**覆盖了长程回归、错误纠正、结束策略三大维度
2. **智能候选人**复用 Skill 基建，有层次化的回答策略
3. **评分引擎**权重化 + 自动报告输出
4. **独立脚本**不进 CI，手动触发，符合"消耗真实 tokens"的特性

### 设计问题

1. **缺少回归基线** — 没有"上次评测结果"的对比机制。每次运行后无法自动判断"变好了还是变差了"
2. **评分阈值硬编码** — `tool_call_rate >= 0.6`、`thinking_turns / turn_count >= 0.5` 等阈值没有数据支撑
3. **缺少延迟指标** — `latency_sec` 被收集但未进入评分。面试官响应时间是用户体验的关键指标
4. **候选人 Skill 未实现** — 设计了 6 个 Skill（candidate-rhythm、error-injection 等），但 `backend/app/agents/candidate/` 目录下没有实际的 SKILL.md 文件
5. **JD 模式的 jd_id 为 None** — `long_session_jd` 场景的 `extra_args: {"jd_id": None}` 需要运行时从 DB 选一个，但没有 fallback 策略

---

## 总结和优先级建议

| 优先级 | Bug | 建议 |
|--------|-----|------|
| **P2** | BUG-001: multi-turn 状态隔离 | 为关键跨 turn 测试添加"状态传递"模式的 `run_single_turn` 变体 |
| **P2** | BUG-003: 缺少负面/压力场景 | 补充 4-6 个异常场景到 SCENARIOS 矩阵 |
| **P2** | BUG-005: 候选人 agent 无上下文管理 | 添加滑动窗口或摘要压缩 |
| **P3** | BUG-002: 评分关键词脆弱 | 扩充同义词列表或改用正则 |
| **P3** | BUG-004: test_chat.py 过大 | 拆分为 4 个聚焦文件 |
| **P3** | BUG-006: coverage 端到端测试缺失 | 添加 coverage event 全链路集成测试 |
| **P3** | BUG-007: 命名不一致 | 统一命名规范 |

**总体结论：测试基础设施设计合理，覆盖率高，但存在"测试看起来通过了但实际上没测到跨 turn 行为"的结构性风险。** 核心纯函数和单元测试质量优秀，主要改进空间在集成测试的状态管理和评测框架的场景完备性。
