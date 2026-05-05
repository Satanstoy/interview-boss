# InterviewBoss

AI 驱动的面试备战平台。支持文本 + 图片混合输入，自动识别 JD 或面经，通过向量聚类去重构建高频题库，配合 AI 生成口述级面试答案、模拟面试和知识图谱。

## 核心功能

- **多模态输入**：纯文本、图片拖拽/粘贴、文本+图片混合，兼容截图型面经
- **智能分类**：LLM 自动识别 JD/面经，提取结构化字段，缺失字段自动推断补全
- **面试题标签化**：6 大类 + 子类自动归类，标注考点标签和难度（L1/L2/L3）
- **向量聚类去重**：Embedding 余弦相似度（阈值可配，默认 0.85），自动合并重复题目
- **高频精炼题库**：按考频排序，支持分类、关键词、难度、收藏多维筛选
- **AI 生成答案**：一键生成口述级回答（算法/系统设计/基础原理三种风格），支持批量生成 + SSE 实时进度
- **答题评估**：AI 对用户口述答案进行质量评分与改进建议
- **模拟面试**：随机抽题，支持难度筛选，先思考后查看参考答案
- **知识图谱**：ECharts 6 可视化知识点关联网络
- **多用户系统**：JWT 双 Token 认证（Access 15min + Refresh HttpOnly Cookie + 服务端 JTI 轮转），三种题库模式（公共/个人/混用），管理员审核
- **数据分析**：技术栈热度、考点分布、难度分布、练习趋势可视化
- **系统配置热更新**：LLM / Embedding 模型、API 地址、超时时间等均可在线修改，持久化至数据库

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | FastAPI + Uvicorn + SQLite (WAL) |
| 前端 | Vue 3 (Composition API) + Vite + Tailwind CSS |
| LLM | OpenAI Compatible API（支持代理/国产模型） |
| 向量 | OpenAI Embeddings + 余弦相似度聚类 |
| 认证 | JWT 双 Token（Access 15min + Refresh HttpOnly Cookie） |
| 图表 | ECharts 6 |
| Markdown | marked（AI 答案渲染） |
| 部署 | Nginx + HTTPS (自签证书) + systemd |

## 项目结构

```
interview-boss/
├── backend/
│   ├── app/
│   │   ├── core/          # auth（JWT 双 Token）、config（热更新）、prompts（4 套模板）、logging
│   │   ├── routers/       # 8 个路由：health / auth / submit / data / master_bank / interview / analytics / profile
│   │   ├── services/      # llm（AsyncOpenAI + 重试）、embedding（余弦相似度去重）、utils（图片编码/URL签名）
│   │   ├── db/            # SQLite 连接管理（线程本地 + WAL）、CRUD operations、自动迁移
│   │   ├── middleware/     # 请求日志
│   │   └── models/        # Pydantic request schemas
│   ├── data/
│   │   └── multimodal.db  # SQLite 数据库（破坏性操作前自动备份）
│   └── .env               # 环境变量（不提交）
├── frontend/
│   ├── src/
│   │   ├── App.vue        # SPA 主控（状态管理 + 条件渲染）
│   │   ├── components/    # 16 个 SFC 组件（模拟面试、题库、分析、知识图谱、设置等）
│   │   ├── composables/   # useSelection（多选）、useNotification（Toast + 确认框）
│   │   ├── api/           # API 函数封装
│   │   └── utils/         # http.js（JWT 注入 + 401 自动刷新 + 重试 + SSE 流式 + 请求取消）
│   └── package.json
├── pyproject.toml         # Python 依赖（权威来源）
└── README.md
```

## 快速开始

### 环境要求

- Python >= 3.10
- Node.js >= 16
- Nginx

### 配置后端

```bash
cd interview-boss/backend
cp .env.example .env
```

编辑 `.env`：

```env
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o

OPENAI_API_KEY_EMBEDDING=your_embedding_key
OPENAI_BASE_URL_EMBEDDING=https://api.openai.com/v1
EMBEDDING_MODEL_NAME=text-embedding-3-small

# 可选
SIMILARITY_THRESHOLD=0.85
LLM_TIMEOUT=120
JWT_SECRET=your-64-byte-random-secret
```

> 后端启动后，上述配置均可通过 `/api/profile` 接口在线修改，变更会同步持久化到数据库和 `.env` 文件。

### 启动

```bash
# 后端
cd backend && uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000

# 前端开发
cd frontend && npm install && npm run dev

# 前端构建部署（自动输出到 /var/www/interview-boss/dist/）
cd frontend && npm run build
```

### Nginx

```nginx
server {
    listen 443 ssl;
    server_name _;
    ssl_certificate     /etc/nginx/ssl/selfsigned.crt;
    ssl_certificate_key /etc/nginx/ssl/selfsigned.key;

    location / {
        root /var/www/interview-boss/dist;
        try_files $uri $uri/ /index.html;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_read_timeout 180s;
    }
}
```

## API 概览

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/login` | 登录（返回 access token + HttpOnly refresh cookie） |
| POST | `/api/auth/refresh` | 刷新 token（cookie 自动携带） |
| POST | `/api/auth/logout` | 注销（服务端撤销 refresh token） |
| GET  | `/api/auth/me` | 获取当前用户信息 |

### 核心业务

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/submit` | 提交文本/图片，自动识别入库 |
| GET  | `/api/master-bank` | 精炼题库（支持分类/搜索/难度/收藏筛选） |
| POST | `/api/master-bank/build` | 全量重建题库（Embedding 聚类，SSE 进度推送） |
| POST | `/api/master-bank/generate-answer/{id}` | AI 生成答案 |
| POST | `/api/master-bank/batch-generate` | 批量生成答案 |
| POST | `/api/master-bank/random` | 随机抽题（模拟面试） |
| POST | `/api/evaluate-answer` | AI 评估答题质量 |
| GET  | `/api/analytics` | 全局分析数据 |
| GET  | `/api/practice-stats` | 个人练习统计 |
| GET  | `/api/knowledge-graph` | 知识图谱数据 |
| GET  | `/api/profile` | 获取系统配置 |
| POST | `/api/profile` | 更新系统配置（LLM/Embedding/阈值等） |

## 数据库

| 表 | 说明 |
|------|------|
| `users` | 用户（用户名、密码哈希、管理员标志、题库模式） |
| `question_bank` | 统一题库（题目、分类、标签、难度、AI 答案、向量、owner_id、审核状态） |
| `refresh_tokens` | Refresh token JTI（服务端校验 + 轮转） |
| `user_practice_history` | 练习记录（用户隔离） |
| `user_profile` | 系统配置 KV 存储（LLM 模型、API 地址、阈值等） |
| `jd` | 职位描述 |
| `interview` | 面经记录 |
| `questions_detail` | 面试题明细 |
| `master_question_bank` | 旧版题库（已迁移至 question_bank，保留兼容） |
| `practice_history` | 旧版练习记录（已迁移至 user_practice_history，保留兼容） |

## License

MIT
