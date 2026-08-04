# Tests — Interview 测试

面试流程相关测试。

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/interview/ -q
```

`test_interview_distribution_storage.py` 覆盖面经题目事实表的 migration 042 和五类题型映射；修改题目关联或分类词表时必须运行该文件。
