# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

InterviewBoss 是一个中文 AI 面试备战平台。核心功能：从 JD / 面经（文本 + 图片）中自动提取面试题，通过 LLM 分类打标、聚类去重，生成口述级答案，并支持模拟面试练习与知识图谱可视化。多用户系统，JWT 双 Token 认证，三种题库模式（公共/个人/混用）。

## Commands

### 后端 (Python / FastAPI)
```bash
cd /root/sj/interview-boss
uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000
```

### 前端 (Vue 3 / Vite)
```bash
cd frontend
npm install
npm run dev      # 开发服务器 http://localhost:3000
npm run build    # 生产构建 → /var/www/interview-boss/dist/
```

### Python 依赖管理（必须使用 uv）
```bash
# uv 二进制绝对路径: /root/.local/bin/uv（不在 PATH 中）
uv sync                    # 从 pyproject.toml 安装所有依赖
uv add <package>           # 添加新依赖
# 安装后需要重启后端服务才能生效
```

**重要：本项目所有 Python 依赖操作必须使用 uv，不要用 pip/pip3。**

### 部署

```bash
# 一键部署（前端构建+部署+后端重启）
./deploy.sh

# 仅部署前端
./deploy.sh frontend

# 仅重启后端
./deploy.sh backend
```

**重要：部署脚本内部使用 sudo 执行 systemctl 和文件复制，`claude_runner` 用户已配置 NOPASSWD: ALL，可直接运行。**

## Architecture

### 后端 (`backend/app/`)

分层设计，4 层架构：

1. **Routers** (`routers/`) — 8 个 FastAPI APIRouter，在 `asgi.py` 注册。主要路由：`/api/auth/*`, `/api/submit`, `/api/data/*`, `/api/master-bank/*`, `/api/analytics`, `/api/profile`。
2. **Services** (`services/`) — 业务逻辑层。`llm.py` 封装 AsyncOpenAI + tenacity 重试；`clustering.py` 提供基于 LLM 的题目聚类去重（cat2 预分组 + 两遍聚类）；`utils.py` 处理图片编码和 URL 签名去重。
3. **Core** (`core/`) — `config.py` 从数据库热加载配置并同步回 `.env`；`auth.py` 实现 JWT Access Token (15min) + Refresh Token (HttpOnly Cookie, 服务端 JTI 跟踪, 轮转)；`prompts.py` 存放 4 个 LLM 提示词模板。
4. **DB** (`db/`) — `connection.py` 管理线程级 SQLite 连接 (WAL 模式)，`run_db()` 用 `asyncio.to_thread()` 包装同步调用。`operations.py` 提供可复用 CRUD。Schema 迁移在 `init_db()` 中内联执行。

**数据库：** SQLite，路径 `backend/data/interview-boss.db`。表包括：`jd`, `interview`, `questions_detail`, `question_bank`, `users`, `refresh_tokens`, `user_profile`, `user_practice_history` 等。

### 前端 (`frontend/src/`)

- **`App.vue`** — 单体编排组件（~750 行），持有所有状态（数据、认证、筛选、选中项）。子组件通过 props 接收数据、emit 触发事件。
- **`api/index.js`** — 类型化 API 客户端封装。
- **`utils/http.js`** — 自定义 Fetch 封装：自动注入 JWT、401 触发 Token 刷新并重试、5xx/网络错误重试、超时、SSE 流式、请求取消。
- **`composables/`** — `useSelection`（多选复选框）、`useNotification`（Toast + 确认对话框）、`useTheme`（主题切换）。
- **`components/`** — 20 个 Vue SFC 组件，使用 `<script setup>` Composition API 风格。

### 认证流程

Access Token 存内存（不存 localStorage）。Refresh Token 存 HttpOnly Cookie。收到 401 时，`http.js` 自动调用 `/api/auth/refresh` 并重试原始请求。

### LLM 集成

使用 OpenAI Python SDK (`AsyncOpenAI`) 对接任意 OpenAI 兼容 API。端点、模型、API Key 均可通过 `/api/profile` 在线配置，持久化到 `user_profile` 表 + `.env` 文件。`core/prompts.py` 中 4 个提示词模板：内容提取、题目打标、答案生成、答案评估。题目去重使用基于 LLM 的聚类方案（非 Embedding 相似度）。

## Key Patterns

- **题目去重：** LLM 聚类方案，cat2 预分组 + 两遍聚类 + 验证步骤。
- **批量操作：** SSE 流式推送进度更新（答案生成、题库重建）。
- **管理员系统：** `users.is_admin` 标记；管理员审核上传题目流程。
- **题库模式：** 三种模式（公共/个人/混用），控制用户可见题目范围。
- **DB 自动备份：** 破坏性操作（清除、重建）前自动备份 SQLite 数据库。
- **配置热更新：** 通过 `/api/profile` 修改配置，自动持久化到数据库和 `.env` 文件。

## Configuration

后端环境变量（`backend/.env`，参考 `.env.example`）：
- `OPENAI_API_KEY`, `OPENAI_BASE_URL` — LLM API 连接
- `LLM_MODEL_NAME` — 生成模型选择
- `JWT_SECRET` — JWT 签名密钥（未设置则自动生成）
- `ADMIN_USERNAME` — 种子管理员用户名（默认 sj）
- `ADMIN_PASSWORD` — 种子管理员密码（首次启动必填，之后可改）
- `DEBUG` — 设为 true 开启热重载和 Swagger 文档
- `ALLOWED_ORIGINS` — CORS 允许的来源（逗号分隔，开发时设 `http://localhost:3000`）

**生产环境：** Nginx 配置 `/etc/nginx/conf.d/interview-boss.conf`，反向代理 `/api/` 到 uvicorn 8000 端口（180s 超时）；前端静态文件从 `/var/www/interview-boss/dist/` 提供。

## README.md 更新规则

每当完成以下类型的工作后，**必须**同步检查并更新 README.md：
- 新增功能模块
- 项目结构发生变化（新增、删除或重命名目录/重要文件）
- API 路由发生变更
- 技术栈发生变化（新增依赖、框架升级等）
- 部署方式发生变更

更新时遵循以下原则：
- 只做最小化修改：更新项目结构展示、补充新功能的简要说明
- 禁止大幅重写或重新组织 README 的整体结构
- 保持原有的文档风格和排版不变

## 阶段性工作流

每完成一个开发阶段后，按顺序执行：
1. 运行测试，确认功能正常
2. 如涉及上述变更，更新 README.md
3. 执行 `git add` + `git commit`（遵循 Conventional Commits 规范）
4. 执行 `git push` 推送到远程仓库（不使用 `--no-verify` 等跳过选项），让用户手动输入凭据

## Language

应用 UI、提示词和文档均为中文（简体）。代码标识符、注释和 commit 消息中英混用。
