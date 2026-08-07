# Profile Pkg — 用户配置子路由

从 `profile.py` 拆分的子模块，按领域组织。

## 子路由

| 文件 | 端点前缀 | 职责 |
|------|---------|------|
| `llm.py` | `/api/profile/llm` | LLM 配置 CRUD（模型、API Key、Base URL、接口类型 api_format、深度思考 thinking）；`/api/profile/llm/test-global` 用全局配置探测连通性（仅 admin，绕过缓存，`check_global_llm_status`）；PUT 校验 api_format 必须在端点能力矩阵支持范围内（不匹配返回 400） |
| `embedding.py` | `/api/profile/embedding` | 全局 Embedding 配置管理（仅 admin）：GET 读取（API key 掩码 + `api_key_set`）、PUT 保存到 `user_profile` 的 `embedding_*` key + `reload_embedding_config()` 热加载、模型/维度变化触发全量重算 job（复用 `jobs` 表 + SSE）、POST `/test` 连通性探测（siliconflow 调 embedding 接口 / onnx 校验模型文件） |
| `taxonomy.py` | `/api/profile/taxonomy` | 分类体系管理（CRUD + 导入导出） |
| `position.py` | `/api/profile/positions` | 岗位管理（CRUD + 切换） |
| `email.py` | `/api/profile/bind-email`, `/api/profile/send-bind-code` | 邮箱绑定（验证码） |
| `resume.py` | `/api/profile/resume`, `/api/profile/resume/text`, `/api/profile/resume/optimize`, `/api/profile/resume/optimization` | 简历上传/查询/删除、原文预览、SSE 优化（points → delta → done）与结果查询 |
| `interview_distribution.py` | `/api/profile/interview-distribution-preference` | 用户按岗位保存模拟面试分布偏好 |
| `mcp.py` | `/api/profile/mcp` | 用户级 MCP 端点、Token 轮换与客户端配置 |

## 注册方式

`__init__.py` 合并所有子路由为一个总路由，在 `asgi.py` 中注册为 `profile_pkg_router`。

## 修改后必做

1. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/ -q`
2. 更新本文件（如新增端点或子模块）

## 岗位列表约定

- `GET /api/positions` 必须排除 `job_positions.is_deleted = 1` 的软删除记录，和删除接口保持同一可见性契约。
