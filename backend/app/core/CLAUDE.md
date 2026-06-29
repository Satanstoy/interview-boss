# Core 层 — 配置与认证

项目配置、认证、提示词模板。此层禁止依赖 routers；`config.py`/`auth.py` 会延迟导入 DB，`config.py` 热更新后会调用 `services.llm.rebuild_clients()` 刷新 LLM client。

## 文件职责

| 文件 | 职责 |
|------|------|
| `config.py` | 数据库热加载配置（`_reload_from_db()`）、环境变量、`.env` 同步 |
| `auth.py` | JWT Access Token (15min) + Refresh Token (HttpOnly Cookie, JTI 跟踪, 轮转) |
| `prompts.py` | LLM 提示词模板（SYSTEM_PROMPT、TAGGING_PROMPT、ANSWER_PROMPT、CODING_REVIEW_PROMPT、CODING_HINT_PROMPT） |
| `logging_config.py` | 日志配置（structlog 双模式：生产 JSON / 开发彩色） |

## 关键模式

- **配置热更新**：`/api/profile` → DB → `_reload_from_db()` → 内存变量更新 → `_sync_env_file()` 写回 `.env`
- **认证流程**：`get_current_user()` 验证 Access Token → `get_admin_user()` 额外检查 `is_admin`
- **用户岗位**：`get_current_user()` 返回值需要包含 `current_position`，并通过 `get_user_job_position(user_id)` 解析个人岗位优先级，保证前端刷新后仍停留在用户切换的岗位。
- **Token 刷新**：401 时前端自动调用 `/api/auth/refresh`，后端轮转 JTI

## 修改后必做

1. 修改 `auth.py` 后必须测试登录/注册/刷新全流程
2. 修改 `prompts.py` 后确认格式与 `llm.py` 的解析逻辑兼容
3. 更新本文件
