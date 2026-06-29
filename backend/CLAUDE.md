# Backend — InterviewBoss

> 位置：`backend/` | 下游：`frontend/` 通过 API 调用 | 部署：Docker 容器
> 职责：Python FastAPI 后端，提供 REST API + SSE 流式接口。

## 命令

```bash
# 开发/测试必须通过 Docker 容器执行（宿主机无 .venv）
docker compose exec backend uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000   # 开发
docker compose exec backend uv run pytest backend/tests/ -q                            # 测试
./deploy/docker-deploy.sh check backend                                               # 后端日常门禁（Docker test-runtime）
docker compose exec backend uv run pytest backend/tests/test_xxx.py -v                 # 单文件

# 依赖管理（在容器内执行）
docker compose exec backend uv sync                                                    # 安装依赖
docker compose exec backend uv add <package>                                           # 添加依赖
```

禁止宿主机直接 `uv run`，必须通过 Docker 容器执行。
后端日常门禁由 `./deploy/docker-deploy.sh check backend` 执行：构建 test-runtime、pytest collect-only、compileall，以及题库/infra/router 结构测试。

## 架构（4 层，依赖方向向内）

```
Routers → Services → Core/DB → (external)
```

### Routers (`app/routers/`) — 路由层
14 个 APIRouter，在 `asgi.py` 注册。**路由函数必须精简，禁止包含业务逻辑。**

### Services (`app/services/`) — 业务逻辑层
- `llm.py` — AsyncOpenAI + tenacity 重试
- `clustering.py` — LLM 聚类去重（cat2 预分组 + 两遍聚类）
- `pipeline.py` — 提交处理流程
- `embedding_service.py` — Embedding 向量编码 + FAISS 预筛选 + 置信度计算
- `chat_service.py` — 对话管理、记忆提取

### Core (`app/core/`) — 配置层
- `config.py` — 数据库热加载配置，同步回 `.env`
- `auth.py` — JWT Access (15min) + Refresh (HttpOnly Cookie, JTI 跟踪, 轮转)
- `prompts.py` — LLM 提示词模板

### DB (`app/db/`) — 数据库层
- `connection.py` — 线程级 SQLite（WAL），`run_db()` 用 `asyncio.to_thread()` 包装
- `operations.py` — 可复用 CRUD | `queries.py` — 查询函数
- `migrations.py` — Schema 迁移（`init_db()` 内联执行）

**数据库：** SQLite `backend/data/interview-boss.db`

### Agents (`app/agents/`) — LangGraph 状态机
`submit/`, `build/`, `batch_generate/`, `chat/` 四个 agent，共享 `shared/`。

### Scripts (`scripts/`) — 运维脚本
一次性运维脚本、数据修复工具。前缀：`fix_*.py`（修复）、`verify_*.py`（验证）、`check_*.py`（检查）。详见 `scripts/CLAUDE.md`。

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

## 修改前必读

| 你要做的事 | 先读这些文件 | 再读这些文件 |
|-----------|------------|------------|
| 修认证 Bug | `core/auth.py` | `routers/auth.py` |
| 改 LLM 答案生成 | `services/llm.py` + `core/prompts.py` | `routers/answers.py` |
| 改题目去重逻辑 | `services/clustering.py` | `db/queries.py` |
| 改提交流程 | `services/pipeline.py` | `routers/submit.py` + `agents/submit/` |
| 改数据库查询 | `db/queries.py` 或 `db/operations.py` | 对应的 `routers/*.py` |
| 改 Agent 流程 | `agents/<name>/graph.py` | `agents/shared/state.py` |
| 新增 API 端点 | `asgi.py`（注册路由） | 新建 `routers/<name>.py` |

## 关键模式

- 题目去重：LLM 聚类 + Embedding 预筛选（cluster_id 显式标识，frequency 记录合并数）
- 批量操作：SSE 流式推送进度
- 管理员：`users.is_admin`；审核上传题目流程
- DB 自动备份：破坏性操作前自动备份
- 配置热更新：`/api/profile` → DB + `.env`

## 面试 Agent 质量保护

面试 chat agent (`agents/chat/pipeline.py`) 包含以下质量保护机制：

### 结束意图硬路由
- 当 `intent == 'end_interview'` 时，**完全跳过 ReAct 循环**，不调用任何工具（load_skill / search_questions / draw_questions）
- 直接生成总结/收尾回复，保留 done/basis SSE 兼容
- `_build_tool_strategy()` 也为 end_interview 注入"禁止工具"指令作为双重保护
- 测试：`TestEndInterviewHardRoute`

### 重复追问节奏保护
- `_count_consecutive_similar_questions()` 用 overlap coefficient 检测连续相似追问
- 超过 `_MAX_CONSECUTIVE_SAME_QUESTION`（默认 2）次后，system prompt 注入硬约束
- 约束要求：给提示/记录短板换题/降级，禁止原样施压
- 测试：`TestRepetitionProtection`

### 抽题 difficulty 映射与降级
- `question_draw_service._map_difficulty()` 映射英文难度到中文模式：easy→L1/基础, medium→L2/中等, hard→L3/困难
- 带 difficulty 抽题返回 0 结果时，自动去掉 difficulty 重试
- 测试：`test_difficulty_mapping_*` 和 `test_difficulty_fallback_when_no_match`

### selected_question 绑定
- `_infer_selected_question()` 新增 single-candidate heuristic：draw 单候选 + 响应有 token overlap 时自动绑定
- 测试：`TestSelectedQuestionBinding`

## 测试基础设施

`conftest.py` 提供 fixtures（自动生效，无需手动导入）：

| Fixture | 作用 | 使用方式 |
|---------|------|---------|
| `test_db` | 内存 SQLite，自动建表/清表 | `def test_xxx(test_db):` |
| `mock_llm` | Mock AsyncOpenAI | `def test_xxx(mock_llm):` |
| `mock_redis` | Mock Redis | `def test_xxx(mock_redis):` |
| `client` | FastAPI TestClient | `def test_xxx(client):` |

**pytest 配置**：`asyncio_mode = "auto"`，无需手动加 `@pytest.mark.asyncio`。

## 测试代码安全规范（强制）

**测试代码不得硬编码敏感信息**，包括但不限于：
- 密码、API Key、Token
- 数据库连接字符串
- 私钥、证书

**正确做法**：
1. 使用环境变量：`os.environ.get("ADMIN_PASSWORD")`
2. 使用明显的测试占位符：`TEST_PASSWORD_PLACEHOLDER`
3. 使用 mock：`mock.patch("app.core.auth.verify_password", return_value=True)`

**禁止**：
- 硬编码真实密码或 API Key
- 在测试代码中提交 `.env` 文件
- 在测试日志中输出敏感信息

## 环境变量（`backend/.env`）

`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL_NAME`, `JWT_SECRET`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `DEBUG`, `ALLOWED_ORIGINS`

## 详细规则

Python 编码规范和测试规则见 `.claude/rules/`：
- `python-backend.md` — 编辑 Python 文件时自动加载
- `test-files.md` — 编辑测试文件时自动加载
