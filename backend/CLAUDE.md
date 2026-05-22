# Backend — InterviewBoss

Python FastAPI 后端。此文件补充根目录 CLAUDE.md。

## 命令

```bash
cd /root/sj/interview-boss
uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000   # 开发
uv run pytest backend/tests/ -q                            # 测试
uv run pytest backend/tests/test_xxx.py -v                 # 单文件
uv sync                                                    # 安装依赖
uv add <package>                                           # 添加依赖
```

禁止 pip，必须用 uv（`/root/.local/bin/uv`）。

## TDD 工作流（强制）

**任何修 Bug 或新功能，必须按以下顺序执行：**

1. **先写测试（红灯）** — 在 `backend/tests/test_<模块>.py` 中写测试，运行确认失败
2. **最小实现（绿灯）** — 只写让测试通过的最少代码，不做任何扩展
3. **重构** — 测试通过后优化代码结构，每次改动后重跑测试
4. **一次一个测试** — 每个循环只处理一个测试用例

## 架构（4 层，依赖方向向内）

```
Routers → Services → Core/DB → (external)
```

### Routers (`app/routers/`) — 路由层

13 个 APIRouter，在 `asgi.py` 注册。**路由函数必须精简，禁止包含业务逻辑。**

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

## 修改前必读（避免盲目搜索）

| 你要做的事 | 先读这些文件 | 再读这些文件 |
|-----------|------------|------------|
| 修认证 Bug | `core/auth.py` | `routers/auth.py` |
| 改 LLM 答案生成 | `services/llm.py` + `core/prompts.py` | `routers/answers.py` |
| 改题目去重逻辑 | `services/clustering.py` | `db/queries.py` |
| 改提交流程 | `services/pipeline.py` | `routers/submit.py` + `agents/submit/` |
| 改数据库查询 | `db/queries.py` 或 `db/operations.py` | 对应的 `routers/*.py` |
| 改 Agent 流程 | `agents/<name>/graph.py` | `agents/shared/state.py` |
| 改配置热更新 | `core/config.py` | `routers/profile.py` |
| 新增 API 端点 | `asgi.py`（注册路由） | 新建 `routers/<name>.py` |

## 关键模式

- 题目去重：LLM 聚类（非 Embedding）
- 批量操作：SSE 流式推送进度
- 管理员：`users.is_admin`；审核上传题目流程
- 题库模式：公共/个人/混用
- DB 自动备份：破坏性操作前自动备份
- 配置热更新：`/api/profile` → DB + `.env`

## 测试基础设施

`conftest.py` 提供以下 fixtures（自动生效，无需手动导入）：

| Fixture | 作用 | 使用方式 |
|---------|------|---------|
| `test_db` | 内存 SQLite，自动建表/清表 | `def test_xxx(test_db):` |
| `mock_llm` | Mock AsyncOpenAI | `def test_xxx(mock_llm):` |
| `mock_redis` | Mock Redis | `def test_xxx(mock_redis):` |
| `client` | FastAPI TestClient | `def test_xxx(client): response = client.get("/api/...")` |

**pytest 配置**（`pyproject.toml`）：`asyncio_mode = "auto"`，无需手动加 `@pytest.mark.asyncio`。

## 环境变量（`backend/.env`）

`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL_NAME`, `JWT_SECRET`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `DEBUG`, `ALLOWED_ORIGINS`

## 详细规则

Python 编码规范和测试规则见 `.claude/rules/`：
- `python-backend.md` — 编辑 Python 文件时自动加载
- `test-files.md` — 编辑测试文件时自动加载

## 修改铁律

1. **修改后必须更新 CLAUDE.md** — 涉及文件增删、职责变更时，更新对应目录的 CLAUDE.md
2. **一组修改必须 commit** — 逻辑相关修改完成后立即提交
3. **新模块必须更新 README** — 新增功能后更新 README.md

子目录 CLAUDE.md 位置：`app/db/`、`app/services/`、`app/core/`、`app/agents/` 及其子目录、`app/routers/profile_pkg/`、`app/routers/questions_pkg/`、`tests/` 及其子目录。
