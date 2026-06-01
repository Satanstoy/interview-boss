# Tests — Services 测试

业务逻辑层的单元测试和集成测试。

## 测试文件

| 文件 | 测试对象 |
|------|---------|
| `test_analysis_flow.py` | 数据分析流程 |
| `test_clustering_stability.py` | 聚类稳定性 |
| `test_cluster.py` | 聚类逻辑 |
| `test_context_builder.py` | Chat 上下文构建 |
| `test_llm_dual_format.py` | LLM 双格式解析（OpenAI/Anthropic） |
| `test_memory_flush.py` | 记忆刷新 |
| `test_resume_service.py` | 简历服务 |
| `test_router_refactor.py` | 路由拆分回归测试 |
| `test_session_search.py` | 会话搜索 |
| `test_title_service.py` | 标题生成 |

## 运行

```bash
uv run pytest backend/tests/services/ -q
```
