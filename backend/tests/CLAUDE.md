# Backend Tests — 测试目录

TDD 测试基础设施。遵循红-绿-重构循环。

## 命令

```bash
uv run pytest backend/tests/ -q                    # 全部测试
uv run pytest backend/tests/<dir>/ -q              # 子目录
uv run pytest backend/tests/test_xxx.py -v         # 单文件
uv run pytest backend/tests/test_xxx.py::test_func # 单个测试
```

## Fixtures（conftest.py 自动注入）

| Fixture | 作用 | 使用方式 |
|---------|------|---------|
| `test_db` | 内存 SQLite，自动建表/清表 | `def test_xxx(test_db):` |
| `mock_llm` | Mock AsyncOpenAI | `def test_xxx(mock_llm):` |
| `mock_redis` | Mock Redis | `def test_xxx(mock_redis):` |
| `client` | FastAPI TestClient | `def test_xxx(client): response = client.get("/api/...")` |

## 目录结构

| 目录 | 测试内容 |
|------|---------|
| `services/` | 业务逻辑测试（LLM、聚类、pipeline、chat 等） |
| `bank/` | 题库操作测试（模式、拆分、合并、编辑） |
| `chat/` | Chatbot 测试（agent、记忆、预算、路由） |
| `pipeline/` | 提交流程测试 |
| `taxonomy/` | 分类体系测试 |
| `security/` | 安全测试（认证、CSRF、注入） |
| `interview/` | 面试流程测试 |
| `infra/` | 基础设施测试（DB、migration、config） |
| `bugs/` | Bug 回归测试（BUG-XXX 命名） |

## 核心规则

- **测试先行**：先写失败测试，再写实现
- **隔离**：每个测试用独立的内存 DB，禁止共享状态
- **Mock 外部**：LLM、Redis、网络请求必须 mock
- **命名**：`test_<场景>_<预期行为>`
- **Bug 回归**：`bugs/test_bug_xxx.py` 中每个 bug 对应 `BUG-XXX` ID

## 修改后必做

1. 新增测试文件后运行确认全部通过
2. 更新本文件（如新增测试目录或改变规范）
