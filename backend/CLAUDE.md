# Backend — InterviewBoss

Python FastAPI 后端。此文件补充根目录 CLAUDE.md。

## 命令

```bash
cd /root/sj/interview-boss
uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000   # 开发
uv run pytest backend/tests/ -q                            # 测试
uv run pytest backend/tests/test_xxx.py -v                 # 单文件
uv run pytest backend/tests/test_xxx.py::test_func -v      # 单用例
uv sync                                                    # 安装依赖
uv add <package>                                           # 添加依赖
```

禁止 pip，必须用 uv（`/root/.local/bin/uv`）。

## TDD 工作流（强制）

**任何修 Bug 或新功能，必须按以下顺序执行：**

### 1. 先写测试（红灯）

在 `backend/tests/test_<模块>.py` 中写测试，运行确认**失败**：

```python
def test_<场景>_<预期行为>():
    # Arrange - 准备测试数据
    # Act - 执行被测函数
    # Assert - 验证结果
    assert result == expected
```

### 2. 最小实现（绿灯）

只写让测试通过的**最少代码**，不做任何扩展。运行确认**通过**。

### 3. 重构

测试通过后优化代码结构，每次改动后重新运行测试确认仍通过。

### 4. 一次一个测试

每个循环只处理一个测试用例，通过后再写下一个。

## 测试规则

### 数据库隔离（核心）

- 测试必须用 SQLite 内存库，**禁止连接生产数据库** `backend/data/interview-boss.db`
- 用 `app.dependency_overrides` 替换 DB 依赖，测试结束后必须 `app.dependency_overrides.clear()`
- 每个测试自动建表 + 清表，保证测试间完全隔离

```python
# conftest.py 中的标准 fixture
@pytest.fixture(autouse=True)
def override_db():
    conn = sqlite3.connect(":memory:")
    # ... 建表 + yield + 清表
    app.dependency_overrides[get_db] = lambda: conn
    yield conn
    conn.close()
    app.dependency_overrides.clear()
```

### Mock 外部服务

- **LLM API**：必须 mock `AsyncOpenAI`，禁止测试时调用真实 API（费钱且不稳定）
- **Redis**：mock `redis.Redis`，不依赖真实 Redis 服务
- **文件操作**：mock 文件读写，不产生临时文件

```python
@pytest.fixture
def mock_llm():
    with patch("app.services.llm.AsyncOpenAI") as mock:
        client = AsyncMock()
        mock.return_value = client
        yield client
```

### 测试命名

- 文件：`test_<模块>.py`
- 函数：`test_<场景>_<预期行为>`
- 模式：AAA（Arrange, Act, Assert）

## 架构（4 层，依赖方向向内）

```
Routers → Services → Core/DB → (external)
```

### Routers (`app/routers/`) — 路由层

13 个 APIRouter，在 `asgi.py` 注册。路由前缀：`/api/auth/*`, `/api/submit`, `/api/data/*`, `/api/master-bank/*`, `/api/analytics`, `/api/profile` 等。

**规则：路由处理函数必须保持精简，禁止包含业务逻辑。**

### Services (`app/services/`) — 业务逻辑层

- `llm.py` — AsyncOpenAI + tenacity 重试
- `clustering.py` — LLM 聚类去重（cat2 预分组 + 两遍聚类）
- `pipeline.py` — 提交处理流程
- `taxonomy_suggest.py` — 分类建议
- `utils.py` — 图片编码、URL 签名去重

### Core (`app/core/`) — 配置层

- `config.py` — 数据库热加载配置，同步回 `.env`
- `auth.py` — JWT Access (15min) + Refresh (HttpOnly Cookie, JTI 跟踪, 轮转)
- `prompts.py` — 4 个 LLM 提示词模板

### DB (`app/db/`) — 数据库层

- `connection.py` — 线程级 SQLite（WAL），`run_db()` 用 `asyncio.to_thread()` 包装
- `operations.py` — 可复用 CRUD
- `queries.py` — 查询函数
- `migrations.py` — Schema 迁移（`init_db()` 内联执行）

**数据库：** SQLite `backend/data/interview-boss.db`

### Agents (`app/agents/`) — LangGraph 状态机

`submit/`, `build/`, `batch_generate/` 三个 agent，共享 `shared/`（state.py, events.py, quality.py）。

## 代码路由表

| 功能 | 路由 | 业务逻辑 | 数据库 |
|------|------|---------|--------|
| 认证 | `routers/auth.py` | `core/auth.py` | `db/operations.py` |
| 提交 | `routers/submit.py` | `services/pipeline.py` | `db/operations.py` |
| 题库 | `routers/questions.py` + `bank_build.py` + `admin_review.py` | `services/clustering.py` | `db/queries.py` |
| 答案 | `routers/answers.py` | `services/llm.py` + `core/prompts.py` | `db/operations.py` |
| 练习 | `routers/practice.py` | — | `db/queries.py` |
| 面试 | `routers/interview.py` | — | `db/queries.py` |
| 分析 | `routers/analytics.py` | — | `db/queries.py` |
| 配置 | `routers/profile.py` | `core/config.py` | `db/operations.py` |
| Agent | — | `agents/submit/` `agents/build/` `agents/batch_generate/` | — |

## 关键模式

- 题目去重：LLM 聚类（非 Embedding）
- 批量操作：SSE 流式推送进度
- 管理员：`users.is_admin`；审核上传题目流程
- 题库模式：公共/个人/混用
- DB 自动备份：破坏性操作前自动备份
- 配置热更新：`/api/profile` → DB + `.env`

## Python 规则

- 所有函数签名必须有类型注解，禁止 `Any`
- 禁止 `print()`，用 loguru
- 所有 async 函数必须处理错误
- DB 查询用 `operations.py`/`queries.py`，禁止路由里裸 SQL
- Pydantic v2（`model_dump()` 不是 `.dict()`，`field_validator` 不是 `@validator`）
- 环境变量通过 `python-dotenv`，禁止硬编码密钥
- 禁止密码/token 出现在日志中

## 环境变量（`backend/.env`）

`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL_NAME`, `JWT_SECRET`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `DEBUG`, `ALLOWED_ORIGINS`

## 禁止

- 返回原始数据库错误给客户端
- 路由层写业务逻辑
- 绕过限流器
- 同步文件操作
