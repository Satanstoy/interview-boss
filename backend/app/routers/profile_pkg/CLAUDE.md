# Profile Pkg — 用户配置子路由

从 `profile.py` 拆分的子模块，按领域组织。

## 子路由

| 文件 | 端点前缀 | 职责 |
|------|---------|------|
| `llm.py` | `/api/profile/llm` | LLM 配置 CRUD（模型、API Key、Base URL） |
| `taxonomy.py` | `/api/profile/taxonomy` | 分类体系管理（CRUD + 导入导出） |
| `position.py` | `/api/profile/positions` | 岗位管理（CRUD + 切换） |
| `email.py` | `/api/profile/bind-email`, `/api/profile/send-bind-code` | 邮箱绑定（验证码） |
| `resume.py` | `/api/profile/resume` | 简历上传/查询/删除 |

## 注册方式

`__init__.py` 合并所有子路由为一个总路由，在 `asgi.py` 中注册为 `profile_pkg_router`。

## 修改后必做

1. 运行 `uv run pytest backend/tests/ -q`
2. 更新本文件（如新增端点或子模块）
