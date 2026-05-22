# Core 层 — 配置与认证

项目配置、认证、提示词模板。此层不依赖 routers/services。

## 文件职责

| 文件 | 职责 |
|------|------|
| `config.py` | 数据库热加载配置（`_reload_from_db()`）、环境变量、`.env` 同步 |
| `auth.py` | JWT Access Token (15min) + Refresh Token (HttpOnly Cookie, JTI 跟踪, 轮转) |
| `prompts.py` | LLM 提示词模板（SYSTEM_PROMPT、TAGGING_PROMPT、ANSWER_PROMPT） |
| `logging_config.py` | 日志配置（loguru） |

## 关键模式

- **配置热更新**：`/api/profile` → DB → `_reload_from_db()` → 内存变量更新 → `_sync_env_file()` 写回 `.env`
- **认证流程**：`get_current_user()` 验证 Access Token → `get_admin_user()` 额外检查 `is_admin`
- **Token 刷新**：401 时前端自动调用 `/api/auth/refresh`，后端轮转 JTI

## 修改后必做

1. 修改 `auth.py` 后必须测试登录/注册/刷新全流程
2. 修改 `prompts.py` 后确认格式与 `llm.py` 的解析逻辑兼容
3. 更新本文件
