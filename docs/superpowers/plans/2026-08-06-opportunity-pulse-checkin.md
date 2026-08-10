# 机会脉冲 + 已掌握题抽查 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将紧迫度改为机会脉冲模型（无 DDL、届次时间线自动流转、用户节奏档位），并上线已掌握题 30 天循环抽查（前后端配套）。

**Architecture:** 后端 `recruitment_milestones.py` 重写为 `OpportunityWindow`（全年 4 窗口）+ `compute_urgency(windows, today, pace)`（base 0.2 + 脉冲叠加 + 节奏偏移）；`practice_scheduler.py` 删 deadline 参数、加 mastered 30 天抽查分支；`practice_deck_service.py` 队列改三桶（due 复习 → 抽查 → 新题）+ `is_checkin` 标记 + `max_new` 后端自动预算；migration 063 加 `pace` 字段（batch 降级为展示标签）。前端状态行改"当前窗口+下一窗口"、设置页加节奏档位、抽查题卡"保持手感"徽标。

**Tech Stack:** Python 3.10 / FastAPI / SQLite / Vue 3。测试必须走 Docker test-runtime。

**设计依据：** `docs/analysis/2026-08-06-today-review-scheduler-decisions.md`（决策+实验）、`docs/superpowers/specs/2026-08-06-today-review-opportunity-pulse-design.md`（本计划按此展开）

**关键参数（实验定稿，勿改）：**
- base=0.2 / AMP=0.6 / 窗口半宽=45 天
- 窗口权重：暑期实习 0.67(3-15) / 提前批 0.50(8-15) / 秋招正式批 1.00(10-15) / 春招主批 0.83(4-15)，届次 N → N-1 年 3月 ~ N 年 4月
- 节奏偏移：easy −0.3 / standard 0 / hard +0.3
- 抽查：mastered + 非 again → 固定 30 天重置；again → 走既有降级（0.02 天 + proficiency-1）
- 容量分配：新题预算 = max(0, 容量 − due复习 − 抽查)

---

## Task 1: 机会窗口模块重写

**Files:**
- Modify: `backend/app/services/recruitment_milestones.py`（重写）
- Modify: `backend/tests/services/test_recruitment_milestones.py`（重写）

- [ ] **Step 1: 写失败测试**（重写测试文件，替换现有全部用例）

```python
from datetime import date

import pytest

from app.services.recruitment_milestones import (
    OpportunityWindow,
    PACE_OFFSETS,
    compute_urgency,
    get_season_windows,
)

def test_season_windows_for_2027_span_two_years():
    windows = get_season_windows(2027)
    assert [w.name for w in windows] == ["暑期实习", "提前批", "秋招正式批", "春招主批"]
    assert windows[0].peak == date(2026, 3, 15)
    assert windows[1].peak == date(2026, 8, 15)
    assert windows[2].peak == date(2026, 10, 15)
    assert windows[3].peak == date(2027, 4, 15)
    assert windows[2].weight == 1.0  # 秋招正式批权重最高

def test_weights():
    windows = get_season_windows(2027)
    assert [round(w.weight, 2) for w in windows] == [0.67, 0.5, 1.0, 0.83]

def test_urgency_at_peak_within_window():
    windows = get_season_windows(2027)
    result = compute_urgency(windows, date(2026, 10, 15), "standard")
    # 0.2 + 1.0*0.6 = 0.8（提前批窗口尾段 8-15+45=9-29 不重叠）
    assert result["urgency"] == pytest.approx(0.8, abs=0.001)

def test_urgency_base_floor_outside_windows():
    windows = get_season_windows(2027)
    result = compute_urgency(windows, date(2027, 1, 15), "standard")
    assert result["urgency"] == pytest.approx(0.2, abs=0.001)  # 间歇期 = base

def test_urgency_ramp_toward_peak():
    windows = get_season_windows(2027)
    early = compute_urgency(windows, date(2026, 9, 1), "standard")["urgency"]
    late = compute_urgency(windows, date(2026, 10, 1), "standard")["urgency"]
    assert late > early  # 越接近高峰越紧

def test_pace_offsets():
    windows = get_season_windows(2027)
    peak = date(2026, 10, 15)
    easy = compute_urgency(windows, peak, "easy")["urgency"]
    standard = compute_urgency(windows, peak, "standard")["urgency"]
    hard = compute_urgency(windows, peak, "hard")["urgency"]
    assert easy < standard < hard
    assert easy == pytest.approx(0.5, abs=0.001)
    assert hard == pytest.approx(1.0, abs=0.001)  # clamp

def test_no_windows_means_base_only():
    result = compute_urgency([], date(2026, 8, 5), "standard")
    assert result["urgency"] == pytest.approx(0.2)
    assert result["current_window"] is None
    assert result["next_window"] is None

def test_current_and_next_window():
    windows = get_season_windows(2027)
    result = compute_urgency(windows, date(2026, 8, 5), "standard")
    assert result["current_window"]["name"] == "提前批"
    assert result["next_window"]["name"] == "秋招正式批"
    assert result["next_window"]["days_left"] == 71

def test_current_window_picks_highest_weight_when_overlap():
    # 暑期实习(3-15, 45天窗=2-30~4-29) 与春招主批(4-15, 45天窗=3-1~5-30) 在 3-1~4-29 重叠
    windows = get_season_windows(2027)
    result = compute_urgency(windows, date(2027, 4, 1), "standard")
    assert result["current_window"]["name"] == "春招主批"  # 权重 0.83 > 0.67

def test_all_windows_past_degrades_to_base():
    windows = get_season_windows(2027)
    result = compute_urgency(windows, date(2027, 7, 15), "standard")
    assert result["urgency"] == pytest.approx(0.2)
    assert result["current_window"] is None

def test_pace_validation():
    windows = get_season_windows(2027)
    with pytest.raises(ValueError):
        compute_urgency(windows, date(2026, 8, 5), "unknown_pace")

def test_pace_offsets_mapping():
    assert PACE_OFFSETS == {"easy": -0.3, "standard": 0.0, "hard": 0.3}
```

- [ ] **Step 2: 运行确认失败** — `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_recruitment_milestones.py -q`（ImportError: OpportunityWindow）

- [ ] **Step 3: 重写实现**（替换 `recruitment_milestones.py` 全部内容）

```python
"""Recruitment opportunity windows and urgency computation.

Opportunity-pulse model (no hard deadlines): urgency is a continuous 0..1
scalar = base (always-on: social recruitment / daily internships) plus
triangular pulses around each recruitment window's peak.  Windows are
generated from the graduation year (届次 N = N 年毕业), following the
recurring campus calendar: summer internship spring of N-1, early batch
and autumn formal batch in Jul-Dec of N-1, spring batch in Feb-Jun of N.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Pace = Literal["easy", "standard", "hard"]
VALID_PACES = ("easy", "standard", "hard")
PACE_OFFSETS = {"easy": -0.3, "standard": 0.0, "hard": 0.3}

BASE_URGENCY = 0.2      # 社招/日常实习随时可能面试，复习永不停
AMP = 0.6               # 全局振幅系数（实验定稿）
HALF_WIDTH_DAYS = 45    # 窗口脉冲半宽（高峰前 45 天爬升、后 45 天衰减）


@dataclass(frozen=True)
class OpportunityWindow:
    name: str
    peak: date
    weight: float


def get_season_windows(graduation_year: int) -> list[OpportunityWindow]:
    """Return the four opportunity windows for a graduation year (届次)."""
    year = int(graduation_year)
    prev = year - 1
    return [
        OpportunityWindow("暑期实习", date(prev, 3, 15), 0.67),
        OpportunityWindow("提前批", date(prev, 8, 15), 0.50),
        OpportunityWindow("秋招正式批", date(prev, 10, 15), 1.00),
        OpportunityWindow("春招主批", date(year, 4, 15), 0.83),
    ]


def _pulse(window: OpportunityWindow, today: date) -> float:
    days = (today - window.peak).days
    if abs(days) > HALF_WIDTH_DAYS:
        return 0.0
    factor = 1.0 - abs(days) / HALF_WIDTH_DAYS
    return window.weight * AMP * factor


def compute_urgency(
    windows: list[OpportunityWindow],
    today: date,
    pace: str = "standard",
) -> dict:
    """Map today to an urgency scalar with window context.

    Returns {urgency, current_window, next_window}.  ``current_window``
    is the window with a non-zero pulse (highest weight wins on overlap);
    ``next_window`` is the first future window (peak > today) with its
    days_left.  Unknown pace raises ValueError.
    """
    if pace not in VALID_PACES:
        raise ValueError(f"pace must be one of {VALID_PACES}")
    urgency = BASE_URGENCY + sum(_pulse(w, today) for w in windows)
    urgency += PACE_OFFSETS[pace]
    urgency = max(0.0, min(1.0, urgency))
    pulsing = [w for w in windows if _pulse(w, today) > 0.0]
    current = max(pulsing, key=lambda w: (w.weight, w.peak)) if pulsing else None
    future = [w for w in windows if w.peak > today]
    nxt = min(future, key=lambda w: w.peak) if future else None
    return {
        "urgency": round(urgency, 4),
        "current_window": (
            {"name": current.name, "peak": current.peak.isoformat(), "weight": current.weight}
            if current else None
        ),
        "next_window": (
            {
                "name": nxt.name,
                "peak": nxt.peak.isoformat(),
                "days_left": (nxt.peak - today).days,
            }
            if nxt else None
        ),
    }
```

- [ ] **Step 4: 确认通过** — 同上命令，11 passed
- [ ] **Step 5: 更新 CLAUDE.md + Commit**

```bash
git add backend/app/services/recruitment_milestones.py backend/tests/services/test_recruitment_milestones.py backend/app/services/CLAUDE.md
git commit -m "feat(backend): opportunity-pulse urgency with season windows and pace"
```

---

## Task 2: 调度器删 deadline + mastered 30 天抽查

**Files:**
- Modify: `backend/app/services/practice_scheduler.py`
- Modify: `backend/tests/services/test_practice_scheduler.py`

- [ ] **Step 1: 写失败测试**（删 6 个 deadline 用例，新增 mastered 用例）

```python
def test_mastered_good_resets_to_30_days():
    mastered = ReviewState(state="mastered", proficiency=5, review_count=8,
                           interval_days=200.0, ease_factor=2.6)
    result = schedule_review(mastered, "good", now=BASE_TIME)
    assert result.next_review_at == BASE_TIME + timedelta(days=30)
    assert result.state == "mastered"
    assert result.proficiency == 5
    assert result.interval_days == 30.0

def test_mastered_easy_resets_to_30_days_and_clamps_proficiency():
    mastered = ReviewState(state="mastered", proficiency=5, review_count=8,
                           interval_days=200.0, ease_factor=2.6)
    result = schedule_review(mastered, "easy", now=BASE_TIME)
    assert result.next_review_at == BASE_TIME + timedelta(days=30)
    assert result.proficiency == 5  # clamp
    assert result.state == "mastered"

def test_mastered_again_falls_back_to_relearning():
    mastered = ReviewState(state="mastered", proficiency=5, review_count=8,
                           interval_days=200.0, ease_factor=2.6)
    result = schedule_review(mastered, "again", now=BASE_TIME)
    assert result.state == "relearning"
    assert result.proficiency == 4
    assert result.next_review_at == BASE_TIME + timedelta(minutes=28.8)

def test_mastered_30_days_not_scaled_by_urgency():
    mastered = ReviewState(state="mastered", proficiency=5, review_count=8,
                           interval_days=200.0, ease_factor=2.6)
    result = schedule_review(mastered, "good", now=BASE_TIME, urgency=1.0)
    assert result.next_review_at == BASE_TIME + timedelta(days=30)  # 抽查恒定 30 天

def test_non_mastered_behavior_unchanged_without_deadline():
    result = schedule_review(ReviewState(), "good", now=BASE_TIME, urgency=0.0)
    assert result.next_review_at == BASE_TIME + timedelta(days=3)
```

（同时删除/改写现有 deadline 相关 5 个用例：test_interval_beyond_deadline_is_pulled_back、test_interval_within_deadline_untouched、test_again_relearning_step_ignores_deadline、test_deadline_today_never_schedules_in_the_past 及 deadline 提及）

- [ ] **Step 2: 确认失败** — `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_scheduler.py -q`（mastered 用例失败/TypeError）
- [ ] **Step 3: 实现**

```python
def schedule_review(
    current: ReviewState,
    rating: str,
    *,
    now: datetime | None = None,
    urgency: float = 0.0,
) -> ScheduledReview:
    """...docstring 更新：移除 deadline 描述，增加 mastered 30 天抽查说明..."""
```

在 `if rating == "again":` 分支之前插入：

```python
    if current.state == "mastered" and rating != "again":
        # 已掌握题 30 天循环抽查（实验定稿：固定 30 天，不受 urgency 缩放）
        interval_days = 30.0
        proficiency = min(5, proficiency + {"hard": 0, "good": 1, "easy": 2}[rating])
        next_review_at = now + timedelta(days=30)
        return ScheduledReview(
            state="mastered",
            proficiency=proficiency,
            review_count=review_count,
            lapse_count=lapse_count,
            interval_days=30.0,
            ease_factor=round(ease_factor, 4),
            next_review_at=next_review_at,
            last_rating=rating,
        )
```

删除 deadline 参数、`deadline` 压缩块（109-123 行区域）及 `pulled_back` 逻辑；保留 urgency 缩放（`if rating != "again": interval_days *= 1 - 0.4*urgency`）。

- [ ] **Step 4: 确认通过** — 上述命令全绿（原 11 个减 4 个 deadline + 新 5 个 = 12 个左右）
- [ ] **Step 5: Commit**

```bash
git add backend/app/services/practice_scheduler.py backend/tests/services/test_practice_scheduler.py
git commit -m "feat(backend): 30-day check-in for mastered cards, drop deadline capping"
```

---

## Task 3: migration 063 pace 字段

**Files:**
- Modify: `backend/app/db/migrations/recruitment.py`
- Modify: `backend/app/db/migrations/__init__.py`
- Modify: `backend/tests/services/test_recruitment_pref_table.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
def test_pace_column_exists(test_db):
    with get_db_connection() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(user_recruitment_pref)").fetchall()]
    assert "pace" in cols
```

- [ ] **Step 2: 确认失败** — 预期 FAIL（no such column: pace）
- [ ] **Step 3: 实现** — migration 重命名/新增 `_migration_063_user_recruitment_pace`：

```python
def migrate(conn):
    conn.execute(
        "ALTER TABLE user_recruitment_pref ADD COLUMN pace TEXT NOT NULL DEFAULT 'standard'"
    )
```

（063 版本；若 063 已被并行工作占用则取下一可用版本号，并在报告说明。原 recruitment.py 的 CREATE TABLE 保留旧列定义，pace 由 ALTER 添加——若 create 表时直接加列会导致已存在库缺列，必须走 ALTER。同时把 CREATE TABLE 的 IF NOT EXISTS 建表语句加上 pace 列（新库一次到位），ALTER 用 try/except 兼容已建表。）

- [ ] **Step 4: 确认通过** — 3 passed
- [ ] **Step 5: Commit**

```bash
git add backend/app/db/migrations/recruitment.py backend/app/db/migrations/__init__.py backend/tests/services/test_recruitment_pref_table.py
git commit -m "feat(backend): add pace column to recruitment preference"
```

---

## Task 4: profile API（pace + windows 契约）

**Files:**
- Modify: `backend/app/routers/profile.py`
- Modify: `backend/tests/services/test_recruitment_pref_api.py`

- [ ] **Step 1: 写失败测试**（更新现有 + 新增）

```python
def test_get_recruitment_pref_returns_windows_and_pace(client):
    token = _make_user(client)   # 复用现有 helper
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, pace) "
            "VALUES (?, 2027, 'autumn', 30, 'hard')",
            (USER_ID,),   # 与现有测试同款用户 id 获取方式
        )
        conn.commit()
    resp = client.get("/api/profile/recruitment", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["pace"] == "hard"
    assert len(data["windows"]) == 4
    assert data["windows"][0]["name"] == "暑期实习"
    assert "current_window" in data
    assert "next_window" in data

def test_put_recruitment_pref_rejects_bad_pace(client):
    token = _make_user(client)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": 2027, "batch": "autumn", "daily_capacity": 30, "pace": "insane"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400

def test_put_recruitment_pref_saves_pace(client):
    token = _make_user(client)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": 2027, "batch": "autumn", "daily_capacity": 30, "pace": "easy"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    get_resp = client.get("/api/profile/recruitment", headers={"Authorization": f"Bearer {token}"})
    assert get_resp.json()["pace"] == "easy"
```

（现有 test_get_recruitment_pref_returns_urgency 断言 milestones 的改为 windows；无偏好时 windows=[]、urgency=0.2、current/next 为 None）

- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 实现** — `profile.py`：

```python
from app.services.recruitment_milestones import (
    VALID_PACES,
    compute_urgency,
    get_season_windows,
)


def _recruitment_pref_payload(user_id: int) -> dict:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT graduation_year, batch, daily_capacity, pace FROM user_recruitment_pref WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    pref = dict(row) if row else {}
    year = int(pref.get("graduation_year") or 0)
    windows = get_season_windows(year) if year else []
    urgency_info = compute_urgency(windows, date_cls.today(), str(pref.get("pace") or "standard"))
    return {
        "graduation_year": year or None,
        "batch": str(pref.get("batch") or ""),
        "daily_capacity": int(pref.get("daily_capacity") or 30),
        "pace": str(pref.get("pace") or "standard"),
        "windows": [
            {"name": w.name, "peak": w.peak.isoformat(), "weight": w.weight}
            for w in windows
        ],
        **urgency_info,
    }
```

PUT：pace 校验（VALID_PACES）；INSERT/UPDATE 语句加 pace 列；响应返回 `_recruitment_pref_payload`。

- [ ] **Step 4: 确认通过 + 回归** — `pytest backend/tests/services/test_recruitment_pref_api.py backend/tests/security/ -q`
- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/profile.py backend/tests/services/test_recruitment_pref_api.py backend/app/routers/CLAUDE.md
git commit -m "feat(backend): expose pace and season windows in recruitment pref API"
```

---

## Task 5: 队列三桶排序 + is_checkin + 自动新题预算

**Files:**
- Modify: `backend/app/services/practice_deck_service.py`
- Modify: `backend/tests/services/test_practice_due_queue.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
def _seed_mastered(conn):
    # Q1 到期复习（非 mastered）、Q2 mastered 到期（抽查）、Q3 从未复习（新题）
    conn.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
        "interval_days, ease_factor, next_review_at, updated_at) "
        "VALUES (1, 1, 'review', 2, 3, 5.0, 2.3, datetime('now', '-2 days'), CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
        "interval_days, ease_factor, next_review_at, updated_at) "
        "VALUES (1, 2, 'mastered', 5, 9, 30.0, 2.6, datetime('now', '-1 days'), CURRENT_TIMESTAMP)"
    )
    conn.commit()


def test_due_queue_orders_review_checkin_new(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        _seed_mastered(conn)
        _, items, total = list_deck_questions(conn, 1, "due")
    # 到期复习(1) → 抽查(2) → 新题(3)
    assert [i["id"] for i in items] == [1, 2, 3]
    assert items[1]["is_checkin"] is True
    assert items[0]["is_checkin"] is False


def test_due_queue_checkin_after_future_review(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        conn.execute(
            "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
            "interval_days, ease_factor, next_review_at, updated_at) "
            "VALUES (1, 1, 'mastered', 5, 9, 30.0, 2.6, datetime('now', '+5 days'), CURRENT_TIMESTAMP)"
        )
        conn.commit()
        _, items, _ = list_deck_questions(conn, 1, "due")
    # mastered 但未来到期 → 不属抽查桶 → 排在最后
    assert items[-1]["id"] == 1


def test_due_queue_auto_new_budget_from_capacity(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        _seed_mastered(conn)
        conn.execute(
            "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, pace) "
            "VALUES (1, 2027, 'autumn', 3, 'standard')"
        )
        conn.commit()
        _, items, _ = list_deck_questions(conn, 1, "due")
    # 容量 3：due 1 + 抽查 1 = 2 已占 → 新题预算 1（Q3 高频先入）
    assert [i["id"] for i in items] == [1, 2, 3]
    # 容量 1：due 1 + 抽查 1 = 2 已占 → 新题预算 0
    with get_db_connection() as conn:
        conn.execute("UPDATE user_recruitment_pref SET daily_capacity = 1 WHERE user_id = 1")
        conn.commit()
        _, items, _ = list_deck_questions(conn, 1, "due")
    assert [i["id"] for i in items] == [1, 2]
```

- [ ] **Step 2: 确认失败**（排序断言失败）
- [ ] **Step 3: 实现** — `list_deck_questions`：

1. 排序改为三桶：

```sql
ORDER BY CASE WHEN uqr.next_review_at IS NULL THEN 2
     WHEN uqr.state = 'mastered' AND datetime(uqr.next_review_at) <= datetime('now') THEN 1
     WHEN datetime(uqr.next_review_at) <= datetime('now') THEN 0
     ELSE 3 END,
     -- 抽查桶内 frequency DESC；新题桶内 frequency DESC（用现有 risk/static 表达式）
```

2. `_normalise_question` 增加：`item["is_checkin"] = item.get("review_state") == "mastered"`（review_state 已存在）
3. `max_new` 自动预算：因 max_new 语义改为"容量−due−抽查"，需在函数内读 `user_recruitment_pref.daily_capacity`。注意：现有 max_new 参数（Task 6 阶段）由前端传——本任务改为**后端读取容量**。签名保持 `max_new: int | None = None`（None → 自动），前端不传时自动生效：

```python
    if deck_key == "due" and offset == 0:
        if max_new is None:
            with conn:
                row = conn.execute(
                    "SELECT daily_capacity FROM user_recruitment_pref WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            capacity = int(row["daily_capacity"] if row and row["daily_capacity"] else 30)
            # 到期复习 + 抽查计数
            due_count = conn.execute(
                _select_sql(from_clause, where_clause, frequency_sql)  # 原条件不含新题？需单独计数
            )
```

**注意实现细节**：现有 where_clause 的 due 条件同时含新题（NULL 也命中）。分区逻辑需要：
- due_review 条件：`next_review_at IS NOT NULL AND <= now AND state != 'mastered'`
- checkin 条件：`state = 'mastered' AND next_review_at IS NOT NULL AND <= now`
- new 条件：`next_review_at IS NULL`，LIMIT = max(0, capacity − len(due_review) − len(checkin))
- 三种分区分别查询拼接（保持既有 replace 模式，但三个分区字符串都要精确匹配现有 where 文本——先跑测试确认）

- [ ] **Step 4: 确认通过 + 回归** — `pytest backend/tests/services/test_practice_due_queue.py backend/tests/services/test_practice_api.py -q`
- [ ] **Step 5: Commit**

```bash
git add backend/app/services/practice_deck_service.py backend/tests/services/test_practice_due_queue.py backend/app/services/CLAUDE.md
git commit -m "feat(backend): three-bucket due queue with mastered check-in and auto new budget"
```

---

## Task 6: review 端点接线（删 deadline 链 + mastered 透传）

**Files:**
- Modify: `backend/app/services/practice_review_service.py`
- Modify: `backend/app/routers/practice.py`
- Modify: `backend/tests/services/test_review_urgency_wiring.py`

- [ ] **Step 1: 写失败测试**（更新）

```python
def test_review_mastered_card_resets_to_30_days(client):
    token, user_id = _make_user(client)
    with get_db_connection() as conn:
        _seed(conn)
        conn.execute(
            "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
            "interval_days, ease_factor, next_review_at, updated_at) "
            "VALUES (?, 1, 'mastered', 5, 9, 30.0, 2.6, datetime('now', '-1 days'), CURRENT_TIMESTAMP)",
            (user_id,),
        )
        conn.commit()
    resp = client.post(
        "/api/practice/review",
        json={"question_id": 1, "rating": "good", "score": 80},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    review = resp.json()["review"]
    assert review["state"] == "mastered"
    assert review["interval_days"] == 30.0
```

（test_review_urgency_wiring 中 deadline 相关断言删除/改写；_user_urgency 签名改回只算 urgency）

- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 实现**

1. `practice_review_service.py.record_review`：删 `deadline` 参数，`schedule_review(..., urgency=urgency)`（不再传 deadline）；state_from_row 已含 state → mastered 分支自然生效
2. `routers/practice.py`：`_user_urgency` 改为 `_user_urgency(user_id)` 只返回 float urgency（读 graduation_year + pace → get_season_windows + compute_urgency）；两处调用（review + evaluate-answer）更新；删除 deadline 相关 import/代码

- [ ] **Step 4: 确认通过 + 全量 services 回归** — `pytest backend/tests/services/ -q`
- [ ] **Step 5: Commit**

```bash
git add backend/app/services/practice_review_service.py backend/app/routers/practice.py backend/tests/services/ backend/app/routers/CLAUDE.md backend/app/services/CLAUDE.md
git commit -m "feat(backend): wire mastered check-in through review endpoints"
```

---

## Task 7: 后端全量回归

- [ ] **Step 1:** `docker compose --profile test run --rm test uv run pytest backend/tests/ -q` — 确认无新失败（已知 pre-existing 除外）
- [ ] **Step 2:** `./deploy/docker-deploy.sh check backend` — Blocking checks 全 PASS
- [ ] **Step 3:** 无代码改动则跳过 commit；有修复则 `git add` + commit

---

## Task 8: 前端状态行 + 设置页节奏档位 + 徽标

**Files:**
- Modify: `frontend/src/views/PracticeView.vue`
- Modify: `frontend/src/components/business/SettingsInterview.vue`
- Modify: `frontend/src/components/business/PracticeMode.vue`
- Modify: `frontend/src/services/profileApi.js`（如无改动则跳过）

- [ ] **Step 1: 状态行重构**（PracticeView.vue）——替换现有 recruitment-status 区块：

```vue
<div v-if="recruitmentStatus.batch || recruitmentStatus.graduation_year" data-testid="recruitment-status" class="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-border bg-card px-4 py-2 text-xs text-muted-foreground">
  <CalendarClock class="size-3.5" />
  <template v-if="recruitmentStatus.current_window">
    <span class="font-medium text-foreground">{{ recruitmentStatus.current_window.name }}窗口 · 冲刺中</span>
    <Badge variant="secondary" class="text-[10px]">{{ stageLabel }}</Badge>
  </template>
  <span v-else-if="recruitmentStatus.next_window">
    距{{ recruitmentStatus.next_window.name }}高峰还有 {{ recruitmentStatus.next_window.days_left }} 天
  </span>
  <span v-else>持续准备中</span>
  <span class="ml-auto">{{ batchLabel }} · 容量 {{ recruitmentStatus.daily_capacity }} 题{{ paceLabel }}</span>
</div>
```

Script 更新：`recruitmentStatus` 初始 `{ batch: '', graduation_year: null, daily_capacity: 30, pace: 'standard', current_window: null, next_window: null, windows: [], urgency: 0 }`；`stageLabel` computed 用 urgency（≥0.7 攻坚中 / ≥0.3 冲刺中 / >0 准备中 / else 从容复习）；`paceLabel`：easy → '· 轻松'、hard → '· 冲刺'、standard → ''；`batchLabel` 沿用。

- [ ] **Step 2: 设置页节奏档位**（SettingsInterview.vue）——批次 Select 下方加节奏 3 档单选（用现有 RadioGroup 或 segmented 风格，参照文件现有组件）：

```vue
<div>
  <Label class="mb-1.5 block text-xs font-semibold text-muted-foreground">复习节奏</Label>
  <div class="flex gap-2">
    <button v-for="opt in paceOptions" :key="opt.value" type="button"
      :class="['h-8 flex-1 rounded-md border px-2 text-xs transition-colors',
               pref.pace === opt.value ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:bg-muted']"
      :data-testid="`pace-${opt.value}`" @click="pref.pace = opt.value">
      {{ opt.label }}
    </button>
  </div>
  <p class="mt-1 text-xs text-muted-foreground">轻松会降低复习强度，冲刺会加密复习间隔</p>
</div>
```

Script：`paceOptions = [{value:'easy',label:'轻松'},{value:'standard',label:'标准'},{value:'hard',label:'冲刺'}]`；onMounted 读 `data.pace || 'standard'`；savePref payload 加 `pace`；时间线预览改为 `data.windows`（name + peak + 距今天数），移除 milestones 引用；提示文案更新"将按招聘季窗口自动安排每日复习量和新题比例"。

- [ ] **Step 3: 徽标**（PracticeMode.vue）——题卡顶部（题目文本前）加：

```vue
<Badge v-if="currentQ?.is_checkin" variant="outline" class="mr-1.5 text-[10px] text-muted-foreground">保持手感</Badge>
```

（确认 `currentQ` 已有 is_checkin 透传：questions 来自后端 item，`_normalise_question` 已加 is_checkin → 自动可用）

- [ ] **Step 4: 构建验证** — `cd frontend && npm run build`
- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/PracticeView.vue frontend/src/components/business/SettingsInterview.vue frontend/src/components/business/PracticeMode.vue
git commit -m "feat(frontend): season window status bar, pace selector, check-in badge"
```

---

## Task 9: 前端测试更新

**Files:**
- Modify: `frontend/tests/e2e/today-review.spec.js`
- Modify: `frontend/tests/e2e/practice-flow.spec.js`（如受状态行影响）

- [ ] **Step 1: 更新 mock**——`/api/profile/recruitment` 响应改为新契约：

```js
{ graduation_year: 2027, batch: 'autumn', daily_capacity: 30, pace: 'standard',
  urgency: 0.43, windows: [{name:'暑期实习',peak:'2026-03-15',weight:0.67}, ...4个],
  current_window: {name:'提前批',peak:'2026-08-15',weight:0.5},
  next_window: {name:'秋招正式批',peak:'2026-10-15',days_left:71} }
```

- [ ] **Step 2: 状态行断言更新**——原"距提前批窗口关闭还有 26 天"改为 `提前批窗口 · 冲刺中` + 徽标；无偏好时（batch:'' → 新增 graduation_year: null）隐藏逻辑确认
- [ ] **Step 3: 新增抽查场景**——mock due questions 含一条 `state:'mastered'` 的题（is_checkin: true）→ 断言「保持手感」徽标出现；复习后（mock review 返回 interval_days 30）断言仍显示（30 天后才消失）
- [ ] **Step 4: 设置页节奏**——mock recruitment API，选「冲刺」保存 → 断言 PUT payload 含 pace:'hard'
- [ ] **Step 5: 运行** — `cd frontend && npx playwright test tests/e2e/today-review.spec.js tests/e2e/practice-flow.spec.js` 全绿；`npm run test`（smoke）绿
- [ ] **Step 6: Commit**

```bash
git add frontend/tests/
git commit -m "test(frontend): cover season window status bar and mastered check-in"
```

---

## Task 10: 文档收尾

- [ ] **Step 1:** 根 `CLAUDE.md` 路由表 practice 行更新（recruitment_milestones 描述 → 机会窗口/抽查）；Gotchas 补 pace/抽查
- [ ] **Step 2:** `backend/app/services/CLAUDE.md` + `backend/app/routers/CLAUDE.md` + `frontend/CLAUDE.md` 同步（windows 契约、pace、抽查、状态行新文案）
- [ ] **Step 3:** 决策报告附录更新（实施结果 vs 预期）
- [ ] **Step 4:** `./deploy/docker-deploy.sh check` 全绿（backend + frontend）
- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md frontend/CLAUDE.md backend/app/services/CLAUDE.md backend/app/routers/CLAUDE.md docs/analysis/2026-08-06-today-review-scheduler-decisions.md
git commit -m "docs: sync docs for opportunity-pulse scheduler and check-in"
```

---

## Self-Review 结论

**Spec 覆盖**：窗口生成/紧迫度/pace → T1 ✓；scheduler 删 deadline + mastered 30 天 → T2 ✓；pace 列 → T3 ✓；API 契约 → T4 ✓；三桶队列/is_checkin/自动预算 → T5 ✓；端点接线 → T6 ✓；前端三处 + 测试 → T8/T9 ✓；文档 → T10 ✓。

**耦合风险**：
- T1 改签名 → T4/T6 必须同步（计划内已列）
- T2 删 deadline → T6 删 _user_urgency deadline 链
- T5 三桶分区依赖现有 where 文本 replace——测试先行暴露
- T8 状态行文案 → T9 断言同步更新
- migration 版本号与并行工作冲突——实施时取下一可用号并说明
