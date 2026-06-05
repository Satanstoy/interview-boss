# Embedding 测试

> 位置：`backend/tests/embedding/` | 测试对象：`app/services/embedding_service.py`
> 职责：Embedding 向量编码 + FAISS 预筛选的单元测试。

## 运行

```bash
docker compose exec backend uv run pytest backend/tests/embedding/ -v
```
