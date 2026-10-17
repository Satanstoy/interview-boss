# Tests — Pipeline 测试

JD/面经提交流程测试。

`test_interview_distribution_write_paths.py` 锁定新建、替换、流水线打标和直接分类改动都写入 linked typed facts，并把公共岗位的统计刷新作业置为 pending。

`test_upload_matching_outcomes.py` 锁定 AC-006 三态：**默认套件即可运行**（走标准 `test_db` fixture，不得再加 `UPLOAD_TEST_DB_PATH` 门禁——那等于 AC-006 从未验收）。断言必须落在队列级：failed 的题不进 `analysis_queue`、no_match 的题进队列；个人新 canonical 由队列（cluster worker）创建，节点同步不建题（`persist_unmatched=False`）。

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/ -q
```
