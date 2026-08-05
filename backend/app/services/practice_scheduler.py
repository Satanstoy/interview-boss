"""Transparent interval-repetition scheduling for interview flashcards.

This is intentionally a small, inspectable scheduler rather than a black-box
recommendation model.  It borrows the useful parts of SM-2/FSRS-style
spaced repetition: active-recall feedback, four ratings, an ease factor, a
short relearning step after a lapse, and intervals that grow over time.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal


Rating = Literal["again", "hard", "good", "easy"]
VALID_RATINGS = frozenset({"again", "hard", "good", "easy"})


@dataclass(frozen=True)
class ReviewState:
    """The fields needed to calculate the next review for one question."""

    state: str = "new"
    proficiency: int = 0
    review_count: int = 0
    lapse_count: int = 0
    interval_days: float = 0.0
    ease_factor: float = 2.3


@dataclass(frozen=True)
class ScheduledReview(ReviewState):
    """The updated state plus the absolute time at which it is due."""

    next_review_at: datetime | None = None
    last_rating: str = ""


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def schedule_review(
    current: ReviewState,
    rating: str,
    *,
    now: datetime | None = None,
    urgency: float = 0.0,
    deadline: datetime | None = None,
) -> ScheduledReview:
    """Calculate the next interval from a flashcard review rating.

    Initial intervals are deliberately easy to understand: Again is a short
    relearning step, then Hard/Good/Easy start at 1/3/7 days.  Subsequent
    reviews use an ease factor: Hard grows conservatively, Good follows the
    current ease, and Easy gets a 30% bonus.  Proficiency is a compact 0..5
    signal used by the product UI, while ``ease_factor`` and intervals remain
    available for later migration to a full FSRS implementation.

    Hiring-season modulation: ``urgency`` (0..1, higher is more urgent)
    shortens intervals by up to 40%; ``deadline``, when given, pulls any
    non-again interval that would cross it back to keep at least one day of
    buffer (0.8 factor) and never before ``now``.  A pulled-back schedule
    recomputes ``interval_days`` so the reported interval matches
    ``next_review_at``.
    """

    if rating not in VALID_RATINGS:
        raise ValueError(f"rating must be one of {sorted(VALID_RATINGS)}")
    now = now or datetime.utcnow()
    urgency = _clamp(float(urgency or 0.0), 0.0, 1.0)
    prior_interval = max(0.0, float(current.interval_days or 0))
    prior_ease = _clamp(float(current.ease_factor or 2.3), 1.3, 2.8)
    proficiency = max(0, min(5, int(current.proficiency or 0)))
    review_count = max(0, int(current.review_count or 0)) + 1
    lapse_count = max(0, int(current.lapse_count or 0))

    if rating == "again":
        interval_days = 0.02  # about 29 minutes
        proficiency = max(0, proficiency - 1)
        lapse_count += 1
        ease_factor = _clamp(prior_ease - 0.2, 1.3, 2.8)
        state = "relearning"
    elif review_count == 1:
        interval_days = {"hard": 1.0, "good": 3.0, "easy": 7.0}[rating]
        proficiency += {"hard": 0, "good": 1, "easy": 2}[rating]
        ease_factor = _clamp(
            prior_ease + {"hard": -0.15, "good": 0.05, "easy": 0.15}[rating],
            1.3,
            2.8,
        )
        state = "mastered" if proficiency >= 5 else "learning"
    else:
        if rating == "hard":
            interval_days = max(1.0, prior_interval * 1.2)
            proficiency = max(0, proficiency)
            ease_factor = _clamp(prior_ease - 0.15, 1.3, 2.8)
        elif rating == "good":
            interval_days = max(1.0, prior_interval * prior_ease)
            proficiency = min(5, proficiency + 1)
            ease_factor = _clamp(prior_ease + 0.05, 1.3, 2.8)
        else:  # easy
            interval_days = max(2.0, prior_interval * prior_ease * 1.3)
            proficiency = min(5, proficiency + 2)
            ease_factor = _clamp(prior_ease + 0.15, 1.3, 2.8)
        state = "mastered" if proficiency >= 5 else "review"

    # 招聘季调制层：urgency 越高间隔越短；deadline 前保证至少一次复习
    if rating != "again":
        interval_days = interval_days * (1.0 - 0.4 * urgency)
    next_review_at = now + timedelta(days=interval_days)
    pulled_back = False
    if deadline and rating != "again" and next_review_at > deadline:
        days_until = max(1, (deadline - now).days - 1)
        if days_until >= 1:
            next_review_at = deadline - timedelta(days=max(1, round(days_until * 0.8)))
            pulled_back = True
        next_review_at = max(next_review_at, now)
    if pulled_back:
        # 重算间隔使其与真实排期一致；截止日已过则至少保留最小步长，绝不早于 now
        interval_days = max((next_review_at - now).total_seconds() / 86400, 0.02)
    interval_days = round(interval_days, 4)
    return ScheduledReview(
        state=state,
        proficiency=proficiency,
        review_count=review_count,
        lapse_count=lapse_count,
        interval_days=interval_days,
        ease_factor=round(ease_factor, 4),
        next_review_at=next_review_at,
        last_rating=rating,
    )


def state_from_row(row) -> ReviewState:
    """Convert a sqlite row/dict into scheduler input with safe defaults."""

    if not row:
        return ReviewState()
    return ReviewState(
        state=row["state"] or "new",
        proficiency=row["proficiency"] or 0,
        review_count=row["review_count"] or 0,
        lapse_count=row["lapse_count"] or 0,
        interval_days=row["interval_days"] or 0,
        ease_factor=row["ease_factor"] or 2.3,
    )
