# 模拟面试 Chatbot 开发设计文档

> **日期**: 2026-05-22
> **状态**: 开发中
> **目标**: 新增模拟面试 Chatbot 功能，支持 JD+简历定制面试（模式一）和自由练习面试（模式二），使用 LangGraph 状态机 + FTS5 全文检索 RAG，零 embedding 模型依赖。

---

## 一、功能概述

### 模式一：JD + 简历定制面试
- 用户上传目标岗位 JD 和个人简历（PDF）
- AI 根据 JD 要求和简历内容生成针对性面试问题
- 支持追问、点评、改进建议

### 模式二：自由练习面试
- 从题库中检索相关题目进行练习
- 支持按分类/难度筛选
- AI 面试官模拟真实面试场景

### 核心特性
- 多轮对话，上下文自动压缩
- 用户长期记忆（跨会话保留简历、弱点等）
- FTS5 全文检索 RAG（零 embedding 模型依赖）
- SSE 流式输出

---

## 二、技术方案

### 2.1 RAG 检索方案：LLM 关键词提取 + FTS5

```
用户输入 → LLM 提取关键词 → FTS5 BM25 检索 → 相关题目作为 context → LLM 生成面试回复
```

**优势**：用户只需配置一个 LLM，无需 embedding 模型。

### 2.2 上下文压缩策略

```
消息轮次 < 5 轮  →  直接全量传给 LLM
消息轮次 5-15 轮 →  保留最近5轮 + 前面的摘要（~200 token）
消息轮次 > 15 轮 →  保留最近5轮 + 多级摘要（摘要的摘要）

UI 始终展示完整历史（从 chat_messages 表读取）
只有传给 LLM 的 context 是压缩后的
```

### 2.3 用户记忆系统

- **会话级**：LangGraph SqliteSaver checkpoint 存储对话状态
- **跨会话**：chat_memories 表存储用户长期记忆（简历、弱点、偏好）
- **自动提取**：每轮对话后 LLM 分析是否需要更新记忆

---

## 三、数据库设计（Migration 024-027）

### 3.1 chat_conversations（对话会话表）
```sql
CREATE TABLE chat_conversations (
    id TEXT PRIMARY KEY,           -- UUID，对应 LangGraph thread_id
    user_id INTEGER NOT NULL,
    mode TEXT NOT NULL,            -- 'jd_resume' | 'free_practice'
    title TEXT,                    -- 自动生成的会话标题
    jd_id INTEGER,                 -- 模式一关联的JD
    resume_text TEXT,              -- 模式一上传的简历文本
    status TEXT DEFAULT 'active',  -- active | archived
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_cc_user ON chat_conversations(user_id, status);
```

### 3.2 chat_messages（消息表）
```sql
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,            -- 'user' | 'assistant' | 'system'
    content TEXT NOT NULL,
    token_count INTEGER,           -- 用于判断何时压缩
    metadata TEXT,                 -- JSON: 检索到的题目ID等
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE
);
CREATE INDEX idx_cm_conversation ON chat_messages(conversation_id, created_at);
```

### 3.3 chat_memories（用户长期记忆表）
```sql
CREATE TABLE chat_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    memory_type TEXT NOT NULL,     -- 'resume' | 'preference' | 'weakness' | 'strength'
    content TEXT NOT NULL,
    source TEXT,                   -- 'user_upload' | 'auto_extract'
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_cmem_user ON chat_memories(user_id, is_active);
```

### 3.4 question_fts（FTS5 全文索引）
```sql
CREATE VIRTUAL TABLE question_fts USING fts5(
    question, cat1, cat2, tags, ai_answer,
    content='question_bank',
    content_rowid='id',
    tokenize='unicode61'
);
```

---

## 四、LangGraph 工作流设计

```
START
  │
  ▼
recall_memories          ← 从 chat_memories 加载用户记忆（简历、弱点等）
  │
  ▼
summarize_context        ← 消息超过阈值时压缩（保留最近5轮 + 摘要）
  │
  ▼
classify_intent          ← LLM 判断：面试提问 | 闲聊 | 练习请求 | 追问
  │
  ├── 面试提问/练习请求 ──→ fts_retrieve → generate_interview_response
  │                                         │
  ├── 闲聊/追问 ─────────→ generate_direct_response
  │                                         │
  └─────────────────────────────────────────┘
                                          │
                                          ▼
                                    extract_memory     ← 自动提取用户弱点/偏好
                                          │
                                          ▼
                                         END
```

---

## 五、开发阶段

### P0：数据库 Migration + FTS5 索引 + 基础 Chat API
- Migration 024-027：chat_conversations, chat_messages, chat_memories, question_fts
- FTS5 索引构建和同步逻辑
- 基础 CRUD API（创建会话、发消息、获取历史）

### P1：LangGraph Chatbot Graph（纯对话，无 RAG）
- ChatState 定义
- 基础对话节点（call_model）
- SqliteSaver checkpoint 持久化
- SSE 流式输出

### P2：FTS5 检索集成 + 意图分类路由
- classify_intent 节点
- fts_retrieve 节点（LLM 提取关键词 → FTS5 查询）
- 路由条件边

### P3：上下文压缩 + 用户记忆提取
- summarize_context 节点（token 超阈值时压缩）
- extract_memory 节点（自动提取弱点/偏好）
- recall_memories 节点

### P4：前端新建会话 UI
- 模式选择卡片（JD+简历 vs 自由练习）
- PDF 上传 + 文本提取
- 分类/难度选择器

### P5：前端对话页面 + SSE 流式输出
- ChatView 主页面
- ChatMessage 消息气泡组件
- ChatSidebar 会话列表
- SSE 流式渲染

### P6：会话管理
- 会话列表（侧边栏）
- 归档/删除会话
- 会话标题自动生成

---

## 六、文件结构规划

```
backend/app/
├── agents/chat/
│   ├── graph.py              # LangGraph 状态机
│   ├── state.py              # ChatState
│   ├── nodes.py              # 各节点实现
│   └── prompts.py            # 面试官 prompt
├── routers/chat.py           # 对话 API
├── services/
│   ├── chat_service.py       # 对话业务逻辑
│   └── fts_service.py        # FTS5 检索服务
├── db/migrations.py          # 新增 migration 024-027

frontend/src/
├── components/business/
│   ├── ChatView.vue           # 主对话页面
│   ├── ChatSidebar.vue        # 会话列表
│   ├── ChatMessage.vue        # 消息气泡
│   └── NewChatModal.vue       # 新建会话
├── services/chatApi.js        # 对话 API 调用
```

---

## 七、关键依赖

```
# 后端新增
langgraph-checkpoint-sqlite    # SQLite 持久化
langmem                        # 上下文压缩（可选，可自行实现）

# 无需新增
# FTS5 是 SQLite 原生能力，无需额外安装
# 用户只需配置一个 LLM API（已有 user_llm_config）
```
