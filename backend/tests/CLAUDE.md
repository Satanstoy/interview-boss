# Backend Tests — 测试目录

TDD 测试基础设施。遵循红-绿-重构循环。

## 命令

```bash
# 通过 Docker 容器执行测试
./deploy/docker-deploy.sh test -q                                             # 全部测试（构建/使用 test-runtime）
./deploy/docker-deploy.sh check backend                                       # 后端日常门禁
docker compose --profile test run --rm test uv run pytest backend/tests/<dir>/ -q
docker compose --profile test run --rm test uv run pytest backend/tests/test_xxx.py -v
docker compose --profile test run --rm test uv run pytest backend/tests/test_xxx.py::test_func -v
```

不要在生产 `backend` 容器里跑 pytest：该容器是 `app-runtime`，不安装 dev 依赖。定向测试可直接使用 `test` profile。

## 路径定位规则

结构测试必须从 repo root 或 `backend/app` 根定位文件，禁止使用脆弱的 `backend/tests/...` 相对路径推导源码位置。需要读取部署配置的测试应通过 Docker `test-runtime` 访问 `/app/Dockerfile`、`/app/docker-compose.yml`、`/app/.dockerignore`、`/app/nginx/` 和 `/app/deploy/`。

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
- **Reasoning 字段回归**：模拟 MiMo/DeepSeek 时使用 `reasoning_content`，断言非流式 `message.reasoning_content` 和流式 `delta.reasoning_content` 都进入 `thinking`/metadata 链路
- **Reasoning 语言契约**：`backend/tests/chat/test_react_prompt.py` 必须覆盖 `build_react_system_prompt()` 注入简体中文约束，确保 `reasoning_content` / 推理过程 / 工具调用分析默认要求中文
- **最终回答流式契约**：`backend/tests/chat/test_react_loop.py` 必须覆盖 ReAct 非流式草稿不会直接展示，最终面向候选人的回复走 `stream_llm_messages()` 分块输出；工具决策/最终流式生成异常必须覆盖“有限重试或直接返回 error、不 fallback 成候选题模板”；相关 E2E 不要硬编码单个 chunk
- **命名**：`test_<场景>_<预期行为>`
- **Bug 回归**：`bugs/test_bug_xxx.py` 中每个 bug 对应 `BUG-XXX` ID

## 文件命名规范

**本目录只放 pytest 测试文件**，必须使用 `test_` 前缀。

| 目录 | 用途 | 命名规范 |
|------|------|---------|
| `tests/` | pytest 自动化测试 | `test_*.py` |
| `scripts/` | 运维脚本、数据修复、手动验证 | `fix_*.py` / `verify_*.py` / `check_*.py` |

**禁止**：不要将手动验证脚本放在 tests 目录。验证脚本应放在 `scripts/` 目录，使用 `verify_` 前缀。

## 修改后必做

1. 新增测试文件后运行确认全部通过
2. 更新本文件（如新增测试目录或改变规范）
