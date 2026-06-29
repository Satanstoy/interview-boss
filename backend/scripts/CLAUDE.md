# Backend Scripts — 运维脚本目录

一次性运维脚本、数据修复工具、手动验证脚本。

## 文件清单

| 文件 | 用途 |
|------|------|
| `check_embedding_health.py` | Embedding 服务健康检查（环境变量 / 模型文件 / 编码测试 / 覆盖率） |
| `backfill_embeddings.py` | 批量回填 question_bank 表中缺失的 embedding 向量 |
| `verify_chat_tools_real_e2e.py` | 真实后端 + 真实 LLM 的 chat tools 稳定性手动 E2E 验证 |
| `verify_compaction_*.py` / `evaluate_clustering.py` | 聚类/孤岛碎片整理的真实库验证和质量评估 |
| `fix_sources_frequency.py` | 来源数量/frequency 修复脚本 |

本目录还包含历史 `.md` 报告和 `.log/.json` 产物；不要把它们当成测试入口。新增手动验证脚本用 `verify_`，数据修复脚本用 `fix_`，健康检查用 `check_`。

## 用法

```bash
# 健康检查
docker compose exec backend uv run python backend/scripts/check_embedding_health.py

# 回填 embedding（预览）
docker compose exec backend uv run python backend/scripts/backfill_embeddings.py --dry-run

# 回填 embedding（执行）
docker compose exec backend uv run python backend/scripts/backfill_embeddings.py --limit 100 --batch-size 32

# 真实 chat tools E2E（会调用真实 LLM；默认给 sj 签发短期 token，使用 sj 的 LLM 配置）
RUN_REAL_CHAT_E2E=1 \
  docker compose exec backend uv run python backend/scripts/verify_chat_tools_real_e2e.py
```

## Chat tools E2E 观测

`verify_chat_tools_real_e2e.py` 会解析 Chat SSE 中拆分后的 `selected_question` 和 `question_plan` 事件，同时保留旧版 `done.metadata` fallback，用于区分工具调用、选题绑定、计划生成、repair/fallback 和内部标记泄露。对必须调工具的场景，verifier 使用 case 期望矩阵要求出现指定工具 step，避免 selected/question_plan 掩盖缺失工具调用。

## 安全警告

脚本直接操作生产数据库，运行前请确认。破坏性操作前必须备份。
