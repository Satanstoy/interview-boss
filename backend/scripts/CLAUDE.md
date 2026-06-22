# Backend Scripts — 运维脚本目录

一次性运维脚本、数据修复工具、手动验证脚本。

## 文件清单

| 文件 | 用途 |
|------|------|
| `check_embedding_health.py` | Embedding 服务健康检查（环境变量 / 模型文件 / 编码测试 / 覆盖率） |
| `backfill_embeddings.py` | 批量回填 question_bank 表中缺失的 embedding 向量 |
| `verify_chat_tools_real_e2e.py` | 真实后端 + 真实 LLM 的 chat tools 稳定性手动 E2E 验证 |

## 用法

```bash
# 健康检查
docker compose exec backend uv run python backend/scripts/check_embedding_health.py

# 回填 embedding（预览）
docker compose exec backend uv run python backend/scripts/backfill_embeddings.py --dry-run

# 回填 embedding（执行）
docker compose exec backend uv run python backend/scripts/backfill_embeddings.py --limit 100 --batch-size 32

# 真实 chat tools E2E（会调用真实 LLM）
RUN_REAL_CHAT_E2E=1 E2E_USERNAME=<user> E2E_PASSWORD=<password> \
  docker compose exec backend uv run python backend/scripts/verify_chat_tools_real_e2e.py
```

## 安全警告

脚本直接操作生产数据库，运行前请确认。破坏性操作前必须备份。
