# Tests — Infra 测试

基础设施测试：数据库、migration、config 热加载。

`test_worker.py` 同时锁定 ARQ 任务注册数量；新增 worker 任务时应先更新其断言并覆盖入队/执行契约。定时聚类质量审查还必须覆盖审计完成后生成管理员待审清单的调用链。

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/infra/ -q
```
