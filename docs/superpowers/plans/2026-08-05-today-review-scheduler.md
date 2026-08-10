# 今日复习 + 招聘季里程碑调度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以"今日复习"为刷题唯一主入口，用招聘季里程碑（届次+批次）驱动的紧迫度 + 频率权重调制每日复习队列，并删除独立"题目抽测"页面。

**Architecture:** 后端新增 `recruitment_milestones.py`（纯函数：届次+批次 → 里程碑 → 紧迫度），`practice_scheduler.py` 增加 urgency/deadline 调制层（SM-2-lite 行为在 urgency=0 时完全不变），`practice_deck_service.py` 暴露 `due` 系统题单并升级排序（复习优先 + 频率×遗忘度风险加权 + 新题容量预算）。用户偏好存新表 `user_recruitment_pref`。前端删除 `/mock-interview`，设置页（SettingsInterview）新增"面试时间偏好"，刷题页默认进入"今日复习"队列并展示距里程碑状态行。

**Tech Stack:** Python 3.10 / FastAPI / SQLite / Vue 3 / shadcn-vue。测试必须通过 Docker test-runtime：`docker compose --profile test run --rm test uv run pytest backend/tests/services/ -q`

**关键设计决策（多轮调研结论）：**
1. 紧迫度 = 距下一个里程碑的连续天数映射（0~1），不用"当前属于哪个阶段"的离散标签；日常实习无里程碑 → 紧迫度恒 0
2. 招聘季时间窗按届程序化生成（N 届秋招 = N-1 年 7-12 月等），不手写每届
3. 频率不压间隔，只管排序：新题引入优先级 + 到期队列内 `frequency × (5 - proficiency)` 风险加权
4. 复习不设上限（Anki 共识），容量只影响新题预算：`新题预算 = max(0, 每日容量 − 到期复习数)`
5. 里程碑前复习保证：`next_review_at` 越过下一个 window_close 里程碑 → 压缩到窗口内

---

## Phase A — 后端算法与 API

### Task 1: 招聘季里程碑模块（纯函数）

**Files:**
- Create: `backend/app/services/recruitment_milestones.py`
- Test: `backend/tests/services/test_recruitment_milestones.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import date

import pytest

from app.services.recruitment_milestones import (
    BATCH_LABELS,
    get_milestones,
    Milestone,
)

def test_autumn_2027_uses_previous_year_window():
    ms = get_milestones(2027, "autumn")
    assert [m.date.year for m in ms] == [2026, 2026, 2026]
    names = [m.name for m in ms]
    assert names == ["提前批窗口关闭", "正式批高峰", "补录收尾"]

def test_spring_2027_uses_graduation_year_window():
    ms = get_milestones(2027, "spring")
    assert [m.date.year for m in ms] == [2027, 2027]

def test_summer_intern_2027_uses_previous_year_window():
    ms = get_milestones(2027, "summer_intern")
    assert [m.date.year for m in ms] == [2026, 2026, 2026]

def test_daily_intern_has_no_milestones():
    assert get_milestones(2027, "daily") == []

def test_invalid_batch_rejected():
    with pytest.raises(ValueError):
        get_milestones(2027, "unknown_batch")

def test_milestone_shape():
    ms = get_milestones(2027, "autumn")
    m = ms[0]
    assert isinstance(m, Milestone)
    assert isinstance(m.date, date)
    assert m.kind in {"window_close", "peak", "horizon"}
    assert BATCH_LABELS["autumn"] == "秋招"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_recruitment_milestones.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.recruitment_milestones'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Recruitment season milestones generated from graduation year + batch.

Pure functions: no DB, no I/O.  A "batch" maps to a time window expressed
as milestones (dates that drive review urgency).  Windows are generated
from the graduation year (届次 N = N 年毕业), following the recurring
campus-recruitment calendar observed in 2025-2026:
- summer internship hiring happens in the spring of year N-1
- autumn recruitment happens Jul-Dec of year N-1
- spring recruitment happens Feb-Jun of year N
- daily internships roll year-round (no window -> no urgency)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Batch = Literal["daily", "summer_intern", "autumn", "spring"]
VALID_BATCHES = ("daily", "summer_intern", "autumn", "spring")
BATCH_LABELS = {
    "daily": "日常实习",
    "summer_intern": "暑期实习",
    "autumn": "秋招",
    "spring": "春招",
}

MilestoneKind = Literal["window_close", "peak", "horizon"]


@dataclass(frozen=True)
class Milestone:
    name: str
    date: date
    kind: MilestoneKind


def get_milestones(graduation_year: int, batch: str) -> list[Milestone]:
    """Return the milestone list for a graduation year + batch.

    ``graduation_year`` is the 届 (year of graduation), e.g. 2027 for 2027届.
    Raises ValueError for unknown batches.
    """
    if batch not in VALID_BATCHES:
        raise ValueError(f"batch must be one of {VALID_BATCHES}")
    year = int(graduation_year)
    if batch == "daily":
        return []
    if batch == "summer_intern":
        prev = year - 1
        return [
            Milestone("投递高峰", date(prev, 3, 15), "peak"),
            Milestone("投递窗口关闭", date(prev, 5, 31), "window_close"),
            Milestone("实习开始", date(prev, 6, 30), "horizon"),
        ]
    if batch == "autumn":
        prev = year - 1
        return [
            Milestone("提前批窗口关闭", date(prev, 8, 31), "window_close"),
            Milestone("正式批高峰", date(prev, 10, 15), "peak"),
            Milestone("补录收尾", date(prev, 12, 31), "horizon"),
        ]
    return [
        Milestone("主批高峰", date(year, 4, 15), "peak"),
        Milestone("补录收尾", date(year, 6, 15), "horizon"),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_recruitment_milestones.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/recruitment_milestones.py backend/tests/services/test_recruitment_milestones.py
git commit -m "feat(backend): add recruitment season milestone generation"
```

---

### Task 2: 紧迫度计算（连续天数 → 0~1）

**Files:**
- Modify: `backend/app/services/recruitment_milestones.py`
- Test: `backend/tests/services/test_recruitment_milestones.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import date

from app.services.recruitment_milestones import compute_urgency

def test_no_milestones_means_zero_urgency():
    result = compute_urgency([], date(2026, 8, 5))
    assert result["urgency"] == 0
    assert result["next_milestone"] is None
    assert result["days_left"] is None

def test_far_away_milestone_means_zero_urgency():
    ms = [Milestone("正式批高峰", date(2026, 10, 15), "peak")]
    result = compute_urgency(ms, date(2026, 8, 5))
    assert result["urgency"] == 0  # 71 days away > 60-day horizon

def test_approaching_milestone_ramps_urgency():
    ms = [Milestone("提前批窗口关闭", date(2026, 8, 31), "window_close")]
    result = compute_urgency(ms, date(2026, 8, 5))
    assert result["urgency"] > 0.4
    assert result["urgency"] < 0.6  # 26/60 -> ~0.567
    assert result["next_milestone"]["name"] == "提前批窗口关闭"
    assert result["days_left"] == 26

def test_milestone_today_is_max_urgency():
    ms = [Milestone("提前批窗口关闭", date(2026, 8, 31), "window_close")]
    assert compute_urgency(ms, date(2026, 8, 31))["urgency"] == 1.0

def test_all_milestones_past_means_zero():
    ms = [Milestone("补录收尾", date(2026, 12, 31), "horizon")]
    result = compute_urgency(ms, date(2027, 3, 1))
    assert result["urgency"] == 0
    assert result["next_milestone"] is None

def test_picks_the_next_milestone_not_the_closest_date():
    ms = [
        Milestone("提前批窗口关闭", date(2026, 8, 31), "window_close"),
        Milestone("正式批高峰", date(2026, 10, 15), "peak"),
    ]
    result = compute_urgency(ms, date(2026, 9, 5))
    assert result["next_milestone"]["name"] == "正式批高峰"
```

（测试文件顶部需补 `from app.services.recruitment_milestones import Milestone` 导入）

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_recruitment_milestones.py -q`
Expected: FAIL — `ImportError: cannot import name 'compute_urgency'`

- [ ] **Step 3: Write minimal implementation**（追加到 `recruitment_milestones.py` 末尾）

```python
URGENCY_HORIZON_DAYS = 60


def compute_urgency(
    milestones: list[Milestone], today: date
) -> dict:
    """Map days until the next milestone to a 0..1 urgency scalar.

    Returns ``{"urgency", "next_milestone", "days_left"}``.  ``urgency`` is
    linear in the remaining days: 0 when >= 60 days away, 1 on the day
    itself.  With no milestone (or all past) urgency is 0.
    """
    future = [
        m for m in milestones if m.date >= today
    ]
    if not future:
        return {"urgency": 0.0, "next_milestone": None, "days_left": None}
    next_m = min(future, key=lambda m: m.date)
    days_left = (next_m.date - today).days
    urgency = max(0.0, min(1.0, 1.0 - days_left / URGENCY_HORIZON_DAYS))
    return {
        "urgency": round(urgency, 4),
        "next_milestone": {
            "name": next_m.name,
            "date": next_m.date.isoformat(),
            "kind": next_m.kind,
        },
        "days_left": days_left,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_recruitment_milestones.py -q`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/recruitment_milestones.py backend/tests/services/test_recruitment_milestones.py
git commit -m "feat(backend): add milestone-based urgency computation"
```

---

### Task 3: SM-2-lite 调制层（urgency 缩放 + deadline 压缩）

**Files:**
- Modify: `backend/app/services/practice_scheduler.py`
- Test: `backend/tests/services/test_practice_scheduler.py`

- [ ] **Step 1: Write the failing test**（追加到 test_practice_scheduler.py）

```python
def test_urgency_zero_keeps_existing_behavior():
    result = schedule_review(ReviewState(), "good", now=BASE_TIME, urgency=0.0)
    assert result.interval_days == pytest.approx(3)
    assert result.next_review_at == BASE_TIME + timedelta(days=3)

def test_high_urgency_shortens_intervals():
    plain = schedule_review(ReviewState(), "good", now=BASE_TIME)
    urgent = schedule_review(ReviewState(), "good", now=BASE_TIME, urgency=1.0)
    assert urgent.interval_days < plain.interval_days

def test_urgency_scaling_is_proportional():
    half = schedule_review(ReviewState(), "good", now=BASE_TIME, urgency=0.5)
    full = schedule_review(ReviewState(), "good", now=BASE_TIME, urgency=1.0)
    assert full.interval_days < half.interval_days < 3.0

def test_interval_beyond_deadline_is_pulled_back():
    deadline = BASE_TIME + timedelta(days=10)
    result = schedule_review(
        ReviewState(), "easy", now=BASE_TIME, deadline=deadline
    )
    assert result.next_review_at <= deadline
    assert result.next_review_at > BASE_TIME + timedelta(days=1)

def test_interval_within_deadline_untouched():
    deadline = BASE_TIME + timedelta(days=60)
    result = schedule_review(ReviewState(), "easy", now=BASE_TIME, deadline=deadline)
    assert result.next_review_at == BASE_TIME + timedelta(days=7)

def test_again_relearning_step_ignores_deadline():
    deadline = BASE_TIME + timedelta(days=1)
    result = schedule_review(ReviewState(), "again", now=BASE_TIME, deadline=deadline)
    assert result.next_review_at == BASE_TIME + timedelta(minutes=28.8)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_scheduler.py -q`
Expected: FAIL — TypeError about unexpected keyword argument `urgency`

- [ ] **Step 3: Write minimal implementation**

修改 `schedule_review` 签名（`practice_scheduler.py:44`）：

```python
def schedule_review(
    current: ReviewState,
    rating: str,
    *,
    now: datetime | None = None,
    urgency: float = 0.0,
    deadline: datetime | None = None,
) -> ScheduledReview:
```

在函数开头（`now = now or datetime.utcnow()` 之后）加钳制：

```python
    urgency = _clamp(float(urgency or 0.0), 0.0, 1.0)
```

在 `interval_days = round(interval_days, 4)` 处替换为调制逻辑（`practice_scheduler.py:99`）：

```python
    # 招聘季调制层：urgency 越高间隔越短；deadline 前保证至少一次复习
    if rating != "again":
        interval_days = interval_days * (1.0 - 0.4 * urgency)
    next_review_at = now + timedelta(days=interval_days)
    if deadline and rating != "again" and next_review_at > deadline:
        days_until = max(1, (deadline - now).days - 1)
        if days_until >= 1:
            next_review_at = deadline - timedelta(days=max(1, round(days_until * 0.8)))
    interval_days = round(interval_days, 4)
```

并把 return 里的 `next_review_at=now + timedelta(days=interval_days)` 改为 `next_review_at=next_review_at`。

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_scheduler.py -q`
Expected: PASS（原 4 个 + 新 6 个全部通过，保证 urgency=0 兼容）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/practice_scheduler.py backend/tests/services/test_practice_scheduler.py
git commit -m "feat(backend): modulate SM-2-lite intervals with urgency and deadline"
```

---

### Task 4: 用户招聘偏好表迁移

**Files:**
- Create: `backend/app/db/migrations/recruitment.py`
- Modify: `backend/app/db/migrations/__init__.py:168`（`run_migrations` 注册）

先读 `backend/app/db/migrations/__init__.py` 确认现有注册模式（第 150-200 行），按同样模式追加。

- [ ] **Step 1: Write the failing test**

Create: `backend/tests/services/test_recruitment_pref_table.py`

```python
from app.db.connection import get_db_connection


def test_user_recruitment_pref_table_exists(test_db):
    with get_db_connection() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(user_recruitment_pref)").fetchall()]
    assert "user_id" in cols
    assert "graduation_year" in cols
    assert "batch" in cols
    assert "daily_capacity" in cols


def test_pref_upsert_roundtrip(test_db):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, updated_at) "
            "VALUES (7, 2027, 'autumn', 30, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id) DO UPDATE SET graduation_year = excluded.graduation_year, "
            "batch = excluded.batch, daily_capacity = excluded.daily_capacity, updated_at = CURRENT_TIMESTAMP"
        )
        row = conn.execute(
            "SELECT graduation_year, batch, daily_capacity FROM user_recruitment_pref WHERE user_id = 7"
        ).fetchone()
        conn.execute(
            "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, updated_at) "
            "VALUES (7, 2027, 'spring', 20, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id) DO UPDATE SET graduation_year = excluded.graduation_year, "
            "batch = excluded.batch, daily_capacity = excluded.daily_capacity, updated_at = CURRENT_TIMESTAMP"
        )
        updated = conn.execute(
            "SELECT batch, daily_capacity FROM user_recruitment_pref WHERE user_id = 7"
        ).fetchone()
        conn.commit()
    assert row["graduation_year"] == 2027
    assert updated["batch"] == "spring"
    assert updated["daily_capacity"] == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_recruitment_pref_table.py -q`
Expected: FAIL — no such table: user_recruitment_pref

- [ ] **Step 3: Write the migration**

Create `backend/app/db/migrations/recruitment.py`：

```python
"""Recruitment preference migration."""


def migrate(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_recruitment_pref (
            user_id INTEGER PRIMARY KEY,
            graduation_year INTEGER,
            batch TEXT DEFAULT '',
            daily_capacity INTEGER DEFAULT 30,
            updated_at TEXT
        )
        """
    )
```

在 `backend/app/db/migrations/__init__.py` 的 `run_migrations()` 中按现有模式 import 并调用 `migrate(conn)`（参考现有模块注册方式，如 `from app.db.migrations.question_bank import migrate`）。

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_recruitment_pref_table.py -q`
Expected: PASS（注意：`test_db` fixture 如果走 `run_migrations()` 则表自动存在；如果 fixture 手动建表则需在测试前调用迁移——按 conftest 现有行为调整）

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/migrations/recruitment.py backend/app/db/migrations/__init__.py backend/tests/services/test_recruitment_pref_table.py
git commit -m "feat(backend): add user recruitment preference table migration"
```

---

### Task 5: 用户招聘偏好 API（GET/PUT + urgency 计算）

**Files:**
- Modify: `backend/app/routers/profile.py`
- Modify: `backend/app/models/schemas.py`（如需要新 Request model）
- Test: `backend/tests/services/test_recruitment_pref_api.py`

- [ ] **Step 1: Write the failing test**

```python
from app.core.auth import get_current_user
from app.db.connection import get_db_connection


def _make_user(client):
    # 复用现有测试的注册/登录方式（参考 backend/tests/security 现有写法）
    ...


def test_get_recruitment_pref_returns_urgency(client):
    # 注册用户并登录拿到 token
    token = _make_user(client)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, updated_at) "
            "VALUES (?, 2027, 'autumn', 30, CURRENT_TIMESTAMP)",
            (1,),
        )
        conn.commit()
    resp = client.get(
        "/api/profile/recruitment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["batch"] == "autumn"
    assert data["graduation_year"] == 2027
    assert data["daily_capacity"] == 30
    assert "urgency" in data
    assert "milestones" in data
    assert len(data["milestones"]) == 3


def test_put_recruitment_pref_validates_batch(client):
    token = _make_user(client)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": 2027, "batch": "not-a-batch", "daily_capacity": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_put_recruitment_pref_saves(client):
    token = _make_user(client)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": 2027, "batch": "daily", "daily_capacity": 25},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    get_resp = client.get("/api/profile/recruitment", headers={"Authorization": f"Bearer {token}"})
    data = get_resp.json()
    assert data["batch"] == "daily"
    assert data["daily_capacity"] == 25
    assert data["urgency"] == 0  # daily 无里程碑
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_recruitment_pref_api.py -q`
Expected: FAIL — 404 (route not found)

- [ ] **Step 3: Write minimal implementation**

在 `backend/app/routers/profile.py` 追加（注意 `user_profile` 是全局表，**不能**存用户偏好；新表是 per-user）：

```python
from datetime import date as date_cls

from app.services.recruitment_milestones import (
    VALID_BATCHES,
    get_milestones,
    compute_urgency,
)

ALLOWED_YEAR_RANGE = (2020, 2035)


@router.get("/api/profile/recruitment")
async def get_recruitment_pref(user: dict = Depends(get_current_user)):
    """当前用户的招聘偏好 + 展开的时间线 + 紧迫度（今日复习调度输入）"""

    def _query():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT graduation_year, batch, daily_capacity FROM user_recruitment_pref WHERE user_id = ?",
                (user["id"],),
            ).fetchone()
        return dict(row) if row else {}

    pref = await run_db(_query)
    year = int(pref.get("graduation_year") or 0)
    batch = str(pref.get("batch") or "")
    milestones = get_milestones(year, batch) if year and batch else []
    urgency_info = compute_urgency(milestones, date_cls.today())
    return {
        "graduation_year": year or None,
        "batch": batch or "",
        "daily_capacity": int(pref.get("daily_capacity") or 30),
        "milestones": [
            {"name": m.name, "date": m.date.isoformat(), "kind": m.kind}
            for m in milestones
        ],
        **urgency_info,
    }


@router.put("/api/profile/recruitment")
async def update_recruitment_pref(req: dict, user: dict = Depends(get_current_user)):
    """保存用户招聘偏好（届次 + 批次 + 每日容量）"""
    year = req.get("graduation_year")
    batch = (req.get("batch") or "").strip()
    capacity = req.get("daily_capacity")

    if year is not None:
        year = int(year)
        if not (ALLOWED_YEAR_RANGE[0] <= year <= ALLOWED_YEAR_RANGE[1]):
            raise HTTPException(status_code=400, detail="届次年份超出合理范围")
    if batch and batch not in VALID_BATCHES:
        raise HTTPException(status_code=400, detail=f"批次必须是: {VALID_BATCHES}")
    if capacity is not None:
        capacity = int(capacity)
        if not (5 <= capacity <= 200):
            raise HTTPException(status_code=400, detail="每日容量须在 5-200 之间")

    def _save():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, updated_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "graduation_year = excluded.graduation_year, "
                "batch = excluded.batch, "
                "daily_capacity = excluded.daily_capacity, "
                "updated_at = CURRENT_TIMESTAMP",
                (user["id"], year, batch, capacity if capacity is not None else 30),
            )
            conn.commit()

    await run_db(_save)
    return {"status": "success", "graduation_year": year, "batch": batch, "daily_capacity": capacity or 30}
```

注意：`run_db` 从 `app.db.connection` 导入（profile.py 顶部已有）。

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_recruitment_pref_api.py -q`
Expected: PASS

- [ ] **Step 5: 跑回归 + Commit**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/security/ backend/tests/services/test_recruitment_pref_api.py -q`
Expected: PASS（确认没破坏 profile 权限测试）

```bash
git add backend/app/routers/profile.py backend/tests/services/test_recruitment_pref_api.py
git commit -m "feat(backend): add per-user recruitment preference API with urgency"
```

---

### Task 6: due 题单暴露 + 队列排序升级 + 新题容量预算

**Files:**
- Modify: `backend/app/services/practice_deck_service.py`
- Test: `backend/tests/services/test_practice_api.py`（或新文件 test_practice_due_queue.py）

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_practice_due_queue.py`（先读 `test_practice_api.py` 复用其 test_db 数据准备方式）：

```python
def _seed(conn):
    # 插入公共题（与 test_practice_api.py 相同的建表方式，参考其 setup）
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, tags, difficulty, ai_answer, status, owner_id, frequency) "
        "VALUES (1, 'Q1', '基础', 'Java', '线程', 'L1-基础', 'A1', 'approved', NULL, 5)"
    )
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, tags, difficulty, ai_answer, status, owner_id, frequency) "
        "VALUES (2, 'Q2', '基础', 'MySQL', '索引', 'L2-中等', 'A2', 'approved', NULL, 1)"
    )
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, tags, difficulty, ai_answer, status, owner_id, frequency) "
        "VALUES (3, 'Q3', '基础', 'Redis', '缓存', 'L3-困难', 'A3', 'approved', NULL, 2)"
    )


def test_due_deck_is_first_and_counted(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        decks = list_decks(conn, 1)
    assert decks[0]["key"] == "due"
    assert decks[0]["name"] == "今日复习"
    assert decks[0]["total"] == 3  # 新题（未复习）也计入 due


def test_due_queue_orders_reviews_before_new_questions(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        # Q1 已复习过且到期（proficiency 2, 30 天前到期），Q2 已复习但未来到期，Q3 从未复习
        conn.execute(
            "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
            "interval_days, ease_factor, next_review_at, updated_at) "
            "VALUES (1, 1, 'review', 2, 3, 5.0, 2.3, datetime('now', '-2 days'), CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
            "interval_days, ease_factor, next_review_at, updated_at) "
            "VALUES (1, 2, 'review', 4, 6, 12.0, 2.5, datetime('now', '+10 days'), CURRENT_TIMESTAMP)"
        )
        conn.commit()
        _, items, total = list_deck_questions(conn, 1, "due")
    assert total == 3
    # 到期复习(1) 最前 → 新题(3) 其次 → 未来(2) 最后
    assert [i["id"] for i in items] == [1, 3, 2]


def test_due_queue_high_frequency_new_first(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        # 都未复习：高频的 Q1 应排在低频 Q2 前
        _, items, _ = list_deck_questions(conn, 1, "due")
    assert [i["id"] for i in items][:2] == [1, 2]


def test_due_queue_max_new_budget(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        conn.execute(
            "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
            "interval_days, ease_factor, next_review_at, updated_at) "
            "VALUES (1, 1, 'review', 2, 3, 5.0, 2.3, datetime('now', '-2 days'), CURRENT_TIMESTAMP)"
        )
        conn.commit()
        # capacity=1：1 条到期复习 + 0 条新题预算
        _, items, _ = list_deck_questions(conn, 1, "due", max_new=0)
    assert [i["id"] for i in items] == [1]
```

（`list_deck_questions` 需从 `app.services.practice_deck_service` 导入；test_db 数据按 conftest 现有建表列调整）

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_due_queue.py -q`
Expected: FAIL（decks[0] 不是 due；排序不符）

- [ ] **Step 3: Write minimal implementation**

修改 `practice_deck_service.py`：

1. `DECKS`（第 11-26 行）在首位插入 due 项：

```python
DECKS = (
    {
        "key": "due",
        "name": "今日复习",
        "description": "到期复习优先，按重要度和遗忘风险安排",
        "kind": "due",
        "sort_order": 0,
    },
    {
        "key": "all",
        "name": "全部题",
        "description": "按复习状态和面试频率安排顺序",
        "kind": "all",
        "sort_order": 1,
    },
    {
        "key": "starred",
        "name": "我的收藏",
        "description": "把收藏题集中起来反复背",
        "kind": "starred",
        "sort_order": 2,
    },
)
```

2. `_deck_condition` 已支持 `"due"`（第 61-62 行），无需改。

3. `list_deck_questions`（第 234 行起）签名加 `max_new: int | None = None`，排序改为"到期复习 → 新题 → 未来 + 风险加权"：

```python
def list_deck_questions(
    conn,
    user_id: int,
    deck_key: str,
    *,
    filter_mode: str = "all",
    limit: int = 100,
    offset: int = 0,
    max_new: int | None = None,
) -> tuple[dict, list[dict], int]:
    limit = max(1, min(int(limit or 100), 200))
    offset = max(0, int(offset or 0))
    deck, from_clause, where_clause, source_params, where_params, frequency_sql = (
        _base_query_parts(conn, user_id, filter_mode, deck_key)
    )
    join = _review_join("?")
    params = source_params + [user_id, user_id] + where_params
    total = conn.execute(
        f"SELECT COUNT(*) {from_clause}{join}{where_clause}", params
    ).fetchone()[0]
    custom_order = "pdi.sort_order ASC, " if deck["kind"] == "custom" else ""
    risk_sql = (
        "COALESCE(qb.frequency, 0) * (5 - COALESCE(uqr.proficiency, 0))"
    )
    order = (
        " ORDER BY CASE WHEN datetime(uqr.next_review_at) <= datetime('now') THEN 0 "
        "WHEN uqr.next_review_at IS NULL THEN 1 ELSE 2 END, "
        f"CASE WHEN uqr.next_review_at IS NULL THEN COALESCE(qb.frequency, 0) "
        f"ELSE {risk_sql} END DESC, "
        "COALESCE(uqr.next_review_at, '1970-01-01') ASC, "
        f"{custom_order}"
        "frequency DESC, qb.id ASC"
    )
    if deck_key == "due" and max_new is not None and offset == 0:
        # 容量预算：到期复习全做（不设上限），新题最多 max_new 条
        max_new = max(0, int(max_new))
        due_where = where_clause.replace(
            "(uqr.next_review_at IS NULL OR datetime(uqr.next_review_at) <= datetime('now'))",
            "(uqr.next_review_at IS NOT NULL AND datetime(uqr.next_review_at) <= datetime('now'))",
        )
        due_rows = conn.execute(
            _select_sql(from_clause, due_where, frequency_sql) + order,
            params,
        ).fetchall()
        new_where = where_clause.replace(
            "(uqr.next_review_at IS NULL OR datetime(uqr.next_review_at) <= datetime('now'))",
            "(uqr.next_review_at IS NULL)",
        )
        new_rows = conn.execute(
            _select_sql(from_clause, new_where, frequency_sql)
            + " ORDER BY COALESCE(qb.frequency, 0) DESC, qb.id ASC LIMIT ?",
            params + [max_new],
        ).fetchall()
        rows = due_rows + new_rows
    else:
        rows = conn.execute(
            _select_sql(from_clause, where_clause, frequency_sql) + order,
            params + [limit, offset],
        ).fetchall()
    return (
        {
            key: value
            for key, value in deck.items()
            if key not in {"owner_id", "sort_order"}
        },
        [_normalise_question(row) for row in rows],
        int(total),
    )
```

注意：`_deck_condition("due")` 返回的 SQL 字符串在 `where_clause` 中拼接为 `AND (uqr.next_review_at IS NULL OR datetime(uqr.next_review_at) <= datetime('now'))`，上面的 `.replace()` 依赖该精确字符串——**先运行测试确认 where 文本匹配**，不匹配时改为在 `_base_query_parts` 增加一个 `due_partition` 参数（计划作者已确认 `_deck_condition` 返回该字面量）。

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_due_queue.py backend/tests/services/test_practice_api.py -q`
Expected: PASS（注意 test_practice_api.py 若有断言旧排序的用例需同步更新）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/practice_deck_service.py backend/tests/services/test_practice_due_queue.py
git commit -m "feat(backend): expose due deck with risk-weighted queue and new-question budget"
```

---

### Task 7: review 端点接入 urgency/deadline + 后端收尾

**Files:**
- Modify: `backend/app/routers/practice.py`
- Modify: `backend/app/services/practice_review_service.py`

- [ ] **Step 1: Write the failing test**

追加到 `backend/tests/services/test_practice_due_queue.py`：

```python
def test_review_endpoint_applies_urgency(client):
    token = _make_user(client)  # 复用 Task 5 的 helper（或按 test_practice_api.py 的登录方式）
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, updated_at) "
            "VALUES (1, 2027, 'autumn', 30, CURRENT_TIMESTAMP)"
        )
        conn.commit()
    resp = client.post(
        "/api/practice/review",
        json={"question_id": 1, "rating": "good", "score": 80},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    interval = resp.json()["review"]["interval_days"]
    # 紧迫度 > 0 → 间隔应小于无紧迫度时的 3 天
    assert interval < 3.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_due_queue.py -q`
Expected: FAIL — interval_days == 3（urgency 未接入）

- [ ] **Step 3: Write minimal implementation**

1. `practice_review_service.py` 的 `record_review` 加透传参数：

```python
def record_review(
    conn,
    *,
    user_id: int,
    question_id: int,
    rating: str,
    score: int | None = None,
    source: str = "flashcard",
    now: datetime | None = None,
    urgency: float = 0.0,
    deadline: datetime | None = None,
) -> dict:
    ...
    result = schedule_review(
        state_from_row(current), rating, now=reviewed_at,
        urgency=urgency, deadline=deadline,
    )
```

2. `routers/practice.py` 的 `review_practice_question`（第 177 行）在 `_review` 里查询用户偏好并计算 urgency/deadline：

```python
from datetime import datetime as dt
from app.services.recruitment_milestones import get_milestones, compute_urgency


def _user_urgency(user_id: int) -> tuple[float, dt | None]:
    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT graduation_year, batch FROM user_recruitment_pref WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row or not row["graduation_year"] or not row["batch"]:
        return 0.0, None
    milestones = get_milestones(int(row["graduation_year"]), row["batch"])
    info = compute_urgency(milestones, dt.utcnow().date())
    deadline = None
    for m in milestones:
        if m.kind == "window_close" and m.date >= dt.utcnow().date():
            deadline = dt.combine(m.date, dt.min.time())
            break
    return float(info["urgency"]), deadline
```

在 `review_practice_question` 的 `_review()` 内调用：

```python
def _review():
    with get_db_connection() as conn:
        _assert_question_visible(conn, user, req.question_id)
        urgency, deadline = _user_urgency(user["id"])
        result = record_review(
            conn,
            user_id=user["id"],
            question_id=req.question_id,
            rating=req.rating,
            score=req.score,
            urgency=urgency,
            deadline=deadline,
        )
        conn.commit()
        return result
```

同时把 `evaluate-answer` 里的 `record_review` 调用（`routers/practice.py:338`）同样传入 `urgency`/`deadline`。

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/ -q`
Expected: PASS

- [ ] **Step 5: 后端全量回归 + Commit**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/ -q`
Expected: PASS（全量，确认旧行为无回归）

```bash
git add backend/app/routers/practice.py backend/app/services/practice_review_service.py backend/tests/services/
git commit -m "feat(backend): wire urgency and deadline into review scheduling"
```

---

## Phase B — 前端

### Task 8: 删除「题目抽测」页面

**Files:**
- Modify: `frontend/src/router/index.js:51-55`
- Modify: `frontend/src/layouts/AuthenticatedLayout.vue:82,99,200,227`
- Delete: `frontend/src/views/MockInterviewView.vue`
- Delete: `frontend/src/components/business/MockInterview.vue`

- [ ] **Step 1: 确认引用范围**

Run: `rg -n "mock-interview|MockInterview" frontend/src frontend/tests --glob '!dist'`
Expected: 命中 router / AuthenticatedLayout / api/index.js / views / components。逐一处理，`fetchRandomQuestions` API 保留（后端无害，删除前端调用即可）。

- [ ] **Step 2: 删除路由**

`frontend/src/router/index.js` 删除 `mock-interview` 路由块（第 51-55 行）。

- [ ] **Step 3: 清理布局映射**

`AuthenticatedLayout.vue`：
- `routeToTabMap` 删 `'mock-interview': 'MockInterview'`（第 82 行）
- `tabToRouteMap` 删 `MockInterview: '/mock-interview'`（第 99 行）
- `sidebarGroups` 删 `{ key: 'MockInterview', label: '题目抽测', route: '/mock-interview' }`（第 200 行）
- `navIconMap` 删 `MockInterview: ClipboardList`（第 227 行）

- [ ] **Step 4: 删除文件**

```bash
rm frontend/src/views/MockInterviewView.vue frontend/src/components/business/MockInterview.vue
```

检查 `frontend/src/components/business/ModelSelectField.vue` 是否只被 MockInterview 使用；若 `SettingsAIConfig` 也用它则保留，否则一并删除并清理 `api/index.js` 对应 re-export。

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功，无 `MockInterview` 未定义引用

- [ ] **Step 6: Commit**

```bash
git add -A frontend/src
git commit -m "refactor(frontend): remove standalone mock-interview quiz page"
```

---

### Task 9: 设置页「面试时间偏好」区块

**Files:**
- Modify: `frontend/src/services/profileApi.js`
- Modify: `frontend/src/components/business/SettingsInterview.vue`
- Modify: `frontend/src/components/business/SettingsPage.vue`（如需要 section 传递）

- [ ] **Step 1: 确认 SettingsInterview.vue 现有结构**

Run: `head -100 frontend/src/components/business/SettingsInterview.vue`
（阅读现有 Card 结构，按同样风格追加新 Card「面试时间偏好」）

- [ ] **Step 2: API 层**

`frontend/src/services/profileApi.js` 追加：

```js
export const fetchRecruitmentPref = () => get(`${API}/profile/recruitment`)
export const updateRecruitmentPref = (payload) => put(`${API}/profile/recruitment`, payload)
```

（确认 `get`/`put` 已在文件内导入；若没有，从 `services/http.js` 引入）

- [ ] **Step 3: 界面**

在 `SettingsInterview.vue` 追加 Card「面试时间偏好」：

```vue
<Card class="mt-6">
  <CardHeader>
    <CardTitle class="text-base flex items-center gap-2">
      <CalendarClock class="size-4 text-muted-foreground" />
      面试时间偏好
    </CardTitle>
    <CardDescription>
      选择你的招聘季和每日复习容量，系统将据此自动安排每天的复习题量和新题比例（影响「今日复习」队列）。
    </CardDescription>
  </CardHeader>
  <CardContent class="space-y-4">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
      <div class="flex-1">
        <Label class="mb-1.5 block text-xs font-semibold text-muted-foreground">届次</Label>
        <Select v-model="pref.graduationYear" @update:open="loading = false">
          <SelectTrigger class="w-full"><SelectValue placeholder="选择届次" /></SelectTrigger>
          <SelectContent>
            <SelectItem v-for="year in graduationYears" :key="year" :value="String(year)">{{ year }} 届</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div class="flex-1">
        <Label class="mb-1.5 block text-xs font-semibold text-muted-foreground">招聘批次</Label>
        <Select v-model="pref.batch">
          <SelectTrigger class="w-full"><SelectValue placeholder="选择批次" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">暂不参加校招</SelectItem>
            <SelectItem v-for="(label, key) in batchOptions" :key="key" :value="key">{{ label }}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div class="w-full sm:w-36">
        <Label class="mb-1.5 block text-xs font-semibold text-muted-foreground">每日容量（题）</Label>
        <Input v-model="pref.dailyCapacity" type="number" min="5" max="200" />
      </div>
    </div>

    <div v-if="timeline.length" class="rounded-lg border border-border bg-muted/30 p-3">
      <p class="text-xs font-semibold text-muted-foreground mb-2">招聘时间线</p>
      <div class="flex flex-col gap-1.5">
        <div v-for="m in timeline" :key="m.date" class="flex items-center justify-between text-xs">
          <span class="text-foreground">{{ m.name }}</span>
          <span class="text-muted-foreground tabular-nums">{{ m.date }}（{{ daysFromNow(m.date) }}）</span>
        </div>
      </div>
    </div>

    <div class="flex items-center justify-between pt-1">
      <p class="text-xs text-muted-foreground">
        将根据距最近里程碑的天数自动调整每日复习题量和新题比例，越临近窗口关闭复习越密集。
      </p>
      <Button size="sm" :disabled="prefSaving" @click="savePref">{{ prefSaving ? '保存中...' : '保存' }}</Button>
    </div>
  </CardContent>
</Card>
```

Script 部分（`SettingsInterview.vue` 追加）：

```js
import { ref, onMounted } from 'vue'
import { fetchRecruitmentPref, updateRecruitmentPref } from '@/services/profileApi.js'
import { useToast } from '@/composables/useNotification.js'

const toast = useToast()
const pref = ref({ graduationYear: '', batch: '__none__', dailyCapacity: 30 })
const prefSaving = ref(false)
const timeline = ref([])
const graduationYears = Array.from({ length: 12 }, (_, i) => 2024 + i)
const batchOptions = {
  daily: '日常实习',
  summer_intern: '暑期实习',
  autumn: '秋招',
  spring: '春招',
}

function daysFromNow(dateStr) {
  const diff = Math.ceil((new Date(dateStr) - new Date()) / 86400000)
  return diff >= 0 ? `${diff} 天后` : `已过 ${-diff} 天`
}

onMounted(async () => {
  try {
    const data = await fetchRecruitmentPref()
    pref.value = {
      graduationYear: data.graduation_year ? String(data.graduation_year) : '',
      batch: data.batch || '__none__',
      dailyCapacity: data.daily_capacity || 30,
    }
    timeline.value = data.milestones || []
  } catch { /* 静默失败，保持默认 */ }
})

async function savePref() {
  prefSaving.value = true
  try {
    const payload = {
      graduation_year: pref.value.graduationYear ? Number(pref.value.graduationYear) : null,
      batch: pref.value.batch === '__none__' ? '' : pref.value.batch,
      daily_capacity: Number(pref.value.dailyCapacity) || 30,
    }
    const data = await updateRecruitmentPref(payload)
    timeline.value = data.milestones || timeline.value
    toast.success('面试时间偏好已保存')
  } catch (err) {
    toast.error('保存失败，请稍后重试')
  } finally { prefSaving.value = false }
}
```

（reka-ui SelectItem 禁止空字符串 value——用 `__none__` 哨兵，提交时转空字符串，符合 frontend CLAUDE.md 规则）

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/profileApi.js frontend/src/components/business/SettingsInterview.vue
git commit -m "feat(frontend): add interview time preference settings block"
```

---

### Task 10: 今日复习主入口 + 状态行

**Files:**
- Modify: `frontend/src/composables/usePracticeDecks.js`
- Modify: `frontend/src/components/business/PracticeMode.vue`
- Modify: `frontend/src/views/PracticeView.vue`

- [ ] **Step 1: 默认选中「今日复习」**

`usePracticeDecks.js`：

```js
const DEFAULT_DECK_KEY = 'due'

async function loadDecks() {
  try {
    const response = await api.fetchPracticeDecks({ filter: unref(filter) })
    serverReady.value = true
    decks.value = response.items || []
    if (!decks.value.some(deck => deck.key === selectedDeckKey.value)) {
      selectedDeckKey.value = DEFAULT_DECK_KEY
    }
  } catch (err) { ... }
}
```

（`selectedDeckKey` 初始值改为 `'due'`；`loadDecks` 后若无匹配则回退 `decks.value[0]?.key || 'all'` 保持兜底——确保 `due` 存在时选 `due`）

- [ ] **Step 2: 复习后从 due 队列移除未来题**

`usePracticeDecks.js` 的 `submitReview`：

```js
async function submitReview({ questionId, rating, score = null }) {
  isReviewing.value = true
  try {
    const response = await api.submitPracticeReview({ question_id: questionId, rating, score })
    const nextState = response.review || {}
    if (selectedDeckKey.value === 'due' && nextState.next_review_at) {
      // 复习后被排到未来 → 移出今日队列；again 仍在今天 → 保留
      const isAgain = nextState.next_review_at && nextState.next_review_at.slice(0, 10) <= new Date().toISOString().slice(0, 10)
      if (!isAgain) {
        const idx = questions.value.findIndex(question => question.id === questionId)
        if (idx !== -1) questions.value.splice(idx, 1)
      }
    }
    const item = questions.value.find(question => question.id === questionId)
    if (item) Object.assign(item, nextState)
    ...（原有 deck.reviewed 更新逻辑保留）
    return response
  } catch ...
}
```

注意：`next_review_at` 为 `YYYY-MM-DD HH:MM:SS` 格式，比较日期部分即可；`again` 的 29 分钟步长仍是今天 → 保留在队列。若 splice 后队列为空，`PracticeMode` 已有空态提示（`sessionQuestions` 为空显示"这个题单还没有可复习的题"）——需把空态文案改为「今日复习已完成」。

- [ ] **Step 3: PracticeMode 空态文案**

`PracticeMode.vue:181-186` 空态块：文案改为「今日复习已经完成」，副文案「明天再来看看新的到期复习题」；保留"切换到全部题"按钮。

- [ ] **Step 4: 刷题页顶部状态行**

`PracticeView.vue` 追加（需先确认 layout 的 `<div data-testid="practice-view">` 结构）：

```vue
<template>
  <div class="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
    <div v-if="recruitment.batch" data-testid="recruitment-status" class="flex shrink-0 items-center gap-2 border-b border-border bg-card px-4 py-2 text-xs text-muted-foreground">
      <CalendarClock class="size-3.5" />
      <span v-if="recruitment.next_milestone" class="font-medium text-foreground">
        距{{ recruitment.next_milestone.name }}还有 {{ recruitment.days_left }} 天 · {{ stageLabel }}
      </span>
      <span v-else>未设置面试时间偏好，使用默认复习节奏</span>
      <span class="ml-auto">
        {{ batchLabel }} · 每日容量 {{ recruitment.daily_capacity }} 题
      </span>
    </div>
    <PracticeMode ... />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchRecruitmentPref } from '@/services/profileApi.js'

const recruitment = ref({ batch: '', next_milestone: null, days_left: null, daily_capacity: 30 })
const stageLabel = computed(() => {
  const u = recruitment.value.urgency ?? 0
  if (u >= 0.7) return '攻坚中'
  if (u >= 0.3) return '冲刺中'
  if (u > 0) return '准备中'
  return '从容复习'
})
const batchLabel = computed(() => ({
  daily: '日常实习', summer_intern: '暑期实习', autumn: '秋招', spring: '春招',
}[recruitment.value.batch] || ''))

onMounted(async () => {
  try { recruitment.value = await fetchRecruitmentPref() } catch { /* 默认 */ }
})
</script>
```

（`CalendarClock` 从 `@lucide/vue` 导入；`computed` 需要引入。PracticeView 是编排层，直接调 services 层 API 符合现有模式）

- [ ] **Step 5: 构建 + 冒烟验证**

Run: `cd frontend && npm run build && npm run test`
Expected: 构建成功；smoke 测试通过

- [ ] **Step 6: Commit**

```bash
git add frontend/src/composables/usePracticeDecks.js frontend/src/components/business/PracticeMode.vue frontend/src/views/PracticeView.vue
git commit -m "feat(frontend): make today-review the default practice entry with status bar"
```

---

### Task 11: 前端 Playwright 测试补充

**Files:**
- Modify: `frontend/tests/`（按现有测试文件风格新增）

- [ ] **Step 1: 阅读现有测试**

Run: `ls frontend/tests && rg -n "practice" frontend/tests`
（按现有 smoke/E2E 风格补一个最小断言：进入 `/practice` 默认题单为「今日复习」）

- [ ] **Step 2: 写测试**（mock API，禁止截图断言、禁止真实密码，遵循 `.claude/rules/test-files.md`）

在现有 practice 相关测试文件中追加：`/practice` 加载后题单选择器显示「今日复习」且顶部状态行出现（mock `/api/profile/recruitment` 返回秋招数据）。

- [ ] **Step 3: 运行**

Run: `cd frontend && npm run test`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/tests
git commit -m "test(frontend): cover today-review default entry"
```

---

### Task 12: 文档与门禁收尾

**Files:**
- Modify: `CLAUDE.md`（根）
- Modify: `backend/CLAUDE.md` / `backend/app/services/CLAUDE.md` / `backend/app/routers/CLAUDE.md`
- Modify: `frontend/CLAUDE.md` / `frontend/src/router/CLAUDE.md` / `frontend/src/components/business/CLAUDE.md`
- Modify: `docs/`（如 README 检查需要，按 `.claude/rules/readme-checklist.md`）

- [ ] **Step 1: 更新文档**

- 根 `CLAUDE.md`：路由表删除"题目抽测"行；代码路由表 practice 行补充"今日复习/招聘季调度"；Gotchas 补充 `user_recruitment_pref` 表说明
- `frontend/CLAUDE.md`：路由表删 `/mock-interview`；八股刷题工作台段落更新（默认今日复习入口、状态行）
- `frontend/src/router/CLAUDE.md`：删除 `/mock-interview` 行
- `frontend/src/components/business/CLAUDE.md`：删除 `MockInterview.vue`、`ModelSelectField.vue` 行（如已删）
- `backend/app/services/CLAUDE.md`：新增 `recruitment_milestones.py` 行
- `backend/app/routers/CLAUDE.md`：`profile.py` 行补充 recruitment 端点
- 按 `.claude/rules/readme-checklist.md` 检查 README

- [ ] **Step 2: 后端全量门禁**

Run: `./deploy/docker-deploy.sh check backend`
Expected: PASS（collect + compile + 结构测试）

- [ ] **Step 3: 前端门禁**

Run: `./deploy/docker-deploy.sh check frontend`
Expected: PASS（build + smoke）

- [ ] **Step 4: 全量测试**

Run: `./deploy/docker-deploy.sh test -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md backend/CLAUDE.md backend/app/services/CLAUDE.md backend/app/routers/CLAUDE.md frontend/CLAUDE.md frontend/src/router/CLAUDE.md frontend/src/components/business/CLAUDE.md
git commit -m "docs: update CLAUDE.md for today-review milestone scheduler"
```

---

## Self-Review 结论

**Spec 覆盖检查：**
- 删除题目抽测 → Task 8 ✓
- 今日复习主入口（due 题单暴露）→ Task 6 + Task 10 ✓
- 届次+批次设置、时间线预览、影响说明 → Task 5 + Task 9 ✓
- 紧迫值（连续天数，日常实习=0）→ Task 2 ✓（scheduler 间隔缩放 + deadline 压缩 → Task 3/7 ✓）
- 频率权重：新题引入优先 + 到期队列 risk 排序 → Task 6 ✓（不动 scheduler 核心）
- 每日容量 → 新题预算 → Task 6 max_new ✓；UI → Task 9 ✓
- 未设置兜底（纯 due 队列）→ `compute_urgency([])=0` + PracticeView 状态行兜底文案 ✓
- 迁移/文档 → Task 4 / Task 12 ✓

**风险标注：**
- Task 6 的 `where_clause.replace()` 依赖 `_deck_condition("due")` 字面量，测试先行会暴露不匹配
- Task 6 排序改动会影响「全部题」队列顺序（设计有意：复习优先）；`test_practice_api.py` 如有旧排序断言需同步更新
- Task 9 的 `Select` 需要确认 SettingsInterview.vue 已有 reka-ui 导入风格；按文件现有写法实现
- 前端测试 mock API 细节按 `frontend/tests` 现有 helper 调整
