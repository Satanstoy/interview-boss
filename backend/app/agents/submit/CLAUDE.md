# Submit Agent — JD/面经提交流程

LangGraph 状态机：识别类型 → 提取结构化数据 → 质量重试/补全 → 分类打标 → 按 target 入库/聚类。

## 流程

```
START → recognize → extract
  ├─ doc_type=jd → jd_persist → END
  ├─ 空题重试失败 → error_empty → END
  └─ complete → classify
       ├─ personal → match_persist_personal → cluster_public → END
       └─ public → persist_public → cluster_public → END
```

> 个人路径与公共路径统一：`match_and_persist_personal_node` 落库后调用
> `enqueue_questions(interview_id, owner_id=user_id)`，与公共路径共用
> `cluster_public_node` 完成聚类；`dequeue_batch` 按 owner_id 分桶保证
> 个人批与公共批不混，`cluster_batch` 通过 FAISSIndexManager
> `(job_position, owner_id)` 双层 key 严格隔离题库。

## 节点说明

| 节点 | 文件 | 职责 |
|------|------|------|
| `recognize_node` | `extract.py` | 识别文本类型（JD/面经） |
| `extract_node` | `extract.py` | LLM 提取结构化数据 |
| `complete_node` | `classify.py` | 补全缺失分类 |
| `classify_node` | `classify.py` | LLM 分类打标（cat1/cat2/tags/difficulty） |
| `retry_extract_node` / `retry_classify_node` | `extract.py` / `classify.py` | 质量不足时重试 |
| `match_and_persist_personal_node` | `persist_personal.py` | 个人题库匹配、入库、生成 answer_tasks |
| `jd_persist_node` / `error_empty_node` | `persist_personal.py` | JD 直接入库；空题错误结束 |
| `persist_public_node` | `persist_public.py` | 公共题库入库 |
| `cluster_public_node` | `persist_public.py` | 公共题库入库后的 LLM 聚类去重 |

## 关键依赖

- `classify.py` 调用 `run_db(lambda: get_taxonomy_for_position(...))` 获取分类体系
- `extract.py` 使用黑名单过滤低质量题目
- `graph.py` 中的 `after_extract` / `after_classify` 条件路由决定流程分支

## 修改后必做

1. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/ -q`
2. 更新本文件
