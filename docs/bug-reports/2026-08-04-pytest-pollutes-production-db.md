# BUG: pytest 污染生产数据库 — sj 账户下不断出现空对话

## 现象

sj 账户（user_id=1）下持续出现大量无效对话：
- 标题"新对话"、mode=free_practice、difficulty=mid（全默认值）
- 每批 4 个（3 active + 1 archived），间隔约 2 分钟
- 只有 1 条 assistant 开场白，无任何用户消息
- 累计 214+ 个，删除后再次运行测试又新增 16 个

## 根因

`backend/tests/conftest.py` 的 `client` fixture 只 patch 了 `app.routers.*` 模块的 `run_db`/`get_db_connection` 引用：

```python
if mod_name.startswith("app.routers.") and mod:
```

但：
1. FastAPI TestClient 在**独立线程**运行 ASGI 请求，`app.db.connection._local.conn`（threading.local）在该线程为空
2. services 层（`app.services.chat_service` 等）没有被 patch，其 `get_db_connection()` 是真实版本
3. TestClient 线程内 `_local.conn` 为空 → `get_db_connection()` 打开真实 `DB_PATH`（生产库）
4. 于是 `POST /api/chat/conversations` 测试真的把对话写进了生产数据库

## 复现

```bash
# 任意使用 client fixture 且触发 services 层写库的测试
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_chat.py -q
# 生产库 chat_conversations 新增 1 条
```

## 修复

`backend/tests/conftest.py` client fixture：
1. patch 范围从 `app.routers.*` 扩展为 `app.*`（routers + services + agents + mcp_server 等所有已导入模块）
2. 额外 patch `app.db.connection`/`operations`/`queries` 模块本身的 `get_db_connection`，兜底拦截直接调用
3. `_test_get_db_connection` 直接返回 test_db 连接对象（sqlite3.Connection 既是 context manager 也支持 `.execute()`，兼容 `with get_db_connection() as conn` 和 `conn = get_db_connection()` 两种用法）

## 回归测试

`backend/tests/chat/test_chat.py::test_api_does_not_write_production_db`：断言 API 测试前后生产库 `chat_conversations` 行数不变。

## 验证

- 修复前：跑 `backend/tests/chat/test_chat.py` 生产库 96 → 97
- 修复后：跑完整 `backend/tests/chat/`（891 passed）生产库保持 80 不变
- `test_mcp_session.py` 使用 `conn = get_db_connection()` 直接调用，回归通过

## 额外发现

- `backend/tests/services/` 下部分前端代码契约测试（如 `test_source_display.py`、`test_settings_position_switch.py`）在 test-runtime 容器中因缺少 `/app/frontend` 挂载而 FileNotFoundError，属预存环境问题，与本次修复无关。可通过 `docker compose --profile test run --rm -v "$PWD/frontend:/app/frontend" test ...` 挂载后运行。
