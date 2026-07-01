# MCP 工具返回信封（Envelope）详细规范

所有 MCP 工具返回统一信封结构，由 `ToolEnvelope` Pydantic 模型定义。

## 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | `bool` | 调用是否成功。`true` 不代表一定有题目，需检查 `items` |
| `tool` | `string` | 工具标识：`search_questions`、`draw_questions`、`select_question` |
| `items` | `list[ToolQuestionItem]` | 题目列表（搜索/抽题返回），可能为空列表 |
| `selected_question` | `ToolQuestionItem \| null` | 仅选题工具返回时存在，绑定的那道题 |
| `question_plan` | `dict \| null` | 仅选题工具返回时存在，生成的出题计划 |
| `metadata` | `ToolMetadata` | 元数据（结果计数、降级信息、调试原因、耗时） |
| `error` | `ToolError \| null` | 错误信息（仅 `ok=false` 时存在） |

## ToolQuestionItem 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `int` | 题库题目 ID（正整数） |
| `question` | `string` | 题目文本（非空） |
| `cat1` | `string` | 一级分类（如 `B.Agent与LLM应用`） |
| `cat2` | `string` | 二级分类（如 `B2.RAG系统设计`） |
| `source` | `string` | 来源：`search`（搜索）或 `draw`（抽题） |
| `score` | `float \| null` | 匹配分数（搜索有，抽题可能无） |
| `reason` | `string` | 匹配/选中原因说明 |
| `tags` | `string` | 标签（逗号分隔） |
| `difficulty` | `string` | 难度（`L1/基础`、`L2/中等`、`L3/困难`） |
| `sources` | `list[dict]` | 来源链接列表 |

## ToolMetadata 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `result_count` | `int` | 结果数量 |
| `fallback_used` | `bool` | 是否使用了降级策略 |
| `fallback_steps` | `list[string]` | 降级步骤记录 |
| `empty_reason` | `string \| null` | 结果为空时的原因 |
| `debug_reason` | `string` | 调试原因（如 `fts_match`、`weighted_random`） |
| `metrics` | `ToolMetrics` | 耗时指标（毫秒） |

## ToolError 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `error_code` | `string` | 错误码（如 `NO_CANDIDATES`、`INDEX_OUT_OF_RANGE`、`NEGATIVE_TERM_FILTERED`） |
| `message` | `string` | 错误描述 |

## 示例信封

### 搜索成功（有结果）

```json
{
  "ok": true,
  "tool": "search_questions",
  "items": [
    {
      "id": 42,
      "question": "请解释 Redis 的 RDB 和 AOF 持久化方式的区别",
      "cat1": "C.基础原理",
      "cat2": "C1.数据库",
      "source": "search",
      "score": 0.87,
      "reason": "keyword_match",
      "tags": "Redis,持久化,数据库",
      "difficulty": "L2/中等",
      "sources": []
    }
  ],
  "metadata": {
    "result_count": 1,
    "fallback_used": false,
    "fallback_steps": [],
    "empty_reason": null,
    "debug_reason": "fts_match",
    "metrics": { "total_ms": 45 }
  },
  "error": null
}
```

### 搜索成功但无结果

```json
{
  "ok": true,
  "tool": "search_questions",
  "items": [],
  "metadata": {
    "result_count": 0,
    "fallback_used": true,
    "fallback_steps": ["fts_no_match", "vector_no_match"],
    "empty_reason": "no_matching_questions",
    "debug_reason": "all_retrieval_paths_empty",
    "metrics": { "total_ms": 120 }
  },
  "error": null
}
```

### 选题成功

```json
{
  "ok": true,
  "tool": "select_question",
  "items": [
    {
      "id": 42,
      "question": "请解释 Redis 的 RDB 和 AOF 持久化方式的区别",
      "cat1": "C.基础原理",
      "cat2": "C1.数据库",
      "source": "search",
      "score": null,
      "reason": "question_plan_bound",
      "tags": "Redis,持久化",
      "difficulty": "L2/中等",
      "sources": []
    }
  ],
  "selected_question": {
    "id": 42,
    "question": "请解释 Redis 的 RDB 和 AOF 持久化方式的区别",
    "cat1": "C.基础原理",
    "cat2": "C1.数据库",
    "source": "search",
    "score": null,
    "reason": "question_plan_bound",
    "tags": "Redis,持久化",
    "difficulty": "L2/中等",
    "sources": []
  },
  "question_plan": {
    "question_id": 42,
    "question_text": "请解释 Redis 的 RDB 和 AOF 持久化方式的区别",
    "intent": "knowledge_probe"
  },
  "metadata": {
    "result_count": 1,
    "fallback_used": false,
    "fallback_steps": [],
    "empty_reason": null,
    "debug_reason": "agent_explicit_selection",
    "metrics": { "total_ms": 0 }
  },
  "error": null
}
```

### 选题失败（无候选）

```json
{
  "ok": false,
  "tool": "select_question",
  "items": [],
  "metadata": {
    "result_count": 0,
    "fallback_used": false,
    "fallback_steps": [],
    "empty_reason": "no_viable_candidate",
    "debug_reason": "no_viable_candidate",
    "metrics": { "total_ms": 0 }
  },
  "error": {
    "error_code": "NO_CANDIDATES",
    "message": "No viable question candidate could be selected"
  }
}
```
