# Tests — Infra 测试

基础设施测试：数据库、migration、config 热加载。

## 运行

```bash
docker compose exec backend uv run pytest backend/tests/infra/ -q
```
