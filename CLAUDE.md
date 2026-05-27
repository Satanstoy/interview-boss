# InterviewBoss Monorepo

中文 AI 面试备战平台。JD/面经 → 提取面试题 → LLM 分类打标聚类 → 口述级答案 + 模拟面试 + 知识图谱。

## 目录地图

```
backend/
├── app/routers/       ← 13 个 API 路由（HTTP 感知层，禁止业务逻辑）
├── app/services/      ← 业务逻辑（LLM 调用、聚类、pipeline）
├── app/core/          ← 配置、认证、提示词模板
├── app/db/            ← SQLite 连接、CRUD、查询、迁移
├── app/agents/        ← LangGraph 状态机（submit/build/batch_generate）
├── app/models/        ← Pydantic schemas
├── app/middleware/     ← 请求日志
└── tests/             ← pytest 测试（不提交 git）

frontend/
├── src/services/      ← API 服务层（按领域拆分），http.js 是 HTTP 客户端
├── src/composables/   ← 领域逻辑复用（use* 前缀）
├── src/components/
│   ├── common/        ← 通用 UI（DataTable、TabBar 等，无业务依赖）
│   └── business/      ← 业务组件（MasterBankList、PracticePanel 等）
├── src/utils/         ← 纯工具函数（markdown、validate）
├── src/constants/     ← config.js、enums.js
└── tests/             ← Playwright E2E 测试（不提交 git）

deploy/                ← 部署脚本（deploy.sh、docker-deploy.sh、systemd）
docs/                  ← 历史经验库（bug-reports、tdd-reports，不提交 git）
nginx/                 ← Docker Nginx 配置（API 代理 + SPA）
```

## 命令

```bash
# 开发测试
uv run pytest backend/tests/ -q          # 后端测试
cd frontend && npm run build              # 前端构建

# 部署（必须用 Docker，不要用 deploy.sh 的 systemd 模式）
./deploy/docker-deploy.sh update          # 代码变更后重新部署（重建后端/worker/nginx 容器）
./deploy/docker-deploy.sh status          # 查看容器状态
./deploy/docker-deploy.sh logs backend    # 查看后端日志
./deploy/docker-deploy.sh backup          # 备份数据库
```

> `deploy/deploy.sh` 是 systemd 模式，**不用于生产**。生产环境全部走 Docker。

Python 依赖必须用 uv（`/root/.local/bin/uv`），禁止 pip。

## 核心规范

- **TDD 原则（强制）**：修 Bug 或开发新功能时，必须**先写测试 → 确认测试失败 → 写最少代码让测试通过 → 重构**。详见 `backend/CLAUDE.md` 和 `frontend/CLAUDE.md` 的测试规则。
- **Commit**：Conventional Commits（`feat(frontend):`、`fix(backend):`），英文。Git hook 会自动检查格式。
- **语言**：UI/提示词/文档中文简体，代码标识符英文
- **禁止**：根目录装包、跨包引用源码、`--force`/`--no-verify`

## 修改铁律（强制遵守）

1. **修改后必须更新 CLAUDE.md** — 任何涉及文件增删、职责变更、架构调整的修改，必须更新对应目录的 CLAUDE.md。不更新 = 任务未完成。
2. **一组修改必须 commit** — 每次会话中完成一组逻辑相关的修改后，必须立即 `git commit`。禁止积攒大量未提交修改。
3. **新模块必须更新 README** — 新增功能模块或 API 端点后，必须更新 README.md 和对应目录的 CLAUDE.md。

## 子目录 CLAUDE.md

每个有一定规模的目录都有自己的 CLAUDE.md，CC 会按目录层级自动加载。修改代码时先读对应目录的 CLAUDE.md：

```
backend/app/db/CLAUDE.md              ← 数据库层规范
backend/app/services/CLAUDE.md        ← 业务逻辑层规范
backend/app/core/CLAUDE.md            ← 配置认证层规范
backend/app/agents/CLAUDE.md          ← Agent 总览
backend/app/agents/submit/CLAUDE.md   ← Submit agent 流程
backend/app/agents/build/CLAUDE.md    ← Build agent 流程
backend/app/agents/chat/CLAUDE.md     ← Chat agent 流程
backend/app/agents/shared/CLAUDE.md   ← 共享模块
backend/app/routers/profile_pkg/CLAUDE.md  ← 配置子路由
backend/app/routers/questions_pkg/CLAUDE.md ← 题库子路由
backend/tests/CLAUDE.md               ← 测试规范
backend/tests/*/CLAUDE.md             ← 各测试子目录
frontend/src/components/business/CLAUDE.md ← 业务组件
frontend/src/components/common/CLAUDE.md   ← 通用组件
frontend/src/services/CLAUDE.md       ← API 服务层
frontend/src/composables/CLAUDE.md    ← composables
frontend/src/utils/CLAUDE.md          ← 工具函数
frontend/tests/CLAUDE.md              ← 前端测试
```

## 测试基础设施

- **后端**：`conftest.py` 提供 `test_db`（内存 SQLite）、`mock_llm`、`mock_redis`、`client` fixtures，开箱即用
- **前端**：Playwright 测试必须 mock API，禁止截图断言，禁止使用真实密码
- **详细规则**：`.claude/rules/test-files.md`（编辑测试文件时自动加载）

## 代码路由表（快速定位文件）

修改功能时，按此表直接找到对应文件，不要盲目搜索：

| 功能 | 后端文件 | 前端文件 |
|------|---------|---------|
| 登录/注册/刷新 | `backend/app/routers/auth.py` + `core/auth.py` | `frontend/src/services/authApi.js` + `components/business/LoginModal.vue` |
| JD/面经提交 | `backend/app/routers/submit.py` + `services/pipeline.py` | `frontend/src/services/dataApi.js` |
| 题库管理 | `backend/app/routers/master_bank.py` | `frontend/src/services/masterBankApi.js` + `components/business/MasterBankList.vue` |
| 答案生成 | `backend/app/routers/answers.py` + `services/llm.py` | `frontend/src/services/practiceApi.js` |
| 练习/模拟面试 | `backend/app/routers/practice.py` + `routers/interview.py` | `frontend/src/components/business/PracticePanel.vue` + `MockInterview.vue` |
| 数据分析 | `backend/app/routers/analytics.py` | `frontend/src/services/analyticsApi.js` + `components/business/AnalyticsSidebar.vue` |
| 用户配置 | `backend/app/routers/profile.py` + `core/config.py` | `frontend/src/services/profileApi.js` + `components/business/SettingsPanel.vue` |
| 题目去重 | `backend/app/services/clustering.py` | — |
| LLM 调用 | `backend/app/services/llm.py` + `core/prompts.py` | — |
| 认证中间件 | `backend/app/core/auth.py` | `frontend/src/services/http.js` |
| 数据库操作 | `backend/app/db/operations.py` + `queries.py` | — |

## Docs（历史经验库）

`docs/bug-reports/` 和 `docs/tdd-reports/` 存放了 20+ 份历史文档。

**修 Bug 前：** 先搜 `docs/bug-reports/` 是否有类似问题的历史记录，避免重复踩坑。
**开发新功能前：** 先搜 `docs/tdd-reports/` 了解相关模块的历史设计决策和已有模式。

## 完成阶段后

1. `uv run pytest backend/tests/ -q` → `cd frontend && npm run build` → `./deploy/docker-deploy.sh update`
2. **更新 CLAUDE.md** — 修改了哪个目录的代码，就更新哪个目录的 CLAUDE.md（铁律）
3. 涉及功能/API/结构变更 → 最小化更新 README.md
4. **创建 docs 记录**（关键修改：README + docs；小修改：仅 docs）
   - `docs/bug-reports/YYYY-MM-DD-描述.md` / `docs/tdd-reports/YYYY-MM-DD-描述.md`
   - 内容：问题描述、根因分析、修复方案、测试验证、影响范围
5. `git add` + `git commit` → `git push`（让用户输入凭据）

## 生产环境（Docker Compose）

```
nginx (port 80) → backend (port 8000) + worker
                  redis (port 6379)
```

- Docker Compose 编排，配置见 `docker-compose.yml`
- Nginx 容器反代 `/api/` → backend:8000（180s 超时），其余 → 静态文件
- 数据卷：`./backend/data` 挂载到容器内 `/app/backend/data`
- `deploy/deploy.sh` 是 systemd 模式，**不用于生产**
- `claude_runner` 已配置 NOPASSWD

## Agent skills

### Issue tracker

Local markdown — issues live as files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
