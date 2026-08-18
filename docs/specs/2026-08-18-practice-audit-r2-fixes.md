# Spec: 八股刷题模块复查修复 — 服务端权威时区 / 读端迁移 / 边界回归

> 位置: `backend/app/services/practice_deck_service.py` + `backend/app/routers/practice.py` + `backend/app/services/insights.py` + `backend/app/agents/chat/context_builder.py` + `frontend/src/composables/usePracticeDecks.js` + `frontend/src/components/business/PracticeMode.vue`
> 类型: 技术质量 spec（tech-audit 复查审计）
> 日期: 2026-08-18
> 状态: 待实施
> 审计依据: 八股刷题模块复查审计（2026-08-18，R1-R10 findings）
> 方法: TDD（先写失败测试）→ 最小实现 → 验证 → 提交

## 背景与根因

复查审计发现上次修复的核心设计错误：**前端仍自行换算时区**。`STUDY_TIMEZONE` 是服务端环境变量（默认 Asia/Shanghai），前端无法可靠地复制这个边界——任何"前端拿某时区日期去比对另一个时区日期"的做法都必然在某边界出错。

**正确架构原则**：**所有时区敏感布尔值由服务端用唯一权威的 `STUDY_TIMEZONE` 计算，前端零时区逻辑**。

```
后端（权威）                         前端（零时区逻辑）
┌────────────────────┐              ┌──────────────────┐
│ reviewed_today      │─────────────▶│ 直接用布尔值       │
│ (per item, 服务端算) │              │ 不再 isStudyDayToday│
│ forecast 日期(研究日) │─────────────▶│ 直接用日期字符串     │
│ next_review_date    │─────────────▶│ 直接用于预测调整     │
│ study_date          │─────────────▶│ 展示用             │
└────────────────────┘              └──────────────────┘
```

同时修复复查发现的遗留问题：三处读端仍依赖已停写的 `user_practice_history`（R4/R5），Insights 天数分组与刷题学习日不一致（R6），以及若干次要问题（R7-R10）。

---

## Task A: 服务端下发 reviewed_today，前端删除 isStudyDayToday 🔴

**Files:**

- Edit: `backend/app/services/practice_deck_service.py`
- Edit: `frontend/src/composables/usePracticeDecks.js`
- Edit: `backend/tests/services/test_practice_study_date.py`（补充边界测试）

**现状**（已核实源码）：
- 后端 `list_deck_questions` 已用 `study_start`/`study_end` 计算每题的 `is_daily_relearning`（practice_deck_service.py:548-552）——**同一个边界计算可以复用**。
- 前端 `isStudyDayToday(value, studyDate)`（usePracticeDecks.js:353-359）用 `raw.slice(0,10) === studyDate` 比较：`raw` 是 UTC-naive `last_reviewed_at`，`studyDate` 是上海日期 → 在 UTC 16:00–24:00（上海 00:00–08:00）窗口必然不相等。
- 影响面：`applyQuestionResponse`（reviewedDueQueueIds）、`submitReview`（wasPassedToday）、`correctReview`（wasPassedToday）。

**Step 1（RED）**：在 `test_practice_study_date.py` 增加边界测试：
- 插入一条 `practice_review_events`，`reviewed_at = 今天上海 06:00`（即 UTC 昨天 22:00）
- 断言 API 返回的该题 `reviewed_today = true`（当前字段不存在，测试失败）

**Step 2**：跑测试确认失败

**Step 3（GREEN，后端）**：

```python
# practice_deck_service.py — 在 due 分支返回 items 时追加 reviewed_today
# 复用已计算的 study_start/study_end 边界
"reviewed_today": (
    deck_key == "due"
    and study_start <= str(row["last_reviewed_at"] or "") < study_end
),
```

**Step 4（GREEN，前端）**：

```javascript
// usePracticeDecks.js — 删除 isStudyDayToday 及 studyDate 传递，改用服务端布尔值
// applyQuestionResponse:
if (deckKey === 'due') {
  reviewedDueQueueIds = new Set((response.items || [])
    .filter(question => question.reviewed_today && ['good', 'easy'].includes(question.last_rating))
    .map(question => question.id))
  attemptedDueQueueIds = new Set((response.items || [])
    .filter(question => question.reviewed_today)
    .map(question => question.id))
}

// submitReview:
const wasPassedToday = item?.reviewed_today && ['good', 'easy'].includes(item?.last_rating)

// correctReview（previousRating 分支保留，else 分支用 reviewed_today）:
const wasPassedToday = previousRating
  ? ['good', 'easy'].includes(previousRating)
  : (item?.reviewed_today && ['good', 'easy'].includes(item?.last_rating))
```

**Step 5**：`cd frontend && npm run build` + 后端测试

**Step 6**：提交 `fix(practice): server-authoritative reviewed_today flag`

**Done when**：前端 `isStudyDayToday` 函数被删除；所有"今天"判断消费服务端 `reviewed_today`。

---

## Task B: Forecast 与复习预测统一服务端研究日 🔴

**Files:**

- Edit: `backend/app/services/practice_deck_service.py`
- Edit: `backend/app/services/practice_review_service.py`
- Edit: `frontend/src/composables/usePracticeDecks.js`
- Edit: `backend/tests/services/test_practice_study_date.py`

**现状**（已核实源码）：
- 服务端 forecast SQL（practice_deck_service.py:496-500）`GROUP BY date(uqr.next_review_at)` → **UTC 日期**
- Python 标签（:507-511）用 `study_start_date` → **上海日期**
- 前端 `utcDateKey`（usePracticeDecks.js:361-368）返回 UTC 日期键，`adjustReviewForecast`（:370-380）用 UTC 键比对上海标签

**Step 1（RED）**：断言 forecast 日期键与 `study_date` 同源（都是研究日而非 UTC）

**Step 2（GREEN，后端）**：forecast SQL 按研究日分组。SQLite 无法直接转换时区，采用 Python 分桶：

```python
# practice_deck_service.py — 查询未来 due 的 next_review_at，在 Python 按研究日分桶
future_rows = conn.execute(
    f"SELECT uqr.next_review_at {from_clause}{_review_join('?')}{future_where} "
    "AND uqr.next_review_at IS NOT NULL",
    params,
).fetchall()
zone = _study_timezone()
forecast_counts: dict[str, int] = {}
study_today = datetime.strptime(study_start, "%Y-%m-%d %H:%M:%S").date()
for row in future_rows:
    raw = str(row["next_review_at"])
    try:
        d = datetime.fromisoformat(raw).replace(tzinfo=UTC).astimezone(zone).date()
    except (TypeError, ValueError):
        continue
    if study_today < d <= study_today + timedelta(days=7):
        forecast_counts[d.isoformat()] = forecast_counts.get(d.isoformat(), 0) + 1
review_forecast = [
    {"date": (study_today + timedelta(days=day_offset)).isoformat(),
     "count": forecast_counts.get((study_today + timedelta(days=day_offset)).isoformat(), 0)}
    for day_offset in range(1, 8)
]
```

**Step 3（GREEN，后端 review payload）**：`_review_payload` 追加研究日日期，供前端预测调整：

```python
# practice_review_service.py
def _to_study_date(dt: datetime) -> str:
    from datetime import UTC
    zone = ZoneInfo(os.environ.get("STUDY_TIMEZONE", "Asia/Shanghai"))
    return dt.replace(tzinfo=UTC).astimezone(zone).date().isoformat()

# _review_payload 中追加
"next_review_date": _to_study_date(result.next_review_at),
```

**Step 4（GREEN，前端）**：`adjustReviewForecast` 改用服务端 `next_review_date`（研究日字符串），删除 `utcDateKey`：

```javascript
// usePracticeDecks.js
function adjustReviewForecast(deck, previousDate, nextDate) {
  if (!Array.isArray(deck?.review_forecast)) return
  deck.review_forecast = deck.review_forecast.map(day => {
    let count = Number(day.count || 0)
    if (previousDate && day.date === previousDate) count = Math.max(0, count - 1)
    if (nextDate && day.date === nextDate) count += 1
    return { ...day, count }
  })
}
// 调用处: previousDate 用 nextState.next_review_date, nextDate 也用 nextState.next_review_date
// correctReview 的 adjustReviewForecast 调用也同步改为传 next_review_date
```

**Step 5**：提交 `fix(practice): study-day anchored forecast and review adjustment`

**Done when**：forecast 日期、review 返回的 `next_review_date`、前端预测调整全部使用同一研究日。

---

## Task C: context_builder 读端迁移到 practice_review_events 🟡

**Files:**

- Edit: `backend/app/agents/chat/context_builder.py`
- Create: `backend/tests/chat/test_context_practice_stats.py`

**现状**（已核实源码）：
- `context_builder.py:80-98` 已迁移到 `practice_review_events`（total/avg/cat_stats）
- **但 :110-114 的「最近练习 3 题」仍读 `user_practice_history`**（已停写）→ 对重建后的用户永远为空

**Step 1（RED）**：测试断言插入一条 `practice_review_events`（source='self_check'）后，context_builder 的练习统计包含该题。

**Step 2（GREEN）**：

```python
# context_builder.py — 最近练习改为读 review events
recent = conn.execute(
    "SELECT qb.question, pr.score FROM practice_review_events pr "
    "JOIN question_bank qb ON pr.question_bank_id = qb.id "
    "WHERE pr.user_id = ? AND pr.source = 'self_check' AND pr.score IS NOT NULL "
    "ORDER BY pr.reviewed_at DESC LIMIT 3",
    (user_id,),
).fetchall()
```

**Step 3**：提交 `fix(chat): migrate practice stats read to review events`

**Done when**：context_builder 不再引用 `user_practice_history` 表。

---

## Task D: 练习记录 history tab 读端迁移（快照 user_answer）🟡

**Files:**

- Edit: `backend/app/db/migrations/practice.py`（新 migration 094：practice_review_events 加 user_answer 列）
- Edit: `backend/app/db/migrations/__init__.py`（登记 094）
- Edit: `backend/app/services/practice_review_service.py`（record_review 接收 user_answer 快照）
- Edit: `backend/app/routers/practice.py`（evaluate-answer 传 user_answer；practice-history 读 review events）
- Edit: `frontend/src/composables/usePractice.js`（loadHistory 兼容新响应）
- Edit: `backend/tests/services/test_review_idempotency.py` + 新增历史测试

**现状**（已核实源码）：
- `GET /api/practice-history/{question_id}`（practice.py:486）读 `user_practice_history`，但自评已停写该表
- `practice_review_events` 不存 `user_answer`/evaluation_result → 现代用户打开「练习记录」**永远为空**
- 前端 `PracticeMode.vue:349-353` 提示"暂无练习记录，先完成一次自测吧"——误导

**方案**：在 `practice_review_events` 增加 `user_answer TEXT` 快照列（仅 self_check 源写入）。历史 tab 改读 review events。

**Step 1（RED）**：测试断言：evaluate-answer 后 `practice_review_events` 存在一条含 user_answer 快照的记录；`GET /api/practice-history/{id}` 返回该记录。

**Step 2（GREEN，迁移）**：新 migration 094：

```python
# app/db/migrations/practice.py
def _migration_094_review_event_answer_snapshot(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(practice_review_events)")]
    if "user_answer" not in cols:
        conn.execute("ALTER TABLE practice_review_events ADD COLUMN user_answer TEXT")
    # 从存量 user_practice_history 回填（可选，best-effort）
```

**Step 3（GREEN，后端）**：
- `record_review` 增加可选 `user_answer: str | None = None` 参数，写入快照
- `evaluate-answer` 调用 record_review 时传 `user_answer=req.user_answer`
- `practice-history` 改读 `practice_review_events`（含 score/reviewed_at/rating/user_answer/source）

**Step 4（GREEN，前端）**：`loadHistory` 兼容新字段（无 evaluation_result 时用 rating 映射展示；保留 user_answer 文本）。

**Step 5**：提交 `fix(practice): history tab reads review events with answer snapshot`

**说明**：若不想加列，替代方案是历史 tab 只显示评分/评级（不显示用户答案原文）——但会损失核心 UX 价值，故推荐快照方案。

**Done when**：新自评在「练习记录」tab 立即可见；`user_practice_history` 无活跃读端。

---

## Task E: Insights 天数分组统一研究日 🟡

**Files:**

- Edit: `backend/app/services/insights.py`
- Create: `backend/tests/services/test_insights_practice_activity.py`（如不存在则新建）

**现状**（已核实源码）：
- `insights._activity_day_counts`（:298-303）`GROUP BY date(reviewed_at)` → UTC 日期
- `_daily_avg_scores`（:310-315）`GROUP BY date(reviewed_at)` → UTC 日期
- `_practice_days`（:346-347）`date(reviewed_at)` → UTC 日期
- 与刷题模块学习日（上海）不一致 → 热量图/连击/趋势在 UTC 16:00–24:00 窗口差一天

**Step 1（RED）**：测试断言 UTC 22:00（上海次日）的记录被计到研究日而非 UTC 日。

**Step 2（GREEN）**：Insights 统一走 `_study_timezone()` 转换（复用 practice_deck_service 的 study 转换或抽公共 helper）：

```python
# insights.py — 抽公共 helper（或直接复用 practice_deck_service._study_timezone）
def _study_day_key(value: str) -> str | None:
    try:
        d = datetime.fromisoformat(str(value)).replace(tzinfo=UTC).astimezone(_study_timezone()).date()
        return d.isoformat()
    except (TypeError, ValueError):
        return None
```

SQL 端改为取 reviewed_at 列表后在 Python 分桶（单用户题量级，数据量小），或直接 `date(reviewed_at, 'localtime')` 仅当容器 TZ=上海时才正确——**必须用 Python 显式转换，不能用 localtime**（容器 TZ 不可信）。

**Step 3**：提交 `fix(insights): study-day anchored activity grouping`

**Done when**：Insights 热量图/连击/趋势的日期边界与刷题页「学习日」一致。

---

## Task F: 次要项收敛 🟢

**Files:**

- Edit: `backend/app/services/practice_deck_service.py`（R7）
- Edit: `frontend/src/composables/usePracticeDecks.js`（R8）
- Edit: `backend/app/routers/practice.py`（R9）

**R7** `_split_bank_params` 字符串子串匹配 → 返回结构化契约：

```python
# practice_deck_service.py
# 让 _base_query_parts 直接由 build_bank_where_clause 的返回结构确定参数切分，
# 不再用 from_clause 字符串匹配 "qp.position_id = ?"
```

**R8** `questionCache` 无上限 → 加 MAX_CACHE_ENTRIES=20，超限删除最旧：

```javascript
// usePracticeDecks.js
const MAX_CACHE_ENTRIES = 20
function trimCache() {
  if (questionCache.size <= MAX_CACHE_ENTRIES) return
  const byAge = [...questionCacheUpdatedAt.entries()].sort((a, b) => a[1] - b[1])
  for (const [key] of byAge.slice(0, questionCache.size - MAX_CACHE_ENTRIES)) {
    questionCache.delete(key)
    questionCacheUpdatedAt.delete(key)
  }
}
```

**R9** evaluate-answer 静默截断 3000 字符 → 截断时记录日志并在响应中标记：

```python
# practice.py — evaluate-answer 截断提示
truncated = len(req.user_answer) > 3000 or len(req.reference_answer) > 3000
if truncated:
    logger.info(f"evaluate-answer 输入截断 (question_id={req.question_id})")
# 响应追加 "truncated": truncated 供前端提示
```

**Step 5**：提交 `refactor(practice): cache cap, params contract, truncation log`

---

## 验证方案

### 后端
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_study_date.py backend/tests/services/test_practice_api.py backend/tests/services/test_review_idempotency.py backend/tests/chat/test_context_practice_stats.py backend/tests/services/test_insights_practice_activity.py -q
```

### 前端
```bash
cd frontend && npm run build && npm run test
```

### 手动验证
1. **边界**：改系统时间为 UTC 16:00–24:00 窗口，刷一题 → 进度、预测柱状图、打卡与后端一致
2. **历史 tab**：新做一次自测 → 「练习记录」立即显示该次自测（评分 + 用户答案）
3. **Insights**：与刷题页今日完成数对比，热量图同日
4. **面试上下文**：练习统计含最近自测
