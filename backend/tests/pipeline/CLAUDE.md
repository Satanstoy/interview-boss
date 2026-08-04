# Tests — Pipeline 测试

JD/面经提交流程测试。

`test_interview_distribution_write_paths.py` 锁定新建、替换、流水线打标和直接分类改动都写入 linked typed facts，并把公共岗位的统计刷新作业置为 pending。

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/ -q
```
