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

> **输入** JD / 面经截图/文字 → **AI 识别分类** → **提取面试题** → **向量聚类去重** → **生成口述级答案** → **模拟面试练习**

零配置开箱即用，支持任意 OpenAI 兼容 API（GPT-4o、Claude、国产模型均可）。

## 工作流程

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  粘贴文本    │     │  LLM 识别     │     │  面试题提取   │     │  向量聚类     │
│  拖拽图片    │────▶│  JD / 面经    │────▶│  标签 + 难度  │────▶│  去重合并     │
│  混合输入    │     │  字段补全     │     │  6 大类归类   │     │  高频排序     │
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
<summary><strong>向量聚类去重</strong> — Embedding 余弦相似度自动合并</summary>

阈值可配（默认 0.85），语义相近的题目自动合并，追踪考频和来源链接。
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

API 地址、模型名称、超时时间、相似度阈值等均可通过界面修改，自动持久化到数据库和 `.env` 文件。
</details>

## 快速开始

### 环境要求

| 依赖 | 版本 |
|------|------|
| Python | >= 3.10 |
| Node.js | >= 16 |

### 1. 克隆项目

```bash
git clone https://gitee.com/your-username/interview-boss.git
cd interview-boss
```

### 2. 配置后端

```bash
cd backend
cp .env.example .env
```

编辑 `.env`，填入你的 API 密钥：

```env
OPENAI_API_KEY=sk-xxx           # LLM API 密钥
OPENAI_BASE_URL=https://api.openai.com/v1   # API 地址（支持代理）
LLM_MODEL_NAME=gpt-4o           # 模型名称
```

> 其他配置（Embedding 模型、相似度阈值、超时时间等）均有默认值，可在启动后通过界面在线修改。

### 3. 启动后端

```bash
uv sync
uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000
```

### 4. 启动前端

```bash
cd ../frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:3000`，注册账号即可开始使用。

### 5. 生产部署（可选）

```bash
# 构建前端
npm run build

# 后端使用 systemd 管理
sudo systemctl restart interview-boss
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 数据库 | SQLite (WAL 模式) |
| LLM | OpenAI Compatible API（支持代理 / 国产模型） |
| 向量检索 | OpenAI Embeddings + 余弦相似度 |
| 前端框架 | Vue 3 (Composition API) + Vite |
| 样式 | Tailwind CSS |
| 图表 | ECharts 6 |
| 认证 | JWT 双 Token（Access + HttpOnly Refresh） |
| 部署 | Nginx + systemd |

## 部署指南

### Nginx 配置

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /etc/nginx/ssl/selfsigned.crt;
    ssl_certificate_key /etc/nginx/ssl/selfsigned.key;

    # 前端静态文件
    location / {
        root /var/www/interview-boss/dist;
        try_files $uri $uri/ /index.html;
    }

    # API 反向代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_read_timeout 180s;
    }
}
```

### systemd 服务（可选）

```ini
[Unit]
Description=InterviewBoss Backend
After=network.target

[Service]
WorkingDirectory=/path/to/interview-boss/backend
ExecStart=/path/to/uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

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
| `MAX_FILE_SIZE_MB` | 最大上传大小（MB） | `10` |

> 所有配置均可在运行时通过 `/api/profile` 界面在线修改，变更会自动持久化到数据库和 `.env` 文件。

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

</details>

完整 API 文档可在启动后访问 `http://localhost:8000/docs` 查看 Swagger UI。

## 项目结构

```
interview-boss/
├── backend/
│   ├── app/
│   │   ├── core/          # 认证、配置热更新、LLM 提示词模板
│   │   ├── routers/       # 8 个 API 路由模块
│   │   ├── services/      # LLM 调用、Embedding 去重、工具函数
│   │   ├── db/            # SQLite 连接管理、CRUD、自动迁移
│   │   ├── middleware/     # 请求日志
│   │   └── models/        # Pydantic 请求模型
│   └── data/              # SQLite 数据库（自动备份）
├── frontend/
│   └── src/
│       ├── components/    # 16 个 Vue 组件
│       ├── composables/   # 组合式函数
│       ├── api/           # API 封装
│       └── utils/         # HTTP 客户端（JWT + 自动刷新）
├── pyproject.toml         # Python 依赖
└── README.md
```

## 许可证

[MIT](LICENSE)
