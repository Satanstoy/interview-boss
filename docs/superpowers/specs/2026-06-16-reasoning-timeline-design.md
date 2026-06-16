# Reasoning Timeline — 模拟面试思考过程持久化

**日期**: 2026-06-16
**状态**: Draft
**范围**: 模拟面试 (chat pipeline) 的 AI 思考过程持久化与展示优化

## 背景

模拟面试中，AI 面试官的思考过程包含三类数据：

| 数据类型 | 流式展示 | 持久化 | 历史可查看 |
|---------|---------|--------|-----------|
| LLM thinking（模型原始推理） | ThinkingBlock | `metadata.thinking` | ✅ |
| Processing steps（pipeline 阶段） | 药丸标签 | ❌ **未持久化** | ❌ |
| Insights（面试官决策说明） | InsightBlock | `metadata.insights` | ✅ |

核心问题：**processing steps 在流式传输后消失**，用户无法回顾 AI 的决策链路。

## 目标

1. 将 processing steps 持久化到消息 metadata 中
2. 每个 step 携带 `reason`（决策理由），点击可查看
3. 将三类数据（steps + thinking）统一到单一折叠区，类似 DeepSeek 风格
4. 流式传输时保持现有药丸标签效果，完成后平滑过渡到折叠区

## 方案选择

**方案 C：步骤中心 + thinking 独立**

- Steps 是主结构，每个 step 自带 reason 和可选 insight
- LLM thinking 保持独立字段
- 向后兼容旧消息格式

## 数据模型

### Step SSE 事件格式（后端 → 前端）

```json
{
  "type": "step",
  "step": "search_questions",
  "message": "正在检索面试题...",
  "reason": "根据你提到的「Redis 缓存一致性」，从题库检索相关高频面试题",
  "insight": "从题库检索到关于「Redis」的题目"
}
```

`reason` 和 `insight` 为可选字段，旧事件格式兼容。

### 持久化格式（metadata.steps）

```json
{
  "steps": [
    {
      "step": "loading",
      "message": "正在加载对话历史...",
      "reason": "加载最近 20 条对话历史和用户记忆，为理解问题提供上下文"
    },
    {
      "step": "search_questions",
      "message": "正在检索面试题...",
      "reason": "根据你提到的「Redis 缓存一致性」，检索相关高频面试题",
      "insight": "从题库检索到关于「Redis」的题目"
    },
    {
      "step": "generating",
      "message": "正在生成回答...",
      "reason": "综合上下文和检索结果，生成口述级回答"
    }
  ],
  "thinking": "用户问的是 Redis 缓存一致性...",
  "thinking_duration": 8
}
```

### Reason 来源映射

| Step 类型 | Reason 来源 | 内容 |
|-----------|------------|------|
| `loading` | 静态 | "加载最近 20 条对话历史和用户记忆，为理解问题提供上下文" |
| `context` | 静态 | "构建面试上下文，包含简历和 JD 信息" |
| `understanding`（首次） | 静态 | "首次消息快速分类，确定面试开场策略" |
| `understanding`（后续） | 静态 | "分析你的回答质量，决定下一步追问方向" |
| `load_skill` | 静态 | "根据对话阶段加载对应的面试技巧" |
| `search_questions` | 模板 + 检索结果 | "根据你的问题关键词，从题库检索「{topic}」相关的高频面试题" |
| `draw_questions` | 静态 | "从题库随机抽取一道面试题" |
| `generating` | 静态 | "综合上下文和检索结果，生成口述级回答" |
| `closing` | 静态 | "面试已达到足够轮次，生成总结评价" |

> search_questions 的 reason 通过模板 + 检索结果的 cat2/cat1 拼接生成，不需要额外 LLM 调用。

## 后端改造

### pipeline.py

**1. `_step()` helper 升级：**

```python
def _step(step: str, message: str, reason: str = "", insight: str = "") -> None:
    event = {"type": "step", "step": step, "message": message}
    if reason:
        event["reason"] = reason
    if insight:
        event["insight"] = insight
    _emit(event)
```

**2. 各 emit 点补充 reason：**

- `_step_load_context` 中的 `loading` 和 `context`：静态 reason
- `_step_classify` 中的 `understanding`：根据 `is_first_message` 选择不同静态 reason
- `_react_loop` 中的工具执行步骤：工具执行后补充 reason（search_questions 用模板拼接，其余用静态）
- `_react_loop` 中的 `generating`：静态 reason
- `_run_pipeline` 中的 `closing`：静态 reason

**3. 洞察合并到步骤：**

当前 insight 是在 step 之后独立 emit 的（通过 `_emit({"type": "insight", ...})`）。改造后，将 insight 作为 step 事件的 `insight` 字段一起发出。原独立的 `_emit({"type": "insight", ...})` 调用被移除。SSE 层（chat.py）保留 insight 事件透传逻辑，确保如果有残留的独立 insight 事件不会丢失。

### chat.py SSE 透传

step 事件增加 `reason` 和 `insight` 字段透传：

```python
elif event_type == "step":
    data = {"type": "step", "step": event["step"], "message": event["message"]}
    if event.get("reason"):
        data["reason"] = event["reason"]
    if event.get("insight"):
        data["insight"] = event["insight"]
    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
```

insight 事件保持向后兼容（继续透传），但新逻辑中 insight 已合并到 step 中。

### chat_service.py

无需改动。metadata 已经是自由 JSON 结构，新增 `steps` 字段自动持久化。

## 前端改造

### 新组件：ReasoningTimeline.vue

替换 ThinkingBlock.vue，统一展示 steps + thinking。

**结构：**

```
ReasoningTimeline
├── 触发按钮（默认折叠）
│   ├── 💡 图标
│   ├── "思考了 {duration} 秒 · {stepCount} 步" 或 "思考中"
│   └── ChevronDown
└── 折叠内容
    ├── 步骤时间线
    │   └── StepItem × N
    │       ├── ✅/⏳ 图标 + 步骤名称
    │       ├── 点击展开 reason
    │       └── insight 附属展示
    └── LLM 思考区域（如有）
        └── thinking 文本
```

**StepItem 交互：**

折叠状态：
```
✅ 正在检索面试题...
```

展开状态：
```
✅ 正在检索面试题...
   └ 根据你提到的「Redis 缓存一致性」，检索相关高频面试题
     💡 从题库检索到关于「Redis」的题目
```

### ChatView.vue 改造

1. 流式传输中的药丸标签样式不变
2. 流式完成后，`processingSteps`（含 reason/insight）写入 `metadata.steps`
3. 用 `ReasoningTimeline` 替换流式区域的 `ThinkingBlock`

### ChatMessage.vue 改造

1. 用 `ReasoningTimeline` 替换 `ThinkingBlock` 和 `InsightBlock`
2. 向后兼容：
   - 有 `metadata.steps` → 完整渲染
   - 无 `steps` 有 `thinking` → 只渲染 thinking
   - 无 `steps` 有 `insights` → 降级渲染 insight 列表

### 前端数据接收改造

`ChatView.vue` SSE 事件处理：

```javascript
if (event.type === 'step') {
  processingSteps.value.forEach(s => { s.done = true })
  processingSteps.value.push({
    step: event.step,
    message: event.message,
    done: false,
    reason: event.reason || '',
    insight: event.insight || '',
  })
}
```

持久化时：

```javascript
if (processingSteps.value.length > 0) {
  metadata.steps = processingSteps.value.map(s => ({
    step: s.step,
    message: s.message,
    reason: s.reason || '',
    insight: s.insight || '',
  }))
}
```

## 错误处理

| 场景 | 处理方式 |
|------|---------|
| `reason` 字段缺失 | 只显示步骤名称，不展示 reason 区域 |
| `steps` 数组为空 | 如有 thinking 则只显示 thinking，否则不渲染 |
| 旧消息无 `steps` 字段 | 向后兼容：显示 thinking 和/或 insights |
| LLM reason 生成失败 | 使用静态 fallback reason |
| SSE 传输中断 | 已接收的 steps 正常保存 |

## 测试策略

### 后端（pytest）

- `_step()` helper 正确生成含 reason/insight 的事件字典
- SSE 事件格式验证（含 reason 和不含 reason）
- metadata 持久化：steps 数组正确写入/读取 chat_messages
- 向后兼容：无 steps 字段的消息正常返回

### 前端（组件级）

- `ReasoningTimeline` 完整渲染（steps + thinking）
- `ReasoningTimeline` 仅 thinking（向后兼容）
- `StepItem` 点击展开/折叠交互
- 流式药丸 → 折叠区过渡

## 不做的事情（YAGNI）

- 不创建数据库 migration（metadata 是自由 JSON）
- 不迁移已有消息数据（旧消息按降级逻辑展示）
- 不为 search_questions 做额外 LLM 调用生成 reason（用模板拼接）
- 不改变 InsightBlock 组件本身（仅在新消息中不再使用）
