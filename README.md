<div align="center">

<img src="logo.png" alt="InterviewBoss Logo" width="400" />

# InterviewBoss

**AI 驱动的面试备战平台 — 从 JD / 面经到高频题库，一键搞定**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://python.org)
[![Vue](https://img.shields.io/badge/Vue-3-42b883.svg)](https://vuejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688.svg)](https://fastapi.tiangolo.com)

[快速开始](#快速开始) | [功能详解](#功能详解) | [技术架构](#技术架构) | [部署指南](#部署指南) | [API 文档](#api-概览)

</div>

---

## 项目简介

面试准备太零散？JD 和面经散落在小红书、牛客、Boss 等各个平台？

InterviewBoss 帮你把**文本 + 截图**丢进来，自动完成：

> **输入** JD / 面经截图/文字 → **AI 识别分类** → **提取面试题** → **聚类去重** → **生成口述级答案** → **模拟面试练习**

零配置开箱即用，支持任意 OpenAI 兼容 API（GPT-4o、Claude、国产模型均可）。

## 工作流程

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  粘贴文本    │     │  LLM 识别     │     │  面试题提取   │     │  聚类去重     │
│  拖拽图片    │────▶│  JD / 面经    │────▶│  标签 + 难度  │────▶│  高频排序     │
│  混合输入    │     │  字段补全     │     │  6 大类归类   │     │  合并来源     │
└─────────────┘     └──────────────┘     └──────────────┘     └──────┬───────┘
                                                                      │
                    ┌──────────────┐     ┌──────────────┐           │
                    │  模拟面试     │     │  答题评估     │           │
                    │  随机抽题     │◀────│  AI 评分反馈  │◀──────────┘
                    │  难度筛选     │     │  改进建议     │
                    └──────────────┘     └──────────────┘
```

## 功能详解

<details>
<summary><strong>多模态输入</strong> — 纯文本、图片拖拽/粘贴、文本+图片混合</summary>

支持截图型面经（小红书、牛客、Boss 直聘等），LLM 自动识别内容类型并提取结构化字段，缺失字段智能推断补全。

</details>

<details>
<summary><strong>智能分类 + 标签化</strong> — 6 大类 + 子类自动归类</summary>

面试题自动归入算法、系统设计、基础原理等 6 大类，标注考点标签和难度等级（L1 基础 / L2 中级 / L3 高级）。

</details>

<details>
<summary><strong>LLM 聚类去重</strong> — 基于大模型的语义聚类合并</summary>

cat2 预分组 + 两遍聚类 + 验证步骤，语义相近的题目自动合并，追踪考频和来源链接。Embedding 预筛选（FAISS）加速候选匹配。

</details>

<details>
<summary><strong>AI 生成答案</strong> — 三种口述风格一键生成</summary>

- 算法/代码风格（含 Python 实现）
- 系统设计/架构风格
- 基础理论风格

支持单题生成和批量生成（SSE 实时进度推送）。

</details>

<details>
<summary><strong>个人答案管理</strong> — 每用户独立维护答案</summary>

- 管理员的参考答案存储在公共题库（`question_bank.ai_answer`）
- 普通用户拥有独立的个人答案（`user_question_view.user_answer`）
- 管理员已有参考答案时，普通用户可一键「使用参考答案」复制到个人答案
- 普通用户生成的答案存入个人表，不影响全局参考答案

</details>

<details>
<summary><strong>模拟面试 + 答题评估</strong> — 实战练习闭环</summary>

加权随机抽题（减少近期重复），支持分类和难度筛选。AI 从完整性、深度、准确性、逻辑性 4 个维度评分并给出改进建议。

</details>

<details>
<summary><strong>知识图谱 + 数据分析</strong> — 可视化备考全景</summary>

ECharts 6 知识点关联网络、技术栈热度趋势、考点分布、难度分布、14 天练习趋势。

</details>

<details>
<summary><strong>AI 对话</strong> — 多轮对话 + PDF 解析 + Skills 技能系统</summary>

独立的对话模块，支持多轮对话、SSE 流式响应、对话归档/重命名/删除。内置记忆系统，AI 可跨对话记住关键信息。支持 PDF 文件上传提取内容。

**Skills 技能系统（Progressive Disclosure）**：面试官 AI 内置 6 种专业技能模式，根据对话内容自动激活：
- **自适应难度** — 基于答题表现动态调整题目深度，好答案升级追问，差答案降级换题
- **算法编码** — 聚焦手撕代码类问题，引导思路而非直接给答案
- **HR 软技能** — 行为面试、STAR 法则、团队协作类问题
- **面试节奏** — 控制提问节奏，冷风格 + 交错式追问
- **项目深挖** — 针对简历项目经验深度追问技术细节和决策理由
- **理论问答** — 基础原理、八股文类问题的结构化追问

**岗位驱动 RAG**：自动注入用户目标岗位、练习薄弱环节、历史面试经验到对话上下文，面试题检索按岗位智能过滤。

</details>

<details>
<summary><strong>手撕代码</strong> — 在线编程 + SSE 流式评测 + 渐进提示</summary>

内置 50+ 编程题库，支持在线代码提交（Monaco Editor）。AI 从语法、逻辑、算法、复杂度、代码风格 5 个维度评测（每项 1-5 分），SSE 实时流式输出分析过程。支持两种模式：
- **完整评审**（`full_review`）— 一次性输出完整分析和评分
- **渐进提示**（`hint`）— 不直接给答案，通过多轮提示链逐步引导思考，支持多轮追问

统计错误类型分布，帮助针对性提升。

</details>

<details>
<summary><strong>多用户系统</strong> — JWT 双 Token 认证</summary>

三种题库模式（公共/个人/混用），管理员审核机制，Access Token 15 分钟 + Refresh Token HttpOnly Cookie + 服务端 JTI 轮转。

</details>

<details>
<summary><strong>系统配置热更新</strong> — LLM / Embedding 参数在线修改</summary>

API 地址、模型名称、超时时间、相似度阈值等均可通过界面修改，自动持久化到数据库和 `.env` 文件。支持个人 LLM 配置独立管理。

</details>

<details>
<summary><strong>数据安全</strong> — 软删除 + 回收站机制</summary>

题库题目删除后进入回收站，支持单条/批量恢复。JD、面经、题目详情均支持软删除，防止数据误删丢失。

</details>

<details>
<summary><strong>异步任务队列</strong> — Redis + ARQ 后台处理</summary>

聚类去重等耗时任务通过 ARQ 异步执行，不阻塞 API 响应。Redis 不可用时自动降级为同步执行，保证功能可用。Worker 独立进程运行，可单独扩缩容。

</details>

## 技术架构

### 整体架构

```
nginx (port 80, 内置前端 dist) → backend (port 8000)
                                redis (port 6379)
worker (--profile worker, 按需启动) → redis/backend data
```

### 后端架构（4 层，依赖方向向内）

```
Routers → Services → Core/DB → (external)
```

| 层级 | 目录 | 职责 |
|------|------|------|
| **路由层** | `app/routers/` | HTTP 感知，禁止业务逻辑 |
| **服务层** | `app/services/` | 业务逻辑（LLM 调用、聚类、pipeline） |
| **Agent 层** | `app/agents/` | LangGraph 状态机（submit/build/batch_generate/chat） |
| **核心层** | `app/core/` | 配置、认证、提示词模板 |
| **数据层** | `app/db/` | SQLite 连接、CRUD、查询、迁移 |

### 前端架构

| 目录 | 职责 |
|------|------|
| `src/services/` | API 服务层（按领域拆分），http.js 是 HTTP 客户端 |
| `src/composables/` | 领域逻辑复用（use* 前缀） |
| `src/components/common/` | 通用 UI（无业务依赖） |
| `src/components/business/` | 业务组件 |
| `src/stores/` | Pinia 状态管理 |
| `src/utils/` | 纯工具函数 |

### 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 数据库 | SQLite (WAL 模式) |
| 任务队列 | Redis + ARQ（异步任务处理，自动降级到同步） |
| LLM | OpenAI Compatible API（支持代理 / 国产模型） |
| 聚类去重 | LLM-based Clustering（cat2 预分组 + 两遍聚类） |
| Embedding | ONNX Runtime + bge-small-zh-v1.5 + FAISS |
| Agent 框架 | LangGraph（状态机 + 条件路由） |
| 前端框架 | Vue 3 (Composition API) + Vite |
| UI 组件 | shadcn-vue + Tailwind CSS |
| 代码编辑器 | Monaco Editor |
| 图表 | ECharts 6 |
| 认证 | JWT 双 Token（Access + HttpOnly Refresh） |
| 日志 | structlog（生产 JSON / 开发彩色） |
| 部署 | Docker Compose |
| 包管理 | uv (Python) / npm (Node.js) |

## 项目结构

```
interview-boss/
├── backend/                    # Python FastAPI 后端
│   ├── app/
│   │   ├── core/               # 认证、配置热更新、LLM 提示词模板、日志
│   │   ├── routers/            # 16+ API 路由模块（含 profile_pkg / questions_pkg 子路由）
│   │   ├── services/           # LLM 调用、聚类去重、管道、简历、邮件等业务服务
│   │   ├── agents/             # LangGraph 状态机（submit / build / batch_generate / chat）
│   │   │   └── chat/skills/    # 6 种面试技能（自适应难度、算法编码、HR 软技能等）
│   │   ├── db/                 # SQLite 连接管理、CRUD、查询、自动迁移
│   │   ├── middleware/         # 请求日志中间件
│   │   └── models/             # Pydantic 请求/响应模型
│   ├── worker.py               # ARQ Worker 入口
│   ├── data/                   # SQLite 数据库文件（自动备份）
│   └── tests/                  # 后端测试
├── frontend/                   # Vue 3 + Vite 前端
│   ├── src/
│   │   ├── api/                # API 接口定义
│   │   ├── components/
│   │   │   ├── common/         # 通用 UI 组件（DataTable, TabBar, BaseModal 等）
│   │   │   └── business/       # 业务组件（MasterBankList, PracticePanel, ChatView 等）
│   │   ├── composables/        # 组合式函数（usePractice, useSelection, useMotionPresets 等）
│   │   ├── constants/          # 配置常量与枚举（config.js, enums.js）
│   │   ├── layouts/            # 页面布局（DefaultLayout, BlankLayout）
│   │   ├── router/             # Vue Router 路由定义
│   │   ├── services/           # API 服务层 + HTTP 客户端（按领域拆分）
│   │   ├── stores/             # Pinia 状态管理
│   │   ├── utils/              # 纯工具函数（markdown、validate、highlight）
│   │   └── views/              # 页面级组件
│   └── tests/                  # 前端测试（Playwright）
├── deploy/                     # 部署配置
│   ├── docker-deploy.sh        # Docker 部署脚本（生产推荐）
│   └── entrypoint.sh           # Docker 容器入口脚本
├── docs/                       # 文档（agents、bug-reports、tdd-reports、dev-log）
├── nginx/                      # Docker Nginx 配置（API 代理 + SPA + 安全头）
├── Dockerfile                  # 多阶段构建（前端 + 后端）
├── docker-compose.yml          # 容器编排（Redis + Backend + Worker + Nginx）
├── pyproject.toml              # Python 依赖定义
├── main.py                     # 本地开发入口
└── README.md
```

## 快速开始

### 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.10 | 后端运行环境 |
| Node.js | >= 16 | 前端构建环境 |
| uv | 最新版 | Python 包管理器（替代 pip） |

### 1. 克隆项目

```bash
git clone https://gitee.com/your-username/interview-boss.git
cd interview-boss
```

### 2. 配置后端环境变量

```bash
cd backend
cp .env.example .env
```

编辑 `.env`，填入你的 API 配置：

```env
# ── 必填 ──
OPENAI_API_KEY=sk-xxx                         # LLM API 密钥
ADMIN_PASSWORD=your-secure-password            # 种子管理员密码（首次启动必填）

# ── 可选（有默认值） ──
OPENAI_BASE_URL=https://api.openai.com/v1     # API 地址（支持代理）
LLM_MODEL_NAME=gpt-4o                         # 模型名称
```

> 其他配置（Embedding 模型、相似度阈值、超时时间等）均有默认值，可在启动后通过界面在线修改。

### 3. 启动服务（Docker 方式，推荐）

```bash
# 首次部署
./deploy/docker-deploy.sh all

# 更新部署
./deploy/docker-deploy.sh update
```

首次启动会自动创建数据库和种子管理员账号。

浏览器打开 `http://localhost`，注册账号即可开始使用。

### 4. 本地开发（可选）

如需本地开发调试，可分别启动前后端：

```bash
# 后端（通过 Docker 容器执行）
docker compose exec backend uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

日常开发收尾可运行统一质量门禁：

```bash
./deploy/docker-deploy.sh check
```

该命令会执行后端 Docker 测试基础检查、前端 build/smoke 测试，并汇总 npm/pip audit 报告。audit 第一阶段只报告不拦截。

浏览器打开 `http://localhost:3000`。

### 5. 生产部署（可选）

详见下方 [部署指南](#部署指南)。

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `REDIS_URL` | Redis 连接地址 | `redis://localhost:6379/0` |
| `OPENAI_API_KEY` | LLM API 密钥 | *(必填)* |
| `OPENAI_BASE_URL` | LLM API 地址 | 空 |
| `LLM_MODEL_NAME` | 生成模型 | `gpt-4o` |
| `OPENAI_API_KEY_EMBEDDING` | Embedding API 密钥 | 回退到 LLM 密钥 |
| `OPENAI_BASE_URL_EMBEDDING` | Embedding API 地址 | 空 |
| `EMBEDDING_MODEL_REPO` | Embedding 模型仓库 | `Xenova/bge-small-zh-v1.5` |
| `SIMILARITY_THRESHOLD` | 去重相似度阈值 | `0.85` |
| `LLM_TIMEOUT` | LLM 超时（秒） | `120` |
| `JWT_SECRET` | JWT 签名密钥 | 自动生成 |
| `ADMIN_USERNAME` | 种子管理员用户名 | `sj` |
| `ADMIN_PASSWORD` | 种子管理员密码 | *(首次必填)* |
| `DEBUG` | 开启热重载和 Swagger 文档 | `false` |
| `ALLOWED_ORIGINS` | CORS 允许来源（逗号分隔） | 空 |
| `MAX_FILE_SIZE_MB` | 最大上传大小（MB） | `10` |
| `SMTP_HOST` | 邮件服务器地址 | 空 |
| `SMTP_PORT` | 邮件服务器端口 | `587` |
| `SMTP_USERNAME` | 邮箱用户名 | 空 |
| `SMTP_PASSWORD` | 邮箱密码 | 空 |
| `SMTP_FROM` | 发件人邮箱 | 空 |
| `SMTP_FROM_NAME` | 发件人显示名称 | `InterviewBoss` |
| `SMTP_USE_TLS` | 启用 TLS | `true` |

> 所有配置均可在运行时通过 `/api/profile` 界面在线修改，变更会自动持久化到数据库和 `.env` 文件。

## Git 工作流与开发规范

### 分支规则

| 分支 | 用途 |
|------|------|
| `main` | 生产分支，始终保持可部署状态 |
| `dev` | 开发分支，功能集成 |
| `feature/*` | 新功能开发（如 `feature/knowledge-graph`） |
| `fix/*` | Bug 修复 |

### Commit 消息规范

采用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
<type>: <简短描述>

<可选的详细说明>
```

常用 type：
- `feat`: 新功能
- `fix`: Bug 修复
- `refactor`: 重构（不改变功能）
- `docs`: 文档更新
- `chore`: 构建/工具/依赖变更
- `style`: 代码格式调整（不影响逻辑）
- `perf`: 性能优化

### PR 流程

1. 从 `dev` 创建功能分支（`feature/*` 或 `fix/*`）
2. 开发完成后提交 PR 到 `dev`
3. 确保功能正常后合并
4. `dev` 稳定后合并到 `main` 发布

## 部署指南

### Docker 部署（推荐）

Docker 一键部署包含 Redis、后端、Nginx 三个核心容器，Worker 通过 profile 按需挂载。镜像已配置国内加速、短健康检查和 BuildKit 本地缓存。

#### 前置条件

- Docker + Docker Compose v1（`docker-compose`）或 v2（`docker compose`）
- 80 端口未被占用（如有系统 Nginx，需先停止：`sudo systemctl stop nginx`）

#### 首次部署

```bash
cd interview-boss

# 1. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入 OPENAI_API_KEY、ADMIN_PASSWORD 等必填项

# 2. 构建并启动所有服务
sudo ./deploy/docker-deploy.sh all
```

首次构建会生成两个本地镜像：`interview-boss-app:local`（backend/worker 共用）和 `interview-boss-nginx:local`（内置前端 dist）。后续代码更新只需执行 `sudo ./deploy/docker-deploy.sh update`；脚本会自动备份数据库、构建镜像、等待健康检查，依赖未变时复用 BuildKit 缓存层、inline cache 和 npm/pip/uv cache mounts，不重新下载。

部署脚本内置磁盘保护：构建前根分区至少保留 4GB，构建后低于 5GB 会自动收缩 BuildKit cache（默认保留 2GB），避免 Docker 部署过程中把磁盘写满。

部署脚本默认复用缓存/稳定默认镜像源，只做短健康检查；健康检查失败才刷新 npm/PyPI/apt 源，避免每次 `update` 都改变 build args 导致依赖层缓存失效。镜像源缓存使用版本化目录，旧脚本留下的坏源不会污染后续 `update`。镜像源整体失效或首次配置机器时，执行 `sudo ./deploy/docker-deploy.sh mirrors` 强制清缓存、完整测速并更新 Docker Hub registry mirror。

`update/build/test/worker-up` 会先做快速部署预检：生产依赖必须保持 `uv export + pip install -i $PYPI_MIRROR`，compose build 必须保留 `network: host`。如果有人把依赖安装改回会直连 `files.pythonhosted.org` 的慢路径，脚本会在真正 build 前直接失败并给出原因。

#### 常用运维命令

```bash
sudo ./deploy/docker-deploy.sh             # 默认等同于 all（构建 + 启动核心服务）
sudo ./deploy/docker-deploy.sh status      # 查看服务状态和资源使用
sudo ./deploy/docker-deploy.sh logs        # 查看日志（可指定: logs backend）
sudo ./deploy/docker-deploy.sh update      # 代码更新后重新部署核心服务
sudo ./deploy/docker-deploy.sh restart     # 重启核心服务
sudo ./deploy/docker-deploy.sh worker-up   # 按需启动 Worker
sudo ./deploy/docker-deploy.sh worker-down # 停止 Worker
sudo ./deploy/docker-deploy.sh worker-logs # 查看 Worker 日志
sudo ./deploy/docker-deploy.sh backup      # 备份数据库和 Redis 数据
sudo ./deploy/docker-deploy.sh mirrors     # 手动刷新镜像源缓存和 Docker Hub mirror
sudo ./deploy/docker-deploy.sh down        # 停止所有服务
```

#### 仅更新前端

前端修改后，只需重建 nginx 镜像并重启 nginx（无需重建 app 镜像）：

```bash
DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose build nginx
sudo docker compose up -d nginx
```

#### 资源分配（2c4g 优化）

| 服务 | 内存限制 | CPU | 说明 |
|------|---------|-----|------|
| Redis | 128MB | 0.25 | 任务队列 + 缓存 |
| Backend | 512MB | 0.75 | FastAPI 应用 |
| Worker | 384MB | 0.75 | ARQ 异步任务，按需启动 |
| Nginx | 64MB | 0.25 | 反向代理 + 静态文件 |

HuggingFace 模型缓存通过只读 volume 挂载到容器内 `/home/appuser/.cache/huggingface`，配合 `HF_HOME` 和 `HF_HUB_OFFLINE=1` 避免运行时联网下载。

#### 端口冲突排查

如果启动时报 `address already in use`，检查占用 80 端口的进程：

```bash
sudo ss -tlnp | grep ':80 '
# 常见原因：系统 Nginx → sudo systemctl stop nginx
```

## API 概览

<details>
<summary><strong>认证接口</strong></summary>

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/login` | 登录（返回 access token + HttpOnly refresh cookie） |
| POST | `/api/auth/refresh` | 刷新 token |
| POST | `/api/auth/logout` | 注销 |
| GET | `/api/auth/me` | 当前用户信息 |

</details>

<details>
<summary><strong>内容提交</strong></summary>

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/submit` | 提交文本/图片，AI 自动识别入库 |
| POST | `/api/submit-stream` | 流式提交（SSE 进度推送） |
| POST | `/api/submit-stream-v2` | 流式提交 v2（改进版） |

</details>

<details>
<summary><strong>题库管理</strong></summary>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/master-bank` | 题库列表（分页、筛选、排序） |
| POST | `/api/master-bank/build` | 全量重建题库（SSE 进度） |
| POST | `/api/master-bank/compact` | 压缩合并题库（SSE 进度） |
| POST | `/api/master-bank/build-personal` | 构建个人题库 |
| POST | `/api/master-bank/generate-answer/{id}` | AI 生成答案 |
| POST | `/api/master-bank/use-reference-answer/{id}` | 使用参考答案 |
| PUT | `/api/master-bank/save-user-answer/{id}` | 保存用户个人答案 |
| POST | `/api/master-bank/batch-generate` | 批量生成答案 |
| POST | `/api/master-bank/random` | 随机抽题（模拟面试） |
| POST | `/api/evaluate-answer` | AI 评估答题质量 |
| DELETE | `/api/master-bank/{id}` | 软删除题目（移至回收站） |
| POST | `/api/master-bank/batch-delete` | 批量软删除题目 |
| GET | `/api/master-bank/trash` | 获取回收站列表 |
| POST | `/api/master-bank/restore/{id}` | 恢复已删除题目 |
| POST | `/api/master-bank/batch-restore` | 批量恢复题目 |
| POST | `/api/master-bank/split-question/{id}` | 拆分题目 |
| POST | `/api/master-bank/merge-question/{id}` | 合并题目 |
| POST | `/api/master-bank/re-tag/{id}` | 重新标签化 |
| POST | `/api/master-bank/upload` | 上传题目 |

</details>

<details>
<summary><strong>数据分析</strong></summary>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/analytics` | 全局分析数据 |
| GET | `/api/practice-stats` | 个人练习统计 |
| GET | `/api/knowledge-graph` | 知识图谱数据 |

</details>

<details>
<summary><strong>AI 对话</strong></summary>

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/conversations` | 创建对话 |
| GET | `/api/chat/conversations` | 对话列表 |
| GET | `/api/chat/conversations/{id}` | 对话详情 |
| PUT | `/api/chat/conversations/{id}/title` | 重命名对话 |
| PUT | `/api/chat/conversations/{id}/archive` | 归档对话 |
| DELETE | `/api/chat/conversations/{id}` | 删除对话 |
| GET | `/api/chat/conversations/{id}/messages` | 获取消息列表 |
| POST | `/api/chat/conversations/{id}/messages` | 发送消息（SSE 流式） |
| GET | `/api/chat/memories` | 获取记忆列表 |
| DELETE | `/api/chat/memories/{id}` | 删除记忆 |
| POST | `/api/chat/extract-pdf` | PDF 文件内容提取 |

</details>

<details>
<summary><strong>手撕代码</strong></summary>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/coding/problems` | 题目列表 |
| GET | `/api/coding/problems/{id}` | 题目详情 |
| POST | `/api/coding/submit` | 提交代码（SSE 流式 AI 评测） |
| GET | `/api/coding/submissions` | 提交记录列表 |
| GET | `/api/coding/submissions/{id}` | 提交详情（含 5 维评分） |
| GET | `/api/coding/error-stats` | 错误统计 |

</details>

<details>
<summary><strong>数据管理</strong></summary>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/data/{file_type}` | 获取指定类型数据列表 |
| PUT | `/api/data/update` | 更新数据记录 |
| DELETE | `/api/data/{file_type}/{id}` | 删除数据记录 |
| POST | `/api/data/batch-delete` | 批量删除 |
| POST | `/api/data/restore/{file_type}/{id}` | 恢复已删除记录 |
| GET | `/api/data/{file_type}/trash` | 回收站列表 |

</details>

<details>
<summary><strong>异步任务</strong></summary>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/jobs/{job_id}` | 查询异步任务状态 |
| GET | `/api/jobs/{job_id}/stream` | SSE 实时任务进度 |

</details>

<details>
<summary><strong>系统管理</strong></summary>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/profile` | 读取系统配置 |
| PUT | `/api/profile` | 更新系统配置 |
| GET | `/api/profile/llm` | 读取个人 LLM 配置 |
| PUT | `/api/profile/llm` | 更新个人 LLM 配置 |
| DELETE | `/api/profile/llm` | 删除个人 LLM 配置 |

</details>

<details>
<summary><strong>管理员审核</strong></summary>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/master-bank/analysis-status` | 分析状态 |
| GET | `/api/master-bank/pending` | 待审核列表 |
| POST | `/api/master-bank/approve/{id}` | 批准题目 |
| POST | `/api/master-bank/reject/{id}` | 拒绝题目 |
| GET | `/api/master-bank/merge-history` | 合并历史 |
| POST | `/api/master-bank/merge-rollback/{id}` | 回滚合并 |
| POST | `/api/master-bank/merge-feedback` | 合并反馈 |
| GET | `/api/master-bank/merge-stats` | 合并统计 |
| POST | `/api/master-bank/clustering-maintenance` | 聚类维护 |

</details>

<details>
<summary><strong>错误上报</strong></summary>

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/error-report` | 前端 JS 错误上报 |

</details>

完整 API 文档：开发模式下（`DEBUG=true`）访问 `http://localhost:8000/docs` 查看 Swagger UI。

## 安全与隐私

### 严禁事项

- **绝对不要**将 `.env` 文件、API 密钥、数据库文件或任何含有真实凭证的文件提交到 Git 仓库。
- **绝对不要**在代码中硬编码 IP 地址、Token、密码或其他敏感信息。
- **绝对不要**将 `backend/data/*.db` 数据库文件提交到版本控制。

### 已有安全措施

- `.gitignore` 已配置排除 `.env`、`*.db`、`*.db-shm`、`*.db-wal`、`.claude/settings.local.json` 等敏感文件。
- Nginx 配置包含安全响应头（CSP、X-Frame-Options、HSTS 等）。
- 后端中间件注入安全响应头（nosniff、DENY、CSP 等）。
- JWT Refresh Token 使用 HttpOnly Cookie，防止 XSS 窃取。
- 全局速率限制（200 次/分钟）。
- 密码使用 bcrypt 加密存储。
- CSRF 中间件拦截缺少自定义头的跨域请求。
- 题库操作（生成答案、批量生成、答题评估）均校验用户可见范围（`bank_mode` + `owner_id`），防止权限提升。
- 分析数据按用户 `bank_mode` 隔离，普通用户仅可见公共/个人数据。

### 开发者须知

1. 复制 `.env.example` 为 `.env`，填入自己的密钥，**不要**使用他人的 `.env`。
2. 生产环境务必设置强密码的 `JWT_SECRET` 和 `ADMIN_PASSWORD`。
3. 定期轮换 API 密钥。
4. 如发现敏感信息泄露，立即轮换相关密钥并清理 Git 历史。

## 许可证

[MIT](LICENSE)
