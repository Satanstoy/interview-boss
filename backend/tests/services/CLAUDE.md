# Tests — Services 测试

业务逻辑层的单元测试和集成测试。

## 测试文件

| 文件 | 测试对象 |
|------|---------|
| `test_clustering_stability.py` | 聚类稳定性 |
| `test_clustering_maintenance.py` | 聚类维护与确定性数据修复 |
| `test_cluster.py` | 聚类逻辑 |
| `test_context_builder.py` | Chat 上下文构建 |
| `test_embedding_service.py` | ONNX/hash embedding 服务 |
| `test_fts_service.py` | FTS 全文搜索 |
| `test_llm_dual_format.py` | LLM 双格式解析（OpenAI/Anthropic） |
| `test_llm_tool_calling.py` | LLM tool calling 兼容 |
| `test_memory_flush.py` | 记忆刷新 |
| `test_memory_recall_rules.py` | 记忆召回规则 |
| `test_question_draw_service.py` | 抽题服务 |
| `test_resume_service.py` | 简历服务 |
| `test_router_refactor.py` | 路由拆分回归测试 |
| `test_session_search.py` | 会话搜索 |
| `test_title_service.py` | 标题生成 |

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/ -q
```
