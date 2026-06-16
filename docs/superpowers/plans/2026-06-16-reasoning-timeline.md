# Reasoning Timeline 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 持久化模拟面试 AI 的处理步骤（processing steps），每个步骤携带决策理由（reason），统一展示在 DeepSeek 风格的折叠时间线中。

**Architecture:** 后端 pipeline 的 `_step()` helper 扩展 reason/insight 字段，SSE 透传新增字段，前端 `ReasoningTimeline.vue` 替换 `ThinkingBlock.vue` 统一展示 steps + thinking。旧消息通过降级逻辑向后兼容。

**Tech Stack:** Python / FastAPI SSE / Vue 3 Composition API / Tailwind CSS / Lucide icons

**Spec:** `docs/superpowers/specs/2026-06-16-reasoning-timeline-design.md`

---

### Task 1: Backend — 升级 `_step()` helper 并添加 reason 常量

**Files:**
- Modify: `backend/app/agents/chat/pipeline.py:154-155`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/chat/test_step_helper.py
"""Tests for the _step() helper with reason and insight fields."""

from unittest.mock import MagicMock
import pytest

from app.agents.chat.pipeline import _step
from app.agents.shared.events import _event_queue_var


class TestStepHelper:
    def test_step_basic_event_format(self):
        """_step() with only step + message produces minimal event."""
        emitted = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            _step("loading", "正在加载对话历史...")
        finally:
            _event_queue_var.reset(token)

        assert len(emitted) == 1
        event = emitted[0]
        assert event["type"] == "step"
        assert event["step"] == "loading"
        assert event["message"] == "正在加载对话历史..."
        assert "reason" not in event
        assert "insight" not in event

    def test_step_with_reason(self):
        """_step() includes reason when provided."""
        emitted = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            _step("loading", "正在加载对话历史...", reason="加载最近20条对话历史")
        finally:
            _event_queue_var.reset(token)

        assert emitted[0]["reason"] == "加载最近20条对话历史"

    def test_step_with_reason_and_insight(self):
        """_step() includes both reason and insight when provided."""
        emitted = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            _step(
                "search_questions",
                "正在检索面试题...",
                reason="从题库检索Redis相关题目",
                insight="从题库检索到关于「Redis」的题目",
            )
        finally:
            _event_queue_var.reset(token)

        event = emitted[0]
        assert event["reason"] == "从题库检索Redis相关题目"
        assert event["insight"] == "从题库检索到关于「Redis」的题目"

    def test_step_empty_reason_not_included(self):
        """_step() omits reason when empty string."""
        emitted = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            _step("loading", "正在加载对话历史...", reason="")
        finally:
            _event_queue_var.reset(token)

        assert "reason" not in emitted[0]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
docker compose exec backend pytest backend/tests/chat/test_step_helper.py -v
```

Expected: FAIL — `_step()` 不接受 `reason`/`insight` 参数

- [ ] **Step 3: 实现最小代码**

修改 `backend/app/agents/chat/pipeline.py:154-155`：

```python
# 改前
def _step(step: str, message: str) -> None:
    _emit({"type": "step", "step": step, "message": message})

# 改后
def _step(step: str, message: str, reason: str = "", insight: str = "") -> None:
    event: dict = {"type": "step", "step": step, "message": message}
    if reason:
        event["reason"] = reason
    if insight:
        event["insight"] = insight
    _emit(event)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
docker compose exec backend pytest backend/tests/chat/test_step_helper.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/pipeline.py backend/tests/chat/test_step_helper.py
git commit -m "feat(backend): upgrade _step() helper with reason and insight fields"
```

---

### Task 2: Backend — 定义 reason 常量并应用到所有 emit 点

**Files:**
- Modify: `backend/app/agents/chat/pipeline.py:924,942,974,988,1101,1276-1282,1363,1441-1446`

- [ ] **Step 1: 在 pipeline.py 顶部（`_step` 函数之后）添加 reason 常量**

```python
# ── Step reason templates ─────────────────────────────────────
STEP_REASONS = {
    "loading": "加载最近 20 条对话历史和用户记忆，为理解问题提供上下文",
    "context": "构建面试上下文，包含简历和 JD 信息",
    "understanding_first": "首次消息快速分类，确定面试开场策略",
    "understanding_follow": "分析你的回答质量，决定下一步追问方向",
    "load_skill": "根据对话阶段加载对应的面试技巧",
    "draw_questions": "从题库随机抽取一道面试题",
    "generating": "综合上下文和检索结果，生成口述级回答",
    "closing": "面试已达到足够轮次，生成总结评价",
}
```

- [ ] **Step 2: 修改 `_step_load_context` 中的两个 emit 点（line 924, 942）**

```python
# line 924 — 改前
_step("loading", "正在加载对话历史...")
# 改后
_step("loading", "正在加载对话历史...", reason=STEP_REASONS["loading"])

# line 942 — 改前
_step("context", "正在加载个人画像...")
# 改后
_step("context", "正在加载个人画像...", reason=STEP_REASONS["context"])
```

- [ ] **Step 3: 修改 `_step_classify` 中的两个 emit 点（line 974, 988）**

```python
# line 974 — 改前
_step("understanding", "正在理解你的问题...")
# 改后
_step("understanding", "正在理解你的问题...", reason=STEP_REASONS["understanding_first"])

# line 988 — 改前
_step("understanding", "正在分析你的回答...")
# 改后
_step("understanding", "正在分析你的回答...", reason=STEP_REASONS["understanding_follow"])
```

- [ ] **Step 4: 修改 `_react_loop` 中的 forced closing emit（line 1101）**

```python
# 改前
_emit({"type": "step", "step": "closing", "message": "正在收尾面试..."})
# 改后
_emit({"type": "step", "step": "closing", "message": "正在收尾面试...", "reason": STEP_REASONS["closing"]})
```

- [ ] **Step 5: 修改 `_react_loop` 中的工具执行 step emit（line 1276-1282）**

在现有 `_emit` 中添加 reason 字段（保持在工具执行之前 emit，避免 UX 回归）：

```python
# 改前 (line 1276-1282)
_emit(
    {
        "type": "step",
        "step": tool_name,
        "message": tool_progress_message(tc),
    }
)

# 改后 — 在工具执行之前 emit，reason 使用静态模板
_emit(
    {
        "type": "step",
        "step": tool_name,
        "message": tool_progress_message(tc),
        "reason": STEP_REASONS.get(tool_name, ""),
    }
)
```

- [ ] **Step 6: 修改 `_react_loop` 中的 insight emit（line 1318-1339）**

将独立 insight emit 保留，但同时将 insight 关联到最近的 step。由于 insight 在工具执行之后发出，前端会通过时序关联（最近的 step 就是对应的 step）。

保持现有 insight emit 代码不变，确保向后兼容。

- [ ] **Step 6: 修改 `_react_loop` 中的 generating emit（line 1363）**

```python
# 改前
_emit({"type": "step", "step": "generating", "message": "正在生成回答..."})
# 改后
_emit({"type": "step", "step": "generating", "message": "正在生成回答...", "reason": STEP_REASONS["generating"]})
```

- [ ] **Step 7: 修改 `_run_pipeline` 中的 closing emit（line 1441-1446）**

```python
# 改前
_emit(
    {
        "type": "step",
        "step": "closing",
        "message": "正在生成面试总结...",
    }
)
# 改后
_emit(
    {
        "type": "step",
        "step": "closing",
        "message": "正在生成面试总结...",
        "reason": STEP_REASONS["closing"],
    }
)
```

- [ ] **Step 8: 运行所有 chat 测试确认无回归**

```bash
docker compose exec backend pytest backend/tests/chat/ -v
```

Expected: 所有现有测试通过（step 事件新增 reason 字段不影响现有断言，因为现有测试只检查 `type`、`step`、`message` 字段）

- [ ] **Step 9: Commit**

```bash
git add backend/app/agents/chat/pipeline.py
git commit -m "feat(backend): add reason to all pipeline step events"
```

---

### Task 3: Backend — 更新 SSE router 透传 reason/insight

**Files:**
- Modify: `backend/app/routers/chat.py:228-229`

- [ ] **Step 1: 修改 SSE event_stream 中的 step 事件处理**

```python
# 改前 (line 228-229)
if event_type == "step":
    yield f"data: {json.dumps({'type': 'step', 'step': event.get('step', ''), 'message': event.get('message', '')}, ensure_ascii=False)}\n\n"

# 改后
if event_type == "step":
    step_data: dict = {"type": "step", "step": event.get("step", ""), "message": event.get("message", "")}
    if event.get("reason"):
        step_data["reason"] = event["reason"]
    if event.get("insight"):
        step_data["insight"] = event["insight"]
    yield f"data: {json.dumps(step_data, ensure_ascii=False)}\n\n"
```

- [ ] **Step 2: 运行 chat API 测试**

```bash
docker compose exec backend pytest backend/tests/chat/ -v -k "sse or event"
```

Expected: 通过

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/chat.py
git commit -m "feat(backend): pass through reason and insight in SSE step events"
```

---

### Task 4: Backend — 更新现有测试以验证 reason 字段

**Files:**
- Modify: `backend/tests/chat/test_react_loop.py`（在现有断言后追加 reason 检查）
- Modify: `backend/tests/chat/test_multi_turn_e2e.py`（追加 reason 断言）

- [ ] **Step 1: 在 test_react_loop.py 的 search_questions 测试中追加 reason 断言**

在 `TestReactLoop.test_tool_call_and_answer` 方法中（约 line 300），在现有断言后追加：

```python
        # 验证 step 事件包含 reason
        assert "reason" in events[0]
        assert events[0]["reason"]  # reason 非空
```

- [ ] **Step 2: 在 test_multi_turn_e2e.py 的 insight 测试中验证 insight 已合并到 step**

修改 `TestSSEEventSequence.test_search_event_sequence`，追加：

```python
        # insight 已合并到 step 事件中
        search_steps = [e for e in events if e["type"] == "step" and e.get("step") == "search_questions"]
        if search_steps:
            assert search_steps[0].get("insight")  # insight 在 step 中
```

- [ ] **Step 3: 运行全部 chat 测试**

```bash
docker compose exec backend pytest backend/tests/chat/ -v
```

Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add backend/tests/chat/test_react_loop.py backend/tests/chat/test_multi_turn_e2e.py
git commit -m "test(backend): add reason/insight assertions to existing step event tests"
```

---

### Task 5: Frontend — 创建 ReasoningTimeline.vue 组件

**Files:**
- Create: `frontend/src/components/business/ReasoningTimeline.vue`

- [ ] **Step 1: 编写组件**

```vue
<!-- frontend/src/components/business/ReasoningTimeline.vue -->
<template>
  <div class="mb-4">
    <!-- Trigger button -->
    <button
      @click="isOpen = !isOpen"
      class="flex items-center gap-2 text-xs text-muted-foreground/70 hover:text-muted-foreground transition-colors select-none"
    >
      <!-- Spinner while streaming -->
      <Loader2 v-if="isStreaming" :size="14" class="animate-spin" />
      <!-- Lightbulb when complete -->
      <Lightbulb v-else :size="14" />

      <span>{{ displayLabel }}</span>

      <!-- Pulsing ellipsis while streaming -->
      <span v-if="isStreaming && !isOpen" class="inline-flex gap-0.5">
        <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 0ms"></span>
        <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 200ms"></span>
        <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 400ms"></span>
      </span>

      <!-- Chevron -->
      <ChevronDown v-else :size="14" class="transition-transform duration-200" :class="{ 'rotate-180': isOpen }" />
    </button>

    <!-- Collapsible content -->
    <Transition name="expand">
      <div v-show="isOpen" class="mt-2">
        <!-- Steps timeline -->
        <div v-if="steps.length > 0" class="space-y-1 mb-3">
          <div
            v-for="(step, i) in steps"
            :key="i"
            class="group/step"
          >
            <!-- Step row -->
            <button
              @click="toggleStep(i)"
              class="flex items-center gap-2 w-full text-left px-2 py-1 rounded-md text-xs hover:bg-muted/50 transition-colors"
            >
              <CheckCircle2 v-if="step.done !== false" :size="12" class="text-emerald-500 shrink-0" />
              <Loader2 v-else :size="12" class="animate-spin text-muted-foreground shrink-0" />
              <span class="text-muted-foreground flex-1">{{ step.message }}</span>
              <ChevronDown
                v-if="step.reason || step.insight"
                :size="12"
                class="text-muted-foreground/50 shrink-0 transition-transform duration-200"
                :class="{ 'rotate-180': expandedSteps.has(i) }"
              />
            </button>

            <!-- Step detail (reason + insight) -->
            <Transition name="expand">
              <div v-if="expandedSteps.has(i) && (step.reason || step.insight)" class="pl-7 pr-2 pb-1">
                <p v-if="step.reason" class="text-xs text-muted-foreground/60 leading-relaxed">
                  {{ step.reason }}
                </p>
                <p v-if="step.insight" class="text-xs text-amber-600/70 dark:text-amber-400/70 mt-0.5 flex items-center gap-1">
                  <Lightbulb :size="10" />
                  {{ step.insight }}
                </p>
              </div>
            </Transition>
          </div>
        </div>

        <!-- LLM Thinking section -->
        <div v-if="content" ref="contentRef"
          class="text-xs leading-relaxed text-muted-foreground/70 max-h-[300px] overflow-y-auto whitespace-pre-wrap break-words p-3 rounded-lg bg-muted/30 border border-border/50"
        >{{ content }}</div>

        <!-- Pulsing ellipsis at bottom while streaming -->
        <div v-if="isStreaming" class="flex justify-center mt-2">
          <span class="inline-flex gap-0.5">
            <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 0ms"></span>
            <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 200ms"></span>
            <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 400ms"></span>
          </span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { Loader2, Lightbulb, ChevronDown, CheckCircle2 } from '@lucide/vue'

const props = defineProps({
  isStreaming: { type: Boolean, default: false },
  content: { type: String, default: '' },
  duration: { type: Number, default: 0 },
  steps: { type: Array, default: () => [] },
})

const isOpen = ref(true)
const contentRef = ref(null)
const expandedSteps = ref(new Set())

const stepCount = computed(() => props.steps.length)

const displayLabel = computed(() => {
  if (props.isStreaming) return '思考中'
  const parts = []
  if (props.duration > 0) parts.push(`思考了 ${props.duration} 秒`)
  if (stepCount.value > 0) parts.push(`${stepCount.value} 步`)
  return parts.length > 0 ? parts.join(' · ') : '思考过程'
})

function toggleStep(index) {
  const s = new Set(expandedSteps.value)
  if (s.has(index)) {
    s.delete(index)
  } else {
    s.add(index)
  }
  expandedSteps.value = s
}

watch(() => props.content, () => {
  if (contentRef.value && isOpen.value) {
    contentRef.value.scrollTop = contentRef.value.scrollHeight
  }
})

watch(() => props.isStreaming, (streaming) => {
  if (!streaming && (props.content || props.steps.length > 0)) {
    setTimeout(() => {
      isOpen.value = false
    }, 1000)
  }
})

onMounted(() => {
  if ((props.content || props.steps.length > 0) && !props.isStreaming) {
    isOpen.value = false
  }
})
</script>

<style scoped>
.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 600px;
}
</style>
```

- [ ] **Step 2: 确认前端构建通过**

```bash
cd frontend && npm run build
```

Expected: 构建成功（组件未被使用，但语法正确不会报错）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/business/ReasoningTimeline.vue
git commit -m "feat(frontend): create ReasoningTimeline component with step reason support"
```

---

### Task 6: Frontend — 更新 ChatView.vue 持久化 steps

**Files:**
- Modify: `frontend/src/components/business/ChatView.vue:658-661,708-766`

- [ ] **Step 1: 更新 SSE step 事件处理，接收 reason/insight**

```javascript
// 改前 (line 658-661)
if (event.type === 'step') {
  processingSteps.value.forEach(s => { s.done = true })
  processingSteps.value.push({ step: event.step, message: event.message, done: false })
  scrollToBottom()

// 改后
if (event.type === 'step') {
  processingSteps.value.forEach(s => { s.done = true })
  processingSteps.value.push({
    step: event.step,
    message: event.message,
    done: false,
    reason: event.reason || '',
    insight: event.insight || '',
  })
  scrollToBottom()
```

- [ ] **Step 2: 更新 metadata 构建逻辑，写入 steps（合并 insight）**

由于 insight 仍然是独立事件（在 step 之后发出），前端在持久化时需要将 insight 合并到对应的 step 中。

在 `ChatView.vue` 的 metadata 构建块中（约 line 730 附近），在 `thinkingContent` 之前添加：

```javascript
      // Persist processing steps, merging insights into their preceding step
      if (processingSteps.value.length > 0) {
        const stepsCopy = processingSteps.value.map(s => ({
          step: s.step,
          message: s.message,
          reason: s.reason || '',
          insight: '',
        }))
        // Merge pending insights into the last tool step (by timing order)
        for (const insight of pendingInsights.value) {
          // Find the last step that could own this insight (load_skill, search_questions, draw_questions)
          for (let j = stepsCopy.length - 1; j >= 0; j--) {
            if (['load_skill', 'search_questions', 'draw_questions'].includes(stepsCopy[j].step)) {
              stepsCopy[j].insight = insight.text
              break
            }
          }
        }
        metadata.steps = stepsCopy
      }
```

- [ ] **Step 3: 更新流式展示区域，用 ReasoningTimeline 替换 ThinkingBlock**

在 `ChatView.vue` 的流式消息区域（约 line 168-175），替换 ThinkingBlock：

```vue
<!-- 改前 -->
<ThinkingBlock
  v-if="isThinking || thinkingContent"
  :is-streaming="isThinking"
  :content="thinkingContent"
  :duration="thinkingDuration"
/>

<!-- 改后 -->
<ReasoningTimeline
  v-if="isThinking || thinkingContent || processingSteps.length > 0"
  :is-streaming="isThinking"
  :content="thinkingContent"
  :duration="thinkingDuration"
  :steps="processingSteps"
/>
```

- [ ] **Step 4: 更新 import 语句**

```javascript
// 改前
import ThinkingBlock from './ThinkingBlock.vue'

// 改后
import ReasoningTimeline from './ReasoningTimeline.vue'
```

- [ ] **Step 5: 确认前端构建通过**

```bash
cd frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/business/ChatView.vue
git commit -m "feat(frontend): persist processing steps and use ReasoningTimeline in ChatView"
```

---

### Task 7: Frontend — 更新 ChatMessage.vue 使用 ReasoningTimeline

**Files:**
- Modify: `frontend/src/components/business/ChatMessage.vue:17-29,189-190`

- [ ] **Step 1: 替换 ThinkingBlock + InsightBlock 为 ReasoningTimeline**

```vue
<!-- 改前 (line 17-29) -->
<!-- Thinking block -->
<ThinkingBlock
  v-if="message.metadata?.thinking"
  :is-streaming="false"
  :content="message.metadata.thinking"
  :duration="message.metadata.thinking_duration || 0"
/>

<InsightBlock
  v-if="message.metadata?.insights?.length"
  :items="message.metadata.insights"
  :is-streaming="false"
/>

<!-- 改后 -->
<!-- Reasoning timeline (unified: steps + thinking) -->
<ReasoningTimeline
  v-if="message.metadata?.steps?.length || message.metadata?.thinking"
  :is-streaming="false"
  :content="message.metadata?.thinking || ''"
  :duration="message.metadata?.thinking_duration || 0"
  :steps="message.metadata?.steps || []"
/>

<!-- Fallback: legacy insight-only messages (no steps, has insights) -->
<InsightBlock
  v-else-if="message.metadata?.insights?.length"
  :items="message.metadata.insights"
  :is-streaming="false"
/>
```

- [ ] **Step 2: 更新 import 语句**

```javascript
// 改前 (line 189-190)
import ThinkingBlock from './ThinkingBlock.vue'
import InsightBlock from './InsightBlock.vue'

// 改后
import ReasoningTimeline from './ReasoningTimeline.vue'
import InsightBlock from './InsightBlock.vue'
```

- [ ] **Step 3: 确认前端构建通过**

```bash
cd frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/business/ChatMessage.vue
git commit -m "feat(frontend): use ReasoningTimeline in ChatMessage with backward compat"
```

---

### Task 8: 集成验证 — 完整构建和部署测试

- [ ] **Step 1: 运行全部后端测试**

```bash
docker compose exec backend pytest backend/tests/chat/ -v
```

Expected: 全部通过

- [ ] **Step 2: 前端构建**

```bash
cd frontend && npm run build
```

Expected: 构建成功

- [ ] **Step 3: 生产部署前端**

```bash
./deploy/docker-deploy.sh frontend
```

Expected: 部署成功

- [ ] **Step 4: 在生产环境验证**

1. 打开 `/chat` 页面
2. 发送一条消息，观察：
   - 流式传输时仍显示药丸标签
   - 传输完成后折叠为"思考了 X 秒 · N 步"
   - 点击展开可看到步骤列表
   - 点击单个步骤可展开 reason
3. 刷新页面，验证历史消息的 ReasoningTimeline 正确渲染
4. 打开旧的面试对话（无 steps 的消息），验证降级显示 thinking

- [ ] **Step 5: Commit 最终确认**

```bash
git add -A && git status
```

确认无未提交文件

- [ ] **Step 6: 更新 CLAUDE.md（如有架构变更需要记录）**

检查是否需要更新 `backend/CLAUDE.md` 或 `frontend/CLAUDE.md` 中关于 chat pipeline 事件格式的描述。
