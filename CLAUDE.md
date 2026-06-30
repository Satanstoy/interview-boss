# InterviewBoss Monorepo

中文 AI 面试备战平台。JD/面经 → 提取面试题 → LLM 分类打标聚类 → 口述级答案 + 模拟面试 + 知识图谱。

## Tech Stack

- **Backend**: Python 3.10 (uv, root `pyproject.toml`) / FastAPI / SQLite (WAL) / LangGraph
- **Frontend**: Vue 3 (Composition API) / Vue Router 4 / Vite / Tailwind CSS / shadcn-vue
- **Deploy**: Docker Compose → nginx 镜像内置前端 (port 80) → backend (8000) + redis (6379)，worker 通过 profile 按需启用
- **LLM**: OpenAI-compatible API (AsyncOpenAI + tenacity)
- **Embedding**: Xenova/bge-small-zh-v1.5 ONNX export (本地 HuggingFace 缓存，离线模式) + FAISS CPU

## Commands

```bash
# 开发测试
./deploy/docker-deploy.sh test -q                                  # 后端全量测试（test-runtime 镜像）
./deploy/docker-deploy.sh check                                    # 日常质量门禁（后端 Docker + 前端 build/test + audit 报告）
cd frontend && npm run build                                       # 前端构建

# 后端定向测试（按功能域，必须通过 Docker）
docker compose --profile test run --rm test uv run pytest backend/tests/bank/ -q              # 题库管理
docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q              # 模拟面试
docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/ -q          # 提交流水线
docker compose --profile test run --rm test uv run pytest backend/tests/services/ -q          # 业务逻辑（含 clustering/）
docker compose --profile test run --rm test uv run pytest backend/tests/security/ -q          # 安全
docker compose --profile test run --rm test uv run pytest backend/tests/infra/ -q             # 基础设施

# 部署
./deploy/docker-deploy.sh update                         # 完整部署（重建镜像，后端/依赖变更时用）
./deploy/docker-deploy.sh frontend                       # 快速更新前端（npm build + docker cp，几秒生效）
./deploy/docker-deploy.sh status                         # 查看容器状态
./deploy/docker-deploy.sh logs backend                   # 查看后端日志
./deploy/docker-deploy.sh worker-up                      # 按需启动 ARQ Worker
./deploy/docker-deploy.sh backup                         # 备份数据库
./deploy/docker-deploy.sh diagnose                       # 磁盘/资源诊断
./deploy/docker-deploy.sh cleanup --dry-run              # 清理预览（等价 diagnose）
./deploy/docker-deploy.sh cleanup                        # 安全清理（BuildKit cache + dangling images）
./deploy/docker-deploy.sh mirrors                        # 手动刷新镜像源缓存和 Docker Hub mirror
```

**部署策略：**
- 仅改前端样式/组件 → `./deploy/docker-deploy.sh frontend`（几秒）
- 改后端代码/依赖 → `./deploy/docker-deploy.sh update`（完整构建）
- 两种都改 → 先 `frontend` 验证前端，再 `update` 完整部署

## 核心规范

- **TDD（强制）**：先写测试 → 确认失败 → 最少代码通过 → 重构。详见 `backend/CLAUDE.md` 和 `frontend/CLAUDE.md`。
- **日常门禁**：开发收尾优先跑 `./deploy/docker-deploy.sh check`；audit 第一阶段只报告不拦截。
- **Commit**：Conventional Commits（`feat(frontend):`、`fix(backend):`），英文。Git hook 自动检查。
- **Git 工作流**：本项目由用户单人维护。除非用户明确要求创建分支、PR 或 worktree，日常修改直接在 `master` 上进行并提交；不要为了常规改动自动创建 feature branch。
- **语言**：UI/提示词/文档中文简体，代码标识符英文。
- **禁止**：跨包引用源码、`--force`/`--no-verify`、在生产 `backend` 容器里跑 pytest。
- **依赖管理**：Python 依赖在根 `pyproject.toml`/`uv.lock`，用 `uv add X`；JS 依赖在 `frontend/`，用 `cd frontend && npm install X`。
- **运行方式**：pytest 必须走 Docker `test-runtime`（`./deploy/docker-deploy.sh test ...` 或 `docker compose --profile test run --rm test ...`）。生产 `backend` 容器是 `app-runtime`，不含 dev 依赖。

## 修改铁律

1. **修改后必须更新对应目录的 CLAUDE.md**（不更新 = 任务未完成）
2. **逻辑相关修改完成后必须立即 commit**（禁止积攒未提交改动）
3. **README 更新检查** — 详见 `.claude/rules/readme-checklist.md`
4. **完成阶段后执行门控流程** — 详见 `.claude/skills/gate-check.md`

## 架构

```
backend/
├── app/routers/       ← API 路由（HTTP 感知层，禁止业务逻辑）
├── app/services/      ← 业务逻辑（LLM 调用、聚类、pipeline）
├── app/core/          ← 配置、认证、提示词模板
├── app/db/            ← SQLite 连接、CRUD、查询、迁移
├── app/agents/        ← LangGraph 状态机（submit/build/batch_generate/chat）
├── app/models/        ← Pydantic schemas
└── tests/
    ├── bank/          ← 题库管理
    ├── chat/          ← 模拟面试
    ├── coding/        ← 手撕代码
    ├── infra/         ← 基础设施
    ├── interview/     ← 面试管理
    ├── pipeline/      ← 提交流水线
    ├── security/      ← 安全测试
    ├── services/      ← 业务逻辑
    │   └── clustering/ ← 聚类相关
    └── taxonomy/      ← 分类体系

frontend/
├── src/services/      ← API 服务层（按领域拆分），http.js 是 HTTP 客户端
├── src/composables/   ← 领域逻辑复用（use* 前缀）
├── src/layouts/       ← AuthenticatedLayout / BlankLayout / DefaultLayout
├── src/views/         ← Vue Router 页面
├── src/components/
│   ├── common/        ← 通用 UI（无业务依赖）
│   ├── business/      ← 业务组件
│   └── ui/            ← shadcn-vue 原始组件
├── src/utils/         ← 纯工具函数
└── tests/             ← Playwright E2E/diagnosis 测试

deploy/                ← 部署脚本（docker-deploy.sh 是生产用）
nginx/                 ← Docker Nginx 配置
docs/                  ← 历史经验库（bug-reports、tdd-reports、superpowers、analysis）
```

子目录各有自己的 CLAUDE.md，Claude 按需自动加载，不需要在此列出。

## 代码路由表

| 功能 | 后端文件 | 前端文件 |
|------|---------|---------|
| 登录/注册/刷新 | `routers/auth.py` + `core/auth.py` | `services/authApi.js` + `components/business/LoginModal.vue` |
| JD/面经提交 | `routers/submit.py` + `agents/submit/` + `services/pipeline/` | `views/ImportView.vue` + `components/business/StagingPanel.vue` + `services/dataApi.js` |
| 题库管理 | `routers/questions.py` + `routers/questions_pkg/` + `routers/admin_review.py` | `services/masterBankApi.js` + `components/business/MasterBankList.vue` |
| 答案生成 | `routers/answers.py` + `services/llm.py` | `services/practiceApi.js` |
| 练习/模拟面试 | `routers/practice.py` + `routers/interview.py` | `components/business/PracticePanel.vue` + `MockInterview.vue` |
| 数据分析 | `routers/analytics.py` | `services/analyticsApi.js` + `components/business/AnalyticsSidebar.vue` |
| 用户配置 | `routers/profile.py` + `routers/profile_pkg/` + `core/config.py` | `services/profileApi.js` + `components/business/SettingsPage.vue` |
| 手撕代码 | `routers/coding.py` | `services/codingApi.js` + `components/business/CodingPractice.vue` |
| 题目去重 | `services/clustering.py` | — |
| LLM 调用 | `services/llm.py` + `core/prompts.py` | — |
| 认证中间件 | `core/auth.py` | `services/http.js` |
| 数据库操作 | `db/operations.py` + `queries.py` | — |

## 测试基础设施

- **后端**：通过 Docker `test-runtime` 跑 pytest；`backend/tests/conftest.py` 提供 `test_db`（内存 SQLite）、`mock_llm`、`mock_redis`、`client` fixtures
- **前端**：Playwright 测试必须 mock API，禁止截图断言，禁止使用真实密码
- **日常门禁**：`./deploy/docker-deploy.sh check` 汇总后端 collect/compile/结构测试、前端 build/smoke test 和 audit WARN。
- **详细规则**：`.claude/rules/test-files.md`（编辑测试文件时自动加载）

## Gotchas

- Python 依赖管理用根目录 uv（`uv add`），测试必须通过 Docker `test-runtime` 执行，禁止宿主机直接 `uv run pytest`
- SQLite 迁移后必须重启 backend 容器
- `http.js` 的 `get()` 不自动转换 params，必须用 URLSearchParams
- 日志系统使用 structlog（生产 JSON / 开发彩色），前端错误通过 sendBeacon 上报到 `/api/error-report`
- Docker 日志轮转：每服务 max-size 10m × max-file 3，用 `docker compose logs backend | jq .` 查看结构化日志
- Docker 磁盘保护：部署必须走 `./deploy/docker-deploy.sh update/all/worker-up`，脚本会在构建前检查根分区至少 4GB 可用，构建后低于 5GB 时自动收缩 BuildKit cache（默认保留 2GB）。不要绕过脚本直接长期执行 `docker compose build`。
- Docker 镜像源策略：`update/build/test/worker-up` 默认复用版本化缓存/稳定默认源，只做短健康检查；健康检查失败才刷新 npm/PyPI/apt 源，避免每次部署改 build args 导致依赖层缓存失效，也避免旧脚本缓存的坏源污染后续 update。只有镜像源整体失效或首次配置机器时运行 `./deploy/docker-deploy.sh mirrors`，它会清缓存、完整测速并更新 Docker Hub registry mirror。
- Docker 部署预检：`update/build/test/worker-up` 在真正 build 前会检查生产依赖仍是 `uv export + pip install -i $PYPI_MIRROR`，compose build 仍保留 `network: host`。不要把生产依赖改回 `uv sync --frozen --no-dev --no-install-project`，否则 `uv.lock` 里的 `files.pythonhosted.org` 直链会绕过 PyPI 镜像并造成 update 卡住。
- Docker 构建 DNS：`docker-compose.yml` 的 build 使用 `network: host`，避免 systemd-resolved 的 `127.0.0.53` stub 让 BuildKit fallback 到不可控外部 DNS。`mirrors` 命令还会持久化 Docker daemon DNS，默认 `223.5.5.5,119.29.29.29`。
- 磁盘诊断：`./deploy/docker-deploy.sh diagnose`（输出根分区、Docker 资源、宿主机大文件目录）；`./deploy/docker-deploy.sh cleanup --dry-run`（等价 diagnose）；`cleanup --aggressive`（同时清理宿主机 node_modules/.venv）

## Docs（历史经验库）

`docs/bug-reports/` 和 `docs/tdd-reports/` 存放了 20+ 份历史文档。
**修 Bug 前**先搜 `docs/bug-reports/`，**开发新功能前**先搜 `docs/tdd-reports/`。

## 生产环境

```
nginx (port 80, 内置前端 dist) → backend (port 8000)
                                redis (port 6379)
worker (--profile worker, 按需启动) → redis/backend data
```

- Docker Compose 编排，配置见 `docker-compose.yml`；`backend`/`worker` 共用 `interview-boss-app:local`，`nginx` 使用 `interview-boss-nginx:local`
- 构建磁盘保护由 `deploy/docker-deploy.sh` 统一执行：`DEPLOY_MIN_FREE_MB=4096`、`DEPLOY_TARGET_FREE_MB=5120`、`BUILDKIT_RESERVED_SPACE=2GB` 可通过环境变量覆盖
- 镜像源构建保护由 `deploy/docker-deploy.sh` 统一执行：`DEPLOY_MIRROR_HEALTHCHECK_ON_BUILD=1`、`DEPLOY_MIRROR_HEALTHCHECK_TIMEOUT=2`、`DEPLOY_SELECT_MIRRORS_ON_BUILD=0`。不要在普通 `update` 中强制完整测速，除非正在排查镜像源故障。镜像缓存目录由 `MIRROR_CACHE_VERSION` 控制，默认写入 `/tmp/interview-boss-mirrors-v2`。
- Docker daemon DNS 可通过 `DEPLOY_DOCKER_DNS=223.5.5.5,119.29.29.29` 覆盖，普通 update 不应频繁改 daemon；只在 `mirrors` 维护命令中持久化。
- Nginx 反代 `/api/` → backend:8000（read timeout 600s，SSE 禁用 buffering/cache/gzip），其余 → `/usr/share/nginx/html` 静态文件
- 数据卷：`./backend/data` → 容器内 `/app/backend/data`；前端 dist 已内置到 nginx 镜像，不再挂载宿主机 `frontend/dist`
- HuggingFace 缓存：`/home/ubuntu/.cache/huggingface` → 容器内 `/home/appuser/.cache/huggingface`（只读）
- 环境变量：`HF_HUB_OFFLINE=1`（强制离线模式，避免访问 huggingface.co）

## 孤岛碎片整理（Compaction）

- **方法**：纯 LLM 聚类（`_cluster_unmatched`），按 cat2 分组并行处理
- **性能**：约 2 分钟/轮，134 个孤岛处理约 120 秒
- **质量**：LLM 判断 + 二次验证；embedding 只能做候选排序/预筛，不能作为自动合并依据
- **跳过**："其他"和空分类不参与聚类
- **调用**：`POST /api/master-bank/compact`（SSE 流式推送）
- **合并历史**：`merge_history` 表记录所有合并操作，支持回滚
- **数据维护**：`POST /api/master-bank/clustering-maintenance`，默认 dry-run，只自动修确定性元数据和精确重复
