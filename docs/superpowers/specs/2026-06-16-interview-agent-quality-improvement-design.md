# Interview Agent Quality Improvement Design

**Date**: 2026-06-16
**Status**: Approved for implementation
**Scope**: Phase 1 (core bug fixes) + Phase 2 (interview behavior enhancement)

## Background

User conducted two mock interviews with the InterviewBoss interview agent and identified 11 behavioral problems. Root cause analysis found 17 code-level issues across system prompt, pipeline logic, context management, and question retrieval. Research was conducted across 20+ industry sources (Friday, Hermes, agent-interviewer, Cognix-AI, Intervu.dev, LangChain, Mem0, multiple arxiv papers) to inform the solution design.

Additional deep research was conducted on 5 top agent harnesses (Claude Code, OpenAI Codex, OpenCode, Hermes, OpenClaw) to identify proven mechanisms for each bug category. Key borrowings:
- **Hermes**: Structured 7-dimension compression template, iterative summary updates, tool output pre-pruning, "remove intermediate pressure warnings"
- **Claude Code**: System reminder pipeline (per-turn injection), write-before-compaction, 5-tier cascade
- **Codex**: Ghost snapshots before compaction, "if a rule matters, it belongs in base_instructions"
- **OpenCode ACP**: Hash-based exact dedup, progressive disclosure pattern

**Decision**: Continue with the hand-crafted ReAct loop (not migrate to LangGraph). All identified problems are prompt design + routing logic + context management issues, not orchestration framework issues.

## Design Principles

1. **Soft guidance over hard constraints** — Control behavior via system prompt, not code-level if/else forced intercepts. Keep budget controls and loop detection as safety nets.
2. **No information loss** — Persist critical info (asked questions, candidate weaknesses) before context compression; restore via injection after.
3. **Minimal invasion** — Modify existing architecture, no framework migration, no pipeline restructuring.

---

## Block 1: System Prompt Overhaul (5 fixes)

### 1a. Clean LRU Example Pollution

**Problem**: LRU Cache appears in 6 layers of the system prompt, creating strong statistical bias toward selecting it repeatedly.

**Files**:
- `backend/app/agents/chat/prompts.py` lines 20, 81
- `backend/app/agents/chat/skills/algorithm-coding/SKILL.md` lines 3, 4, 8, 9, 33
- `backend/app/agents/chat/tools.py` line 172
- `backend/app/services/memory_recall_service.py` lines 70, 440, 456

**Changes**:
- `prompts.py`: Replace `（LRU Cache、TopK、排序、图遍历等）` with `（如 TopK、LRU Cache、排序、链表操作、二分查找等，每次随机选取，不要重复出同一道题）`
- `SKILL.md`: Change `preferred_topics` from fixed list to "randomly select from algorithm_coding question bank"; remove LRU as first item; update examples
- `tools.py`: Change draw_questions example from LRU to `如 TopK、二分查找、链表反转`
- `memory_recall_service.py`: Replace LRU examples with diverse alternatives
- Keep `fts_service.py:30` expansion map (legitimate search expansion, not bias source)

### 1b. Add "Challenge Vague Answers" Rules

**Problem**: Interviewer never challenges candidates, accepts "textbook-like" answers without questioning data sources or real-world experience.

**File**: `backend/app/agents/chat/prompts.py`

**Add to system prompt**:
```
## 追问与挑战规则（重要）
- 当候选人回答过于笼统或像在背书时（如给出精确百分比但没有解释来源、
  用四段式"原理→优点→缺点→场景"模板回答），你必须追问：
  - "这个数据是怎么测的？测试集多大？"
  - "你说提升了 X%，对比的 baseline 是什么？"
  - "你提到的这个方案，实际跑过生产环境吗？遇到过什么问题？"
- 当候选人给出完整但缺乏深度的回答时，选择一个具体细节深入追问，
  而不是直接切到下一个话题。
- 每次回答后，至少做 1 轮追问再考虑切换话题。追问的方式要多样化：
  - 质疑数据来源
  - 要求对比方案
  - 问失败案例
  - 问边界条件
```

**References**: Hermes ("Follow-up depth — probe 'why X over Y?'"), CallSphere ("Push back on vague statements"), AI Tools Guidebook ("Every vague claim must trigger a follow-up")

### 1c. Add "Handle Candidate Counter-Questions" Rules

**Problem**: When the candidate asks the interviewer a question mid-interview, the agent either ignores it or responds with "你不用回答我的问题".

**File**: `backend/app/agents/chat/prompts.py`

**Add to system prompt**:
```
## 候选人反问处理
- 候选人中途向你提问是正常的（如"您觉得这个思路在实际业务里好落地吗？"）
- 处理方式：用 1-2 句话简短回应，然后自然地引回面试主题
- 示例回应：
  - "这个思路方向是对的，不过我们更看重 X。回到你刚才的方案..."
  - "实际落地的话确实会有 Y 的挑战。好，我们接着聊下一个方向..."
- 不要拒绝回答，不要说"你不用回答我的问题"
```

**References**: agent-interviewer ("No grading during the interview — if asked, defer"), Hermes ("Calibrated probing")

### 1d. Inject "Previously Asked Questions" Section (Per-Turn Dynamic Injection)

**Problem**: LLM doesn't know what questions were already asked, leading to repeated selection of the same topic (especially LRU Cache).

**File**: `backend/app/agents/chat/pipeline.py` (`_react_loop`, message assembly section)

**Key design decision** (borrowed from Hermes + Claude Code): The `PREVIOUSLY ASKED` section is **NOT** baked into the cached system prompt. Instead, it is **dynamically generated and injected as a user message before each LLM call**. This ensures it survives context compression — even if the system prompt is rebuilt or old messages are summarized away, the asked-question list is regenerated fresh every turn.

**Implementation**: In `_react_loop`, after building messages and before appending the current user message:
```python
# Inject PREVIOUSLY ASKED as dynamic user message (not in cached system prompt)
asked_section = _build_previously_asked_section(state)
if asked_section:
    messages.append({"role": "user", "content": asked_section})
```

**Content format**:
```
[面试状态 - 由系统自动生成]
## 本轮已问过的题目（禁止重复）
1. [B.Agent与LLM应用] Agentic RAG 和传统 RAG 的区别
2. [E.算法与数据结构] 手撕：LRU Cache
3. [B.Agent与LLM应用] OpenAI 提出的 Agent 新范式

规则：不要再出以上题目或类似题目的变体。每次出题必须是新的知识点方向。
```

**References**: Hermes ("ephemeral instructions injected at API-call time, not baked into cached string"), Claude Code system reminder pipeline (per-turn re-injection), Medium Mock Interview Platform (`=== PREVIOUSLY ASKED QUESTIONS ===`)

### 1e. Diversify Question Phrasing

**Problem**: Interviewer repeatedly uses the same template "我们先收束到一道具体题：XXX，直接说核心思路、关键取舍，以及你会怎么验证这个方案".

**File**: `backend/app/agents/chat/prompts.py`

**Add to system prompt**:
```
## 提问风格（避免机械化）
- 不要每次都用相同的话术模板切换话题
- 提问方式要多样化，例如：
  - "你了解过 XXX 吗？说说你的理解"
  - "换个方向，你对 XXX 怎么看？"
  - "好，这个聊得差不多了。来写一道代码题 / 来聊一个八股题"
  - 直接抛出问题，不加过渡（真实面试官经常这样）
- 禁止连续 2 次使用完全相同的话题切换句式
```

---

## Block 2: Pipeline Logic Changes (2 fixes)

### 2a. Remove LRU Hardcoded Fallback

**Problem**: `_fallback_coding_question()` hardcodes LRU Cache as the default coding question.

**File**: `backend/app/agents/chat/pipeline.py` lines 292-318

**Change**: Replace hardcoded LRU text with:
1. First try to find a coding question from `candidate_questions`/`retrieved_questions`
2. If none found, return a generic prompt that lets the LLM choose based on context:

```python
def _fallback_coding_question(state: ChatState) -> str:
    candidates = (
        state.get("candidate_questions") or state.get("retrieved_questions") or []
    )
    coding_candidate = None
    for q in candidates:
        haystack = " ".join(
            str(q.get(k) or "") for k in ("question", "cat1", "cat2", "tags")
        )
        if re.search(
            r"(算法|代码|手撕|数据结构|链表|排序|二分)", haystack, re.I
        ):
            coding_candidate = q
            break
    if coding_candidate:
        state["question_source"] = "bank"
        state["question_source_reason"] = "fallback_from_bank"
        return f"来写一道代码题：{coding_candidate.get('question', '')}\n\n"
    
    state["question_source"] = state.get("question_source") or "generated"
    state["question_source_reason"] = "fallback_generated_coding_question"
    return (
        "好，来写一道代码题。请根据候选人的技术栈和之前的面试内容，"
        "选择一道合适的手撕题（不要重复之前问过的方向）。"
        "要求候选人写代码并说明设计思路。"
    )
```

### 2b. Remove Forced Tool-Call Interceptor

**Problem**: `_requires_tool_calls()` injects "【系统强制提醒】" forcing the LLM to call tools, killing natural conversation flow.

**Files**:
- `backend/app/agents/chat/pipeline.py` lines 105-120 (function definition)
- `backend/app/agents/chat/pipeline.py` lines 1236-1261 (forced retry logic)

**Changes**:
1. Delete `_requires_tool_calls()` function
2. Delete the forced retry logic block in `_react_loop`
3. Add soft guidance in system prompt (covered in Block 1, plus the tool calling guidance below)

**New system prompt section**:
```
## 什么时候调用工具检索题目
- 候选人回答完毕，你准备切换到下一个话题时 → 调用 search_questions 或 draw_questions
- 候选人提到了某个技术关键词，你想围绕这个方向出题时 → search_questions
- 你要出一道手撕代码题时 → draw_questions(question_type="algorithm_coding")
- 候选人自我介绍完毕，准备进入正式面试时 → draw_questions 抽第一批题

## 什么时候不需要调工具
- 你正在对候选人的回答做深入追问 → 直接回复，不需要搜题
- 候选人反问你问题 → 简短回应，不需要搜题
- 候选人回答明显不完整，你还要继续追问细节 → 先追问，下一轮再搜题
```

**Safety nets preserved** (no changes):
- Budget controls: `max_steps`, `max_tool_calls`, `max_seconds`
- Loop detection: `seen_tool_calls`
- Tool allowlist: `validate_tool_call`

**Staleness guard**: If the LLM goes 3+ consecutive turns without calling tools AND without a follow-up pattern, inject a soft reminder into session notes: "⚠️ 你已经连续多轮没有出新题，请考虑切换考察方向。"

---

## Block 3: Context Management Fixes (3 fixes)

### 3a. Fix Empty `memory_context`

**Problem**: `build_react_system_prompt()` hardcodes `memory_context=""`, losing candidate background info.

**File**: `backend/app/agents/chat/nodes.py` lines 1720-1724

**Change**: Extract user background from state and populate:
```python
memory_parts = []
if state.get("user_resume_summary"):
    memory_parts.append(f"候选人背景：{state['user_resume_summary']}")
if state.get("weaknesses"):
    memory_parts.append(f"薄弱环节：{', '.join(state['weaknesses'])}")
if state.get("strengths"):
    memory_parts.append(f"擅长领域：{', '.join(state['strengths'])}")

memory_context = "\n".join(memory_parts) if memory_parts else "暂无历史记录"
```

### 3b. Improve Compressed Context Labeling

**Problem**: Compressed context injected as `role: "user"` could be mistaken for actual candidate speech.

**File**: `backend/app/agents/chat/pipeline.py` lines 1177-1179

**Change**: Add clearer labeling:
```python
if compressed:
    messages.append({
        "role": "user",
        "content": f"[以下是更早对话的压缩摘要，由系统生成，不是候选人的话]\n{compressed}"
    })
```

**Rationale**: Industry consensus (Andrew Zhu, Jatin Bansal, OpenAI Codex) is that compressed context should remain as `user` role (correct current behavior), but with clear labeling to prevent role confusion.

### 3c. Bookend Pattern for Context Placement

**Problem**: Critical info placed in the "dead zone" (middle third of context) gets ignored by LLMs.

**File**: `backend/app/agents/chat/pipeline.py` lines 1173-1188

**Current structure** (already largely correct):
1. System prompt (top = high attention)
2. Compressed context (after system prompt = high attention)
3. Recent messages (middle = lower attention on older messages)
4. Current user message (bottom = high attention)

**Change**: Minimal — the current structure already follows the bookend pattern. Only improve the labeling per 3b.

**Reference**: EngineersOfAI ("place the most task-critical information at the top of the system prompt or at the bottom of the message history"), Liu et al. 2023 ("accuracy drops from ~95% at start to ~60% in middle")

### 3d. Tool Output Pre-Pruning (NEW — from Hermes + Claude Code)

**Problem**: Large tool outputs (especially `search_questions` returning 15+ results) consume significant context budget and get summarized away anyway during compression.

**File**: `backend/app/agents/chat/pipeline.py` (`_react_loop`, after tool execution)

**Change**: Before appending tool results to messages, apply cheap pre-pruning:
- `search_questions` / `draw_questions` results: keep only top 3 (already returned to LLM in tool output), replace full `state["retrieved_questions"]` with trimmed version for context
- Tool call arguments: use sanitized version (already have `_sanitize_tool_args`) for older messages
- After a tool result has been followed by 5+ subsequent messages, replace its content with a 1-line summary: `[search_questions: 检索到 3 个关于 B.Agent与LLM应用 的题目]`

**Rationale** (Hermes): "Prune old tool results (cheap, no LLM call)" is Phase 1 of the 4-phase compression algorithm, running before any LLM summarization. This reduces the input to the expensive Phase 4 (LLM summary) by 30-50%.

**References**: Hermes ContextCompressor Phase 1 (tool output pruning), Claude Code MicroCompact (clear old tool results based on time/count)

### 4a. Replace Hardcoded Summary with LLM-Generated Feedback

**Problem**: `_generate_end_interview_response()` returns identical text regardless of actual interview performance.

**File**: `backend/app/agents/chat/pipeline.py` lines 488-521

**Changes**:

1. Define Pydantic schema for structured output:
```python
class InterviewSummary(BaseModel):
    overall_comment: str       # 2-3 sentences, based on actual dialogue
    strongest_topic: str       # Best performed topic + specific reason
    weakest_topic: str         # Weakest topic + specific evidence
    key_suggestions: list[str] # 3 actionable suggestions
    score_estimate: int        # 1-10 overall estimate
```

2. Collect data from state: session notes, message history, memory summaries

3. Call LLM with structured prompt:
```
你是一个面试复盘教练。基于以下面试记录，给出一份结构化的面试反馈。

要求：
- 评价必须基于候选人实际说了什么，不要用泛泛的套话
- 最弱的话题要给出具体的"答不上来"或"答得浅"的证据
- 建议要具体可操作（如"建议复习 LangGraph 的条件路由机制"），
  不要给空泛建议（如"继续深度学习"）
- 整体评价要诚实，好的夸、差的指出
```

4. Render as markdown for the user

5. Fallback: If LLM call fails, use a slightly improved generic summary that at least mentions how many topics were covered

6. Trigger conditions:
   - User says "结束面试"/"生成总结" → generate structured summary
   - Forced closing at >44 messages → also generate structured summary (not generic farewell)

**References**: agent-interviewer (separate Feedback agent + Pydantic schema), Intervu.dev (separate judge model), Friday (Coach agent generates final report)

---

## Block 5: Question Deduplication & Quota (2 fixes)

### 5a. Per-Competency Quota

**Problem**: Frequency-weighted sampling causes popular questions to dominate; no per-topic limit.

**File**: `backend/app/services/question_draw_service.py`

**Change**: Add quota constraint to sampling:
```python
def _draw_with_quota(state: ChatState, candidates: list,
                     max_per_category: int = 2) -> list:
    """Limit each cat2 category to max_per_category questions per interview."""
    asked_categories = _count_asked_categories(state)  # from session notes
    filtered = []
    for q in candidates:
        cat = q.get("cat2", "unknown")
        if asked_categories.get(cat, 0) < max_per_category:
            filtered.append(q)
    return filtered or candidates  # fallback to original if all exceeded
```

**Effect**: After asking 1 LRU Cache (cat2: "E1.数据结构"), same category limited to 1 more, then forced to switch.

**Reference**: Friday ("Per-competency question budget prevents any single topic from dominating")

### 5b. Output-Level Repetition Detection (Hash + Jaccard Two-Level Dedup)

**Problem**: No protection against the interviewer repeating itself; if LLM loops, identical content is streamed to user.

**File**: `backend/app/agents/chat/pipeline.py`

**Design** (borrowed from OpenCode ACP hash-based dedup + Manneri Jaccard): Two-level detection:
- **Level 1: Hash exact match** — normalize text, MD5 hash, check against ring buffer. Zero cost, catches exact duplicates.
- **Level 2: Jaccard fuzzy match** — token overlap ≥0.7. Catches near-duplicates.

**Change**: Replace the original single-level Jaccard approach:

```python
import hashlib

class OutputDeduplicator:
    def __init__(self, window_size: int = 8, jaccard_threshold: float = 0.7):
        self.hash_buffer: set[str] = set()
        self.token_buffer: list[set[str]] = []
        self.window_size = window_size
        self.jaccard_threshold = jaccard_threshold

    def check(self, text: str) -> str:
        """Return 'exact' | 'similar' | 'ok'"""
        normalized = re.sub(r'\s+', ' ', text.strip().lower())
        # Level 1: Hash exact match
        h = hashlib.md5(normalized.encode()).hexdigest()
        if h in self.hash_buffer:
            return "exact"
        # Level 2: Jaccard fuzzy match
        tokens = set(normalized.split())
        if len(tokens) >= 5:
            for prev in self.token_buffer:
                union = tokens | prev
                if not union:
                    continue
                jaccard = len(tokens & prev) / len(union)
                if jaccard >= self.jaccard_threshold:
                    return "similar"
        return "ok"

    def record(self, text: str):
        normalized = re.sub(r'\s+', ' ', text.strip().lower())
        self.hash_buffer.add(hashlib.md5(normalized.encode()).hexdigest())
        tokens = set(normalized.split())
        self.token_buffer.append(tokens)
        if len(self.token_buffer) > self.window_size:
            self.token_buffer.pop(0)
```

**Integration point**: Before streaming final answer in `_react_loop`:
- `exact` → inject system note: "你刚才的回答和之前的完全相同，请换一个角度或切换话题" + regenerate once
- `similar` → inject system note: "你刚才的回答和之前的高度相似，请用不同的话术" + regenerate once
- `ok` → normal output, record for future checks
- Store `OutputDeduplicator` instance in `state["output_deduplicator"]` for session persistence

**References**: OpenCode ACP (hash-based dedup for tool outputs), Agent Patterns Catalog (ring buffer + Jaccard ≥0.7), Manneri (similarityThreshold: 0.75, lookbackWindow: 10)

---

## Block 6: Structured Compression Template (NEW — from Hermes)

### 6a. Structured LLM Summary Prompt for Context Compression

**Problem**: The current 5-tier compression cascade produces generic summaries that lose critical interview context (asked questions, candidate weaknesses, assessment decisions).

**File**: `backend/app/agents/chat/budget.py` (Tier 5 LLM compression prompt)

**Change**: Replace the generic compression prompt with Hermes-style structured template:

```
请将以下对话压缩为结构化摘要。不要回答任何问题，只做总结。

## 面试目标
（正在面试什么岗位，JD 关键要求）

## 已完成的考察
（每个已问过的知识点 + 候选人回答质量评估 1-5 分）

## 候选人表现模式
（强项、弱项、回答风格特征，如"倾向于背书式回答"）

## 已解决的问题
（已经深入追问过的方向，不需要再重复）

## 待考察的方向
（还没问到的知识点，面试官应该接下来覆盖的）

## 关键决策
（面试官做出的判断，如"这个候选人 RAG 强但算法弱"）

## 剩余工作
（面试还需要做什么，如"还需要考一道手撕题和一个八股"）
```

**Key borrowing from Hermes**:
- "Remaining Work" not "Next Steps" — avoids model reading summary as active instructions to execute immediately
- Structured dimensions instead of free-form summary — preserves critical categories
- Iterative updates: if a previous summary exists, generate an update rather than summarizing from scratch (preserves info across multiple compressions)

**References**: Hermes ContextCompressor 4-phase algorithm, Hermes structured summary template (Goal/Progress/Decisions/Resolved/Pending/Files/Remaining Work)

---

## Block 7: Remove Intermediate Pressure Warnings (NEW — from Hermes)

### 7a. Remove Context Pressure Warning Injections

**Problem**: Intermediate context-pressure warnings injected into the conversation cause the LLM to "give up prematurely on complex tasks" (Hermes finding).

**Files**: `backend/app/agents/chat/budget.py`, `backend/app/agents/chat/pipeline.py`

**Change**: Search for and remove any code that injects warnings like "⚠️ context 快满了" or "你还有 N 轮可用" into the conversation messages. Compression should fire silently — the LLM should not be aware of context pressure.

**Rationale** (Hermes): "Intermediate context-pressure warnings have been removed — they caused models to 'give up' prematurely on complex tasks. Compression fires when prompt tokens reach the configured threshold with no prior warning step."

**References**: Hermes ContextCompressor (removed pressure warnings), Hermes documentation

| Block | Fix | File(s) | Complexity | Borrowed From |
|-------|-----|---------|------------|---------------|
| 1a | Clean LRU examples | prompts.py, SKILL.md, tools.py, memory_recall_service.py | Low | — |
| 1b | Challenge vague answers | prompts.py | Low | Hermes, CallSphere |
| 1c | Handle counter-questions | prompts.py | Low | agent-interviewer |
| 1d | Inject PREVIOUSLY ASKED (per-turn dynamic) | pipeline.py | Low | Hermes, Claude Code |
| 1e | Diversify question phrasing | prompts.py | Low | — |
| 2a | Remove LRU fallback | pipeline.py | Low | — |
| 2b | Remove forced tool interceptor | pipeline.py + prompts.py | Medium | azmx.ai, Claude Lab |
| 3a | Fix memory_context="" | nodes.py | Low | — |
| 3b | Improve context labeling | pipeline.py | Low | Andrew Zhu, Codex |
| 3c | Bookend pattern | pipeline.py | Low | EngineersOfAI |
| 3d | Tool output pre-pruning | pipeline.py | Medium | Hermes, Claude Code |
| 4a | LLM-generated summary | pipeline.py + new Pydantic model | Medium | agent-interviewer, Intervu.dev |
| 5a | Per-competency quota | question_draw_service.py | Medium | Friday |
| 5b | Hash + Jaccard two-level dedup | pipeline.py | Medium | OpenCode ACP, Manneri |
| 6a | Structured compression template | budget.py | Medium | Hermes |
| 7a | Remove pressure warnings | budget.py, pipeline.py | Low | Hermes |

## What We Explicitly Do NOT Change

- **ReAct loop core structure** — stays as hand-crafted async pipeline
- **Budget controls** — max_steps, max_tool_calls, max_seconds stay
- **Loop detection** — seen_tool_calls stays
- **Tool allowlist** — validate_tool_call stays
- **SSE event system** — _emit stays
- **Context compression tiers** — 5-tier cascade stays (optimization deferred to Phase 3)

## Verification Plan

After implementation:
1. Run backend tests: `docker compose exec backend pytest backend/tests/ -q`
2. Run frontend build: `cd frontend && npm run build`
3. Deploy: `./deploy/docker-deploy.sh update`
4. Manual verification: Conduct 2 mock interviews and evaluate:
   - Does the interviewer still ask LRU Cache? (should not, or at most once)
   - Does it challenge vague answers? (should ask for specifics)
   - Does it handle counter-questions? (should respond briefly and continue)
   - Is the end-of-interview summary personalized? (should reference actual topics)
   - Does it vary its question phrasing? (should not repeat templates)
