# 模拟面试 Agent 多轮 E2E 测试计划

## Context

当前面试 agent 系统已有单元级测试覆盖（`test_react_e2e.py` 的 6 个用例、`test_react_loop.py` 的 ReAct 循环测试、各模块独立测试），但缺少**多轮对话级**的系统性 E2E 测试。现有测试都是 mock 单次 LLM 调用验证事件流，无法验证：

- 10-15 轮面试的节奏控制和问题分布
- RAG 检索质量（混合搜索精度、加权随机抽取合理性）
- 自适应难度升降级的实际效果
- 面试阶段转换（开场→进行中→收尾→强制关闭）
- 多技能协同（interview-rhythm + adaptive-difficulty + 具体技能）
- 跨会话记忆和上下文压缩在长面试中的表现

**目标**：编写一套完整的多轮 E2E 测试，验证整个面试 agent 系统的质量、健壮性和一致性。

---

## 测试架构

### 基础设施

复用现有 `conftest.py` 的 `test_db`、`mock_llm`、`mock_redis`、`client` fixtures，新增一个 `multi_turn_runner` 辅助函数：

```python
async def run_multi_turn_interview(
    turns: list[TurnSpec],       # 每轮的用户输入 + 预期的 LLM 行为
    mode: str = "free_practice", # 或 "jd_resume"
    initial_context: dict = None, # 面试上下文（JD、简历等）
) -> InterviewResult:
    """
    多轮面试 runner：
    - 逐轮调用 run_chat()
    - 收集每轮的 SSE 事件序列
    - 追踪 state 变化（retrieved_questions, active_skills, basis 等）
    - 返回 InterviewResult 包含所有轮次的完整记录
    """
```

每个 `TurnSpec` 定义：
- `user_message`: 用户输入
- `classify_updates`: intent 分类结果
- `llm_responses`: 该轮 LLM 的多次调用响应（ReAct 步骤）
- `stream_chunks`: 最终流式输出
- `tool_patches`: 工具 mock（search/draw 结果）
- `expected_events`: 预期的 SSE 事件类型序列
- `expected_state`: 预期的 state 变化

### 文件结构

```
backend/tests/chat/
├── test_multi_turn_e2e.py           # 主测试文件
├── test_rag_quality.py              # RAG 检索质量测试
├── test_interview_rhythm.py         # 面试节奏测试
├── test_adaptive_difficulty.py      # 自适应难度测试
├── test_basis_tracking.py           # Basis 追踪测试
├── test_error_recovery.py           # 错误恢复测试
└── conftest_multi_turn.py           # 多轮测试专用 fixtures
```

---

## 测试维度与用例

### 维度 1：面试节奏控制（interview-rhythm）

**文件**：`test_interview_rhythm.py`

| # | 用例 | 验证点 | 优先级 |
|---|------|--------|--------|
| R1 | 完整面试流程（12 轮问答） | 问题数量 10-15，类型分布合理（项目≥50%、理论≥25%、算法≥15%），阶段转换正确 | P0 |
| R2 | 开场阶段行为（前 2 条消息） | intent 为 `interview_question`，phase="开场阶段"，直接从项目深挖开始 | P0 |
| R3 | 连续同类型上限 | 连续 3 个同类型问题后必须切换（通过 active_skills 和 tool_strategy 验证） | P0 |
| R4 | 项目深挖模式切换 | 2 个项目追问后，LLM 被引导切换到理论/算法（验证 tool_strategy 变化） | P1 |
| R5 | 面试结束检测 | 用户说"结束面试"时 intent 分类为 `end_interview` | P1 |

### 维度 2：强制关闭机制

**文件**：`test_interview_rhythm.py`（续）

| # | 用例 | 验证点 | 优先级 |
|---|------|--------|--------|
| FC1 | 44 条消息硬关闭 | message_history=44 时 `_forced_closing_response` 返回"你有什么想问我们的吗？"，不进入 ReAct 循环 | P0 |
| FC2 | 候选人反问后关闭 | 已问过"你有什么想问"且用户提了反问问题，返回通用收尾语 | P0 |
| FC3 | 33-44 条消息收尾建议 | phase="面试已进行较长时间"，LLM 被提示可以收尾 | P1 |

### 维度 3：RAG 检索质量

**文件**：`test_rag_quality.py`

| # | 用例 | 验证点 | 优先级 |
|---|------|--------|--------|
| RG1 | search_questions 关键词传递 | LLM 提取的 keywords 正确传给 hybrid_search，question_type 正确 | P0 |
| RG2 | search_questions 结果注入 | 检索结果正确存入 `retrieved_questions`，SSE `retrieved` 事件包含 top-3 | P0 |
| RG3 | draw_questions 加权抽取 | count、filters（cat1/cat2/topic/difficulty）正确传递，bank_mode 正确 | P0 |
| RG4 | 检索结果为空时降级 | search_questions 返回空 → LLM 收到空结果 → 可选择 draw_questions 补充 | P1 |
| RG5 | 已见题排除 | draw_questions 排除对话中已出现的 question IDs | P1 |
| RG6 | 多次检索不重复触发 | `has_retrieved=True` 时 tool_strategy 指示直接使用已有结果 | P1 |

### 维度 4：自适应难度（adaptive-difficulty）

**文件**：`test_adaptive_difficulty.py`

| # | 用例 | 验证点 | 优先级 |
|---|------|--------|--------|
| AD1 | 好回答→升级 | answer_complete=True + 长回答 → LLM 被引导提升难度（系统设计/工程权衡） | P0 |
| AD2 | 差回答→降级 | answer_complete=False + 短回答 → LLM 被引导降低难度（基础高频题） | P0 |
| AD3 | 中等回答→换角度 | answer_complete=True + 中等回答 → LLM 被引导换角度（同难度不同方向） | P1 |
| AD4 | 连续 3 难题上限 | 连续 3 个高难度问题后系统提示切换（通过 skill 指令验证） | P1 |

### 维度 5：Basis 追踪与验证

**文件**：`test_basis_tracking.py`

| # | 用例 | 验证点 | 优先级 |
|---|------|--------|--------|
| BS1 | 正常 basis 提取 | LLM 输出含 `[BASIS]{...}[/BASIS]` → 正确解析、验证、注入 SSE basis 事件 | P0 |
| BS2 | 非 retrieved ID 过滤 | basis 中的 question_ids 不在 retrieved 集合内 → 被过滤掉 | P0 |
| BS3 | 低 confidence 不展示 | confidence < 0.65 → `should_show_references=False` | P0 |
| BS4 | 无 basis 默认 conversation | LLM 不输出 BASIS 标记 → basis_type="conversation", 不展示引用 | P0 |
| BS5 | response-question 对齐过滤 | basis IDs 中与回复文本无 token 重叠的被丢弃 | P1 |
| BS6 | BASIS 标记从回复中清除 | 最终 response 和 SSE chunk 中不包含 `[BASIS]...[/BASIS]` 文本 | P0 |
| BS7 | coding 题 bare prompt 替换 | LLM 输出"来，写代码吧"(< 40 chars) → 替换为完整 LRU Cache 题目 | P1 |

### 维度 6：技能系统集成

**文件**：`test_multi_turn_e2e.py`

| # | 用例 | 验证点 | 优先级 |
|---|------|--------|--------|
| SK1 | load_skill → state 更新 | skill 加入 `active_skills`，instruction 加入 `active_skill_instructions` | P0 |
| SK2 | skill 指令注入 system prompt | 下一轮 ReAct 的 system prompt 包含 skill 指令内容 | P0 |
| SK3 | 多 skill 协同 | interview-rhythm (always_active) + algorithm-coding (trigger) 共存 | P1 |
| SK4 | HR 软技能触发 | 12+ 消息后用户提到"职业规划" → hr-soft-skills 加载 | P1 |
| SK5 | 内部标记泄露防护 | LLM 输出"project-deep-dive" → 被 `_is_internal_react_marker` 捕获并替换 | P0 |

### 维度 7：SSE 事件流正确性

**文件**：`test_multi_turn_e2e.py`（续）

| # | 用例 | 验证点 | 优先级 |
|---|------|--------|--------|
| SSE1 | 完整事件序列 | 每轮事件按 step→retrieved→chunk→basis→done 顺序 | P0 |
| SSE2 | insight 事件生成 | load_skill → "切换到XX模式"，search/draw → "检索到关于XX的题目" | P1 |
| SSE3 | thinking 事件支持 | DeepSeek reasoning_content / Anthropic ThinkingBlock → thinking_start/thinking/thinking_done | P1 |
| SSE4 | 错误事件 | LLM 调用失败 → error 事件 + fallback 回复 | P0 |

### 维度 8：错误恢复与 Fallback

**文件**：`test_error_recovery.py`

| # | 用例 | 验证点 | 优先级 |
|---|------|--------|--------|
| ER1 | 工具执行失败恢复 | search_questions 抛异常 → LLM 收到错误 → 直接回答 | P0 |
| ER2 | LLM 调用失败 fallback | ReAct 步骤中 LLM 抛异常 → 跳出循环 → fallback 回答 | P0 |
| ER3 | max_seconds 超时 | ReAct 循环超 30s → 使用候选题或关键词生成 fallback | P0 |
| ER4 | 循环检测 | 完全相同的 tool call 重复 → loop_detected → 停止 | P0 |
| ER5 | 无效工具调用 | tool name 不在 allowlist → tool_denied → 停止 | P1 |
| ER6 | final_answer 生成失败 | stream_llm_messages 失败 → fallback 回答 | P1 |

### 维度 9：JD/简历模式

**文件**：`test_multi_turn_e2e.py`（续）

| # | 用例 | 验证点 | 优先级 |
|---|------|--------|--------|
| JD1 | JD 模式 system prompt | mode="jd_resume" + jd_text → 使用 `INTERVIEW_SYSTEM_PROMPT_JD` 模板 | P0 |
| JD2 | JD 模式问题定制 | 问题围绕 JD 中的技术栈和岗位要求展开 | P1 |
| JD3 | 简历引用追踪 | LLM 引用简历内容时 basis_type="resume", resume_ref 事件 | P1 |

### 维度 10：上下文管理

**文件**：`test_multi_turn_e2e.py`（续）

| # | 用例 | 验证点 | 优先级 |
|---|------|--------|--------|
| CTX1 | 上下文压缩 | 长面试（20+ 轮）后 compressed_context 被注入 | P1 |
| CTX2 | 记忆召回 | 跨会话记忆在 system prompt 中作为"候选人相关记忆"出现 | P1 |
| CTX3 | session notes 积累 | 面试笔记在每轮 state 中正确传递 | P2 |

---

## 实施步骤

### Step 1：创建多轮测试基础设施
- 文件：`backend/tests/chat/conftest_multi_turn.py`
- 实现 `MultiTurnRunner` 类和 `TurnSpec` dataclass
- 实现 `InterviewResult` 收集器
- 复用现有 `_tool_call`、`_stream_chunks`、`_routerize_events` 辅助函数

### Step 2：实现 Basis 追踪测试（维度 5）
- 文件：`backend/tests/chat/test_basis_tracking.py`
- 最独立、最容易验证，作为测试基础设施的验证

### Step 3：实现 SSE 事件流测试（维度 7）
- 文件：嵌入 `test_multi_turn_e2e.py`
- 验证事件顺序、insight 生成、error 事件

### Step 4：实现面试节奏测试（维度 1-2）
- 文件：`backend/tests/chat/test_interview_rhythm.py`
- 12 轮完整面试、连续同类型检测、强制关闭

### Step 5：实现 RAG 质量测试（维度 3）
- 文件：`backend/tests/chat/test_rag_quality.py`
- 检索参数传递、结果注入、空结果降级

### Step 6：实现自适应难度测试（维度 4）
- 文件：`backend/tests/chat/test_adaptive_difficulty.py`
- 难度升降级、连续难题上限

### Step 7：实现错误恢复测试（维度 8）
- 文件：`backend/tests/chat/test_error_recovery.py`
- 工具失败、LLM 失败、超时、循环检测

### Step 8：实现技能集成和 JD 模式测试（维度 6, 9, 10）
- 文件：嵌入 `test_multi_turn_e2e.py`

### Step 9：运行全部测试，验证通过

---

## 验证方式

```bash
# 运行全部多轮 E2E 测试
docker compose exec backend pytest backend/tests/chat/test_multi_turn_e2e.py backend/tests/chat/test_rag_quality.py backend/tests/chat/test_interview_rhythm.py backend/tests/chat/test_adaptive_difficulty.py backend/tests/chat/test_basis_tracking.py backend/tests/chat/test_error_recovery.py -v

# 运行单个维度
docker compose exec backend pytest backend/tests/chat/test_basis_tracking.py -v
```

---

## 关键设计决策

1. **Mock 策略**：mock LLM 调用和工具执行，但保留真实 state 流转（pipeline → nodes → tools 的集成链路）。这比纯单元测试更接近真实行为，比真 LLM 调用更可控。

2. **多轮状态累积**：每轮的 state 变化会影响下一轮（retrieved_questions、active_skills、message_history 等）。MultiTurnRunner 需要维护跨轮的 state 累积。

3. **事件序列断言**：不只验证事件类型存在，还验证顺序和内容。使用 `_routerize_events` 镜像 router 的 SSE 转换逻辑。

4. **优先级策略**：P0 用例覆盖核心路径（节奏、RAG、basis、错误恢复），P1 覆盖边界和集成，P2 覆盖nice-to-have。
