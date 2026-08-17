# Spec: 八股刷题模块深度修复 — 时区一致性 / 进度平衡 / UX 收敛

> 位置: `backend/app/services/practice_deck_service.py` + `backend/app/routers/practice.py` + `frontend/src/composables/usePracticeDecks.js` + `frontend/src/components/business/PracticeMode.vue` + `frontend/src/views/PracticeDecksView.vue`
> 类型: 技术质量 spec（tech-audit 深度审计）
> 日期: 2026-08-18
> 状态: 待实施
> 审计依据: 八股刷题模块 tech-audit 深度审计（14 条 findings，6 维度）
> 方法: TDD（先写失败测试）→ 最小实现 → 验证 → 提交

## 背景

tech-audit 深度审计对八股刷题模块（practice）进行了全链路追踪，发现 6 类问题。其中 🔴 时区不一致影响所有非 UTC 时区用户的进度统计，🔴 进度条漂移可导致用户在 1 次修正后看到 100% 完成。

**最佳实践参考**：

| 问题 | 参考产品 | 核心原则 |
|------|---------|---------|
| 时区不一致 | GitHub Contribution Graph / LeetCode Streak / FSRS | Server-authoritative today：服务端返回 study_date，前端用它替代 new Date() |
| 进度条漂移 | FSRS review sync | Single source of truth：前端只做最小乐观更新，不重推全局状态 |
| 双重确认 | shadcn-vue Dialog / Radix UI | Single confirmation：只用一个 styled dialog |
| 模式切换跳题单 | LeetCode 题单内模式切换 | Mode ≠ Scope：视图模式不应改变数据范围 |

---

## Task A: 后端返回 study_date，前端统一使用 🔴

**Files:**

- Edit: `backend/app/services/practice_deck_service.py`
- Edit: `backend/app/routers/practice.py`
- Edit: `frontend/src/composables/usePracticeDecks.js`
- Create: `backend/tests/services/test_practice_study_date.py`

**现状**（已核实源码）：
- 后端 `_study_day_utc_bounds()`（:51）用 `STUDY_TIMEZONE`（默认 Asia/Shanghai）计算今天 UTC 边界
- 后端 `_today_review_metrics()`（:217）用此边界统计 completed_today / attempted_today
- 后端 `_study_streak()`（:251）用 `_study_timezone()` 计算连续打卡
- **前端 `isStudyDayToday()`（usePracticeDecks.js:350）用 `new Date()`（浏览器本地时区）判断今天**
- **后端从未向前端暴露 study timezone 或 study_date**（grep practice.py/profile.py 确认）
- UTC-8 用户在美西 7:59 AM 刷题：后端认为是「昨天」，前端认为是「今天」→ reviewedDueQueueIds 与 completed_today 不一致

**Step 1（RED）**：写 `test_practice_study_date.py` 断言：
- `list_deck_questions` 返回的 deck dict 包含 `study_date` 字段
- `study_date` 格式为 `YYYY-MM-DD`
- `list_decks` 返回的每个 deck 也包含 `study_date`

**Step 2**：跑测试确认失败（Docker test-runtime）

**Step 3（GREEN）**：

```python
# practice_deck_service.py — 新增辅助函数
def _study_date_string(now: datetime | None = None) -> str:
    """Return the current learner-facing calendar day as YYYY-MM-DD."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    zone = _study_timezone()
    return current.astimezone(zone).date().isoformat()
```

```python
# practice_deck_service.py — list_deck_questions due 分支，deck dict 追加：
deck = {
    **deck,
    "study_date": _study_date_string(),  # 新增
    # ... 其余字段不变
}
```

```python
# practice_deck_service.py — list_decks 返回中追加 study_date
# 在 result.append(...) 中加入 "study_date": _study_date_string()
```

**Step 4**：跑后端测试确认通过

**Step 5（前端修改）**：

```javascript
// usePracticeDecks.js — isStudyDayToday 改用 studyDate 参数
function isStudyDayToday(value, studyDate) {
  if (!value || !studyDate) return false
  const raw = String(value)
  // 后端存储格式 "YYYY-MM-DD HH:MM:SS"（UTC-naive）
  // 取前 10 位即日期部分
  return raw.slice(0, 10) === studyDate
}
```

```javascript
// usePracticeDecks.js — applyQuestionResponse 中传入 studyDate
if (deckKey === 'due') {
  const studyDate = response.deck?.study_date
  reviewedDueQueueIds = new Set((response.items || [])
    .filter(question => isStudyDayToday(question.last_reviewed_at, studyDate)
      && ['good', 'easy'].includes(question.last_rating))
    .map(question => question.id))
  attemptedDueQueueIds = new Set((response.items || [])
    .filter(question => isStudyDayToday(question.last_reviewed_at, studyDate))
    .map(question => question.id))
}
```

```javascript
// usePracticeDecks.js — submitReview 中 wasPassedToday 改用 studyDate
const studyDate = selectedDeck.value?.study_date
const wasPassedToday = isStudyDayToday(item?.last_reviewed_at, studyDate)
  && ['good', 'easy'].includes(item?.last_rating)
```

```javascript
// usePracticeDecks.js — correctReview 中 wasPassedToday 同理
const studyDate = selectedDeck.value?.study_date
const wasPassedToday = previousRating
  ? ['good', 'easy'].includes(previousRating)
  : (isStudyDayToday(item?.last_reviewed_at, studyDate) && ['good', 'easy'].includes(item?.last_rating))
```

**Step 6**：`cd frontend && npm run build` 确认构建通过

**Step 7**：提交 `fix(practice): server-authoritative study_date for timezone consistency`

**Done when**：前端不再依赖 new Date() 判断「今天」；后端 study_date 在 due 队列和 decks 列表中均返回。

---

## Task B: 修正自评时进度条数字平衡 🔴

**Files:**

- Edit: `frontend/src/composables/usePracticeDecks.js`
- Create: `frontend/tests/unit/usePracticeDecks-correction.test.js`（或 Playwright 验证）

**现状**（已核实源码）：
- 用户对 Q1 评 again → completed_today 不变, remaining_today 不变, relearning_count +1（usePracticeDecks.js:262-264）
- 用户修正为 good → completed_today +1, remaining_today -1, relearning_count -1（:324-328）
- remaining_today 在 Step 1 没有 +1，Step 2 的 -1 导致负数（clamp 到 0）
- planned_today = completed(1) + remaining(0) = 1 → 进度条显示 100%

**Step 1（RED）**：写测试断言：
- 初始评 again 后 completed_today=0, remaining_today 不变, relearning_count+1
- 修正为 good 后 completed_today+1, remaining_today-1, relearning_count-1
- planned_today 在修正前后保持不变（completed + remaining = 常数）

**Step 2**：跑测试确认失败

**Step 3（GREEN）**：

```javascript
// usePracticeDecks.js — correctReview 中 wasPassedToday !== passedNow 分支
// 修改前缺少 relearning_count 调整
// 修改后：
if (wasPassedToday !== passedNow) {
  const delta = passedNow ? 1 : -1
  reviewedDeck.completed_today = Math.max(0, Number(reviewedDeck.completed_today || 0) + delta)
  reviewedDeck.remaining_today = Math.max(0, Number(reviewedDeck.remaining_today || 0) - delta)
  reviewedDeck.relearning_count = Math.max(0, Number(reviewedDeck.relearning_count || 0) - delta)
  if (passedNow) reviewedDueQueueIds.add(questionId)
  else reviewedDueQueueIds.delete(questionId)
  reviewedDeck.planned_today = Number(reviewedDeck.completed_today || 0) + Number(reviewedDeck.remaining_today || 0)
}
```

**Step 4**：跑测试确认通过

**Step 5**：提交 `fix(practice): balance progress counters on review correction`

**Done when**：again→good 修正后 remaining_today 不变为负数；planned_today 修正前后一致。

---

## Task C: 删除题单单一确认弹窗 🟡

**Files:**

- Edit: `frontend/src/views/PracticeDecksView.vue`
- Edit: `frontend/src/components/SiteHeader.vue`

**现状**：
- PracticeDecksView.vue:51 用 `window.confirm()`（原生弹窗）
- usePracticeDecks.js:411 用 `showConfirm()`（shadcn styled dialog）
- 用户被迫连续确认两次，体验极差

**Step 1（RED）**：E2E 测试断言删除题单只弹一次确认框

**Step 2（GREEN）**：

```javascript
// PracticeDecksView.vue — 删除 window.confirm
async function deleteManagerDeck(deckKey) {
  // deleteDeck 内部已有 styled confirm dialog
  await deleteDeck(deckKey)
  if (selectedDeckKey.value === deckKey) questions.value = []
}
```

```javascript
// SiteHeader.vue — coding 题单删除同样删除 window.confirm
// 直接调用 delete 函数（内部已有 confirm）
```

**Step 3**：`cd frontend && npm run build` 确认构建通过

**Step 4**：提交 `fix(frontend): remove duplicate window.confirm on deck delete`

**Done when**：删除题单/题单只弹一次 styled confirm dialog。

---

## Task D: 模式切换不改变当前题单 🟡

**Files:**

- Edit: `frontend/src/components/business/PracticeMode.vue`

**现状**：
- switchToQuiz（:867-869）无条件 emit `select-deck('due')`
- switchToBrowse（:862-866）在 due 队列时 emit `select-deck('all')`
- 用户从自定义题单点「切回八股刷题」后丢失当前题单上下文

**Step 1（RED）**：E2E 测试断言：从自定义题单切换模式后题单不变

**Step 2（GREEN）**：

```javascript
// PracticeMode.vue — switchToQuiz 不再切换题单
function switchToQuiz() {
  if (reviewStatus.value === 'saving' || correctionLoading.value) {
    toast.warning('正在保存这道题的自评，请稍候')
    return
  }
  viewMode.value = 'quiz'
  // 不再 emit('select-deck', 'due')
}
```

```javascript
// PracticeMode.vue — switchToBrowse 不再切换题单
function switchToBrowse() {
  if (reviewStatus.value === 'saving' || correctionLoading.value) {
    toast.warning('正在保存这道题的自评，请稍候')
    return
  }
  viewMode.value = 'browse'
  // 不再 emit('select-deck', 'all')
}
```

**Step 3**：`cd frontend && npm run build` 确认构建通过

**Step 4**：提交 `fix(practice): mode switch should not change current deck`

**Done when**：quiz/browse 切换只改变视图模式，不改变 selectedDeckKey。

---

## Task E: review_forecast 使用 study timezone 🟡

**Files:**

- Edit: `backend/app/services/practice_deck_service.py`

**现状**（已核实源码）：
- :492 `today = datetime.now(UTC).date()` 用 UTC 日期
- :220 `_today_review_metrics` 用 study timezone（Shanghai→UTC）
- forecast 的 `date(next_review_at)` 按 UTC 分组，但 completed_today 按 Shanghai 分组
- 北京 23:30（UTC 15:30）的复习：completed_today 计入今天，forecast 可能归到明天

**Step 1（RED）**：后端测试断言 forecast 日期与 study_date 一致

**Step 2（GREEN）**：

```python
# practice_deck_service.py — review_forecast 日期计算
# 修改前
today = datetime.now(UTC).date()

# 修改后：用 study_start 的日期部分
study_start, study_end = _study_day_utc_bounds()
today = datetime.strptime(study_start, "%Y-%m-%d %H:%M:%S").date()
```

**Step 3**：跑后端测试确认通过

**Step 4**：提交 `fix(practice): align forecast dates with study timezone`

**Done when**：forecast 柱状图日期与 completed_today 使用同一时区基准。

---

## Task F: _study_streak 加时间范围限制 🟢

**Files:**

- Edit: `backend/app/services/practice_deck_service.py`

**现状**：
- :259 `SELECT reviewed_at FROM practice_review_events WHERE user_id = ? ORDER BY reviewed_at ASC`
- 无 LIMIT，拉取用户全部复习事件
- 有索引 `idx_practice_events_user_time(user_id, reviewed_at)` 覆盖
- 活跃用户 500+ 事件时每次加载刷题页全量拉取

**Step 1（GREEN）**：

```python
# practice_deck_service.py — _study_streak 加时间范围
cutoff = (datetime.now(UTC) - timedelta(days=400)).strftime("%Y-%m-%d %H:%M:%S")
rows = conn.execute(
    "SELECT reviewed_at FROM practice_review_events "
    "WHERE user_id = ? AND reviewed_at >= ? ORDER BY reviewed_at ASC",
    (user_id, cutoff),
).fetchall()
```

**Step 2**：跑后端测试确认通过

**Step 3**：提交 `perf(practice): limit streak query to recent 400 days`

**Done when**：_study_streak 查询有时间范围限制，不全表扫描。

---

## Task G: list_decks 缓存 _base_query_parts 🟢

**Files:**

- Edit: `backend/app/services/practice_deck_service.py`

**现状**：
- list_decks 循环中每个 deck 调用 _base_query_parts（含 build_bank_where_clause + get_dynamic_frequency_sql）
- 3 系统 + 5 自定义 = 17 次 SQL 查询

**Step 1（GREEN）**：

```python
# practice_deck_service.py — list_decks 缓存 _base_query_parts
def list_decks(conn, user_id: int, filter_mode: str = "all") -> list[dict]:
    result = []
    # ... 现有 custom_decks 查询 ...

    _parts_cache = {}
    for deck in deck_definitions:
        cache_key = deck["key"]
        if cache_key not in _parts_cache:
            _parts_cache[cache_key] = _base_query_parts(
                conn, user_id, filter_mode, deck["key"]
            )
        _, from_clause, where_clause, source_params, where_params, _ = (
            _parts_cache[cache_key]
        )
        # ... 其余 COUNT 查询逻辑不变 ...
```

**Step 2**：跑后端测试确认通过

**Step 3**：提交 `perf(practice): cache _base_query_parts in list_decks`

**Done when**：list_decks 查询次数从 17 降至 8（系统 3 + 自定义 5，每 deck 1 次 COUNT）。

---

## 验证方案

### 后端测试
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_api.py -q -v
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_scheduler.py -q -v
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_due_queue.py -q -v
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_study_date.py -q -v
```

### 前端测试
```bash
cd frontend && npm run build
cd frontend && npm run test
```

### 手动验证
1. **时区测试**：将系统时区改为 UTC-8，验证刷题进度与 Asia/Shanghai 一致
2. **修正测试**：对一道题评 again，然后修正为 good，验证进度条不跳到 100%
3. **删除测试**：删除自定义题单，验证只弹一次确认框
4. **模式切换测试**：从自定义题单点「切回八股刷题」，验证题单不变
5. **forecast 测试**：查看未来 7 天预测，验证日期与今日完成数一致

