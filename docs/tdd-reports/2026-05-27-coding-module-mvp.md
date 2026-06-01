# 手撕代码模块 MVP — 设计决策与实现记录

日期：2026-05-27

## 概述

在 InterviewBoss 中新增"手撕代码"练习模块，模拟面试手撕场景。核心卖点是 AI 评审（不跑代码），每次提交后 AI 分析语法/思路/复杂度，错误归类存入用户错误集。

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 是否执行代码 | 否，纯 AI 评审 | 服务器 4c4g，无法安全运行用户代码沙箱 |
| 编辑器 | Monaco Editor | 功能完整，支持语法高亮、自动补全 |
| 支持语言 | Python、C、Java | 覆盖主流面试语言 |
| 是否存参考答案 | 否 | AI 直接分析用户代码，更灵活 |
| 错误分类 | syntax/logic/algorithm/complexity/style | 5 类覆盖常见面试错误 |
| 集成方式 | 直接添加文件 | 复用现有 auth/LLM/DB 基础设施 |
| 前端集成 | Tab 切换 | 复用现有 TabBar 模式，无 Vue Router |

## 数据模型

### coding_problems（题库）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 ID |
| title | TEXT | 题目标题 |
| description | TEXT | 题目描述（Markdown） |
| difficulty | TEXT | easy/medium/hard |
| tags | TEXT | JSON 数组，如 `["数组","哈希表"]` |
| expected_complexity | TEXT | 预期最优复杂度 |
| source | TEXT | 来源标记 |
| supported_languages | TEXT | JSON 数组，默认 `["python","c","java"]` |
| is_active | INTEGER | 是否启用 |

### coding_submissions（提交记录）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 ID |
| user_id | INTEGER FK | 用户 ID |
| problem_id | INTEGER FK | 题目 ID |
| language | TEXT | python/c/java |
| code | TEXT | 用户代码 |
| mode | TEXT | full_review/hint |
| hint_round | INTEGER | 提示轮次（0=完整评审） |
| parent_submission_id | INTEGER FK | 渐进提示时指向上一轮 |
| ai_feedback | TEXT | AI 评审/提示内容（Markdown） |
| error_categories | TEXT | JSON 数组，如 `["logic","boundary"]` |
| is_passed | INTEGER | 是否通过 |

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/coding/problems` | 题目列表（difficulty/tag 筛选、分页） |
| GET | `/api/coding/problems/{id}` | 单题详情 |
| POST | `/api/coding/submit` | 提交代码，触发 AI 评审 |
| GET | `/api/coding/submissions` | 提交历史（problem_id 筛选、分页） |
| GET | `/api/coding/submissions/{id}` | 单条提交详情 |
| GET | `/api/coding/error-stats` | 错误统计（按 category 聚合） |

## 前端架构

```
TabBar.vue (新增 "手撕代码" Tab)
  └── CodingPractice.vue (主页面，左右分栏)
        ├── 左侧：题目列表 + 筛选 + 错误统计
        └── 右侧：题目描述 + 语言切换 + Monaco 编辑器 + AI 反馈
              └── CodeEditor.vue (Monaco 封装)
```

## 测试覆盖

15 个测试用例，覆盖：
- 题目列表（空/有数据/筛选/详情/404）
- 代码提交（成功/无效语言/空代码/题目不存在）
- 提交历史（空/详情 404）
- 错误统计（空数据）
- 数据库迁移（表结构/列验证）

## 测试基础设施修复

开发过程中发现并修复了 conftest.py 的两个关键问题：

1. **`from X import Y` 拷贝引用问题**：路由模块用 `from app.db.connection import run_db` 导入，拷贝了函数引用。修改 `db_module.run_db` 不影响已导入的副本。修复：在 `client` fixture 中遍历 `sys.modules`，对所有 `app.routers.*` 模块直接 patch `run_db` 和 `get_db_connection`。

2. **SQLite 线程安全**：内存 SQLite 连接默认 `check_same_thread=True`，TestClient 的 handler 线程无法使用。修复：`sqlite3.connect(":memory:", check_same_thread=False)`。

## 题库

50 道高频面试算法题，覆盖：
- 数组/字符串（8 题）
- 链表（6 题）
- 树（8 题）
- 排序/搜索（5 题）
- 动态规划（8 题）
- 栈/队列（4 题）
- 字符串（2 题）
- 回溯（4 题）
- 图（2 题）
- 堆（2 题）
- 区间（1 题）

## 文件清单

| 操作 | 文件 |
|------|------|
| 新建 | `backend/app/routers/coding.py` |
| 新建 | `frontend/src/components/business/CodeEditor.vue` |
| 新建 | `frontend/src/components/business/CodingPractice.vue` |
| 新建 | `frontend/src/services/codingApi.js` |
| 修改 | `backend/app/db/migrations.py` — 新增 migration 030 + 50 道 seed 题 |
| 修改 | `backend/app/models/schemas.py` — 新增 CodingSubmitRequest |
| 修改 | `backend/app/core/prompts.py` — 新增 CODING_REVIEW_PROMPT、CODING_HINT_PROMPT |
| 修改 | `backend/app/asgi.py` — 注册 coding router |
| 修改 | `frontend/src/api/index.js` — re-export codingApi |
| 修改 | `frontend/src/components/common/TabBar.vue` — 新增 Tab |
| 修改 | `frontend/src/App.vue` — 新增 CodingPractice 组件 |
