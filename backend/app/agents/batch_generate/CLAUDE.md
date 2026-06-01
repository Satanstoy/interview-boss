# Batch Generate Agent — 批量答案生成

LangGraph 状态机：加载无答案题目 → 逐题生成 AI 答案 → 写回数据库。

## 流程

```
START → load_questions → generate_answers → write_back → END
```

## 修改后必做

1. 运行 `uv run pytest backend/tests/ -q`
2. 更新本文件
