# 设计文档：模拟面试状态、节奏学习与前端观测性

> 日期: 2026-07-01
> 状态: 待实施
> 作者: Claude Code

## 第一章：设计概述

### 1.1 目标

根据 spec 文档，实施模拟面试状态、节奏学习与前端观测性功能，解决以下三个前端观测性问题：

1. **模型思考时间与 thinking 内容**：兼容 `content` 和 `data.text`，统一保存格式
2. **Skill 加载与可见性**：在 step 事件中添加 `skill_name`，前端刷新后可见
3. **Tool call 摘要与 raw tool call 边界**：新增 `tool_steps` 字段，保存工具调用摘要

### 1.2 实施范围

**后端核心**：
- 修正 thinking metadata 收集字段
- 增强 load_skill step
- 增强 tool step 摘要
- 添加 coverage_config.py 和 rhythm_profile.py
- 添加 interview_state.py
- 修改 create conversation
- 修改 _step_load_context / prompt 构建
- 修改 done metadata
- 添加 chat_tool_traces 审计表

**前端展示**：
- 兼容旧格式字符串和新格式 list chunks
- 展示 skill 名称
- 展示 tool step 摘要

### 1.3 实施顺序

按照 spec 中的实施顺序，逐步实现每个功能：

1. 修正 thinking metadata 收集字段
2. 统一前端历史 thinking 渲染
3. 增强 load_skill step
4. 增强 tool step 摘要
5. 添加 coverage_config.py 和 rhythm_profile.py
6. 添加 interview_state.py
7. 修改 create conversation
8. 修改 _step_load_context / prompt 构建
9. 修改 done metadata
10. 添加 chat_tool_traces 审计表

---

## 第二章：Thinking Metadata 收集与前端兼容

### 2.1 后端 Thinking 收集修改

**当前实现**（`pipeline.py` 第 490-491 行）：
```python
elif item_type == "thinking":
    if collected_thinking:
        collected_thinking[-1].setdefault("chunks", []).append(
            item.get("data", {}).get("text", "")
        )
```

**修改方案**：优先 `content`，fallback 到 `data.text`
```python
elif item_type == "thinking":
    if collected_thinking:
        # 优先 content，fallback 到 data.text
        chunk = item.get("content") or item.get("data", {}).get("text", "")
        if chunk:
            collected_thinking[-1].setdefault("chunks", []).append(chunk)
```

**metadata 保存格式**：
```json
{
  "thinking": [
    {
      "chunks": ["思考片段1", "思考片段2"],
      "duration_ms": 1234
    }
  ],
  "thinking_duration": 1.2
}
```

### 2.2 前端 Thinking 渲染兼容

**当前实现**（`ChatMessage.vue` 第 21 行）：
```vue
:content="message.metadata?.thinking || ''"
```

**修改方案**：兼容旧格式字符串和新格式 list chunks
```vue
:content="thinkingContent"
```

```javascript
const thinkingContent = computed(() => {
  const thinking = props.message.metadata?.thinking
  if (!thinking) return ''
  
  // 旧格式：字符串
  if (typeof thinking === 'string') return thinking
  
  // 新格式：list chunks
  if (Array.isArray(thinking)) {
    return thinking
      .map(t => t.chunks?.join('') || '')
      .filter(Boolean)
      .join('\n')
  }
  
  return ''
})
```

### 2.3 测试计划

**后端测试**：
- thinking 事件用真实 `content` 字段时，metadata.thinking chunks 不为空
- thinking 事件用 `data.text` 字段时，metadata.thinking chunks 不为空
- 两种字段都为空时，chunks 不添加空字符串

**前端测试**：
- 旧格式字符串正常显示
- 新格式 list chunks 正常显示
- 空 metadata 不报错

---

## 第三章：Skill 加载与可见性

### 3.1 后端 load_skill step 增强

**当前实现**（`react_loop.py` 第 535-541 行）：
```python
if tool_name == "load_skill":
    skill_label = (
        chat_tools.tool_progress_message(tc)
        .replace("正在加载", "")
        .replace("...", "")
    )
    _emit({"type": "insight", "text": f"切换到{skill_label}模式"})
```

**修改方案**：在 step 事件中添加 `skill_name`
```python
if tool_name == "load_skill":
    skill_name = json.loads(tc["function"]["arguments"]).get("skill_name", "")
    skill_label = (
        chat_tools.tool_progress_message(tc)
        .replace("正在加载", "")
        .replace("...", "")
    )
    _emit({
        "type": "step",
        "step": "load_skill",
        "message": f"已加载{skill_label}",
        "skill_name": skill_name,
        "reason": STEP_REASONS.get("load_skill", ""),
    })
    _emit({"type": "insight", "text": f"切换到{skill_label}模式"})
```

### 3.2 前端 Skill 名称展示

**当前实现**（`ReasoningTimeline.vue`）：
- 只展示 `step.message`，不展示 `skill_name`

**修改方案**：在 step 展示中添加 `skill_name`
```vue
<span class="text-muted-foreground flex-1">
  {{ step.message }}
  <span v-if="step.skill_name" class="text-primary ml-1">({{ step.skill_name }})</span>
</span>
```

### 3.3 Skill 名称中文映射

**映射表**（`tools.py`）：
```python
skill_labels = {
    "adaptive-difficulty": "自适应难度策略",
    "algorithm-coding": "算法面试策略",
    "hr-soft-skills": "HR 软技能策略",
    "interview-rhythm": "面试节奏策略",
    "project-deep-dive": "项目深挖策略",
    "theory-qa": "理论问答策略",
}
```

### 3.4 测试计划

**后端测试**：
- `load_skill` step 事件包含 `skill_name` 字段
- `skill_name` 字段值正确（如 "project-deep-dive"）
- 历史消息从 `GET /messages` 恢复后仍能看到本轮加载过的 skill

**前端测试**：
- `load_skill` step 展示具体 skill 名称
- 历史消息刷新后仍能看到 skill 名称
- 旧消息 metadata 为空时 UI 不报错

---

## 第四章：Tool Step 摘要与审计表

### 4.1 后端 tool_steps 字段增强

**当前实现**（`pipeline.py` 第 469-512 行）：
- 收集 `steps`、`insights`、`thinking` 事件
- 保存到 `metadata.steps`、`metadata.insights`、`metadata.thinking`

**修改方案**：新增 `tool_steps` 字段，保存工具调用摘要

```python
# 在 pipeline.py 中添加
collected_tool_steps: list[dict] = []

# 在 item_type == "done" 时
metadata["tool_steps"] = collected_tool_steps
```

**tool_step 数据结构**：
```json
{
  "step": "search_questions",
  "tool_name": "search_questions",
  "message": "检索了相关面试题",
  "elapsed_ms": 320,
  "result_count": 3,
  "fallback_used": false
}
```

### 4.2 后端 tool_step 收集逻辑

**在 react_loop.py 中收集**：
```python
# 在工具执行完成后
if tool_name in ("search_questions", "draw_questions", "select_question", "load_skill"):
    tool_step = {
        "step": tool_name,
        "tool_name": tool_name,
        "message": chat_tools.tool_progress_message(tc),
        "elapsed_ms": int((time.monotonic() - tool_started) * 1000),
        "result_count": _summarize_tool_output(tool_name, output, state).get("result_count", 0),
        "fallback_used": _summarize_tool_output(tool_name, output, state).get("fallback_used", False),
    }
    _emit({"type": "tool_step", "data": tool_step})
```

**在 pipeline.py 中收集 tool_step 事件**：
```python
elif item_type == "tool_step":
    collected_tool_steps.append(item.get("data", {}))
```

### 4.3 chat_tool_traces 审计表

**表结构**：
```sql
CREATE TABLE chat_tool_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    message_id INTEGER,
    react_step INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    sanitized_args_json TEXT NOT NULL,
    result_summary_json TEXT NOT NULL,
    elapsed_ms INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**写入逻辑**：
- 只保存 `_sanitize_tool_args()` 之后的参数
- 只保存 `_summarize_tool_output()` 之后的结果摘要
- 不保存 skill 全文、完整 retrieved items、用户隐私原文

### 4.4 前端 Tool Step 展示

**当前实现**（`ReasoningTimeline.vue`）：
- 只展示 `steps`，不展示 `tool_steps`

**修改方案**：在 ReasoningTimeline 中展示 `tool_steps`
```vue
<div v-if="toolSteps.length > 0" class="space-y-1 mb-3">
  <div v-for="(step, i) in toolSteps" :key="i" class="group/step">
    <button
      @click="toggleToolStep(i)"
      class="flex items-center gap-2 w-full text-left px-2 py-1 rounded-md text-xs hover:bg-muted/50 transition-colors"
    >
      <CheckCircle2 v-if="step.done !== false" :size="12" class="text-emerald-500 shrink-0" />
      <Loader2 v-else :size="12" class="animate-spin text-muted-foreground shrink-0" />
      <span class="text-muted-foreground flex-1">{{ step.message }}</span>
      <span v-if="step.elapsed_ms" class="text-xs text-muted-foreground/50">{{ step.elapsed_ms }}ms</span>
      <span v-if="step.result_count !== undefined" class="text-xs text-muted-foreground/50">{{ step.result_count }} 结果</span>
    </button>
  </div>
</div>
```

### 4.5 测试计划

**后端测试**：
- tool call 通过 tool_steps 摘要进入前端 metadata
- tool_steps 包含工具名、耗时、结果数量、fallback 状态
- 完整 raw tool call 不暴露给前端
- 可选 tool trace 审计只保存脱敏 args 和 result summary

**前端测试**：
- tool_steps 正常展示
- 历史消息刷新后仍能看到 tool_steps
- 旧消息 metadata 为空时 UI 不报错

---

## 第五章：Coverage Config 与 Rhythm Profile

### 5.1 coverage_config.py 设计

**文件位置**：`backend/app/agents/chat/coverage_config.py`

**核心功能**：
- 定义 `InterviewPhase` 枚举
- 定义默认覆盖度阈值
- 提供获取阈值的函数

**代码结构**：
```python
"""Coverage configuration for interview phases."""

from enum import Enum
from typing import Optional


class InterviewPhase(str, Enum):
    """面试阶段枚举，与现有题型和 harness 术语对齐"""
    WARMUP = "warmup"
    PROJECT_FOLLOWUP = "project_followup"
    KNOWLEDGE_PROBE = "knowledge_probe"
    ALGORITHM_CODING = "algorithm_coding"
    SYSTEM_DESIGN = "system_design"
    BEHAVIORAL = "behavioral"
    WRAP_UP = "wrap_up"


# 默认覆盖度阈值（岗位 + 难度维度）
DEFAULT_COVERAGE_THRESHOLDS = {
    ("agent_llm", "junior"): {
        InterviewPhase.PROJECT_FOLLOWUP: 3,
        InterviewPhase.KNOWLEDGE_PROBE: 3,
        InterviewPhase.ALGORITHM_CODING: 1,
        InterviewPhase.SYSTEM_DESIGN: 0,
        InterviewPhase.BEHAVIORAL: 1,
    },
    ("agent_llm", "mid"): {
        InterviewPhase.PROJECT_FOLLOWUP: 5,
        InterviewPhase.KNOWLEDGE_PROBE: 3,
        InterviewPhase.ALGORITHM_CODING: 1,
        InterviewPhase.SYSTEM_DESIGN: 1,
        InterviewPhase.BEHAVIORAL: 1,
    },
    # ... 其他岗位和难度
}


def get_coverage_thresholds(
    job_position: str,
    difficulty: str,
    rhythm_profile: Optional[dict] = None,
) -> dict[str, int]:
    """获取覆盖度阈值，支持节奏学习调整"""
    # 1. 获取默认阈值
    key = (job_position, difficulty)
    thresholds = DEFAULT_COVERAGE_THRESHOLDS.get(
        key,
        DEFAULT_COVERAGE_THRESHOLDS[("agent_llm", "mid")]
    ).copy()
    
    # 2. 如果有节奏学习配置，调整阈值
    if rhythm_profile and rhythm_profile.get("confidence", 0) >= 0.5:
        distribution = rhythm_profile.get("distribution", {})
        for phase, count in distribution.items():
            if phase in thresholds:
                # 调整阈值，但设置上下限
                adjusted = max(1, min(count * 2, thresholds[phase] * 2))
                thresholds[phase] = adjusted
    
    return thresholds
```

### 5.2 rhythm_profile.py 设计

**文件位置**：`backend/app/agents/chat/rhythm_profile.py`

**核心功能**：
- 从面经中学习节奏
- 分类题目阶段
- 生成节奏配置

**代码结构**：
```python
"""Rhythm profile learning from interview experiences."""

import re
from typing import Optional
from app.db.connection import get_db_connection


def classify_question_phase(question: str) -> str:
    """分类题目阶段，优先使用已有 question_type/cat1/cat2"""
    # 1. 如果题目来自 questions_detail 或 question_bank，优先用已有分类
    # 2. 否则使用关键词兜底
    # 3. 分类失败时归入 project_followup
    
    normalized = question.lower()
    
    if re.search(r"(系统设计|架构设计|高可用|扩展性|scalability)", question, re.I):
        return "system_design"
    if re.search(r"(行为面|协作|冲突|失败|复盘|STAR|影响力)", question, re.I):
        return "behavioral"
    if re.search(r"(算法|代码|手撕|数据结构|链表|排序|二分|LRU|滑动窗口)", question, re.I):
        return "algorithm_coding"
    if re.search(r"(项目|架构|系统设计|Agent|RAG|LangGraph)", question, re.I):
        return "project_followup"
    if re.search(r"(Redis|MySQL|TCP|HTTP|缓存|锁|线程|进程|索引)", question, re.I):
        return "knowledge_probe"
    
    return "project_followup"


def analyze_topic_distribution(questions: list[str]) -> dict[str, int]:
    """分析题目分布"""
    distribution = {}
    for question in questions:
        phase = classify_question_phase(question)
        distribution[phase] = distribution.get(phase, 0) + 1
    return distribution


def analyze_topic_transition(questions: list[str]) -> dict[str, dict[str, int]]:
    """分析题目转换模式"""
    transition = {}
    for i in range(len(questions) - 1):
        from_phase = classify_question_phase(questions[i])
        to_phase = classify_question_phase(questions[i + 1])
        if from_phase not in transition:
            transition[from_phase] = {}
        transition[from_phase][to_phase] = transition[from_phase].get(to_phase, 0) + 1
    return transition


def build_rhythm_profile(
    experience_id: int,
    user_id: int,
    job_position: str,
) -> Optional[dict]:
    """从面经构建节奏配置"""
    # 1. 按权限读取面经
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT id, questions_list, difficulty, job_position, owner_id, status
            FROM interview
            WHERE id = ?
              AND deleted_at IS NULL
              AND status = 'approved'
              AND (owner_id = ? OR owner_id IS NULL)
              AND (job_position = ? OR job_position = '')
            """,
            (experience_id, user_id, job_position),
        ).fetchone()
    
    if not row:
        return None
    
    # 2. 解析题目列表
    questions = row["questions_list"].split("\n") if row["questions_list"] else []
    questions = [q.strip() for q in questions if q.strip()]
    
    if not questions:
        return None
    
    # 3. 分析分布和转换
    distribution = analyze_topic_distribution(questions)
    transition = analyze_topic_transition(questions)
    
    # 4. 计算置信度
    unknown_count = sum(1 for q in questions if classify_question_phase(q) == "project_followup")
    confidence = 1.0 - (unknown_count / len(questions))
    
    # 5. 生成推荐顺序
    recommended_order = sorted(
        distribution.keys(),
        key=lambda x: distribution[x],
        reverse=True,
    )
    
    return {
        "source": "experience",
        "experience_id": experience_id,
        "distribution": distribution,
        "transition": transition,
        "recommended_order": recommended_order,
        "confidence": confidence,
        "unknown_count": unknown_count,
    }
```

### 5.3 测试计划

**coverage_config 测试**：
- 已知岗位 + 难度返回指定阈值
- 未知岗位/难度回退 `agent_llm/mid`
- 节奏学习配置调整阈值

**rhythm_profile 测试**：
- 面经题目可分类并生成 distribution/transition
- 低质量面经返回低 confidence
- 读取面经时必须校验 owner/status/job_position

---

## 第六章：Interview State 快照

### 6.1 interview_state.py 设计

**文件位置**：`backend/app/agents/chat/interview_state.py`

**核心功能**：
- 从 InterviewLedger 构建覆盖度快照
- 序列化为可保存的格式
- 注入到 ChatState

**代码结构**：
```python
"""Interview state snapshot management."""

import time
from dataclasses import dataclass, asdict
from typing import Optional

from app.agents.chat.coverage_config import (
    InterviewPhase,
    get_coverage_thresholds,
)
from app.agents.chat.question_plan import InterviewLedger, _big_tech_phase_counts


@dataclass
class InterviewStateSnapshot:
    """面试状态快照，保存进 assistant message metadata"""
    conversation_id: str
    job_position: str
    difficulty: str
    current_phase: str
    next_focus: Optional[str]
    turn_count: int
    coverage: dict[str, dict[str, int | bool]]
    last_answer_evaluation: Optional[dict]
    recent_decisions: list[dict]
    rhythm_profile: dict
    generated_at: float


def build_interview_state_snapshot(
    state: dict,
    ledger: InterviewLedger,
    rhythm_profile: Optional[dict] = None,
) -> dict:
    """从 ChatState 和 InterviewLedger 构建面试状态快照"""
    conversation_id = state.get("conversation_id", "")
    job_position = state.get("job_position", "agent_llm")
    difficulty = state.get("difficulty", "mid")
    
    # 获取覆盖度阈值
    thresholds = get_coverage_thresholds(job_position, difficulty, rhythm_profile)
    
    # 从 ledger 获取当前覆盖度
    phase_counts = _big_tech_phase_counts(ledger)
    
    # 构建覆盖度快照
    coverage = {}
    for phase in InterviewPhase:
        if phase == InterviewPhase.WARMUP or phase == InterviewPhase.WRAP_UP:
            continue
        current_count = phase_counts.get(phase.value, 0)
        threshold = thresholds.get(phase.value, 0)
        coverage[phase.value] = {
            "current_count": current_count,
            "threshold": threshold,
            "is_covered": current_count >= threshold,
        }
    
    # 确定当前阶段和下一焦点
    current_phase = _determine_current_phase(coverage, phase_counts)
    next_focus = _determine_next_focus(coverage, current_phase)
    
    # 构建快照
    snapshot = InterviewStateSnapshot(
        conversation_id=conversation_id,
        job_position=job_position,
        difficulty=difficulty,
        current_phase=current_phase,
        next_focus=next_focus,
        turn_count=len(state.get("message_history", [])),
        coverage=coverage,
        last_answer_evaluation=state.get("last_answer_evaluation"),
        recent_decisions=state.get("recent_decisions", []),
        rhythm_profile=rhythm_profile or {},
        generated_at=time.time(),
    )
    
    return asdict(snapshot)


def _determine_current_phase(
    coverage: dict[str, dict],
    phase_counts: dict[str, int],
) -> str:
    """确定当前面试阶段"""
    # 1. 如果有未覆盖的阶段，优先选择
    for phase, info in coverage.items():
        if not info["is_covered"]:
            return phase
    
    # 2. 如果所有阶段都已覆盖，选择计数最多的
    if phase_counts:
        return max(phase_counts, key=phase_counts.get)
    
    # 3. 默认返回 project_followup
    return "project_followup"


def _determine_next_focus(
    coverage: dict[str, dict],
    current_phase: str,
) -> Optional[str]:
    """确定下一焦点阶段"""
    # 1. 找到未覆盖的阶段
    uncovered = [
        phase for phase, info in coverage.items()
        if not info["is_covered"] and phase != current_phase
    ]
    
    if uncovered:
        # 2. 优先选择阈值最高的未覆盖阶段
        return max(uncovered, key=lambda p: coverage[p]["threshold"])
    
    # 3. 如果所有阶段都已覆盖，返回 None
    return None
```

### 6.2 Pipeline 集成

**在 _step_load_context 中注入 interview_state**：
```python
async def _step_load_context(state: ChatState) -> ChatState:
    # ... 现有代码 ...
    
    # 构建 interview_state 快照
    from app.agents.chat.interview_state import build_interview_state_snapshot
    from app.agents.chat.question_plan import _build_interview_ledger
    
    ledger = _build_interview_ledger(state)
    rhythm_profile = state.get("rhythm_profile")
    interview_state = build_interview_state_snapshot(state, ledger, rhythm_profile)
    state["interview_state"] = interview_state
    
    return state
```

**在 done metadata 中持久化 interview_state**：
```python
# 在 pipeline.py 的 _run_pipeline 中
metadata["interview_state"] = state.get("interview_state", {})
metadata["observability"] = {
    "thinking_duration": metadata.get("thinking_duration", 0),
    "step_count": len(metadata.get("steps", [])),
    "active_skills": metadata.get("active_skills", []),
    "tool_trace_persisted": False,
}
```

### 6.3 测试计划

**interview_state 测试**：
- 能从 InterviewLedger 构建覆盖度快照
- Enum/string 可 JSON 序列化
- 旧消息缺 metadata 时不崩

**Pipeline 测试**：
- run_chat() 的 done metadata 包含 interview_state
- interview_state 包含 current_phase、next_focus、coverage

---

## 第七章：Create Conversation 修改

### 7.1 后端 CreateConversationRequest 修改

**当前实现**（`backend/app/models/schemas.py`）：
```python
class CreateConversationRequest(BaseModel):
    mode: str = Field(..., pattern="^(jd_resume|free_practice)$")
    title: str | None = None
    jd_id: int | None = None
    resume_text: str | None = None
```

**修改方案**：增加 `difficulty` 和 `experience_id` 字段
```python
class CreateConversationRequest(BaseModel):
    mode: str = Field(..., pattern="^(jd_resume|free_practice)$")
    title: str | None = None
    jd_id: int | None = None
    resume_text: str | None = None
    difficulty: str | None = Field(None, pattern="^(junior|mid|senior|staff_plus)$")
    experience_id: int | None = None
```

### 7.2 后端创建流程修改

**在 chat_service.py 中修改 create_conversation**：
```python
def create_conversation(
    user_id: int,
    mode: str,
    title: str | None = None,
    jd_id: int | None = None,
    resume_text: str | None = None,
    difficulty: str | None = None,
    experience_id: int | None = None,
) -> dict:
    """创建会话，保存 interview_config"""
    # 1. 解析 difficulty，默认 mid
    difficulty = difficulty or "mid"
    
    # 2. 用当前用户 profile 得到 job_position
    job_position = get_user_job_position(user_id)
    
    # 3. 如果有 experience_id，按权限过滤并构建 rhythm_profile
    rhythm_profile = None
    if experience_id:
        from app.agents.chat.rhythm_profile import build_rhythm_profile
        rhythm_profile = build_rhythm_profile(experience_id, user_id, job_position)
    
    # 4. 合成 coverage_thresholds
    from app.agents.chat.coverage_config import get_coverage_thresholds
    coverage_thresholds = get_coverage_thresholds(job_position, difficulty, rhythm_profile)
    
    # 5. 写入 chat_conversations.metadata.interview_config
    conversation = _create_conversation_in_db(user_id, mode, title, jd_id, resume_text)
    
    interview_config = {
        "difficulty": difficulty,
        "experience_id": experience_id,
        "rhythm_profile_id": f"experience:{experience_id}" if experience_id else None,
        "coverage_thresholds": coverage_thresholds,
    }
    
    update_conversation_metadata(
        conversation["id"],
        {"interview_config": interview_config},
    )
    
    return conversation
```

### 7.3 前端 MockInterview.vue 修改

**当前实现**：
- 只有模式选择（jd_resume/free_practice）

**修改方案**：添加难度和面经选择
```vue
<template>
  <!-- 现有代码 -->
  
  <!-- 难度选择 -->
  <div class="mb-4">
    <label class="block text-sm font-medium mb-2">面试难度</label>
    <select v-model="difficulty" class="w-full p-2 border rounded">
      <option value="junior">初级</option>
      <option value="mid">中级</option>
      <option value="senior">高级</option>
      <option value="staff_plus">专家</option>
    </select>
  </div>
  
  <!-- 面经选择（可选） -->
  <div class="mb-4">
    <label class="block text-sm font-medium mb-2">面经来源（可选）</label>
    <select v-model="experienceId" class="w-full p-2 border rounded">
      <option :value="null">不使用面经</option>
      <option v-for="exp in experiences" :key="exp.id" :value="exp.id">
        {{ exp.company }} - {{ exp.round }}
      </option>
    </select>
  </div>
</template>

<script setup>
const difficulty = ref('mid')
const experienceId = ref(null)
const experiences = ref([])

// 加载面经列表
onMounted(async () => {
  const response = await interviewApi.getExperiences()
  experiences.value = response.data
})

// 创建会话
async function createConversation() {
  const response = await chatApi.createConversation({
    mode: mode.value,
    difficulty: difficulty.value,
    experience_id: experienceId.value,
  })
  // ...
}
</script>
```

### 7.4 测试计划

**Router/Service 测试**：
- 创建会话保存 interview_config
- experience_id 越权返回 404 或 403
- difficulty 默认 mid

**前端测试**：
- 难度选择正常工作
- 面经选择正常工作
- 创建会话时传递 difficulty 和 experience_id

---

## 第八章：Prompt 构建与 Done Metadata

### 8.1 Prompt 构建修改

**在 nodes.py 中修改 build_react_system_prompt**：
```python
def build_react_system_prompt(state: ChatState) -> str:
    """构建 ReAct 系统提示，注入 interview_state 上下文"""
    # ... 现有代码 ...
    
    # 注入 interview_state 上下文
    interview_state = state.get("interview_state")
    if interview_state:
        prompt += "\n\n<interview_state>\n"
        prompt += f"当前阶段: {interview_state.get('current_phase', 'unknown')}\n"
        prompt += f"下一焦点: {interview_state.get('next_focus', 'none')}\n"
        
        coverage = interview_state.get("coverage", {})
        if coverage:
            prompt += "覆盖度:\n"
            for phase, info in coverage.items():
                status = "✓" if info["is_covered"] else "○"
                prompt += f"  {phase}: {info['current_count']}/{info['threshold']} {status}\n"
        
        prompt += "</interview_state>"
    
    return prompt
```

### 8.2 Done Metadata 修改

**在 pipeline.py 中修改 done metadata**：
```python
# 在 _run_pipeline 中
if event_type == "done":
    metadata = event.get("metadata", {})
    built_metadata, clean_response = _build_react_metadata(state, response)
    if built_metadata:
        metadata = {**built_metadata, **metadata}
    
    # 添加 interview_state 和 observability
    metadata["interview_state"] = state.get("interview_state", {})
    metadata["observability"] = {
        "thinking_duration": metadata.get("thinking_duration", 0),
        "step_count": len(metadata.get("steps", [])),
        "active_skills": metadata.get("active_skills", []),
        "tool_trace_persisted": False,
    }
    
    response = clean_response
    _emit({"type": "basis", **_basis_event_payload(metadata)})
    _emit({"type": "done", "metadata": metadata})
```

### 8.3 测试计划

**Prompt 构建测试**：
- interview_state 注入到系统提示
- 覆盖度信息正确显示
- 无 interview_state 时不注入

**Done Metadata 测试**：
- done metadata 包含 interview_state
- done metadata 包含 observability
- interview_state 包含 current_phase、next_focus、coverage

---

## 第九章：实施顺序与验收标准

### 9.1 实施顺序

按照 spec 中的实施顺序，逐步实现每个功能：

1. **修正 thinking metadata 收集字段**（后端）
   - 修改 `pipeline.py` 第 490-491 行
   - 优先 `content`，fallback 到 `data.text`

2. **统一前端历史 thinking 渲染**（前端）
   - 修改 `ChatMessage.vue` 第 21 行
   - 兼容旧格式字符串和新格式 list chunks

3. **增强 load_skill step**（后端）
   - 修改 `react_loop.py` 第 535-541 行
   - 在 step 事件中添加 `skill_name`

4. **增强 tool step 摘要**（后端）
   - 修改 `pipeline.py`，新增 `tool_steps` 字段
   - 修改 `react_loop.py`，收集 tool_step 事件

5. **添加 coverage_config.py 和 rhythm_profile.py**（后端）
   - 新建 `backend/app/agents/chat/coverage_config.py`
   - 新建 `backend/app/agents/chat/rhythm_profile.py`

6. **添加 interview_state.py**（后端）
   - 新建 `backend/app/agents/chat/interview_state.py`
   - 复用现有的 InterviewLedger

7. **修改 create conversation**（后端 + 前端）
   - 修改 `backend/app/models/schemas.py`
   - 修改 `backend/app/services/chat_service.py`
   - 修改 `frontend/src/components/business/MockInterview.vue`

8. **修改 _step_load_context / prompt 构建**（后端）
   - 修改 `backend/app/agents/chat/pipeline.py`
   - 修改 `backend/app/agents/chat/nodes.py`

9. **修改 done metadata**（后端）
   - 修改 `backend/app/agents/chat/pipeline.py`
   - 持久化 `interview_state` 和 observability 摘要

10. **添加 chat_tool_traces 审计表**（后端）
    - 修改 `backend/app/db/migrations/`
    - 添加写入逻辑

### 9.2 验收标准

**功能验收**：
- 新会话能配置 difficulty，可选指定面经节奏来源
- 同一会话多轮后，`GET /messages` 中 assistant metadata 包含可恢复的 `interview_state`
- 页面刷新后能看到每轮 assistant 的思考耗时、thinking 内容、已加载 skill 名称、工具步骤摘要和采用题目
- 完整 raw tool call 不暴露给前端
- 越权 `experience_id` 不能读取

**测试验收**：
- `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q` 通过
- 前端 build 通过
- 前端 smoke test 通过

**性能验收**：
- metadata 体积不显著膨胀
- thinking chunks 限制在 50 个以内
- tool_steps 限制在 10 个以内

### 9.3 风险控制

**metadata 体积膨胀**：
- thinking chunks 限制在 50 个以内
- tool_steps 限制在 10 个以内
- interview_state 只保存必要字段

**阶段分类不准**：
- 保留 confidence 和 unknown_count
- 低置信面经只使用默认岗位阈值

**状态双写分裂**：
- InterviewLedger 是重建来源
- interview_state 是快照
- 不允许两边各自独立推进

**隐私泄露**：
- tool trace 只保存脱敏 args 和摘要
- 不保存 skill 全文、完整 retrieved items、用户隐私原文

---

## 附录：参考文件

- `backend/app/agents/chat/CLAUDE.md`
- `backend/app/agents/chat/pipeline.py`
- `backend/app/agents/chat/react_loop.py`
- `backend/app/agents/chat/question_plan.py`
- `backend/app/agents/chat/metadata.py`
- `backend/app/agents/chat/answer.py`
- `backend/app/routers/chat.py`
- `backend/app/services/chat_service.py`
- `backend/app/mcp_server/session.py`
- `backend/app/db/migrations/chat.py`
- `backend/app/db/migrations/question_bank.py`
