# 题目分类 1.1 与数据库迁移运行手册

## 结论

- 分类规则版本为 `1.1`。
- 项目 Harness 继续使用 `1.0`；分类评测新增 `question-tagging-eval@1.1`。
- 数据库变更由仓库内的 migration 102 执行，不由 Codex 直接连接生产库改数据。
- 迁移不调用 LLM。旧答案保留，但会被标记为 `answer_taxonomy_version IS NULL`，等待管理员按需批量刷新。

## 发布流程

1. 先在预发布数据库执行部署，确认 `schema_version` 已到 102。
2. 部署服务。应用启动时的 `run_migrations()` 会自动执行 migration 102；也可以使用部署脚本的迁移命令：

   ```bash
   sudo ./deploy/docker-deploy.sh migrate
   ```

3. 迁移前，版本化迁移 runner 会通过 SQLite backup API 创建：

   ```text
   backend/data/backups/pre_migration_v102_YYYYMMDD_HHMMSS.db
   ```

4. 在应用容器内执行只读校验：

   ```bash
   uv run python backend/scripts/verify_taxonomy_v11.py --json
   ```

   重点检查 `schema_version >= 102`、系统分类版本为 `1.1`、`invalid_category_count == 0`，以及 `answer_refresh_required` 的数量是否符合预期。

## 答案刷新

迁移成功不自动调用外部模型。管理员确认联网搜索配置和调用额度后，调用已有批量生成接口：

```http
POST /api/master-bank/batch-generate-answers
{
  "ids": [题目 ID 列表],
  "refresh_stale": true,
  "allow_no_search": false
}
```

`refresh_stale=true` 只会重新生成已有有效答案但答案分类版本不是 `1.1` 的题目；生成成功后写入 `answer_taxonomy_version = '1.1'`。题目列表和详情接口会返回 `answer_needs_refresh`，可据此分批投递。

## 失败与回滚

- migration 102 在一个事务中执行；执行异常时事务自动回滚，`schema_version` 不会记录 102。
- 若迁移已经提交但业务验证不通过，应停止应用写入，保留现场日志，并使用对应的 `pre_migration_v102_*.db` 快照恢复。恢复不是 Codex 自动执行的操作，需要数据库管理员确认目标文件和停机窗口。
- 答案刷新失败不会覆盖已有有效答案；失败题目保留旧答案并继续显示 `answer_needs_refresh=true`。
