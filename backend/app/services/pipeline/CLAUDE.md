# Pipeline — 批处理流水线

> 位置：`backend/app/services/pipeline/` | 上游调用方：`backend/app/services/clustering/`, `backend/app/services/submit_service.py`, `backend/app/agents/submit/` | 下游依赖：`backend/app/db/`, `backend/app/services/clustering/`
> 职责：增量聚类、完整流水线、孤岛碎片整理、队列管理、数据清洗。

## 文件职责

| 文件 | 职责 |
|------|------|
| `batch.py` | 增量聚类、完整流水线（主入口），共享写库辅助函数 |
| `batch_v2.py` | v2 版本，新增"孤岛匹配已有聚类"步骤 |
| `compact.py` | 孤岛碎片整理（frequency=1 题目合并），共享 `batch.py` 辅助函数 |
| `queue.py` | 队列操作：enqueue / dequeue / mark_done / mark_failed / trigger 判断 |
| `sanitize.py` | 数据清洗：剔除纯数字、非面试话术等脏数据（`BATCH_SIZE = 40`） |
| `writer.py` | 数据库写入：将聚类结果写入 question_bank 及关联表 |

## 核心规则

- 批处理入口在 `batch.py`，不要绕过直接调用内部函数
- 队列状态通过 `queue.py` 管理，禁止直接操作数据库队列表
- 数据清洗规则在 `sanitize.py` 的 `_BLACKLIST_PHRASES` 中维护
- 合并写库统一走 `batch.py` 的 helper，`frequency` 必须等于去重后的 `original_questions` 数量且最低为 1
- compaction 的 LLM 匹配必须二次验证；embedding 阈值不得作为自动合并依据

## 修改后必做

1. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/ -q`
2. 更新本文件（如新增文件或改变职责）
