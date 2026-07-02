# Spec: 模拟面试官质量修复 — 三个残留问题

> **位置**: `backend/app/agents/chat/`
> **类型**: 质量修复 spec
> **日期**: 2026-07-02
> **状态**: 待实施
> **来源**: Codex E2E 测试（12 个对话，280+ 条消息）分析

## 背景

基于 `sj` 账号中 12 个 Codex E2E 测试对话的详细审查，对比业界优秀 AI 面试官标准，识别出 3 个仍存在的质量问题。已修复的问题（next_focus 阶段追踪、面试结束后回复、情绪化表达、HR 问题覆盖）不在本 spec 范围内。

### 已确认的测试基线

| 对话 | 时间 | 候选人类型 | 机械化切换 | 重复容忍 | 情绪化 |
|------|------|-----------|-----------|---------|--------|
| 停止策略-分类修复后 | 7/2 03:19 | ✅ 正常 | **5 次** | 5 次 | 0 次 |
| coverage长程E2E | 7/2 04:14 | 重复 bot | 0 次 | **13 次** | 8 次 |
| 被动自然停止E2E | 7/2 01:58 | 重复 bot | 3 次 | **11 次** | 4 次 |

---

## 问题一：机械化话题切换

### 现象

面试官频繁输出 `"换个具体点的问题：{题目}"` 作为话题切换，例如：
```
"换个具体点的问题：MySQL相关（直接拷打穿了）"
"换个具体点的问题：混合检索怎么做的"
"换个具体点的问题：时序中一般如何做幂等控制的"
```

### 根因

**代码侧（主因）**：`answer.py:246-258` 的 `_format_bank_question_fallback()` 在 `style="plan"` 时硬编码前缀 `"换个具体点的问题："`. 当 `_enforce_question_plan_on_text()` 检测到 LLM 生成偏离 question_plan 且修复失败时，fallback 到此硬编码文案，**丢失了候选人上一个回答的上下文**，无法做自然承接。

调用链：
```
_enforce_question_plan_on_text()  (answer.py:147)
  → _repair_response_to_question_plan()  (nodes.py:585) — LLM 修复
  → 修复仍偏离
  → _format_bank_question_fallback(question_text, style="plan")  (answer.py:193)
  → 硬编码输出 "换个具体点的问题：{题目}"
```

**Skill 侧（次因）**：`<next_question_plan>` 标签注入了题目信息，但 prompt 中没有"出题过渡必须用候选人关键词承接"的规则。LLM 偏离 plan 后，后端兜底用硬编码文案。

### 修复方案：代码兜底 + Skill 引导

#### 代码改动

**文件**: `backend/app/agents/chat/answer.py`

1. **改造 `_format_bank_question_fallback()`**：增加 `last_user_answer` 参数，注入候选人上一个回答，用多样化模板池替代单一前缀。

```python
def _format_bank_question_fallback(
    question_text: str,
    *,
    style: str = "candidate",
    last_user_answer: str = "",
) -> str:
    question = (question_text or "").strip()
    if not question:
        return "我先追问你刚才提到的一个点。选一个你最熟的模块，把关键设计和你当时做的取舍讲清楚。"

    if style == "plan":
        # 从候选人回答中提取关键词做承接
        if last_user_answer:
            keywords = _extract_transition_keywords(last_user_answer)
            if keywords:
                templates = [
                    f"你刚才提到了{keywords[0]}，那{question}",
                    f"好，围绕{keywords[0]}，{question}",
                    f"接着你刚才说的——{question}",
                    f"换个角度——{question}",
                ]
            else:
                templates = [
                    f"好，我们聊另一个方向——{question}",
                    f"刚才说的先放一放，{question}",
                    f"换个角度——{question}",
                ]
        else:
            templates = [
                f"好，我们聊另一个方向——{question}",
                f"刚才说的先放一放，{question}",
                f"换个角度——{question}",
            ]
        import random
        return random.choice(templates)

    return f"顺着你刚才的回答，我问一个具体问题：{question}"
```

2. **新增 `_extract_transition_keywords()`**：从候选人回答中提取可用于承接的关键词。

```python
def _extract_transition_keywords(answer: str) -> list[str]:
    """从候选人回答中提取技术关键词，用于话题过渡承接。"""
    # 简单实现：提取中文技术术语（2-6字的词）
    import re
    # 常见技术关键词模式
    patterns = [
        r'(?:Redis|MySQL|Python|FastAPI|Docker|LangGraph|LLM|RAG|MCP|SSE|'
        r'向量|检索|缓存|索引|架构|设计|实现|部署|测试|监控)',
    ]
    keywords = []
    for pattern in patterns:
        matches = re.findall(pattern, answer)
        keywords.extend(matches[:3])
    return keywords[:2]
```

3. **修改 `_enforce_question_plan_on_text()`**：传递 `last_user_answer` 给 fallback。

```python
# answer.py:193 附近
fallback = _format_bank_question_fallback(
    str(plan.get("question_text") or ""),
    style="plan",
    last_user_answer=str(state.get("user_message") or ""),  # 新增
)
```

4. **修改 `_fallback_react_answer()`**：同样传递 `last_user_answer`。

```python
# answer.py:271 附近
return _format_bank_question_fallback(
    str(selected.get("question") or ""),
    last_user_answer=str(state.get("user_message") or ""),  # 新增
)
```

#### Skill 改动

**文件**: `backend/app/agents/chat/skills/interview-rhythm/SKILL.md`

在 Rules 部分新增：

```markdown
- **出题过渡**：出新题时，先从候选人上一个回答中找一个关键词或技术点做 1 句话承接，再自然引入新题目。禁止使用 "换个方向"、"换个问题"、"换个具体点的问题" 这类机械前缀。
```

**文件**: `backend/app/agents/chat/prompts.py`

在"提问风格（避免机械化）"部分，将现有规则：

```
- 切换话题时不要宣布"抽题"、"来聊八股"、"换个方向"这类流程话；真实面试里更像是自然进入下一个具体问题。
```

强化为：

```
- 切换话题时，必须先用候选人上一个回答中的具体技术点做 1 句话承接，再自然引入新题目。例如："你刚才提到了 Redis 做缓存，那 MySQL 的索引原理你了解吗？"
- 禁止使用 "换个方向"、"换个问题"、"换个具体点的问题"、"换个角度" 这类机械前缀。真实面试里没有这些话。
```

### 验证

- E2E 测试：运行 `verify_interview_agent_real_e2e.py`，检查 fallback 文案中不再出现 "换个具体点的问题"
- 手动测试：创建对话，故意让 LLM 偏离 question_plan，观察 fallback 文案是否自然

---

## 问题二：重复容忍次数过多（5-13 次）

### 现象

候选人重复同一段回答 5-13 次，面试官才采取行动。真实面试官 2-3 次就会换题或结束。

### 根因

**系统完全没有"候选人重复回答"的检测机制。**

- `_count_consecutive_similar_questions()`（`question_plan.py:647-703`）只检测 **assistant 消息**（面试官自己的追问），不检测 user 消息
- `stop_policy.py` 只根据 `message_count` 和 `coverage` 做决策，不检查候选人回答重复性
- `answer_complete` 是布尔值，只判断"完整/不完整"，不判断"是否重复"
- 候选人粘贴同一段回答 13 次，每次 `answer_complete=True`，系统继续走正常出题循环

### 修复方案：代码检测 + 代码门控 + Skill 回应策略

#### 代码改动

**文件**: `backend/app/agents/chat/question_plan.py`

1. **新增 `_count_consecutive_similar_user_answers()`**：检测候选人最近 N 条回答的 token overlap。

```python
def _count_consecutive_similar_user_answers(state: ChatState) -> int:
    """Count how many consecutive user messages are essentially the same answer.

    Uses the same _core_tokens overlap approach as
    _count_consecutive_similar_questions but on user messages,
    with a higher threshold (0.5) because candidate repetition
    is more clear-cut than interviewer topic similarity.
    """
    messages = state.get("message_history", []) or []
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if len(user_msgs) < 2:
        return 0

    recent = user_msgs[-6:]
    token_sets = [_core_tokens(m.get("content", "")) for m in recent]

    count = 0
    for i in range(len(token_sets) - 1, 0, -1):
        curr, prev = token_sets[i], token_sets[i - 1]
        if not curr or not prev:
            break
        intersection = curr & prev
        overlap = len(intersection) / max(min(len(curr), len(prev)), 1)
        if overlap >= 0.5:
            count += 1
        else:
            break
    return count
```

**文件**: `backend/app/agents/chat/stop_policy.py`

2. **在 `evaluate_interview_stop()` 中集成重复检测门控**。

```python
from app.agents.chat.question_plan import _count_consecutive_similar_user_answers

def evaluate_interview_stop(state: dict[str, Any]) -> dict[str, Any]:
    message_count = len(state.get("message_history") or [])
    coverage = _coverage_status(state)
    missing_phases = [...]
    all_covered = not missing_phases

    base = {...}

    # 新增：候选人重复回答检测（在所有现有逻辑之前）
    user_repeat_count = _count_consecutive_similar_user_answers(state)

    if user_repeat_count >= 5:
        return {
            **base,
            "action": "close",
            "mode": "forced_by_repetition",
            "reason": "candidate_repeated_answers_excessive",
        }

    if user_repeat_count >= 3 and not _last_assistant_asked_candidate_question(state):
        return {
            **base,
            "action": "ask_candidate_question",
            "mode": "degraded",
            "reason": "candidate_repeated_answers",
            "message": "我注意到你连续几次的回答内容比较相似。我们换个方向——你有什么想问我们的吗？",
        }

    # 现有逻辑继续...
    if message_count > HARD_STOP_MESSAGE_COUNT:
        ...
```

3. **新增重复回答计数注入 `_build_repetition_protection_note()` 扩展**。

在 `question_plan.py` 的 `_build_repetition_protection_note()` 中，同时检测候选人重复：

```python
def _build_repetition_protection_note(state: ChatState) -> str:
    # 现有：检测面试官追问重复
    count, topic_summary = _count_consecutive_similar_questions(state)

    # 新增：检测候选人回答重复
    user_repeat = _count_consecutive_similar_user_answers(state)
    if user_repeat >= 2:
        return (
            f"\n【系统提示】候选人已连续 {user_repeat} 次给出实质相同的回答。"
            "不要继续追问同一话题，直接切换到完全不同的面试方向（如从项目转算法），"
            "或者结束面试。\n"
        )

    if count < _MAX_CONSECUTIVE_SAME_QUESTION:
        return ""
    # 现有逻辑...
```

#### Skill 改动

**文件**: `backend/app/agents/chat/skills/interview-rhythm/SKILL.md`

在 Rules 部分新增：

```markdown
- **候选人重复回答**：如果候选人连续 2 次回答内容基本相同（不管你的问题是否不同），直接指出 "我注意到你的回答和刚才基本一样"，然后换一个完全不同的方向。不要在同一话题上继续追问。
```

### 验证

- 单元测试：`test_question_plan.py` 新增 `_count_consecutive_similar_user_answers` 测试用例
  - 连续 2 条相同 user 消息 → 返回 1
  - 连续 3 条相同 → 返回 2
  - 中间穿插不同消息 → 返回 0
- E2E 测试：运行 `verify_interview_agent_real_e2e.py`，用重复 bot 候选人验证面试在 5 轮内结束

---

## 问题三：答非所问应对策略单一

### 现象

面试官识别出答非所问后，唯一的应对策略是重复追问同一问题。例如：
- 问 "InterviewLedger 的下一步重点怎么算的？" → 候选人答 "Redis session 存储策略" → 面试官指出答非所问 → 候选人再答同一段 → **重复 4 次相同追问**

### 根因

**Skill 侧（主因）**：
- `prompts.py` 只对"回答过于简短"有升级策略，对"答非所问"没有
- `adaptive-difficulty` SKILL.md 的 "Bad answer" 定义不包含答非所问
- `interview-rhythm` SKILL.md 的 `clarification` 策略只覆盖短回答
- prompt 中 "至少做 1 轮追问再考虑切换话题" 反而鼓励继续追问

**代码侧（次因）**：
- `answer_complete` 是布尔值，无法区分"答了但答非所问"
- `_build_tool_strategy()` 没有连续追问次数的硬上限

### 修复方案：Skill 策略 + Code 硬上限

#### Skill 改动

**文件**: `backend/app/agents/chat/prompts.py`

1. **在"追问与挑战规则"部分新增答非所问升级策略**：

```python
## 答非所问处理（升级策略）
如果候选人的回答和你的问题明显不相关（你问 A，他答 B）：
1. 第 1 次：直接指出不相关（"你回答的是 X，我问的是 Y"），要求重新回答
2. 第 2 次：缩小问题范围或给一个具体提示，帮助候选人理解问题
3. 第 3 次：放弃这个问题，换一个完全不同的方向（如从项目转算法，或从八股转系统设计）
不要在同一道题上追问超过 3 次。如果候选人连续 3 次答非所问，说明他对这个领域不熟悉，继续追问没有价值。
```

2. **修改现有"追问与挑战规则"中的"至少做 1 轮追问"**：

将：
```
- 每次回答后，至少做 1 轮追问再考虑切换话题。追问的方式要多样化：质疑数据来源、要求对比方案、问失败案例、问边界条件。
```

改为：
```
- 每次回答后，至少做 1 轮追问再考虑切换话题（答非所问除外——答非所问时直接指出，不需要追问）。追问的方式要多样化：质疑数据来源、要求对比方案、问失败案例、问边界条件。
```

**文件**: `backend/app/agents/chat/skills/interview-rhythm/SKILL.md`

3. **扩展 `clarification` 策略的触发条件**：

将：
```yaml
clarification:
  trigger: "answer is short, incomplete, or ambiguous"
  retrieve: false
```

改为：
```yaml
clarification:
  trigger: "answer is short, incomplete, ambiguous, or off-topic (doesn't address the question asked)"
  retrieve: false
  escalation: "第1次指出不相关；第2次给提示；第3次换题"
```

**文件**: `backend/app/agents/chat/skills/adaptive-difficulty/SKILL.md`

4. **扩展 "Bad answer" 定义**：

将：
```
- **Bad answer** (vague, textbook-style, "I don't know") → de-escalate: give hints, narrow scope, switch topic
```

改为：
```
- **Bad answer** (vague, textbook-style, "I don't know", OR completely off-topic) → de-escalate: if off-topic, point it out directly first; if still off-topic after 1 attempt, switch topic immediately. Don't keep pressing the same question.
```

#### 代码改动

**文件**: `backend/app/agents/chat/nodes.py`

5. **在 `_build_tool_strategy()` 中增加连续追问硬上限**：

```python
def _build_tool_strategy(state: ChatState) -> str:
    ...
    intent = state.get("intent", "chat")
    answer_complete = state.get("answer_complete", False)
    has_retrieved = bool(state.get("retrieved_questions"))
    ...

    # 新增：连续追问同一话题次数检测
    from app.agents.chat.question_plan import _count_consecutive_similar_questions
    consecutive_same_topic, topic_summary = _count_consecutive_similar_questions(state)

    if consecutive_same_topic >= 3 and intent == "interview_question":
        return (
            "<tool_strategy>\n"
            "当前状态：你已连续多次追问同一话题，候选人未能有效回答。\n"
            "必须：切换到完全不同的面试方向（如从项目转算法，或从八股转系统设计），"
            "调用 draw_questions 换一个类型。\n"
            f"之前的话题：{topic_summary}。不要再围绕这个话题追问。\n"
            "禁止：继续围绕同一话题追问或检索。\n"
            "</tool_strategy>"
        )

    # 现有逻辑继续...
```

### 验证

- 单元测试：`test_interview_rhythm.py` 新增答非所问场景
  - 连续 3 次答非所问 → tool_strategy 强制切换
  - 中间穿插正常回答 → 计数器重置
- E2E 测试：用答非所问 bot 候选人验证面试官在 3 轮内切换话题

---

## 实施顺序

| 步骤 | 改动 | 文件 | 预计工作量 |
|------|------|------|-----------|
| 1 | 问题一：模板池 + 关键词提取 | `answer.py` | 小 |
| 2 | 问题一：Skill 出题过渡规则 | `interview-rhythm/SKILL.md` + `prompts.py` | 小 |
| 3 | 问题二：候选人重复检测函数 | `question_plan.py` | 小 |
| 4 | 问题二：stop_policy 门控 | `stop_policy.py` | 小 |
| 5 | 问题三：prompt 答非所问升级策略 | `prompts.py` + 两个 SKILL.md | 小 |
| 6 | 问题三：tool_strategy 连续追问硬上限 | `nodes.py` | 小 |
| 7 | 测试 | `test_question_plan.py` + `test_interview_rhythm.py` + E2E | 中 |

## 验收标准

1. **机械化切换**：fallback 文案中不再出现 "换个具体点的问题：" 前缀；多样化模板池 ≥ 4 种
2. **重复容忍**：候选人连续 3 次重复 → 面试官切换方向；连续 5 次 → 面试结束
3. **答非所问**：候选人连续 3 次答非所问 → tool_strategy 强制切换方向
4. **回归**：现有 `backend/tests/chat/` 全部通过
5. **E2E**：`verify_interview_agent_real_e2e.py` 4 个 case 全部 PASS
