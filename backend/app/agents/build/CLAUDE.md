# Build Agent — 题库构建流程

LangGraph 状态机：备份 → 加载所有题目 → LLM 聚类 → 生成答案 → 写入题库。

## 流程

```
START → backup_db → load_all → cluster → generate_answers → write_to_db → END
```

## 节点说明

| 节点 | 职责 |
|------|------|
| `backup_db_node` | 操作前自动备份数据库 |
| `load_all_node` | 加载所有待处理的原始题目 |
| `cluster_node` | LLM 聚类去重 |
| `generate_answers_node` | 为每个聚类生成 AI 答案 |
| `write_to_db_node` | 写入 question_bank 表 |

## 修改后必做

1. 运行 `uv run pytest backend/tests/bank/ -q`
2. 更新本文件
