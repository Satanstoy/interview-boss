# Embedding 测试

> 位置：`backend/tests/embedding/` | 测试对象：`backend/app/services/embedding_service.py`
> 职责：Embedding 向量编码 + FAISS 预筛选的单元测试。

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/embedding/ -v
```
