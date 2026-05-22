# Services 层 — 业务逻辑

所有业务逻辑在此层实现，路由层禁止包含业务逻辑。

## 文件职责

| 文件 | 职责 | 依赖 |
|------|------|------|
| `llm.py` | LLM 调用（OpenAI/Anthropic 双格式）、重试、流式输出 | `core/config` |
| `pipeline.py` | JD/面经提交处理流程（解析→去重→入库） | `llm`, `clustering` |
| `clustering.py` | LLM 聚类去重（cat2 预分组 + 两遍聚类） | `llm` |
| `chat_service.py` | 对话管理、消息存储、记忆提取 | `llm`, `memory_recall_service` |
| `fts_service.py` | FTS5 全文搜索 | `db/connection` |
| `memory_recall_service.py` | 用户长期记忆召回 | `db/connection` |
| `title_service.py` | 对话标题自动生成 | `llm` |
| `resume_service.py` | 简历 PDF 解析、存储、查询 | `db/connection` |
| `email_service.py` | 邮箱验证码发送/验证 | `core/config` |
| `taxonomy_suggest.py` | 分类建议 | `llm` |
| `utils.py` | 图片编码、URL 签名、分类规范化 | — |

## 核心规则

- LLM 调用必须通过 `llm.py` 的函数，禁止直接实例化 OpenAI client
- 重试逻辑用 tenacity，不要手写 retry 循环
- 错误处理：捕获异常后记录日志，向上抛出业务异常

## 修改后必做

1. 运行 `uv run pytest backend/tests/services/ -q`
2. 更新本文件（如新增文件或改变职责）
