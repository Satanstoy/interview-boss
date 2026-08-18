# Spec: 八股刷题模块性能/配额/死代码修复 — 第四轮（R16-R22）

> 位置: `backend/app/core/cache.py` + `backend/app/routers/practice.py` + `backend/app/services/llm_quota.py` + `frontend/src/components/business/PracticeMode.vue` + 迁移
> 类型: 技术质量 spec（tech-audit 第四轮）
> 日期: 2026-08-18
> 状态: 待实施
> 方法: TDD（先写失败测试）→ 最小实现 → 验证 → 提交

## 背景

第四轮审计聚焦「未覆盖角度」：缓存、配额、索引、死代码。主要发现：

| # | 严重度 | 问题 |
|---|--------|------|
| R16 | 🟡 | 每次复习/改判/收藏全局失效所有用户 master-bank 缓存 |
| R17 | 🟡 | `get_practiced_questions` 缺 (user_id, updated_at) 索引 |
| R18 | 🟢 | LLM 失败仍扣配额 |
| R19 | 🟢 | `rememberedIds` 死变量 |
| R20 | 🟢 | 「已刷过的题」列表不刷新 |
| R21 | 🟢 | 配额日边界用服务器时区非学习日 |
| R22 | 🟢 | ~~完成态时间显示~~（已复核为非问题，本轮不修）|

> R22 复核：`formatNextReview` 比较绝对时间戳（UTC vs Date.now()），对相对显示时区正确——不是 bug，移除。

---

## Task R16: 复习路径改用 per-user 缓存失效 🔶

**Files:**

- Edit: `backend/app/core/cache.py`
- Edit: `backend/app/routers/practice.py`
- Create: `backend/tests/cache/test_master_bank_cache_scope.py`（或并入现有）

**现状**（已核实）：
- `invalidate_master_bank_cache()`（cache.py:173-183）增全局 epoch：`client.incr(_MASTER_BANK_EPOCH_KEY)`
- 缓存 key（:83）`interview-boss:cache:v2:master-bank:u{user_id}:{digest(含 epoch)}`
- `practice.py` 的 review(:238)/correct(:267)/toggle-star(:310)/evaluate(:431) 都调全局失效 → **任一用户复习清掉全站所有人缓存**
- 但复习只改**该用户自己的** proficiency/review_state/is_starred（cache key 已含 user_id）
- TTL 默认 15s（config.py:115），影响被时效部分缓冲，但高并发刷题时仍抖动

**方案**：签名加 per-user epoch。新增 `_MASTER_BANK_EPOCH_KEY_USER = f"{prefix}:u{{uid}}:epoch"`，签名 payload 加 `user_epoch`。新增 `invalidate_master_bank_cache(user_id=None)`：
- `user_id=None` → 增全局 epoch（bank 级变更用）
- `user_id=X` → 增 X 的 per-user epoch（复习/收藏用）

**Step 1（RED）**：测试断言：
- review 后**其他用户**的 master-bank cached key 不变（还能命中）
- review 后**本人**的 master-bank cached key 失效

**Step 2**：跑测试确认失败（当前全局失效会清掉他人 key）

**Step 3（GREEN，cache.py）**：
初始化 per-user epoch：
```python
_USER_EPOCH_CACHE: dict[int, str] = {}  # 进程内缓存，降低 Redis 往返

async def _user_epoch(client, user_id: int) -> str:
    key = f"{_MASTER_BANK_PREFIX}:u{int(user_id)}:epoch"
    epoch = _USER_EPOCH_CACHE.get(user_id)
    if epoch is None:
        epoch = str(await client.get(key) or "1")
        _USER_EPOCH_CACHE[user_id] = epoch
    return epoch
```

签名加入 user_epoch（get/set 都读）：
```python
# _cache_signature 增加 user_epoch 参数，payload 加 "user_epoch": user_epoch
```

get/set 调用处传 `await _user_epoch(client, int(user["id"]))`

invalidate 支持 user_id：
```python
async def invalidate_master_bank_cache(user_id: int | None = None) -> None:
    client = get_cache_client()
    if client is None:
        return
    try:
        if user_id is None:
            await client.incr(_MASTER_BANK_EPOCH_KEY)
        else:
            _USER_EPOCH_CACHE.pop(user_id, None)  # 进程缓存失效
            await client.incr(f"{_MASTER_BANK_PREFIX}:u{int(user_id)}:epoch")
    except RedisError as exc:
        logger.debug("失效 master-bank Redis cache 失败: %s", exc)
```

**Step 4（GREEN，practice.py）**：复习/改判/收藏路径传 `user_id=user["id"]`：
```python
# review/correct/toggle-star
await invalidate_master_bank_cache(user_id=user["id"])
```

**Step 5**：跑全部 cache + practice 测试

**Step 6**：提交 `perf(practice): per-user master-bank cache invalidation for review paths`

**Done when**：复习只失效本人缓存；bank 级变更（answers/mutations）仍全局失效。

---

## Task R17: get_practiced_questions 加 (user_id, updated_at) 索引 🟡

**Files:**

- Edit: `backend/app/db/migrations/practice.py`（新 migration 097）
- Edit: `backend/app/db/migrations/__init__.py`

**现状**（已核实）：`practice.py:474-480` `WHERE user_id = ? ORDER BY updated_at DESC LIMIT 50`，无 (user_id, updated_at) 索引 → 全量扫用户行排序。

**Step 1（GREEN）**：migration 097 加索引：

```python
def _migration_097_practiced_list_index(conn):
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_uqr_user_updated "
        "ON user_question_review(user_id, updated_at)"
    )
```

**Step 2**：提交 `perf(practice): add (user_id, updated_at) index for practiced list`

**Done when**：practiced 查询走索引。

---

## Task R18: LLM 失败释放配额 🟢

**Files:**

- Edit: `backend/app/services/llm_quota.py`
- Edit: `backend/app/routers/practice.py`
- Edit: `backend/tests/services/test_llm_quota.py`（如有）

**现状**（已核实）：`check_and_record`（llm_quota.py:34-49）先 `+1` 并 `commit`，LLM 调用失败后不回滚。evaluate-answer 中配额在 LLM 调用前已扣。

**方案**：新增 `release_quota(user_id)`（有界：≥0 才减），在 evaluate-answer 的 LLM 失败 catch 分支调用：

```python
# llm_quota.py
async def release_quota(user_id: int, day: str | None = None) -> None:
    """在 LLM 调用失败后释放一次配额（有界不减为负）。"""
    day = day or _today()

    def _run():
        conn = get_db_connection()
        conn.execute(
            "UPDATE llm_usage SET call_count = MAX(0, call_count - 1) "
            "WHERE user_id = ? AND day = ? AND call_count > 0",
            (user_id, day),
        )
        conn.commit()
    await run_db(_run)
```

evaluate-answer 的 error catch：在 `except json.JSONDecodeError / AuthenticationError / APIConnectionError / APITimeoutError / Exception` 分支抛 HTTPException 前调 `await release_quota(user["id"])`（放最外层统一处理）。

**Step 1（RED）**：测试断言 LLM 失败后 llm_usage 计数回退。

**Step 2（GREEN）**：实现如上。

**Step 3**：提交 `fix(practice): release LLM quota on evaluation failure`

**Done when**：evaluate-answer 失败不净扣配额。

---

## Task R19: 删除 rememberedIds 死变量 🟢

**Files:**

- Edit: `frontend/src/components/business/PracticeMode.vue`

**现状**（已核实）：`rememberedIds` ref（:580）声明 + markAndNext 写入（:888），从未读取。

**Step 1（GREEN）**：删除声明（:580）与写入（:888）。

**Step 2**：`cd frontend && npm run build`

**Step 3**：提交 `refactor(practice): remove dead rememberedIds state`

**Done when**：构建通过，无死引用。

---

## Task R20: 「已刷过的题」列表会话内刷新 🟢

**Files:**

- Edit: `frontend/src/components/business/PracticeMode.vue`

**现状**（已核实）：`togglePracticed`（:1031-1044）只在 `!practicedList.value.length` 时加载一次；会话内新复习不反映。

**Step 1（GREEN）**：每次打开都重新拉（或至少 30s TTL）：

```javascript
let practicedLoadedAt = 0
async function togglePracticed() {
  showPracticed.value = !showPracticed.value
  if (!showPracticed.value) return
  const nowMs = Date.now()
  // 30s 内不重复拉取；但提交复习后也会陈旧 → 每次打开刷新
  practicedLoading.value = true
  try {
    const { fetchPracticedQuestions } = await import('@/services/practiceApi.js')
    const data = await fetchPracticedQuestions()
    practicedList.value = data.items || []
    practicedLoadedAt = nowMs
  } catch (e) {
    toast.error('加载已刷题列表失败')
  } finally {
    practicedLoading.value = false
  }
}
```

**Step 2**：`cd frontend && npm run build`

**Step 3**：提交 `fix(practice): refresh practiced list on each open`

**Done when**：新复习在「已刷过的题」即时可见。

---

## Task R21: 配额日边界用学习日 🟢

**Files:**

- Edit: `backend/app/services/llm_quota.py`

**现状**（已核实）：`_today()`（llm_quota.py:29-31）用 `date.today()`（服务器时区），与刷题学习日（STUDY_TIMEZONE）不一致。

**Step 1（GREEN）**：改用学习日：

```python
def _today() -> str:
    from app.services.practice_deck_service import _study_timezone
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone(_study_timezone()).date().isoformat()
```

（保持独立函数便于测试固定日期）

**Step 2**：跑 llm_quota 测试（如有）

**Step 3**：提交 `fix(quota): use study-day boundary for daily quota`

**Done when**：配额日边界与学习日一致。

---

## 验证

### 后端
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_api.py backend/tests/services/test_practice_history.py backend/tests/cache/ backend/tests/services/test_insights.py -q
```

### 前端
```bash
cd frontend && npm run build
```
