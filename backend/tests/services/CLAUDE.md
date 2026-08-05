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
| `test_settings_position_switch.py` | 设置页岗位切换 |
| `test_source_display.py` | 来源展示 |
| `test_title_service.py` | 标题生成 |
| `clustering/` | 聚类相关测试子目录（质量、稳定性、频率、来源、压缩、v2、孤岛修复等 20+ 文件） |

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/ -q
```
