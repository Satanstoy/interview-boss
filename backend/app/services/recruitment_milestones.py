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
