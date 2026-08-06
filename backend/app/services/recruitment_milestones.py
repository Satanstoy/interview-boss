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

BASE_URGENCY = 0.2
AMP = 0.6
HALF_WIDTH_DAYS = 45


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
    ``next_window`` is the first window not yet in its pulse ramp (peak
    more than HALF_WIDTH_DAYS away) with its days_left.  Unknown pace
    raises ValueError.
    """
    if pace not in VALID_PACES:
        raise ValueError(f"pace must be one of {VALID_PACES}")
    urgency = BASE_URGENCY + sum(_pulse(w, today) for w in windows)
    urgency += PACE_OFFSETS[pace]
    urgency = max(0.0, min(1.0, urgency))
    pulsing = [w for w in windows if _pulse(w, today) > 0.0]
    current = max(pulsing, key=lambda w: (w.weight, w.peak)) if pulsing else None
    future = [w for w in windows if (w.peak - today).days >= HALF_WIDTH_DAYS]
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
