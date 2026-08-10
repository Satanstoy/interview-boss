# 洞察总览「我的练习足迹」图表改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把洞察总览改造成带 6 个激励型图表的「练习足迹」页：打卡热力图、连续打卡 Streak、刷题趋势、主题熟练度雷达、难度分布环形、最近刷题时间线。

**Architecture:** 后端新增 `GET /api/insights/practice-activity` 端点，`build_practice_activity(user)` 聚合 `user_practice_history`（答题）+ `practice_review_events`（闪卡复习）两个来源，JOIN `question_bank` 补难度/主题，SRS 熟练度来自 `user_question_review`。前端在 `InsightsOverview.vue` 统计卡片下方新增图表区，6 个新业务组件（热力图 CSS grid 自绘，其余 ECharts 6），共享新增 `useEChart.js` composable 统一图表生命周期。

**Tech Stack:** FastAPI / SQLite / Vue 3 / ECharts 6 / Tailwind / shadcn-vue / Playwright（mock API）

---

## 文件结构

**后端**
- Modify: `backend/app/services/insights.py` — 新增 `build_practice_activity()` 及 6 个私有聚合函数
- Modify: `backend/app/routers/insights.py` — 新增 `GET /api/insights/practice-activity` 端点
- Modify: `backend/tests/services/test_insights.py` — 追加 7 个测试 + 修改 `_insert_question` helper 支持 difficulty

**前端**
- Modify: `frontend/src/services/insightsApi.js` — 新增 `fetchPracticeActivity()`
- Modify: `frontend/src/api/index.js` — re-export `fetchPracticeActivity`
- Modify: `frontend/src/composables/useInsightsData.js` — 新增 practiceActivity 状态
- Create: `frontend/src/composables/useEChart.js` — ECharts 生命周期封装
- Create: `frontend/src/utils/time.js` — `formatRelativeTime()`
- Create: `frontend/src/components/business/PracticeHeatmap.vue`
- Create: `frontend/src/components/business/PracticeStreakCard.vue`
- Create: `frontend/src/components/business/PracticeTrendChart.vue`
- Create: `frontend/src/components/business/PracticeDifficultyChart.vue`
- Create: `frontend/src/components/business/PracticeRadarChart.vue`
- Create: `frontend/src/components/business/PracticeRecentTimeline.vue`
- Modify: `frontend/src/views/InsightsView.vue` — overview 时加载 practiceActivity 并透传
- Modify: `frontend/src/components/business/InsightsOverview.vue` — 新增图表区
- Modify: `frontend/tests/e2e/insights.spec.js` — mock practice-activity + 断言足迹区

**文档**
- Modify: `backend/app/services/CLAUDE.md`、`frontend/CLAUDE.md`、`frontend/src/components/business/CLAUDE.md`、`frontend/src/composables/CLAUDE.md`、`frontend/src/services/CLAUDE.md`、`frontend/src/views/CLAUDE.md`、根 `CLAUDE.md` 代码路由表

---

## API 契约（后端返回结构）

```
GET /api/insights/practice-activity → {
  version: 1,
  heatmap:  [ { date: "YYYY-MM-DD", count: int, avg_score: float } × 90 ],  // 含今天，无活动 count=0
  streak:   { current: int, longest: int },                                  // 自然日连续
  trend:    [ { date, count, avg_score } × 30 ],
  radar:    [ { topic: str, proficiency: int(0-100) } × ≤8 ],               // SRS 熟练度 top8
  difficulty: [ { difficulty: str(简单/中等/困难/未标注), count: int, correct_rate: int(0-100) } ],
  recent:   [ { id, type: "answer"|"review", question: str, difficulty: str,
                topic: str, score: int|null, rating: str|null, created_at: str } × ≤10 ]
}
```

口径：count = 答题 + 复习事件总数；avg_score 只算 `user_practice_history` 有分记录；correct = score ≥ 60；streak 按全部历史日期（不限于 90 天窗口）。

---

## Task 1: 后端 — build_practice_activity 聚合服务（TDD）

**Files:**
- Modify: `backend/tests/services/test_insights.py`
- Modify: `backend/app/services/insights.py`

### Step 1: 写失败测试

在 `backend/tests/services/test_insights.py` 末尾追加。先改 helper（第 12-26 行的 `_insert_question` 加 difficulty 参数）：

```python
def _insert_question(conn, question_id, topic, position="测试岗位", frequency=1, deleted_at=None, difficulty="简单"):
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, frequency, status, owner_id, job_position, deleted_at, difficulty) "
        "VALUES (?, ?, ?, ?, ?, 'approved', NULL, ?, ?, ?)",
        (
            question_id,
            f"{topic}面试题",
            "能力域",
            topic,
            frequency,
            position,
            deleted_at,
            difficulty,
        ),
    )
```

再追加 helper 和测试（追加在文件末尾）：

```python
def _insert_review(conn, user_id, review_id, question_bank_id, rating, reviewed_at, score=None):
    conn.execute(
        "INSERT INTO user_question_review "
        "(id, user_id, question_bank_id, proficiency, state, last_rating) "
        "VALUES (?, ?, ?, 40, 'review', ?)",
        (review_id, user_id, question_bank_id, rating),
    )
    conn.execute(
        "INSERT INTO practice_review_events "
        "(user_id, question_bank_id, review_id, rating, score, reviewed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, question_bank_id, review_id, rating, score, reviewed_at),
    )


def test_practice_activity_heatmap_trend_and_streak(test_db):
    from datetime import datetime, timedelta

    from app.services.insights import build_practice_activity

    _insert_user(test_db, 401)
    _insert_question(test_db, 1, "RAG系统设计", difficulty="medium")
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

    for i, score in enumerate((85, 90)):
        test_db.execute(
            "INSERT INTO user_practice_history "
            "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, ?)",
            (401, 1, score, f"{today} 10:0{i}:00"),
        )
    test_db.execute(
        "INSERT INTO user_practice_history "
        "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, ?)",
        (401, 1, 50, f"{three_days_ago} 09:00:00"),
    )
    _insert_review(test_db, 401, 1, 1, "good", f"{yesterday} 20:00:00", score=85)
    test_db.commit()

    data = build_practice_activity({"id": 401})

    assert data["streak"] == {"current": 2, "longest": 2}
    assert len(data["heatmap"]) == 90
    assert len(data["trend"]) == 30
    day_map = {d["date"]: d for d in data["heatmap"]}
    assert day_map[today]["count"] == 2
    assert day_map[today]["avg_score"] == 87.5
    assert day_map[yesterday]["count"] == 1
    assert day_map[three_days_ago]["count"] == 1
    trend_map = {d["date"]: d for d in data["trend"]}
    assert trend_map[today]["count"] == 2
    assert trend_map[today]["avg_score"] == 87.5


def test_practice_activity_streak_breaks_with_gap(test_db):
    from datetime import datetime, timedelta

    from app.services.insights import build_practice_activity

    _insert_user(test_db, 402)
    _insert_question(test_db, 2, "Agent编排")
    today = datetime.now().strftime("%Y-%m-%d")
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    test_db.execute(
        "INSERT INTO user_practice_history "
        "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, ?)",
        (402, 2, 70, f"{today} 09:00:00"),
    )
    test_db.execute(
        "INSERT INTO user_practice_history "
        "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, ?)",
        (402, 2, 70, f"{three_days_ago} 09:00:00"),
    )
    test_db.commit()

    data = build_practice_activity({"id": 402})

    assert data["streak"] == {"current": 1, "longest": 1}


def test_practice_activity_streak_zero_without_activity(test_db):
    from app.services.insights import build_practice_activity

    _insert_user(test_db, 403)
    _insert_question(test_db, 3, "函数调用")

    data = build_practice_activity({"id": 403})

    assert data["streak"] == {"current": 0, "longest": 0}
    assert data["heatmap"][-1]["count"] == 0


def test_practice_activity_radar_topics_by_proficiency(test_db):
    from app.services.insights import build_practice_activity

    _insert_user(test_db, 404)
    _insert_question(test_db, 1, "RAG系统设计")
    _insert_question(test_db, 2, "Agent编排")
    _insert_question(test_db, 3, "前端工程", position="其他岗位")
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, proficiency) VALUES (?, ?, ?)",
        (404, 1, 80),
    )
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, proficiency) VALUES (?, ?, ?)",
        (404, 2, 40),
    )
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, proficiency) VALUES (?, ?, ?)",
        (404, 3, 90),
    )
    test_db.commit()

    data = build_practice_activity({"id": 404})

    topics = {item["topic"]: item["proficiency"] for item in data["radar"]}
    assert topics == {"前端工程": 90, "RAG系统设计": 80, "Agent编排": 40}


def test_practice_activity_difficulty_correct_rate(test_db):
    from app.services.insights import build_practice_activity

    _insert_user(test_db, 405)
    _insert_question(test_db, 1, "RAG系统设计", difficulty="简单")
    _insert_question(test_db, 2, "Agent编排", difficulty="中等")
    _insert_question(test_db, 3, "前端工程", difficulty="hard")
    _insert_question(test_db, 4, "未标注难度", difficulty="")
    for qid, score in ((1, 70), (1, 50), (2, 90), (3, 45), (4, 66)):
        test_db.execute(
            "INSERT INTO user_practice_history "
            "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, datetime('now'))",
            (405, qid, score),
        )
    test_db.commit()

    data = build_practice_activity({"id": 405})

    stats = {item["difficulty"]: item for item in data["difficulty"]}
    assert stats["简单"] == {"difficulty": "简单", "count": 2, "correct_rate": 50}
    assert stats["中等"] == {"difficulty": "中等", "count": 1, "correct_rate": 100}
    assert stats["困难"] == {"difficulty": "困难", "count": 1, "correct_rate": 0}
    assert stats["未标注"] == {"difficulty": "未标注", "count": 1, "correct_rate": 100}


def test_practice_activity_recent_merges_and_limits(test_db):
    from datetime import datetime

    from app.services.insights import build_practice_activity

    _insert_user(test_db, 406)
    _insert_question(test_db, 1, "RAG系统设计")
    for i in range(12):
        test_db.execute(
            "INSERT INTO user_practice_history "
            "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, ?)",
            (406, 1, 60 + i, f"2026-08-01 {i:02d}:00:00"),
        )
    _insert_review(test_db, 406, 1, 1, "easy", "2026-08-05 09:00:00")
    test_db.commit()

    data = build_practice_activity({"id": 406})

    assert len(data["recent"]) == 10
    first = data["recent"][0]
    assert first["type"] == "review"
    assert first["rating"] == "easy"
    assert first["question"] == "RAG系统设计面试题"
    assert first["score"] is None
    answers = [item for item in data["recent"] if item["type"] == "answer"]
    assert len(answers) == 9
    assert all(item["score"] is not None and item["created_at"] for item in answers)


def test_practice_activity_is_user_scoped(test_db):
    from app.services.insights import build_practice_activity

    _insert_user(test_db, 407)
    _insert_user(test_db, 408)
    _insert_question(test_db, 1, "RAG系统设计")
    test_db.execute(
        "INSERT INTO user_practice_history "
        "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, datetime('now'))",
        (407, 1, 88),
    )
    test_db.commit()

    data = build_practice_activity({"id": 408})

    assert data["heatmap"][-1]["count"] == 0
    assert data["streak"] == {"current": 0, "longest": 0}
    assert data["radar"] == []
    assert data["difficulty"] == []
    assert data["recent"] == []
```

### Step 2: 运行测试确认失败

Run:
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_insights.py -q
```
Expected: FAIL — `ImportError: cannot import name 'build_practice_activity' from 'app.services.insights'`

### Step 3: 最小实现

在 `backend/app/services/insights.py` 顶部 import 处追加：

```python
from datetime import datetime, timedelta
```

在文件末尾（`build_insights_snapshot` 之后）追加：

```python
_DIFFICULTY_LABELS = {"easy": "简单", "medium": "中等", "hard": "困难"}


def _difficulty_label(raw: str | None) -> str:
    return _DIFFICULTY_LABELS.get((raw or "").lower(), raw or "未标注")


def _activity_day_counts(conn, user_id: int, since: str) -> dict[str, int]:
    """按天统计练习次数（正式答题 + 闪卡复习）。"""
    counts: dict[str, int] = {}
    for row in conn.execute(
        "SELECT date(created_at) AS day, COUNT(*) AS cnt FROM user_practice_history "
        "WHERE user_id = ? AND created_at >= ? GROUP BY day",
        (user_id, since),
    ).fetchall():
        counts[row["day"]] = counts.get(row["day"], 0) + row["cnt"]
    for row in conn.execute(
        "SELECT date(reviewed_at) AS day, COUNT(*) AS cnt FROM practice_review_events "
        "WHERE user_id = ? AND reviewed_at >= ? GROUP BY day",
        (user_id, since),
    ).fetchall():
        counts[row["day"]] = counts.get(row["day"], 0) + row["cnt"]
    return counts


def _daily_avg_scores(conn, user_id: int, since: str) -> dict[str, float]:
    """按天统计答题平均分（仅 user_practice_history 的有分记录）。"""
    avgs = {}
    for row in conn.execute(
        "SELECT date(created_at) AS day, AVG(score) AS avg_s FROM user_practice_history "
        "WHERE user_id = ? AND score IS NOT NULL AND created_at >= ? GROUP BY day",
        (user_id, since),
    ).fetchall():
        avgs[row["day"]] = round(row["avg_s"] or 0, 1)
    return avgs


def _build_daily_series(
    conn, user_id: int, days: int, today: datetime.date
) -> list[dict]:
    """生成近 N 天的 {date, count, avg_score} 序列（含今天，无活动补 0）。"""
    since = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    counts = _activity_day_counts(conn, user_id, since)
    avgs = _daily_avg_scores(conn, user_id, since)
    series = []
    for i in range(days - 1, -1, -1):
        key = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        series.append(
            {
                "date": key,
                "count": counts.get(key, 0),
                "avg_score": avgs.get(key, 0),
            }
        )
    return series


def _practice_days(conn, user_id: int) -> set[str]:
    """返回用户全部有练习活动的日期集合（跨 90 天窗口，用于 streak）。"""
    days = set()
    for table, column in (
        ("user_practice_history", "created_at"),
        ("practice_review_events", "reviewed_at"),
    ):
        rows = conn.execute(
            f"SELECT DISTINCT date({column}) AS day FROM {table} WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        for row in rows:
            if row["day"]:
                days.add(row["day"])
    return days


def _streak_stats(days: set[str], today: str) -> dict:
    """计算当前连续天数与历史最长连续天数（自然日，今天未打卡不断连）。"""
    today_date = datetime.strptime(today, "%Y-%m-%d").date()
    cursor = today_date if today in days else today_date - timedelta(days=1)
    current = 0
    while cursor.strftime("%Y-%m-%d") in days:
        current += 1
        cursor -= timedelta(days=1)

    longest = 0
    run = 0
    prev = None
    for day_str in sorted(days):
        day = datetime.strptime(day_str, "%Y-%m-%d").date()
        run = run + 1 if prev is not None and (day - prev).days == 1 else 1
        longest = max(longest, run)
        prev = day
    return {"current": current, "longest": longest}


def _radar_topics(conn, user_id: int, limit: int = 8) -> list[dict]:
    """按 SRS 熟练度取前 N 个主题（cat2 fallback cat1）。"""
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(qb.cat2, ''), NULLIF(qb.cat1, ''), '未分类') AS topic, "
        "AVG(uqr.proficiency) AS prof "
        "FROM user_question_review uqr "
        "JOIN question_bank qb ON qb.id = uqr.question_bank_id "
        "WHERE uqr.user_id = ? AND qb.deleted_at IS NULL "
        "GROUP BY topic ORDER BY prof DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [{"topic": row["topic"], "proficiency": round(row["prof"] or 0)} for row in rows]


def _difficulty_stats(conn, user_id: int) -> list[dict]:
    """按难度统计练习次数与正确率（score >= 60 算对）。"""
    rows = conn.execute(
        "SELECT qb.difficulty AS d, COUNT(*) AS total, "
        "SUM(CASE WHEN uph.score >= 60 THEN 1 ELSE 0 END) AS correct "
        "FROM user_practice_history uph "
        "JOIN question_bank qb ON qb.id = uph.question_bank_id "
        "WHERE uph.user_id = ? AND uph.score IS NOT NULL "
        "GROUP BY qb.difficulty",
        (user_id,),
    ).fetchall()
    stats = []
    for row in rows:
        total = row["total"]
        correct = row["correct"] or 0
        stats.append(
            {
                "difficulty": _difficulty_label(row["d"]),
                "count": total,
                "correct_rate": round(correct * 100 / total),
            }
        )
    stats.sort(key=lambda item: -item["count"])
    return stats


def _recent_activities(conn, user_id: int, limit: int = 10) -> list[dict]:
    """合并最近的答题与复习事件，按时间倒序取前 N 条。"""
    answers = conn.execute(
        "SELECT uph.id, 'answer' AS type, uph.question_bank_id, uph.score, "
        "uph.created_at AS ts FROM user_practice_history uph "
        "WHERE uph.user_id = ? ORDER BY uph.created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    reviews = conn.execute(
        "SELECT pre.id, 'review' AS type, pre.question_bank_id, NULL AS score, "
        "pre.rating, pre.reviewed_at AS ts FROM practice_review_events pre "
        "WHERE pre.user_id = ? ORDER BY pre.reviewed_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    merged = sorted(
        [dict(row) for row in answers] + [dict(row) for row in reviews],
        key=lambda item: item["ts"] or "",
        reverse=True,
    )[:limit]

    questions = {}
    qids = [item["question_bank_id"] for item in merged]
    if qids:
        placeholders = ",".join("?" * len(qids))
        for row in conn.execute(
            f"SELECT id, question, difficulty, cat2 FROM question_bank "
            f"WHERE id IN ({placeholders})",
            qids,
        ).fetchall():
            questions[row["id"]] = dict(row)

    result = []
    for item in merged:
        q = questions.get(item["question_bank_id"]) or {}
        result.append(
            {
                "id": item["id"],
                "type": item["type"],
                "question": q.get("question") or "题目已删除",
                "difficulty": _difficulty_label(q.get("difficulty")),
                "topic": q.get("cat2") or "未分类",
                "score": item.get("score"),
                "rating": item.get("rating"),
                "created_at": item.get("ts"),
            }
        )
    return result


def build_practice_activity(user: dict) -> dict:
    """同步聚合当前用户的练习足迹数据（热力图/连击/趋势/雷达/难度/最近刷题）。"""

    user_id = int(user["id"])
    with get_db_connection() as conn:
        today = datetime.now().date()
        heatmap = _build_daily_series(conn, user_id, 90, today)
        trend = _build_daily_series(conn, user_id, 30, today)
        days = _practice_days(conn, user_id)
        streak = _streak_stats(days, today.strftime("%Y-%m-%d"))
        radar = _radar_topics(conn, user_id)
        difficulty = _difficulty_stats(conn, user_id)
        recent = _recent_activities(conn, user_id)

    return {
        "version": API_VERSION,
        "heatmap": heatmap,
        "streak": streak,
        "trend": trend,
        "radar": radar,
        "difficulty": difficulty,
        "recent": recent,
    }
```

### Step 4: 运行测试确认通过

Run:
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_insights.py -q
```
Expected: PASS（原 3 个 + 新 7 个全绿）

### Step 5: Commit

```bash
git add backend/app/services/insights.py backend/tests/services/test_insights.py
git commit -m "feat(backend): add practice activity aggregation service for insights"
```

---

## Task 2: 后端 — 路由端点

**Files:**
- Modify: `backend/tests/services/test_insights.py`
- Modify: `backend/app/routers/insights.py`

### Step 1: 写失败测试

在 `backend/tests/services/test_insights.py` 末尾追加：

```python
def test_practice_activity_endpoint_contract(client, test_db):
    from app.asgi import app
    from app.core.auth import get_current_user

    _insert_user(test_db, 501)
    app.dependency_overrides[get_current_user] = lambda: {"id": 501}
    try:
        response = client.get("/api/insights/practice-activity")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "version",
        "heatmap",
        "streak",
        "trend",
        "radar",
        "difficulty",
        "recent",
    }
    assert len(body["heatmap"]) == 90
    assert len(body["trend"]) == 30
    assert body["streak"] == {"current": 0, "longest": 0}
```

### Step 2: 运行测试确认失败

Run:
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_insights.py::test_practice_activity_endpoint_contract -q
```
Expected: FAIL — 404 Not Found

### Step 3: 实现端点

`backend/app/routers/insights.py`：

```python
"""洞察工作台 API。"""

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.db.connection import run_db
from app.services.insights import build_insights_snapshot, build_practice_activity


router = APIRouter()


@router.get("/api/insights")
async def get_insights(user: dict = Depends(get_current_user)):
    """返回当前用户当前岗位的洞察快照。"""

    return await run_db(lambda: build_insights_snapshot(user))


@router.get("/api/insights/practice-activity")
async def get_practice_activity(user: dict = Depends(get_current_user)):
    """返回当前用户的练习足迹数据（热力图/连击/趋势/雷达/难度/最近刷题）。"""

    return await run_db(lambda: build_practice_activity(user))
```

### Step 4: 运行测试确认通过

Run:
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_insights.py -q
```
Expected: PASS

### Step 5: Commit

```bash
git add backend/app/routers/insights.py backend/tests/services/test_insights.py
git commit -m "feat(backend): expose practice-activity insights endpoint"
```

---

## Task 3: 前端 — API service + composable

**Files:**
- Modify: `frontend/src/services/insightsApi.js`
- Modify: `frontend/src/api/index.js`
- Modify: `frontend/src/composables/useInsightsData.js`

### Step 1: service + re-export

`frontend/src/services/insightsApi.js` 全文替换为：

```js
import { get } from './http.js'

/** 获取当前用户当前岗位的洞察快照。 */
export function fetchInsights(options = {}) {
  return get('/api/insights', options)
}

/** 获取用户练习足迹图表数据（热力图/连击/趋势/雷达/难度/最近刷题）。 */
export function fetchPracticeActivity(options = {}) {
  return get('/api/insights/practice-activity', options)
}
```

`frontend/src/api/index.js` 第 91 行改为：

```js
export { fetchInsights, fetchPracticeActivity } from '../services/insightsApi.js'
```

### Step 2: composable

`frontend/src/composables/useInsightsData.js` 全文替换为：

```js
import { ref } from 'vue'
import { fetchInsights, fetchPracticeActivity } from '@/services/insightsApi.js'

export function useInsightsData() {
  const snapshot = ref(null)
  const practiceActivity = ref(null)
  const isLoading = ref(false)
  const practiceLoading = ref(false)
  const error = ref(null)

  async function loadInsights() {
    isLoading.value = true
    error.value = null
    try {
      snapshot.value = await fetchInsights({ noCache: true })
    } catch (err) {
      error.value = err
    } finally {
      isLoading.value = false
    }
  }

  async function loadPracticeActivity() {
    practiceLoading.value = true
    try {
      practiceActivity.value = await fetchPracticeActivity({ noCache: true })
    } catch {
      practiceActivity.value = null
    } finally {
      practiceLoading.value = false
    }
  }

  return {
    snapshot,
    practiceActivity,
    isLoading,
    practiceLoading,
    error,
    loadInsights,
    loadPracticeActivity,
  }
}
```

### Step 3: 构建验证

Run:
```bash
cd frontend && npm run build
```
Expected: build 成功，无 lint 报错

### Step 4: Commit

```bash
git add frontend/src/services/insightsApi.js frontend/src/api/index.js frontend/src/composables/useInsightsData.js
git commit -m "feat(frontend): add practice activity api service and composable state"
```

---

## Task 4: 前端 — useEChart 生命周期 composable

**Files:**
- Create: `frontend/src/composables/useEChart.js`

### Step 1: 创建文件

```js
import { nextTick, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { useTheme } from './useTheme.js'

/**
 * ECharts 生命周期封装：init / ResizeObserver / 主题切换 / dispose。
 * buildOption(dark) 返回完整 option；数据变化后调用 refresh() 重绘。
 */
export function useEChart(chartRef, buildOption) {
  const { isDark } = useTheme()
  let myChart = null
  let resizeObserver = null

  function refresh() {
    nextTick(() => {
      if (!myChart && chartRef.value) {
        myChart = echarts.init(chartRef.value)
        resizeObserver = new ResizeObserver(() => {
          if (myChart) myChart.resize()
        })
        resizeObserver.observe(chartRef.value)
      }
      if (myChart && buildOption) myChart.setOption(buildOption(isDark.value), true)
    })
  }

  watch(isDark, () => {
    if (myChart && buildOption) myChart.setOption(buildOption(isDark.value), true)
  })

  onMounted(refresh)
  onUnmounted(() => {
    if (resizeObserver) {
      resizeObserver.disconnect()
      resizeObserver = null
    }
    if (myChart) {
      myChart.dispose()
      myChart = null
    }
  })

  return { refresh }
}
```

### Step 2: 构建验证 + Commit

Run:
```bash
cd frontend && npm run build
```
Expected: 成功（该文件无引用暂不会被 tree-shake 报错；lint 通过即可）

```bash
git add frontend/src/composables/useEChart.js
git commit -m "feat(frontend): add useEChart lifecycle composable"
```

---

## Task 5: 前端 — 工具函数 formatRelativeTime

**Files:**
- Create: `frontend/src/utils/time.js`

### Step 1: 创建文件

```js
/** 相对时间：刚刚 / N 分钟前 / N 小时前 / 昨天 / N 天前 / 日期 */
export function formatRelativeTime(value) {
  if (!value) return ''
  const time = new Date(String(value).replace(' ', 'T'))
  if (Number.isNaN(time.getTime())) return String(value).slice(0, 10)
  const diff = Date.now() - time.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days === 1) return '昨天'
  if (days < 7) return `${days} 天前`
  return String(value).slice(0, 10)
}
```

### Step 2: Commit

```bash
git add frontend/src/utils/time.js
git commit -m "feat(frontend): add relative time formatter util"
```

---

## Task 6: 前端 — PracticeHeatmap（CSS grid 自绘，GitHub 风格）

**Files:**
- Create: `frontend/src/components/business/PracticeHeatmap.vue`

### Step 1: 创建组件

```vue
<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h3 class="text-sm font-semibold text-card-foreground">打卡热力图</h3>
        <p class="mt-0.5 text-xs text-muted-foreground">近 90 天练习分布，每天点亮一格</p>
      </div>
      <div v-if="totalCount > 0" class="flex items-center gap-1.5 text-[10px] text-muted-foreground">
        <span>少</span>
        <span class="h-2.5 w-2.5 rounded-[3px] bg-muted/50" />
        <span class="h-2.5 w-2.5 rounded-[3px] bg-emerald-200 dark:bg-emerald-800" />
        <span class="h-2.5 w-2.5 rounded-[3px] bg-emerald-300 dark:bg-emerald-600" />
        <span class="h-2.5 w-2.5 rounded-[3px] bg-emerald-500" />
        <span class="h-2.5 w-2.5 rounded-[3px] bg-emerald-600 dark:bg-emerald-400" />
        <span>多</span>
      </div>
    </div>

    <div v-if="totalCount > 0" class="mt-3 flex-1 overflow-x-auto custom-scrollbar">
      <div class="flex flex-col gap-1">
        <div class="flex gap-1 pl-6">
          <span v-for="month in monthLabels" :key="month.key" class="w-[14px] text-[9px] leading-3 text-muted-foreground">{{ month.label }}</span>
        </div>
        <div class="flex gap-1">
          <div class="flex w-5 flex-col justify-between text-[9px] text-muted-foreground">
            <span>一</span>
            <span>三</span>
            <span>五</span>
            <span>日</span>
          </div>
          <div class="flex gap-1">
            <div v-for="(week, wi) in weeks" :key="wi" class="flex flex-col gap-1">
              <AppTooltip
                v-for="cell in week"
                :key="cell.date"
                :text="cell.date ? `${cell.date} 练习 ${cell.count} 题${cell.avg_score ? `，平均 ${cell.avg_score} 分` : ''}` : ''"
              >
                <div
                  class="h-2.5 w-2.5 rounded-[3px]"
                  :class="cellClass(cell)"
                />
              </AppTooltip>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center">
      <p class="text-sm text-muted-foreground">还没有练习记录</p>
      <Button variant="outline" size="sm" @click="goPractice">去刷一题，点亮第一格</Button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import AppTooltip from '@/components/common/AppTooltip.vue'

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const router = useRouter()
const totalCount = computed(() => props.data.reduce((sum, day) => sum + (day.count || 0), 0))

function cellClass(cell) {
  if (!cell.date || cell.count === 0) return 'bg-muted/50'
  if (cell.count <= 2) return 'bg-emerald-200 dark:bg-emerald-800'
  if (cell.count <= 5) return 'bg-emerald-300 dark:bg-emerald-600'
  if (cell.count <= 9) return 'bg-emerald-500'
  return 'bg-emerald-600 dark:bg-emerald-400'
}

const weeks = computed(() => {
  const days = props.data
  if (!days.length) return []
  const today = new Date(days[days.length - 1].date + 'T00:00:00')
  const start = new Date(today)
  start.setDate(today.getDate() - (days.length - 1))
  while (start.getDay() !== 1) start.setDate(start.getDate() - 1)
  const byDate = new Map(days.map((d) => [d.date, d]))
  const weekRows = []
  let col = start
  for (let w = 0; w < 13; w += 1) {
    const week = []
    for (let r = 0; r < 7; r += 1) {
      const date = new Date(col)
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
      const day = byDate.get(key)
      week.push({ date: day ? key : '', count: day?.count || 0, avg_score: day?.avg_score || 0 })
      col.setDate(col.getDate() + 1)
    }
    weekRows.push(week)
  }
  return weekRows
})

const monthLabels = computed(() => {
  const labels = []
  for (const week of weeks.value) {
    for (const cell of week) {
      if (!cell.date) continue
      const d = new Date(cell.date + 'T00:00:00')
      if (d.getDate() === 1) {
        labels.push({ key: cell.date, label: `${d.getMonth() + 1}月` })
      }
    }
  }
  return labels
})

function goPractice() {
  router.push({ name: 'mock-interview' })
}
</script>
```

### Step 2: 构建 + Commit

Run:
```bash
cd frontend && npm run build
```
Expected: 成功

```bash
git add frontend/src/components/business/PracticeHeatmap.vue
git commit -m "feat(frontend): add github-style practice heatmap component"
```

---

## Task 7: 前端 — PracticeStreakCard

**Files:**
- Create: `frontend/src/components/business/PracticeStreakCard.vue`

### Step 1: 创建组件

```vue
<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div class="flex items-center gap-2">
      <Flame class="h-5 w-5 text-orange-500" />
      <h3 class="text-sm font-semibold text-card-foreground">连续打卡</h3>
    </div>
    <div class="mt-4 flex items-baseline gap-1">
      <span class="text-4xl font-bold tracking-tight text-foreground">{{ streak.current }}</span>
      <span class="text-sm text-muted-foreground">天</span>
    </div>
    <p class="mt-1 text-xs text-muted-foreground">历史最长 {{ streak.longest }} 天</p>
    <p v-if="todayCount === 0 && streak.current > 0" class="mt-3 text-xs font-medium text-amber-600 dark:text-amber-400">
      今天还没打卡，再刷一题连击 +1
    </p>
    <p v-else-if="todayCount === 0" class="mt-3 text-xs text-muted-foreground">
      从今天开始，连续 7 天养成面试准备习惯
    </p>
    <p v-else class="mt-3 text-xs font-medium text-emerald-600 dark:text-emerald-400">
      今日已打卡 {{ todayCount }} 题，保持住
    </p>
    <div class="mt-auto pt-4">
      <Button variant="outline" size="sm" class="w-full" @click="goPractice">
        {{ todayCount === 0 ? '去刷一题' : '继续刷题' }}
      </Button>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { Flame } from '@lucide/vue'
import { Button } from '@/components/ui/button'

const props = defineProps({
  streak: { type: Object, default: () => ({ current: 0, longest: 0 }) },
  todayCount: { type: Number, default: 0 },
})

const router = useRouter()

function goPractice() {
  router.push({ name: 'mock-interview' })
}
</script>
```

### Step 2: 构建 + Commit

Run:
```bash
cd frontend && npm run build
```

```bash
git add frontend/src/components/business/PracticeStreakCard.vue
git commit -m "feat(frontend): add practice streak card"
```

---

## Task 8: 前端 — PracticeTrendChart（ECharts 双轴）

**Files:**
- Create: `frontend/src/components/business/PracticeTrendChart.vue`

### Step 1: 创建组件

```vue
<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h3 class="text-sm font-semibold text-card-foreground">刷题趋势</h3>
        <p class="mt-0.5 text-xs text-muted-foreground">近 30 天练习量与平均分</p>
      </div>
    </div>
    <div v-if="totalCount > 0" ref="chartRef" class="mt-2 min-h-[220px] w-full flex-1" style="min-width: 0;" />
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      还没有练习记录，趋势图将在刷题后出现
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useEChart } from '@/composables/useEChart.js'

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const chartRef = ref(null)
const totalCount = computed(() => props.data.reduce((sum, d) => sum + (d.count || 0), 0))

const buildOption = (dark) => ({
  tooltip: {
    trigger: 'axis',
    confine: true,
    backgroundColor: dark ? 'rgba(45, 42, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
    borderColor: dark ? '#574f49' : '#e8e4dd',
    textStyle: { color: dark ? '#e7e5e2' : '#4a4540', fontSize: 12 },
  },
  legend: {
    top: 0,
    textStyle: { color: dark ? '#cfcac5' : '#4a4540', fontSize: 11 },
    data: ['练习次数', '平均分'],
  },
  grid: { left: 8, right: 8, top: 28, bottom: 0, containLabel: true },
  xAxis: {
    type: 'category',
    data: props.data.map((d) => d.date.slice(5)),
    axisLine: { lineStyle: { color: dark ? '#574f49' : '#e8e4dd' } },
    axisLabel: { color: dark ? '#8f8881' : '#a8a29e', fontSize: 10, interval: 6 },
    axisTick: { show: false },
  },
  yAxis: [
    {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: dark ? '#2e2a27' : '#f1efe9' } },
      axisLabel: { color: dark ? '#8f8881' : '#a8a29e', fontSize: 10 },
    },
    {
      type: 'value',
      min: 0,
      max: 100,
      splitLine: { show: false },
      axisLabel: { color: dark ? '#8f8881' : '#a8a29e', fontSize: 10 },
    },
  ],
  series: [
    {
      name: '练习次数',
      type: 'bar',
      data: props.data.map((d) => d.count),
      itemStyle: { color: '#10b981', borderRadius: [3, 3, 0, 0] },
      barMaxWidth: 14,
    },
    {
      name: '平均分',
      type: 'line',
      yAxisIndex: 1,
      smooth: true,
      data: props.data.map((d) => d.avg_score || null),
      itemStyle: { color: '#6366f1' },
      lineStyle: { color: '#6366f1', width: 2 },
      connectNulls: false,
      symbolSize: 5,
    },
  ],
})

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.data, refresh)
</script>
```

### Step 2: 构建 + Commit

Run:
```bash
cd frontend && npm run build
```

```bash
git add frontend/src/components/business/PracticeTrendChart.vue
git commit -m "feat(frontend): add practice trend chart"
```

---

## Task 9: 前端 — PracticeDifficultyChart（ECharts 环形）

**Files:**
- Create: `frontend/src/components/business/PracticeDifficultyChart.vue`

### Step 1: 创建组件

```vue
<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div>
      <h3 class="text-sm font-semibold text-card-foreground">难度分布</h3>
      <p class="mt-0.5 text-xs text-muted-foreground">各难度练习次数与正确率</p>
    </div>
    <div v-if="props.data.length" ref="chartRef" class="mt-2 min-h-[220px] w-full flex-1" style="min-width: 0;" />
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      刷题后这里会显示难度分布
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useEChart } from '@/composables/useEChart.js'

echarts.use([PieChart, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const chartRef = ref(null)
const palette = ['#10b981', '#f59e0b', '#f43f5e', '#94a3b8']

const buildOption = (dark) => ({
  tooltip: {
    trigger: 'item',
    confine: true,
    backgroundColor: dark ? 'rgba(45, 42, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
    borderColor: dark ? '#574f49' : '#e8e4dd',
    textStyle: { color: dark ? '#e7e5e2' : '#4a4540', fontSize: 12 },
    formatter: (params) => {
      const item = props.data[params.dataIndex]
      return `${params.name}: ${params.value} 次 · 正确率 ${item.correct_rate}%`
    },
  },
  series: [
    {
      type: 'pie',
      radius: ['35%', '68%'],
      center: ['50%', '54%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 6, borderColor: dark ? '#1a1816' : '#faf9f7', borderWidth: 2 },
      label: {
        show: true,
        fontSize: 10,
        color: dark ? '#cfcac5' : '#4a4540',
        formatter: '{b}\n{c} 次',
      },
      labelLine: { show: true, length: 6, length2: 8 },
      data: props.data.map((item, i) => ({
        name: item.difficulty,
        value: item.count,
        itemStyle: { color: palette[i % palette.length] },
      })),
    },
  ],
})

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.data, refresh)
</script>
```

### Step 2: 构建 + Commit

Run:
```bash
cd frontend && npm run build
```

```bash
git add frontend/src/components/business/PracticeDifficultyChart.vue
git commit -m "feat(frontend): add practice difficulty donut chart"
```

---

## Task 10: 前端 — PracticeRadarChart（ECharts 雷达）

**Files:**
- Create: `frontend/src/components/business/PracticeRadarChart.vue`

### Step 1: 创建组件

```vue
<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div>
      <h3 class="text-sm font-semibold text-card-foreground">主题熟练度</h3>
      <p class="mt-0.5 text-xs text-muted-foreground">按主题的间隔复习熟练度</p>
    </div>
    <div v-if="props.data.length" ref="chartRef" class="mt-2 min-h-[240px] w-full flex-1" style="min-width: 0;" />
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      用闪卡复习后这里会生成熟练度雷达
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useEChart } from '@/composables/useEChart.js'

echarts.use([RadarChart, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const chartRef = ref(null)

function shortName(name) {
  return name.length > 6 ? `${name.slice(0, 6)}…` : name
}

const buildOption = (dark) => ({
  tooltip: {
    trigger: 'item',
    confine: true,
    backgroundColor: dark ? 'rgba(45, 42, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
    borderColor: dark ? '#574f49' : '#e8e4dd',
    textStyle: { color: dark ? '#e7e5e2' : '#4a4540', fontSize: 12 },
    formatter: (params) => `${params.name}: 熟练度 ${params.value}%`,
  },
  radar: {
    indicator: props.data.map((item) => ({ name: shortName(item.topic), max: 100 })),
    radius: '68%',
    center: ['50%', '55%'],
    axisName: { color: dark ? '#cfcac5' : '#4a4540', fontSize: 10 },
    splitLine: { lineStyle: { color: dark ? '#2e2a27' : '#f1efe9' } },
    splitArea: { areaStyle: { color: dark ? ['#1e1b19', '#221f1c'] : ['#faf9f7', '#f5f3ef'] } },
    axisLine: { lineStyle: { color: dark ? '#2e2a27' : '#f1efe9' } },
  },
  series: [
    {
      type: 'radar',
      data: [
        {
          name: '熟练度',
          value: props.data.map((item) => item.proficiency),
          areaStyle: { color: 'rgba(99, 102, 241, 0.25)' },
          lineStyle: { color: '#6366f1', width: 2 },
          itemStyle: { color: '#6366f1' },
          symbolSize: 4,
        },
      ],
    },
  ],
})

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.data, refresh)
</script>
```

### Step 2: 构建 + Commit

Run:
```bash
cd frontend && npm run build
```

```bash
git add frontend/src/components/business/PracticeRadarChart.vue
git commit -m "feat(frontend): add topic proficiency radar chart"
```

---

## Task 11: 前端 — PracticeRecentTimeline

**Files:**
- Create: `frontend/src/components/business/PracticeRecentTimeline.vue`

### Step 1: 创建组件

```vue
<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div>
      <h3 class="text-sm font-semibold text-card-foreground">最近刷题</h3>
      <p class="mt-0.5 text-xs text-muted-foreground">最近的答题与闪卡复习记录</p>
    </div>
    <div v-if="props.data.length" class="mt-3 flex-1 divide-y divide-border overflow-y-auto custom-scrollbar">
      <div v-for="item in props.data" :key="`${item.type}-${item.id}`" class="flex items-center gap-3 py-2.5">
        <Badge variant="secondary" class="w-11 shrink-0 justify-center">
          {{ item.type === 'answer' ? '答题' : '复习' }}
        </Badge>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm text-foreground">{{ item.question }}</p>
          <p class="mt-0.5 text-xs text-muted-foreground">
            {{ item.topic }} · {{ item.difficulty }} · {{ formatRelativeTime(item.created_at) }}
          </p>
        </div>
        <Badge v-if="item.type === 'answer'" :variant="scoreVariant(item.score)">
          {{ item.score }} 分
        </Badge>
        <Badge v-else :variant="ratingVariant(item.rating)">
          {{ ratingLabel(item.rating) }}
        </Badge>
      </div>
    </div>
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      还没有刷题记录，去刷一题吧
    </div>
  </div>
</template>

<script setup>
import { Badge } from '@/components/ui/badge'
import { formatRelativeTime } from '@/utils/time.js'

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const ratingLabels = { again: '忘了', hard: '困难', good: '不错', easy: '简单' }

function ratingLabel(rating) {
  return ratingLabels[rating] || rating || '复习'
}

function ratingVariant(rating) {
  if (rating === 'easy') return 'secondary'
  if (rating === 'good') return 'secondary'
  if (rating === 'hard') return 'outline'
  return 'destructive'
}

function scoreVariant(score) {
  return score >= 60 ? 'secondary' : 'destructive'
}
</script>
```

### Step 2: 构建 + Commit

Run:
```bash
cd frontend && npm run build
```

```bash
git add frontend/src/components/business/PracticeRecentTimeline.vue
git commit -m "feat(frontend): add recent practice timeline"
```

---

## Task 12: 前端 — 集成到洞察总览

**Files:**
- Modify: `frontend/src/views/InsightsView.vue`
- Modify: `frontend/src/components/business/InsightsOverview.vue`

### Step 1: InsightsView.vue 加载并透传

`frontend/src/views/InsightsView.vue` 的 `<script setup>` 部分改为：

```js
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Button } from '@/components/ui/button'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import InsightsOverview from '@/components/business/InsightsOverview.vue'
import InsightsReadiness from '@/components/business/InsightsReadiness.vue'
import InsightsReviews from '@/components/business/InsightsReviews.vue'
import { useInsightsData } from '@/composables/useInsightsData.js'

const route = useRoute()
const { snapshot, practiceActivity, isLoading, practiceLoading, error, loadInsights, loadPracticeActivity } = useInsightsData()
const reloading = ref(false)

const activeView = computed(() => {
  if (route.name === 'insights-readiness') return 'readiness'
  if (route.name === 'insights-reviews') return 'reviews'
  return 'overview'
})

onMounted(loadInsights)

watch(activeView, (view) => {
  if (view === 'overview' && practiceActivity.value === null) loadPracticeActivity()
}, { immediate: true })
```

模板部分（`<template>` 内第 41-43 行）改为：

```vue
    <template v-else-if="snapshot">
      <InsightsOverview
        v-if="activeView === 'overview'"
        :snapshot="snapshot"
        :practice-activity="practiceActivity"
        :practice-loading="practiceLoading"
      />
      <InsightsReadiness v-else-if="activeView === 'readiness'" :snapshot="snapshot" />
      <InsightsReviews v-else :snapshot="snapshot" />
    </template>
```

### Step 2: InsightsOverview.vue 新增图表区

script 部分：props 增加 `practiceActivity`、`practiceLoading`，import 6 个新组件：

```js
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, CircleAlert } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import AppLoading from '@/components/common/AppLoading.vue'
import PracticeHeatmap from './PracticeHeatmap.vue'
import PracticeStreakCard from './PracticeStreakCard.vue'
import PracticeTrendChart from './PracticeTrendChart.vue'
import PracticeDifficultyChart from './PracticeDifficultyChart.vue'
import PracticeRadarChart from './PracticeRadarChart.vue'
import PracticeRecentTimeline from './PracticeRecentTimeline.vue'

const props = defineProps({
  snapshot: { type: Object, required: true },
  practiceActivity: { type: Object, default: null },
  practiceLoading: { type: Boolean, default: false },
})
```

在 template 末尾（`</section>` 前）追加足迹区。在"本周最该做"Card 之后：

```vue
    <section v-if="practiceLoading" class="rounded-xl border border-border bg-card p-6 shadow-sm">
      <AppLoading type="skeleton" rows="4" />
    </section>

    <section v-else-if="!practiceActivity" class="rounded-xl border border-border bg-card p-6 shadow-sm">
      <div class="flex flex-col items-center gap-3 py-10 text-center">
        <p class="text-sm font-medium text-foreground">练习足迹暂不可用</p>
        <p class="max-w-md text-xs text-muted-foreground">刷新页面或稍后再试，开始刷题后这里会展示你的打卡热力图和进步趋势。</p>
      </div>
    </section>

    <section v-else class="flex flex-col gap-3">
      <div class="flex items-center justify-between gap-4">
        <div>
          <h2 class="text-lg font-semibold tracking-tight text-foreground">我的练习足迹</h2>
          <p class="mt-0.5 text-sm text-muted-foreground">坚持每天刷题，图表会见证你的成长。</p>
        </div>
        <Button variant="outline" size="sm" @click="goPractice">去刷题 <ArrowRight class="h-4 w-4" /></Button>
      </div>
      <div class="grid gap-3 xl:grid-cols-3">
        <div class="xl:col-span-2">
          <PracticeHeatmap :data="practiceActivity.heatmap || []" />
        </div>
        <PracticeStreakCard
          :streak="practiceActivity.streak || { current: 0, longest: 0 }"
          :today-count="todayCount"
        />
        <div class="xl:col-span-2">
          <PracticeTrendChart :data="practiceActivity.trend || []" />
        </div>
        <PracticeDifficultyChart :data="practiceActivity.difficulty || []" />
        <PracticeRadarChart :data="practiceActivity.radar || []" />
        <div class="xl:col-span-2">
          <PracticeRecentTimeline :data="practiceActivity.recent || []" />
        </div>
      </div>
    </section>
```

`<script setup>` 追加（注意原组件已有 `goPractice` 跳 mock-interview）：

```js
const todayCount = computed(() => {
  const heatmap = props.practiceActivity?.heatmap || []
  return heatmap[heatmap.length - 1]?.count || 0
})
```

### Step 3: 构建验证

Run:
```bash
cd frontend && npm run build
```
Expected: 成功

### Step 4: Commit

```bash
git add frontend/src/views/InsightsView.vue frontend/src/components/business/InsightsOverview.vue
git commit -m "feat(frontend): integrate practice footprint charts into insights overview"
```

---

## Task 13: 前端 — E2E 测试更新

**Files:**
- Modify: `frontend/tests/e2e/insights.spec.js`

### Step 1: mock practice-activity + 断言足迹区

在 `frontend/tests/e2e/insights.spec.js` 中：

1. 在 `insightsSnapshot` 后追加 mock 数据：

```js
const practiceActivity = {
  version: 1,
  heatmap: Array.from({ length: 90 }, (_, i) => ({
    date: `2026-05-${String((i % 28) + 1).padStart(2, '0')}`,
    count: i % 7 === 0 ? 3 : 0,
    avg_score: i % 7 === 0 ? 78 : 0,
  })),
  streak: { current: 3, longest: 5 },
  trend: Array.from({ length: 30 }, (_, i) => ({
    date: `2026-07-${String((i % 28) + 1).padStart(2, '0')}`,
    count: i % 3 === 0 ? 2 : 0,
    avg_score: i % 3 === 0 ? 80 : 0,
  })),
  radar: [{ topic: 'RAG系统设计', proficiency: 80 }],
  difficulty: [
    { difficulty: '简单', count: 6, correct_rate: 83 },
    { difficulty: '中等', count: 3, correct_rate: 67 },
  ],
  recent: [
    {
      id: 1,
      type: 'answer',
      question: 'RAG 的检索阶段如何减少幻觉？',
      difficulty: '中等',
      topic: 'RAG系统设计',
      score: 85,
      rating: null,
      created_at: '2026-08-05 09:30:00',
    },
  ],
}
```

2. 在 `mockInsightsApis` 中 `/api/insights` 分支后追加：

```js
    if (pathname === '/api/insights/practice-activity') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(practiceActivity) })
      return
    }
```

3. 在 `总览展示行动建议并可切换三个洞察 Tab` 测试中追加断言（`getByText('尚未形成个人能力分数')` 之后）：

```js
    await expect(page.getByRole('heading', { name: '我的练习足迹' })).toBeVisible()
    await expect(page.getByText('打卡热力图')).toBeVisible()
    await expect(page.getByText('连续 3 天')).toBeVisible()
    await expect(page.getByText('最近刷题')).toBeVisible()
```

### Step 2: 运行 E2E 验证

Run:
```bash
cd frontend && npx playwright test tests/e2e/insights.spec.js
```
Expected: PASS

### Step 3: Commit

```bash
git add frontend/tests/e2e/insights.spec.js
git commit -m "test(frontend): cover practice footprint section in insights e2e"
```

---

## Task 14: 全量验证 + 文档更新

**Files:**
- Modify: `backend/app/services/CLAUDE.md`、`frontend/CLAUDE.md`、`frontend/src/components/business/CLAUDE.md`、`frontend/src/composables/CLAUDE.md`、`frontend/src/services/CLAUDE.md`、`frontend/src/views/CLAUDE.md`、`frontend/src/utils/CLAUDE.md`（如存在）、根 `CLAUDE.md`

### Step 1: 后端全量回归

Run:
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/ -q
```
Expected: 全部 PASS

### Step 2: 前端全量验证

Run:
```bash
cd frontend && npm run build && npm run test
```
Expected: build 成功 + smoke 测试 PASS

### Step 3: 更新文档

- `backend/app/services/CLAUDE.md` 文件职责表：`insights.py` 行追加"练习足迹聚合（heatmap/streak/trend/radar/difficulty/recent）"
- `frontend/src/services/CLAUDE.md`：`insightsApi.js` 行追加 `/api/insights/practice-activity`
- `frontend/src/composables/CLAUDE.md`：新增 `useEChart.js` 行
- `frontend/src/components/business/CLAUDE.md`：新增 6 个 Practice* 组件行
- `frontend/src/views/CLAUDE.md`：`InsightsView.vue` 行描述更新
- 根 `CLAUDE.md` 代码路由表"洞察工作台"行：追加 practice-activity 端点与前端组件
- 若 `frontend/src/utils/CLAUDE.md` 存在，登记 `time.js`

### Step 4: Commit

```bash
git add -A
git commit -m "docs: update CLAUDE.md for practice footprint charts"
```

---

## Self-Review 记录

- **Spec 覆盖**：6 图表（热力图/Streak/趋势/雷达/难度/时间线）→ Task 1-2（后端数据）+ Task 6-11（前端组件）+ Task 12（集成）。空态与激励文案：热力图/Streak/时间线组件内置。E2E 回归：Task 13。
- **类型一致性**：`build_practice_activity` 返回键名 heatmap/streak/trend/radar/difficulty/recent 在 Task 1 契约、Task 3 前端、Task 13 mock 中一致；`avg_score` 为 0 时前端趋势图用 `null` 断连（Task 8 `|| null` 处理）。
- **风险**：`practice_review_events` FK 需要先插 `user_question_review`（Task 1 helper 已处理）；趋势图分数为 0 的天显示 null 点而非 0 分（避免误导），heatmap 用 count 不显示 avg_score 文案当它为 0。
