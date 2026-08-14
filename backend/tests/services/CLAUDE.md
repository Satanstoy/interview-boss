# Tests — Services 测试

业务逻辑层的单元测试和集成测试。

## 测试文件

| 文件 | 测试对象 |
|------|---------|
| `test_backend_bugs.py` | 后端 bug 回归 |
| `test_context_builder.py` | Chat 上下文构建 |
| `test_embedding_core.py` | Embedding 核心逻辑 |
| `test_embedding_service.py` | ONNX/hash embedding 服务 |
| `test_fts_service.py` | FTS 全文搜索 |
| `test_generate_answer_fix.py` | 答案生成修复 |
| `test_integration_bugs.py` | 集成 bug 回归 |
| `test_llm_dual_format.py` | LLM 双格式解析（OpenAI/Anthropic） |
| `test_llm_tool_calling.py` | LLM tool calling 兼容 |
| `test_memory_flush.py` | 记忆刷新 |
| `test_memory_recall_rules.py` | 记忆召回规则 |
| `test_position_management.py` | 岗位管理 |
| `test_question_draw_service.py` | 抽题服务 |
| `test_resume_service.py` | 简历服务 |
| `test_router_refactor.py` | 路由拆分回归测试 |
| `test_session_search.py` | 会话搜索 |
| `test_review_urgency_wiring.py` | review 端点接入 urgency/deadline：`_user_urgency` 助手（固定 today 测 deadline 选择）+ 端点记录复习 smoke |
| `test_review_idempotency.py` | 复习提交幂等键（audit D14）：同 `idempotency_key` 提交两次只写一行事件、SRS review_count 只 +1；不同键/无键照常推进；`/api/practice/review` 透传请求体 `idempotency_key` |
| `test_practice_due_queue.py` | 今日复习 due 队列：四桶排序、复习风险权重 = 动态来源数 × (5 - proficiency)（静态变体数不参与）、新题预算与动态频率排序、mastered 抽查 |
| `test_frequency_display_bugs.py` | 频率口径回归：动态频率 SQL 必须过滤 `qs.deleted_at`、同 URL 公共/私有面经去重、面经软删不计；题卡展示频率 = 活跃来源数（静态 6 / 动态 1 时显示 1，无来源显示 0） |
| `test_settings_position_switch.py` | 设置页岗位切换 |
| `test_source_display.py` | 来源展示 |
| `test_title_service.py` | 标题生成 |
| `test_admin_assistant_api.py` | 管理员 AI 助手：鉴权（401/403）、读工具即时执行、写操作内联确认门（staging 不改 DB + 批量置信度下限 0.85）、确认端点执行与审计（reviewed_by + action 日志）、会话持久化与 `[已执行操作]` 续接回执；mock `app.services.admin_assistant_service.llm_with_tools` |
| `test_question_variant_reconciliation.py` | 跨题簇原始题目扫描、来源迁移、规范化表同步、待审卡关闭、全局 ownership claim 与写入拦截 |
| `clustering/test_unmerged_quality.py` | 漏合并质量清单：孤岛预筛、LLM 判定、pending 幂等入列与管理员审批合并 |
| `clustering/` | 聚类相关测试子目录（质量、稳定性、频率、来源、压缩、v2、孤岛修复等 20+ 文件） |

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/ -q
```
