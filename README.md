# 多模态 JD 与面经智能解析系统

基于 LLM 的多模态信息提取与面试题智能分类系统。支持文本 + 图片混合输入，自动识别 JD（职位描述）或面经，提取结构化数据，并通过向量聚类去重构建高频精炼题库，配合 AI 生成口述级面试答案。

## 系统功能

- **多模态输入**：支持纯文本、图片拖拽/粘贴、或文本+图片混合提交，兼容截图型面经
- **智能分类**：LLM 自动判断内容为 JD 或面经，提取结构化字段；对缺失字段（公司、轮次、难度）自动推断补全
- **面试题标签化**：自动将面试题归入 6 大类（项目经验、Agent/LLM、基础工程、分布式、算法、模型训练）及子类，标注考点标签和难度（L1-基础 / L2-中等 / L3-困难）
- **向量聚类去重**：基于 Embedding 向量的余弦相似度（阈值可配置，默认 0.85），自动合并重复题目，统计出现频次
- **高频精炼题库**：按考频排序的核心真题库，支持按分类、关键词、难度、收藏状态多维筛选
- **AI 生成答案**：一键召唤 LLM 生成口述级面试回答（区分算法题/系统设计题/基础原理题三种风格），支持批量生成、手动编辑和失败重试
- **模拟面试**：从题库中随机抽题，支持按难度筛选，先思考后查看参考答案
- **题目收藏**：对重点题目标记收藏，支持仅看收藏筛选
- **面经溯源**：每道题目可追溯到原始面经来源（公司、轮次、链接）
- **数据分析**：ECharts 可视化考点分布、技术栈热度、难度分布
- **数据管理**：支持行内编辑、批量删除、批量重新分析、重新打标、CSV 导出
- **URL 去重**：基于 URL 签名的增强去重（支持小红书、牛客、Boss直聘等平台）

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 前端框架 | Vue 3 (Composition API) + Vite |
| UI 样式 | Tailwind CSS |
| 数据库 | SQLite |
| LLM 接口 | OpenAI Compatible API（支持代理/国产模型） |
| 向量计算 | OpenAI Embeddings API + 余弦相似度 |
| 重试机制 | Tenacity（指数退避，最多 3 次） |
| 图表 | ECharts 6 |
| Markdown 渲染 | Marked.js |
| HTTP 客户端 | 自封装 Fetch（超时控制、自动重试、请求取消） |

## 项目结构

```
multimodal-parser/
├── backend/
│   ├── main.py              # FastAPI 主应用（全部 API 路由、中间件、Prompt 模板）
│   ├── requirements.txt     # Python 依赖
│   ├── .env.example         # 环境变量模板
│   ├── .env                 # 实际环境变量（不提交到 Git）
│   ├── migrate_to_sqlite.py # CSV → SQLite 迁移脚本
│   ├── convert_to_tagged.py # 面经题目批量打标脚本
│   └── data/
│       └── multimodal.db    # SQLite 数据库文件
├── frontend/
│   ├── index.html           # 入口 HTML
│   ├── package.json         # 前端依赖与构建脚本
│   ├── vite.config.js       # Vite 配置
│   ├── tailwind.config.js   # Tailwind 配置
│   ├── postcss.config.js    # PostCSS 配置
│   └── src/
│       ├── main.js          # Vue 入口
│       ├── App.vue          # 主组件（全部前端逻辑）
│       ├── style.css        # Tailwind 引入
│       └── utils/
│           └── http.js      # 统一 HTTP 请求封装（超时/重试/取消）
├── .gitignore
└── README.md
```

## 快速开始

### 1. 环境要求

- Python >= 3.10
- Node.js >= 16
- Nginx

### 2. 配置后端

```bash
cd multimodal-parser/backend

# 安装 Python 依赖
pip install -r requirements.txt

# 创建环境变量文件
cp .env.example .env
```

编辑 `.env` 文件，填入你的 API 配置：

```env
# 主 LLM 接口（用于内容提取、分类、生成答案）
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o

# Embedding 接口（用于向量聚类，可与主 LLM 使用不同服务）
OPENAI_API_KEY_EMBEDDING=your_embedding_api_key
OPENAI_BASE_URL_EMBEDDING=https://api.openai.com/v1
EMBEDDING_MODEL_NAME=text-embedding-3-small

# 可选配置
SIMILARITY_THRESHOLD=0.85    # 向量相似度阈值（0-1），越高越严格
LLM_TIMEOUT=120              # LLM 调用超时时间（秒）
MAX_FILE_SIZE_MB=10          # 单张图片最大体积（MB）
```

> 如果使用国内兼容 OpenAI 格式的模型服务，修改 `BASE_URL` 即可。主 LLM 和 Embedding 可以使用不同的服务。

### 3. 启动后端

```bash
cd multimodal-parser/backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

后端将运行在 `http://localhost:8000`，启动时自动初始化 SQLite 数据库。

### 4. 构建前端

```bash
cd multimodal-parser/frontend

# 安装依赖
npm install

# 开发模式
npm run dev

# 构建并自动部署到 Nginx 目录
npm run build
```

`npm run build` 会执行 Vite 构建，并将产物自动拷贝到 `/var/www/multimodal-parser/dist/`。

### 5. 配置 Nginx

在 `/etc/nginx/sites-available/` 下创建配置文件（如 `multimodal-parser`）：

```nginx
server {
    listen 80;
    server_name your_domain.com;  # 替换为你的域名或 IP

    # 前端静态文件
    root /var/www/multimodal-parser/dist;
    index index.html;

    # 前端路由（Vue SPA history 模式）
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 反向代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 文件上传大小限制（支持多张图片）
        client_max_body_size 50m;
    }
}
```

启用配置并重启 Nginx：

```bash
sudo ln -s /etc/nginx/sites-available/multimodal-parser /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## API 接口概览

### 核心业务

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/submit` | 提交文本/图片，自动识别 JD 或面经并入库（支持多文件上传） |
| GET | `/api/data/{type}` | 分页获取数据（type: jd / interview / tagged），支持 page/page_size 参数 |
| GET | `/api/download/{type}` | 下载 CSV（type: jd / interview / tagged） |
| DELETE | `/api/data/{type}/{record_id}` | 按记录 ID 删除指定行（面经删除时联动清理题库来源） |
| PUT | `/api/data/update` | 通用字段更新（白名单校验，仅允许更新指定字段） |
| GET | `/api/analytics` | 获取全局分析数据（技术栈热度、考点分布、难度分布） |

### 精炼题库

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/master-bank` | 分页获取精炼题库（支持 sort=frequency_desc/recent） |
| POST | `/api/master-bank/build` | 全量重建精炼题库（Embedding 向量聚类，保留已有 AI 答案） |
| POST | `/api/master-bank/generate-answer/{id}` | 为指定题目生成 AI 答案（已有有效答案则直接返回） |
| POST | `/api/master-bank/re-tag/{id}` | 重新调用 LLM 对题目进行结构化打标 |
| POST | `/api/master-bank/toggle-star/{id}` | 切换题目收藏状态 |
| GET | `/api/master-bank/random` | 随机抽题（支持 count/cat1/difficulty 参数，用于模拟面试） |
| DELETE | `/api/master-bank/{id}` | 删除精炼题库中的题目（联动清理 questions_detail） |

### 面经管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/interview/{id}/re-process` | 重新分析面经记录（清理旧来源 → 重新提取打标 → 增量更新题库） |

### 系统维护

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查（含数据库连通性检测） |
| POST | `/api/sync-db` | 同步数据库（从 questions_detail 重建 master_question_bank） |
| POST | `/api/clear-db` | 清空所有数据库表 |
| POST | `/api/normalize-categories` | 批量规范化 cat1/cat2 字段格式 |

## 前端功能模块

| 模块 | 说明 |
|------|------|
| **JD 库** | 展示职位描述数据，支持行内编辑公司/岗位、批量删除、CSV 导出 |
| **面经** | 展示原始面经记录，支持行内编辑所有字段、单条/批量重新分析、批量删除 |
| **🔥 题库** | 精炼题库核心页面，支持分类筛选、关键词搜索、难度过滤、收藏筛选、全选/反选、批量生成答案、批量删除、重新打标、展开查看 AI 答案与面经溯源 |
| **🎯 模拟** | 模拟面试模式，随机抽取 5 题，支持难度筛选，先思考后查看参考答案 |
| **全局分析** | 左侧面板展示考点分布饼图（ECharts）、技术栈热度排行、题库分类目录 |

## 数据库表结构

| 表名 | 说明 |
|------|------|
| `jd` | 职位描述（来源链接、公司、岗位名称、薪资范围、核心技术要求、加分项） |
| `interview` | 面经原始记录（来源链接、公司、面试轮次、考察重点、具体题目清单、难易程度） |
| `questions_detail` | 面试题明细（来源链接、公司、面试轮次、题目、一级大类、二级子类、考点标签、难度标签） |
| `master_question_bank` | 精炼题库（题目、一级大类、二级子类、考点标签、难度、考频、AI 答案、Embedding 向量、面经来源列表、收藏状态） |

## 面试题分类体系

| 一级大类 | 二级子类 |
|----------|----------|
| A. 项目经验与设计 | A1. 项目介绍与背景 / A2. 系统架构设计 / A3. 难点攻关与优化 / A4. 反思与改进 |
| B. Agent与LLM应用 | B1. Agent架构设计 / B2. 记忆管理 / B3. RAG / B4. 工具调用 / B5. Prompt工程 / B6. 推理范式 / B7. 上下文管理 / B8. 监控评估 |
| C. 基础工程能力 | C1. 编程语言基础 / C2. 框架与中间件 / C3. 数据库基础 / C4. 操作系统与网络 |
| D. 分布式系统与高并发 | D1. 分布式一致性 / D2. 高并发策略 / D3. 链路与排障 |
| E. 算法与数据结构 | E1. 算法手撕与数据结构 |
| F. 模型训练与评估 | F1. 微调与评估 |

## 工具脚本

### migrate_to_sqlite.py

将旧版 CSV 数据迁移到 SQLite 数据库。适用于从 CSV 存储升级到 SQLite 的场景。

```bash
cd multimodal-parser/backend
python3 migrate_to_sqlite.py
```

### convert_to_tagged.py

批量对 `interview.csv` 中的面经题目调用 LLM 进行结构化打标，结果写入 `interview_questions.csv`。适用于离线批量处理。

```bash
cd multimodal-parser/backend
python3 convert_to_tagged.py
```

## License

MIT