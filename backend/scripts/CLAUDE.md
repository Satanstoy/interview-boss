# Backend Scripts — 运维脚本目录

一次性运维脚本、数据修复工具、手动验证脚本。

## 快速参考：脚本分类

| 类型 | 运行方式 | 环境变量 | 何时用 |
|------|---------|---------|--------|
| **pytest 测试** | `docker compose --profile test run --rm test uv run pytest backend/tests/` | 无 | CI/日常开发 |
| **真实 E2E 验证** | `docker compose exec backend uv run python backend/scripts/verify_*.py` | `RUN_REAL_*=1` | 手动验证、发版前 |
| **评测框架** | `docker compose exec backend uv run python backend/scripts/eval_interview_agent.py` | `RUN_REAL_INTERVIEW_EVAL=1` | 质量评估、回归测试 |
| **数据修复** | `docker compose exec backend uv run python backend/scripts/fix_*.py` | 无 | 一次性数据修复 |
| **健康检查** | `docker compose exec backend uv run python backend/scripts/check_*.py` | 无 | 运维诊断 |

**关键区别**：
- `backend/tests/` 下的文件由 **pytest 自动收集**，CI 会跑
- `backend/scripts/` 下的文件是 **手动运行**，CI 不跑（除非显式调用）
- `verify_*.py` 和 `eval_interview_agent.py` 需要 **真实 LLM API**，默认拒绝运行

## 文件清单

| 文件 | 用途 |
|------|------|
| `check_embedding_health.py` | Embedding 服务健康检查（环境变量 / 模型文件 / 编码测试 / 覆盖率） |
| `backfill_embeddings.py` | 批量回填 question_bank 表中缺失的 embedding 向量 |
| `eval_interview_agent.py` | 统一 Interview Agent 评测框架（多场景、LLM 候选人、评分、JSON/MD 报告） |
| `verify_chat_tools_real_e2e.py` | 真实后端 + 真实 LLM 的 chat tools 稳定性手动 E2E 验证 |
| `verify_interview_agent_real_e2e.py` | 真实后端面试官 + 轻量 LLM 候选人的多轮模拟面试质量验证 |
| `verify_interview_distribution_e2e.py` | 校验默认统计；传 `--exercise-runtime` 时还会创建真实会话、完成冻结计划，并验证实际计数、题库绑定与题库默认分布对齐；必须设置 `RUN_REAL_INTERVIEW_DISTRIBUTION_E2E=1` |
| `verify_compaction_*.py` / `evaluate_clustering.py` | 聚类/孤岛碎片整理的真实库验证和质量评估 |
| `mock_clustering_approaches.py` | 聚类策略 mock 对比脚本（产出 `mock_clustering_report.json`） |
| `rescore_with_judge.py` | 用 judge 模型对已有评测结果重新评分 |
| `fix_sources_frequency.py` | 来源数量/frequency 修复脚本 |
| `fix_duplicate_of_mirrors.py` | 清理历史 duplicate_of 镜像题（软删除，--dry-run 预览） |
| `eval_framework/` | Interview Agent 评测框架内部模块（candidate、scenarios、rubrics、scoring、reports、metrics、http_client、runner、types）；由 `eval_interview_agent.py` 调用；每轮请求必须携带 `client_request_id`，并用 turn status 对账 SSE terminal |

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

# 真实多轮模拟面试 E2E（会调用真实 LLM；候选人 agent 从 CANDIDATE_* 或系统 OPENAI_* env 读取配置）
RUN_REAL_INTERVIEW_E2E=1 \
  docker compose exec backend uv run python backend/scripts/verify_interview_agent_real_e2e.py

# 真实分布控制 E2E（需传入短期 token；默认删除测试会话）
RUN_REAL_INTERVIEW_DISTRIBUTION_E2E=1 INTERVIEW_BOSS_E2E_TOKEN="$TOKEN" \
  docker compose exec backend uv run python backend/scripts/verify_interview_distribution_e2e.py \
    --base-url http://localhost:8000 --exercise-runtime --report /tmp/interview_distribution_runtime_e2e.json

# 统一 Interview Agent 评测框架（会调用真实后端和候选人 LLM）
RUN_REAL_INTERVIEW_EVAL=1 \
  docker compose exec backend uv run python backend/scripts/eval_interview_agent.py --scenario error_correction
```

## Chat tools E2E 观测

`verify_chat_tools_real_e2e.py` 会解析 Chat SSE 中拆分后的 `selected_question` 和 `question_plan` 事件，同时保留旧版 `done.metadata` fallback，用于区分工具调用、选题绑定、计划生成、repair/fallback 和内部标记泄露。对必须调工具的场景，verifier 使用 case 期望矩阵要求出现指定工具 step，避免 selected/question_plan 掩盖缺失工具调用。

## Interview agent E2E 观测

`verify_interview_agent_real_e2e.py` 通过真实 `/api/chat` SSE 调用系统面试官，同时用轻量候选人 LLM actor 根据简历和能力画像作答。脚本只从环境变量或参数读取候选人 LLM 配置，默认拒绝运行，必须设置 `RUN_REAL_INTERVIEW_E2E=1`。候选人侧变量优先级为 `CANDIDATE_OPENAI_API_KEY` / `CANDIDATE_OPENAI_BASE_URL` / `CANDIDATE_LLM_MODEL`，缺省回退到系统 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `LLM_MODEL_NAME`。默认清理测试 conversation，传 `--keep-conversation` 才保留。

## Interview Distribution E2E 观测

`verify_interview_distribution_e2e.py --exercise-runtime` 先读取当前岗位的公开默认统计，再用同一默认值创建模拟面试。它读取会话冻结 plan 与持久化 coverage events，要求 `actual_counts == soft_target_counts`、主问题数等于目标题数，且每一个计数事件都对应 high-confidence 的题库绑定题。默认删除测试会话，传 `--keep-conversation` 才保留排查证据。

## Interview Agent 评测框架

`eval_interview_agent.py` 固化长程面试、错误纠正和结束策略场景。运行前必须设置 `RUN_REAL_INTERVIEW_EVAL=1`，候选人 LLM 从 `CANDIDATE_OPENAI_API_KEY`、`CANDIDATE_OPENAI_BASE_URL` 或设计文档中的 `CANDIDATE_LLM_BASE_URL`、`CANDIDATE_LLM_MODEL` 读取；面试官认证可用 `EVAL_USER_NAME`/`EVAL_USER_PASSWORD` 或内部短期 token。报告写入 `backend/data/evaluations/`，默认运行后删除测试 conversation，传 `--keep-conversation` 才保留。

## 安全警告

脚本直接操作生产数据库，运行前请确认。破坏性操作前必须备份。
