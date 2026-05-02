# 多模态 JD 与面经智能解析系统

基于 LLM 的多模态信息提取与面试题智能分类系统。支持文本 + 图片混合输入，自动识别 JD（职位描述）或面经，提取结构化数据，并通过向量聚类去重构建高频精炼题库，配合 AI 生成口述级面试答案。

## 系统功能

- **多模态输入**：支持纯文本、图片、或文本+图片混合提交，兼容截图型面经
- **智能分类**：LLM 自动判断内容为 JD 或面经，提取结构化字段
- **面试题标签化**：自动将面试题归入 6 大类（项目经验、Agent/LLM、基础工程、分布式、算法、模型训练）及子类，标注考点标签和难度
- **向量聚类去重**：基于 Embedding 向量的余弦相似度（阈值 0.85），自动合并重复题目，统计出现频次
- **高频精炼题库**：按考频排序的核心真题库，支持按分类筛选
- **AI 生成答案**：一键召唤 LLM 生成口述级面试回答，支持批量生成和手动编辑
- **面经溯源**：每道题目可追溯到原始面经来源（公司、轮次、链接）
- **数据分析**：ECharts 可视化考点分布、技术栈热度、难度分布
- **数据管理**：支持行内编辑、批量删除、重新打标、CSV 导出

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 前端框架 | Vue 3 + Vite |
| UI 样式 | Tailwind CSS |
| 数据库 | SQLite |
| LLM 接口 | OpenAI Compatible API（支持代理/国产模型） |
| 向量计算 | OpenAI Embeddings API + 余弦相似度 |
| 图表 | ECharts |
| Markdown 渲染 | Marked.js |

## 项目结构

```
multimodal-parser/
├── backend/
│   ├── main.py              # FastAPI 主应用（全部 API 路由）
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
│       └── style.css        # Tailwind 引入
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
```

> 如果使用国内兼容 OpenAI 格式的模型服务，修改 `BASE_URL` 即可。

### 3. 启动后端

```bash
cd multimodal-parser/backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

后端将运行在 `http://localhost:8000`。

### 4. 构建前端

```bash
cd multimodal-parser/frontend

# 安装依赖
npm install

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

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/submit` | 提交文本/图片，自动识别 JD 或面经并入库 |
| GET | `/api/data/{type}` | 获取数据（type: jd / interview / tagged） |
| GET | `/api/download/{type}` | 下载 CSV（type: jd / interview / tagged） |
| DELETE | `/api/data/{type}/{index}` | 删除指定行 |
| PUT | `/api/data/update` | 通用字段更新 |
| GET | `/api/analytics` | 获取全局分析数据 |
| GET | `/api/master-bank` | 获取精炼题库 |
| POST | `/api/master-bank/build` | 全量重建精炼题库（向量聚类） |
| POST | `/api/master-bank/generate-answer/{id}` | 为指定题目生成 AI 答案 |
| POST | `/api/master-bank/re-tag/{id}` | 重新打标题目 |
| DELETE | `/api/master-bank/{id}` | 删除精炼题库中的题目 |
| POST | `/api/interview/{id}/re-process` | 重新分析面经记录 |
| POST | `/api/sync-db` | 同步数据库（从 questions_detail 重建 master） |
| POST | `/api/clear-db` | 清空所有数据库表 |
| POST | `/api/normalize-categories` | 批量规范化分类字段格式 |

## 工具脚本

### migrate_to_sqlite.py

将旧版 CSV 数据迁移到 SQLite 数据库。适用于从 CSV 存储升级到 SQLite 的场景。

```bash
cd multimodal-parser/backend
python migrate_to_sqlite.py
```

### convert_to_tagged.py

批量对 `interview.csv` 中的面经题目调用 LLM 进行结构化打标，结果写入 `interview_questions.csv`。适用于离线批量处理。

```bash
cd multimodal-parser/backend
python convert_to_tagged.py
```

## 数据库表结构

| 表名 | 说明 |
|------|------|
| `jd` | 职位描述（公司、岗位、薪资、技术栈、加分项） |
| `interview` | 面经原始记录（公司、轮次、考察重点、题目清单） |
| `questions_detail` | 面试题明细（题目、一级大类、二级子类、考点标签、难度） |
| `master_question_bank` | 精炼题库（聚类去重后的高频真题，含向量、AI 答案、面经溯源） |

## License

MIT