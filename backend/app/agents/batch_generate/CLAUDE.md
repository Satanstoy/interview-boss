# Batch Generate Agent — 批量答案生成

LangGraph 状态机：加载指定题目 → 逐题生成并写回 AI 答案 → 汇总结果。

## 流程

```
START → load_questions → generate_answer ↺ → summarize → END
```

`generate_answer_node` 自身负责生成、质量评估和写回；`should_continue_generate` 决定继续下一题或进入 `summarize`。

## 修改后必做

1. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/ -q`
2. 更新本文件
