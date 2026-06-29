# DB 层 — 数据库操作

SQLite 数据库层，线程安全，WAL 模式。

## 核心规则

- **线程安全**：`get_db_connection()` 返回线程本地连接，禁止跨线程传递
- **async 桥接**：async 函数必须用 `run_db()` 包装 DB 操作，禁止在 async 中直接调用 `get_db_connection()`
- **事务**：写操作用 `conn.commit()`，失败时 `conn.rollback()`
- **迁移**：新增表/列必须在 `migrations/` 对应领域文件添加 migration，并在 `migrations/__init__.py` 的 `_MIGRATIONS` 按序登记
- **依赖边界**：DB 层总体应避免业务服务依赖；当前 `operations.py` 复用 `services.utils` 的 URL 签名/分类规范化，改动时先确认调用链，不要扩大交叉依赖。

## 文件职责

| 文件 | 职责 |
|------|------|
| `connection.py` | 线程级连接管理、`run_db()`、岗位查询、动态频率 SQL |
| `migrations/` | Schema 迁移包；领域文件保存 `_migration_NNN_*`，`__init__.py` 维护 `_MIGRATIONS` 并提供 `run_migrations()` |
| `operations.py` | 可复用 CRUD（提交、去重、软删除） |
| `queries.py` | 跨领域查询（岗位、频率、分类体系） |
| `question_bank_sources.py` | 题库来源表 CRUD + dual-write 工具 |

## 关键模式

- **Dual-write**：`question_bank` 的 JSON 字段和 `question_sources`/`question_original_items` 表同步写入
- **软删除**：`deleted_at` 列，查询时加 `WHERE deleted_at IS NULL`
- **岗位过滤**：通过 `question_position` 关联表，fallback 到 `job_position` 列
- **模拟面试历史**：`chat_conversations.job_position` 记录会话所属岗位，列表和详情必须按用户当前岗位过滤。
- **手撕代码**：`coding_problems`（题库，50 道 seed 数据）+ `coding_submissions`（提交记录 + AI 评审结果），migration 030

## 修改后必做

1. 新增 migration → 更新 `migrations/` 对应领域文件和 `migrations/__init__.py` 的 `_MIGRATIONS` 列表
2. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/ -q` 确认不回归
3. 更新本文件（如新增文件或改变职责）
