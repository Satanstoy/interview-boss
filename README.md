<div align="center">

<img src="logo.png" alt="InterviewBoss Logo" width="400" />

# InterviewBoss

**AI 驱动的面试备战平台 — 从 JD / 面经到高频题库，一键搞定**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://python.org)
[![Vue](https://img.shields.io/badge/Vue-3-42b883.svg)](https://vuejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688.svg)](https://fastapi.tiangolo.com)

[快速开始](#快速开始) | [功能详解](#功能详解) | [部署指南](#部署指南) | [API 文档](#api-概览)

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

cat2 预分组 + 两遍聚类 + 验证步骤，语义相近的题目自动合并，追踪考频和来源链接。
</details>

<details>
<summary><strong>AI 生成答案</strong> — 三种口述风格一键生成</summary>

- 算法/代码风格（含 Python 实现）
- 系统设计/架构风格
- 基础理论风格

支持单题生成和批量生成（SSE 实时进度推送）。
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

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 数据库 | SQLite (WAL 模式) |
| LLM | OpenAI Compatible API（支持代理 / 国产模型） |
| 聚类去重 | LLM-based Clustering（cat2 预分组 + 两遍聚类） |
| 前端框架 | Vue 3 (Composition API) + Vite |
| 样式 | Tailwind CSS |
| 图表 | ECharts 6 |
| 认证 | JWT 双 Token（Access + HttpOnly Refresh） |
| 部署 | Nginx + systemd |
| 包管理 | uv (Python) / npm (Node.js) |

## 项目结构

```
interview-boss/
├── backend/
│   ├── app/
│   │   ├── core/          # 认证、配置热更新、LLM 提示词模板、日志
│   │   ├── routers/       # 8 个 API 路由模块（auth, submit, data, master_bank, interview, analytics, profile, health）
│   │   ├── services/      # LLM 调用、聚类去重、工具函数
│   │   ├── db/            # SQLite 连接管理、CRUD、自动迁移
│   │   ├── middleware/     # 请求日志中间件
│   │   └── models/        # Pydantic 请求/响应模型
│   ├── data/              # SQLite 数据库文件（自动备份）
│   └── .env.example       # 环境变量模板
├── frontend/
│   ├── src/
│   │   ├── components/    # 20 个 Vue SFC 组件
│   │   ├── composables/   # 组合式函数（useSelection, useNotification, useTheme）
│   │   ├── api/           # API 封装
│   │   └── utils/         # HTTP 客户端（JWT + 自动刷新）、Markdown 渲染、校验
│   └── public/            # 静态资源（favicon）
├── pyproject.toml         # Python 依赖定义
├── deploy-frontend.sh     # 前端部署脚本
├── nginx-hardened.conf    # Nginx 安全配置参考
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

### 3. 启动后端

```bash
cd backend
uv sync
uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000
```

首次启动会自动创建数据库和种子管理员账号。

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:3000`，注册账号即可开始使用。

### 5. 生产部署（可选）

详见下方 [部署指南](#部署指南)。

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | LLM API 密钥 | *(必填)* |
| `OPENAI_BASE_URL` | LLM API 地址 | 空 |
| `LLM_MODEL_NAME` | 生成模型 | `gpt-4o` |
| `OPENAI_API_KEY_EMBEDDING` | Embedding API 密钥 | 回退到 LLM 密钥 |
| `OPENAI_BASE_URL_EMBEDDING` | Embedding API 地址 | 空 |
| `EMBEDDING_MODEL_NAME` | Embedding 模型 | `text-embedding-3-small` |
| `SIMILARITY_THRESHOLD` | 去重相似度阈值 | `0.85` |
| `LLM_TIMEOUT` | LLM 超时（秒） | `120` |
| `JWT_SECRET` | JWT 签名密钥 | 自动生成 |
| `ADMIN_USERNAME` | 种子管理员用户名 | `sj` |
| `ADMIN_PASSWORD` | 种子管理员密码 | *(首次必填)* |
| `DEBUG` | 开启热重载和 Swagger 文档 | `false` |
| `ALLOWED_ORIGINS` | CORS 允许来源（逗号分隔） | 空 |
| `MAX_FILE_SIZE_MB` | 最大上传大小（MB） | `10` |

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

示例：
```
feat: 添加知识图谱可视化模块
fix: 修复模拟面试抽题权重计算错误
refactor: 提取 HTTP 客户端为独立模块
```

### PR 流程

1. 从 `dev` 创建功能分支（`feature/*` 或 `fix/*`）
2. 开发完成后提交 PR 到 `dev`
3. 确保功能正常后合并
4. `dev` 稳定后合并到 `main` 发布

## 部署指南

### 后端部署

#### systemd 服务

```ini
# /etc/systemd/system/interview-boss.service
[Unit]
Description=InterviewBoss Backend
After=network.target

[Service]
WorkingDirectory=/root/sj/interview-boss/backend
ExecStart=/root/.local/bin/uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
EnvironmentFile=/root/sj/interview-boss/backend/.env

[Install]
WantedBy=multi-user.target
```

启用并启动：
```bash
sudo systemctl daemon-reload
sudo systemctl enable interview-boss
sudo systemctl start interview-boss
```

#### 常用运维命令

```bash
# 查看服务状态
sudo systemctl status interview-boss

# 重启服务（代码或配置变更后）
sudo systemctl restart interview-boss

# 查看实时日志
sudo journalctl -u interview-boss -f

# 查看最近 100 行日志
sudo journalctl -u interview-boss -n 100

# 查看错误日志
sudo journalctl -u interview-boss -p err
```

### 前端部署

#### 构建与部署

```bash
cd frontend
npm run build
```

构建完成后，静态文件输出到 `frontend/dist/`。使用部署脚本复制到 Nginx 目录：

```bash
sudo bash deploy-frontend.sh
```

或手动操作：
```bash
sudo rm -rf /var/www/interview-boss/dist/*
sudo cp -r frontend/dist/* /var/www/interview-boss/dist/
sudo chown -R www-data:www-data /var/www/interview-boss/dist/
```

#### Nginx 配置

生产环境 Nginx 配置参考 `nginx-hardened.conf`，核心配置：

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /etc/nginx/ssl/selfsigned.crt;
    ssl_certificate_key /etc/nginx/ssl/selfsigned.key;

    client_max_body_size 15m;

    # 前端静态文件
    location / {
        root /var/www/interview-boss/dist;
        try_files $uri $uri/ /index.html;

        # 缓存策略：带 hash 的静态资源长期缓存，index.html 不缓存
        location ~* \.(?:js|css|woff2?|svg|png|jpg|ico)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
        location = /index.html {
            expires -1;
            add_header Cache-Control "no-store, no-cache, must-revalidate";
        }
    }

    # API 反向代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
    }

    # 安全响应头
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'" always;
}
```

HTTP → HTTPS 自动跳转：
```nginx
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}
```

配置文件位置：`/etc/nginx/conf.d/interview-boss.conf`

```bash
# 测试配置
sudo nginx -t

# 重载配置
sudo systemctl reload nginx
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

</details>

<details>
<summary><strong>题库管理</strong></summary>

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/master-bank` | 题库列表（分页、筛选、排序） |
| POST | `/api/master-bank/build` | 全量重建题库（SSE 进度） |
| POST | `/api/master-bank/generate-answer/{id}` | AI 生成答案 |
| POST | `/api/master-bank/batch-generate` | 批量生成答案 |
| POST | `/api/master-bank/random` | 随机抽题（模拟面试） |
| POST | `/api/evaluate-answer` | AI 评估答题质量 |
| DELETE | `/api/master-bank/{id}` | 软删除题目（移至回收站） |
| POST | `/api/master-bank/batch-delete` | 批量软删除题目 |
| GET | `/api/master-bank/trash` | 获取回收站列表 |
| POST | `/api/master-bank/restore/{id}` | 恢复已删除题目 |
| POST | `/api/master-bank/batch-restore` | 批量恢复题目 |

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
- 题库操作（生成答案、批量生成、答题评估）均校验用户可见范围（`bank_mode` + `owner_id`），防止权限提升。
- 分析数据按用户 `bank_mode` 隔离，普通用户仅可见公共/个人数据。

### 开发者须知

1. 复制 `.env.example` 为 `.env`，填入自己的密钥，**不要**使用他人的 `.env`。
2. 生产环境务必设置强密码的 `JWT_SECRET` 和 `ADMIN_PASSWORD`。
3. 定期轮换 API 密钥。
4. 如发现敏感信息泄露，立即轮换相关密钥并清理 Git 历史。

## 许可证

[MIT](LICENSE)
