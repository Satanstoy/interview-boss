# Submit Agent — JD/面经提交流程

LangGraph 状态机：识别类型 → 提取结构化数据 → 分类打标 → 入库。

## 流程

```
START → recognize → extract → classify → [persist_personal | persist_public | cluster_public] → END
```

## 节点说明

| 节点 | 文件 | 职责 |
|------|------|------|
| `recognize_node` | `extract.py` | 识别文本类型（JD/面经） |
| `extract_node` | `extract.py` | LLM 提取结构化数据 |
| `classify_node` | `classify.py` | LLM 分类打标（cat1/cat2/tags/difficulty） |
| `complete_node` | `classify.py` | 补全缺失分类 |
| `persist_personal_node` | `persist_personal.py` | 个人题库入库 |
| `persist_public_node` | `persist_public.py` | 公共题库入库 |
| `cluster_public_node` | `persist_public.py` | LLM 聚类去重 |

## 关键依赖

- `classify.py` 调用 `run_db(lambda: get_taxonomy_for_position(...))` 获取分类体系
- `extract.py` 使用黑名单过滤低质量题目
- `graph.py` 中的 `after_extract` / `after_classify` 条件路由决定流程分支

## 修改后必做

1. 运行 `uv run pytest backend/tests/pipeline/ -q`
2. 更新本文件
