# Tech Audit Round-4 修复 Spec — 2026-08-17

> 来源：tech-audit round-4（`.tech-audit/work/2026-08-17/findings.tsv`）的 9 个 🟡 发现。
> 原则：TDD（先写失败测试）→ 最小实现 → 验证 → 提交。涉及数据库迁移的任务先备份。
> 方法：writing-plans 原子任务拆分，每个 Task 2-5 分钟。
> 状态口径：✅ 完成 / 🚧 进行中 / ⬜ 未开始

## 范围总览（按优先级）

| 阶段 | # | 发现 | 风险 | 修复 | 状态 |
|---|---|---|---|---|:---:|
| P0 | A | 测试隔离：threading.local vs asyncio.to_thread | 🔴 ~80 个 chat 测试失败 | contextvars 传播连接 | ⬜ |
| P0 | B | 用户 API key 明文落库 | 🟡 敏感数据泄露 | Fernet 加密 | ⬜ |
| P0 | C | 死依赖 python-jose/passlib | 🟡 4 个 CVE | 迁移 PyJWT + bcrypt | ⬜ |
| P1 | D | uvicorn 硬钉 0.24.0 | 🟡 click CVE | 放开 >=0.30 | ⬜ |
| P1 | E | FK 缺 ON DELETE 策略 | 🟡 数据完整性 | 添加级联策略 | ⬜ |
| P1 | F | clear_db 无二次确认 | 🟡 误操作风险 | confirmation token | ⬜ |
| P2 | G | insights.py naive datetime | 🟡 时区错误 | datetime.now(timezone.utc) | ⬜ |
| P2 | H | 图标按钮无 aria-label | 🟡 无障碍 | 添加 aria-label | ⬜ |
| P2 | I | ECharts 内联硬编码颜色 | 🟡 设计一致性 | 统一 chartTokens | ⬜ |

**不做（本轮）**：D3 回归测试纪律（需 CI 门禁改造，单独规划）；D16 死组件清理（需产品确认）。

---

## 阶段 P0 — 测试/安全（本轮优先）

### Task A: 测试隔离 — contextvars 传播连接

**Files**: `backend/app/db/connection.py`、`backend/tests/conftest.py`、`backend/tests/`（回归）
**现状**：`get_db_connection()` 使用 `threading.local` 存储连接，但 `asyncio.to_thread()` 会创建新线程，导致 chat 流水线的 DB 访问落到真实 DB_PATH → ~80 个 chat 测试 "no such table"。

#### 实现方案

1. 将 `threading.local` 改为 `contextvars.ContextVar`
2. `conftest.py` 的 `test_db` fixture 设置 contextvar
3. `run_db()` 确保 contextvar 在异步边界传播

#### TDD 步骤

- [ ] Step 1（RED）：新建 `backend/tests/infra/test_db_contextvars.py`
  - 测试 1：`test_contextvar_isolation_between_threads` — 两个线程各自设置不同连接，互不影响
  - 测试 2：`test_to_thread_preserves_connection` — `asyncio.to_thread()` 内部能访问到 contextvar 中的连接
- [ ] Step 2：跑测试确认失败
- [ ] Step 3（GREEN）：修改 `connection.py`
  ```python
  import contextvars
  _db_conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar('_db_conn_var', default=None)
  
  def get_db_connection() -> sqlite3.Connection:
      conn = _db_conn_var.get()
      if conn is None:
          conn = sqlite3.connect(DB_PATH)
          conn.row_factory = sqlite3.Row
          _db_conn_var.set(conn)
      return conn
  ```
- [ ] Step 4：修改 `conftest.py` 的 `test_db` fixture
  ```python
  @pytest.fixture
  def test_db():
      conn = sqlite3.connect(':memory:')
      conn.row_factory = sqlite3.Row
      token = _db_conn_var.set(conn)
      yield conn
      _db_conn_var.reset(token)
      conn.close()
  ```
- [ ] Step 5：跑 `pytest backend/tests/infra/test_db_contextvars.py -q` 全绿
- [ ] Step 6：跑 `pytest backend/tests/chat/ -q` 确认 chat 测试恢复
- [ ] Step 7：提交 `fix(db): use contextvars for thread-safe connection isolation`

#### 验证标准

- [ ] `pytest backend/tests/infra/test_db_contextvars.py -q` 全绿
- [ ] `pytest backend/tests/chat/ -q` 从 ~80 failures 降到 0
- [ ] `pytest backend/tests/ -q` 全量通过

---

### Task B: 用户 API key Fernet 加密

**Files**: `backend/app/core/config.py`、`backend/app/routers/profile_pkg/llm.py`、`backend/app/services/search.py`、`backend/tests/security/`（新）
**现状**：`user_llm_config.api_key` / `user_search_config.api_key` 明文存储，数据库泄露即暴露用户密钥。

#### 实现方案

1. 从 `JWT_SECRET` 派生 Fernet 密钥
2. 写入时加密，读取时解密
3. 存量明文数据迁移脚本

#### TDD 步骤

- [ ] Step 1（RED）：新建 `backend/tests/security/test_api_key_encryption.py`
  - 测试 1：`test_encrypt_decrypt_roundtrip` — 加密后解密返回原值
  - 测试 2：`test_db_stores_encrypted_not_plaintext` — 写入后 SELECT 不含明文
  - 测试 3：`test_decrypt_wrong_key_raises` — 错误密钥解密抛错
- [ ] Step 2：跑测试确认失败
- [ ] Step 3（GREEN）：新建 `backend/app/services/encryption.py`
  ```python
  from cryptography.fernet import Fernet
  import hashlib
  import os
  
  def _derive_key(secret: str) -> bytes:
      return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
  
  def encrypt_value(plaintext: str) -> str:
      key = _derive_key(os.getenv("JWT_SECRET", ""))
      return Fernet(key).encrypt(plaintext.encode()).decode()
  
  def decrypt_value(ciphertext: str) -> str:
      key = _derive_key(os.getenv("JWT_SECRET", ""))
      return Fernet(key).decrypt(ciphertext.encode()).decode()
  ```
- [ ] Step 4：修改 `profile_pkg/llm.py` 和 `search.py` 的写入/读取路径
- [ ] Step 5：新建 `backend/scripts/migrate_api_keys.py` — 存量明文迁移
- [ ] Step 6：跑 `pytest backend/tests/security/test_api_key_encryption.py -q` 全绿
- [ ] Step 7：提交 `fix(security): encrypt user API keys at rest with Fernet`

#### 验证标准

- [ ] `pytest backend/tests/security/test_api_key_encryption.py -q` 全绿
- [ ] 手动验证：设置用户 LLM key → 重启 → 读取正确
- [ ] `python backend/scripts/migrate_api_keys.py` 迁移存量数据

---

### Task C: 死依赖迁移 — python-jose → PyJWT

**Files**: `pyproject.toml`、`backend/app/core/auth.py`、`backend/tests/security/`（回归）
**现状**：`python-jose`（2021 停更）经 `ecdsa`/`pyasn1` 携带 4 个 CVE；`passlib`（2020 停更）。

#### 实现方案

1. `python-jose` → `PyJWT`（活跃维护，原生支持 EdDSA/HS256）
2. `passlib[bcrypt]` → 直接用 `bcrypt`（passlib 已不推荐）
3. 保留兼容：新旧 token 均可验证

#### TDD 步骤

- [ ] Step 1（RED）：现有 `backend/tests/security/test_auth.py` 应全部通过（基线）
- [ ] Step 2：修改 `pyproject.toml`
  ```toml
  dependencies = [
      # 移除
      # "passlib[bcrypt]>=1.7.4",
      # "python-jose[cryptography]>=3.3.0",
      # 新增
      "PyJWT>=2.8.0",
      "bcrypt>=4.0",
  ]
  ```
- [ ] Step 3（GREEN）：修改 `core/auth.py`
  ```python
  import jwt
  import bcrypt
  
  def create_access_token(data: dict) -> str:
      return jwt.encode(data, JWT_SECRET, algorithm="HS256")
  
  def verify_token(token: str) -> dict:
      return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
  
  def hash_password(password: str) -> str:
      return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
  
  def verify_password(password: str, hashed: str) -> bool:
      return bcrypt.checkpw(password.encode(), hashed.encode())
  ```
- [ ] Step 4：`uv sync` 安装新依赖
- [ ] Step 5：跑 `pytest backend/tests/security/test_auth.py -q` 全绿
- [ ] Step 6：跑 `pytest backend/tests/ -q` 全量通过
- [ ] Step 7：提交 `fix(deps): migrate python-jose/passlib to PyJWT/bcrypt`

#### 验证标准

- [ ] `pytest backend/tests/security/test_auth.py -q` 全绿
- [ ] `pip-audit` 无 ecdsa/pyasn1 CVE
- [ ] 登录/注册/token 刷新功能正常

---

## 阶段 P1 — 依赖/数据完整性

### Task D: uvicorn 解钉

**Files**: `pyproject.toml`
**现状**：`uvicorn==0.24.0` 硬钉，锁死旧 `click==8.3.2`（PYSEC-2026-2132）。

#### TDD 步骤

- [ ] Step 1：修改 `pyproject.toml`
  ```toml
  "uvicorn>=0.30.0,<1.0",
  ```
- [ ] Step 2：`uv sync` 安装新版
- [ ] Step 3：`./deploy/docker-deploy.sh update` 重启服务
- [ ] Step 4：验证服务正常启动
- [ ] Step 5：提交 `fix(deps): unpin uvicorn to >=0.30 for click CVE fix`

#### 验证标准

- [ ] `uvicorn --version` >= 0.30
- [ ] 服务正常启动，健康检查通过

---

### Task E: FK ON DELETE 策略

**Files**: `backend/app/db/migrations/schema_hygiene.py`、`backend/tests/infra/test_schema_hygiene.py`
**现状**：`analysis_queue.interview_id` FK 无 ON DELETE 策略，hard-delete interview 会因 NO ACTION 阻塞。

#### TDD 步骤

- [ ] Step 1（RED）：`test_schema_hygiene.py` 增测试
  - 测试：`test_analysis_queue_cascades_on_interview_delete` — 删除 interview 后 analysis_queue 对应行自动清理
- [ ] Step 2：跑测试确认失败
- [ ] Step 3（GREEN）：新建 migration 090
  ```sql
  -- 重建 analysis_queue 表，interview_id FK 添加 ON DELETE CASCADE
  CREATE TABLE analysis_queue_new AS SELECT * FROM analysis_queue;
  DROP TABLE analysis_queue;
  CREATE TABLE analysis_queue (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      interview_id INTEGER REFERENCES interviews(id) ON DELETE CASCADE,
      -- ... 其他列
  );
  INSERT INTO analysis_queue SELECT * FROM analysis_queue_new;
  DROP TABLE analysis_queue_new;
  ```
- [ ] Step 4：跑 `pytest backend/tests/infra/test_schema_hygiene.py -q` 全绿
- [ ] Step 5：提交 `fix(db): add ON DELETE CASCADE to analysis_queue.interview_id`

#### 验证标准

- [ ] `pytest backend/tests/infra/test_schema_hygiene.py -q` 全绿
- [ ] 手动验证：删除 interview 后 analysis_queue 无孤儿行

---

### Task F: clear_db 二次确认

**Files**: `backend/app/routers/analytics.py`、`backend/tests/`（新）
**现状**：`POST /api/analytics/clear-db` 单个请求直接清空全库，无预览/确认步骤。

#### 实现方案

1. 新增 `POST /api/analytics/clear-db/preview` — 返回将删除的行数统计
2. 修改 `POST /api/analytics/clear-db` — 需要 `confirm_token` 参数
3. `confirm_token` = 预览接口返回的 SHA256(token + timestamp)

#### TDD 步骤

- [ ] Step 1（RED）：新建 `backend/tests/test_clear_db_confirm.py`
  - 测试 1：`test_preview_returns_stats` — 预览接口返回各表行数
  - 测试 2：`test_clear_without_token_returns_400` — 无 token 返回 400
  - 测试 3：`test_clear_with_invalid_token_returns_400` — 错误 token 返回 400
  - 测试 4：`test_clear_with_valid_token_succeeds` — 正确 token 清空成功
- [ ] Step 2：跑测试确认失败
- [ ] Step 3（GREEN）：修改 `analytics.py`
  ```python
  @router.post("/clear-db/preview")
  async def preview_clear_db():
      stats = {}
      for table in ["interviews", "question_bank", "jd", ...]:
          stats[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
      token = hashlib.sha256(f"{SECRET}:{datetime.now().isoformat()}".encode()).hexdigest()
      return {"stats": stats, "confirm_token": token}
  
  @router.post("/clear-db")
  async def clear_db(confirm_token: str):
      # 验证 token
      # 执行清空
  ```
- [ ] Step 4：跑 `pytest backend/tests/test_clear_db_confirm.py -q` 全绿
- [ ] Step 5：提交 `fix(analytics): add confirmation token for clear-db operation`

#### 验证标准

- [ ] `pytest backend/tests/test_clear_db_confirm.py -q` 全绿
- [ ] 前端调用流程：先 preview → 用户确认 → 带 token 调用 clear

---

## 阶段 P2 — 正确性/UX

### Task G: insights.py naive datetime

**Files**: `backend/app/services/insights.py`、`backend/tests/`（回归）
**现状**：`datetime.now().date()` 无时区感知，可能返回错误日期。

#### TDD 步骤

- [ ] Step 1（RED）：现有测试应覆盖（或新增跨时区测试）
- [ ] Step 2（GREEN）：修改 `insights.py:479`
  ```python
  from datetime import datetime, timezone
  today = datetime.now(timezone.utc).date()
  ```
- [ ] Step 3：跑 `pytest backend/tests/services/ -q` 全绿
- [ ] Step 4：提交 `fix(services): use timezone-aware datetime in insights`

#### 验证标准

- [ ] `pytest backend/tests/services/ -q` 全绿

---

### Task H: 图标按钮 aria-label

**Files**: `frontend/src/components/business/PracticePanel.vue`
**现状**：关闭按钮纯 SVG 无文本标签，屏幕阅读器无法识别。

#### TDD 步骤

- [ ] Step 1（RED）：无自动化测试（手动验证）
- [ ] Step 2（GREEN）：修改 `PracticePanel.vue:19`
  ```vue
  <button @click="close" aria-label="关闭">
    <svg>...</svg>
  </button>
  ```
- [ ] Step 3：手动验证：屏幕阅读器可识别"关闭"按钮
- [ ] Step 4：提交 `fix(ui): add aria-label to close button in PracticePanel`

#### 验证标准

- [ ] VoiceOver/NVDA 可读出"关闭"

---

### Task I: ECharts 统一 chartTokens

**Files**: `frontend/src/components/business/KnowledgeGraph.vue`、`frontend/src/utils/chartTokens.js`
**现状**：ECharts 配置内联 14 个 porcelain hex 值，绕过设计 token。

#### TDD 步骤

- [ ] Step 1（RED）：无自动化测试（视觉回归）
- [ ] Step 2（GREEN）：修改 `KnowledgeGraph.vue`
  ```javascript
  import { porcelain, porcelainTooltip } from '@/utils/chartTokens.js'
  
  const option = {
      backgroundColor: porcelain.bg,
      textStyle: { color: porcelain.text },
      // ... 使用 token 替换硬编码
  }
  ```
- [ ] Step 3：视觉对比：图表颜色无变化
- [ ] Step 4：提交 `fix(ui): unify ECharts colors with chartTokens in KnowledgeGraph`

#### 验证标准

- [ ] 图表颜色与修改前一致
- [ ] 无硬编码 hex 值

---

## 提交计划

按 Task 顺序提交，每个 Task 一个 commit：

1. `fix(db): use contextvars for thread-safe connection isolation` (Task A)
2. `fix(security): encrypt user API keys at rest with Fernet` (Task B)
3. `fix(deps): migrate python-jose/passlib to PyJWT/bcrypt` (Task C)
4. `fix(deps): unpin uvicorn to >=0.30 for click CVE fix` (Task D)
5. `fix(db): add ON DELETE CASCADE to analysis_queue.interview_id` (Task E)
6. `fix(analytics): add confirmation token for clear-db operation` (Task F)
7. `fix(services): use timezone-aware datetime in insights` (Task G)
8. `fix(ui): add aria-label to close button in PracticePanel` (Task H)
9. `fix(ui): unify ECharts colors with chartTokens in KnowledgeGraph` (Task I)

---

## 验证清单

每个 Task 完成后：

- [ ] 对应测试全绿
- [ ] `./deploy/docker-deploy.sh check` 通过
- [ ] 手动验证功能正常

全部完成后：

- [ ] `./deploy/docker-deploy.sh check` 全量通过
- [ ] `pytest backend/tests/ -q` 全量通过
- [ ] 前端 build 成功
- [ ] 部署到生产环境验证
