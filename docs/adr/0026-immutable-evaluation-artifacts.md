# ADR-0026: 评测结果采用数据库索引与不可变 Artifact 分离存储

**Status:** accepted

评测系统不把完整 E2E 轨迹、工具调用、Judge 证据和报告全部塞入关系型数据库。数据库保存可查询的状态、摘要、引用关系和 Artifact 元数据；完整原文写入不可变 Artifact 存储。

1.0 使用 Docker bind mount 下的本地 Artifact 目录作为存储实现，并沿用现有 `backend/data/evaluations` 目录作为兼容入口。Artifact 路径应按系统版本、Batch、Run、Item 和 Attempt 分层，例如：

```text
evaluations/<system-release>/<batch-id>/<run-id>/<item-id>/<attempt-id>/
  transcript.json
  sse-events.jsonl
  tool-trace.jsonl
  judge-input.json
  judge-output.json
  report.json
```

每个 Artifact 的数据库记录至少包含 `artifact_id`、类型、相对路径或 URI、Schema 版本、字节大小、创建时间和 `content_digest`。写入采用临时文件、完整落盘、校验摘要、原子移动后再提交数据库引用；一旦被 Eval Run 引用，不得原地覆盖。

数据库可以保存面向列表和进度页的摘要，但管理员查看详情时必须能够通过 Artifact 引用加载原始证据。Artifact 中不得写入 API Key、Cookie 或其他运行时秘密。未来迁移到对象存储时，只替换 Artifact Store，不改变 Eval Run、Attempt 和事件模型。
