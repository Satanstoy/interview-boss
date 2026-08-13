"""Persistence for flashcard review feedback."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from app.services.practice_scheduler import ReviewState, schedule_review, state_from_row


CORRECTION_WINDOW = timedelta(minutes=15)
PASSING_RATINGS = frozenset({"good", "easy"})


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ReviewCorrectionError(ValueError):
    """Raised when an existing review event cannot safely be corrected."""


def _review_payload(result, *, score, timestamp, event_id: int) -> dict:
    return {
        "state": result.state,
        "proficiency": result.proficiency,
        "review_count": result.review_count,
        "lapse_count": result.lapse_count,
        "last_rating": result.last_rating,
        "last_score": score,
        "last_reviewed_at": timestamp,
        "next_review_at": result.next_review_at.strftime("%Y-%m-%d %H:%M:%S"),
        "interval_days": result.interval_days,
        "ease_factor": result.ease_factor,
        "algorithm": "sm2_lite",
        "has_been_practiced": True,
        "event_id": event_id,
        "can_correct": True,
        "passed_today": result.last_rating in PASSING_RATINGS,
        "is_daily_relearning": result.last_rating not in PASSING_RATINGS,
    }


def _persist_state(
    conn,
    *,
    user_id: int,
    question_id: int,
    result,
    score: int | None,
    reviewed_at: str,
    updated_at: str,
) -> int:
    next_review_at = result.next_review_at.strftime("%Y-%m-%d %H:%M:%S")
    difficulty = max(
        0.1,
        min(
            1.0,
            0.7
            - result.proficiency * 0.1
            + (0.15 if result.last_rating == "again" else 0),
        ),
    )
    conn.execute(
        """
        INSERT INTO user_question_review (
            user_id, question_bank_id, state, proficiency, review_count,
            lapse_count, last_rating, last_score, last_reviewed_at,
            next_review_at, interval_days, ease_factor, stability_days,
            difficulty, algorithm, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sm2_lite', ?)
        ON CONFLICT(user_id, question_bank_id) DO UPDATE SET
            state = excluded.state,
            proficiency = excluded.proficiency,
            review_count = excluded.review_count,
            lapse_count = excluded.lapse_count,
            last_rating = excluded.last_rating,
            last_score = excluded.last_score,
            last_reviewed_at = excluded.last_reviewed_at,
            next_review_at = excluded.next_review_at,
            interval_days = excluded.interval_days,
            ease_factor = excluded.ease_factor,
            stability_days = excluded.stability_days,
            difficulty = excluded.difficulty,
            algorithm = excluded.algorithm,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            question_id,
            result.state,
            result.proficiency,
            result.review_count,
            result.lapse_count,
            result.last_rating,
            score,
            reviewed_at,
            next_review_at,
            result.interval_days,
            result.ease_factor,
            result.interval_days,
            difficulty,
            updated_at,
        ),
    )
    row = conn.execute(
        "SELECT id FROM user_question_review WHERE user_id = ? AND question_bank_id = ?",
        (user_id, question_id),
    ).fetchone()
    return int(row["id"])


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
) -> dict:
    """Atomically update a user's state and append an auditable review event."""

    reviewed_at = (now or _utcnow_naive()).replace(microsecond=0)
    current = conn.execute(
        "SELECT * FROM user_question_review WHERE user_id = ? AND question_bank_id = ?",
        (user_id, question_id),
    ).fetchone()
    before_state = state_from_row(current)
    result = schedule_review(
        before_state,
        rating,
        now=reviewed_at,
        urgency=urgency,
    )
    timestamp = reviewed_at.strftime("%Y-%m-%d %H:%M:%S")
    review_id = _persist_state(
        conn,
        user_id=user_id,
        question_id=question_id,
        result=result,
        score=score,
        reviewed_at=timestamp,
        updated_at=timestamp,
    )
    event = conn.execute(
        """
        INSERT INTO practice_review_events
            (user_id, question_bank_id, review_id, rating, score, source,
             reviewed_at, before_state_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            question_id,
            review_id,
            rating,
            score,
            source,
            timestamp,
            json.dumps(asdict(before_state), separators=(",", ":")),
        ),
    )
    return _review_payload(
        result, score=score, timestamp=timestamp, event_id=int(event.lastrowid)
    )


def correct_review(
    conn,
    *,
    user_id: int,
    event_id: int,
    rating: str,
    score: int | None = None,
    now: datetime | None = None,
    urgency: float = 0.0,
) -> tuple[int, dict]:
    """Replace a recent rating from its captured pre-review state."""

    correction_time = (now or _utcnow_naive()).replace(microsecond=0)
    event = conn.execute(
        "SELECT * FROM practice_review_events WHERE id = ? AND user_id = ?",
        (event_id, user_id),
    ).fetchone()
    if not event:
        raise ReviewCorrectionError("复习记录不存在")
    latest = conn.execute(
        "SELECT MAX(id) AS id FROM practice_review_events "
        "WHERE user_id = ? AND question_bank_id = ?",
        (user_id, event["question_bank_id"]),
    ).fetchone()
    if int(latest["id"] or 0) != event_id:
        raise ReviewCorrectionError("这道题已有更新的复习记录，不能再改判")
    reviewed_at = datetime.fromisoformat(str(event["reviewed_at"]))
    if correction_time - reviewed_at > CORRECTION_WINDOW:
        raise ReviewCorrectionError("改判时间已超过 15 分钟")
    if not event["before_state_json"]:
        raise ReviewCorrectionError("旧复习记录不支持改判")

    before_state = ReviewState(**json.loads(event["before_state_json"]))
    result = schedule_review(
        before_state,
        rating,
        now=reviewed_at,
        urgency=urgency,
    )
    timestamp = reviewed_at.strftime("%Y-%m-%d %H:%M:%S")
    _persist_state(
        conn,
        user_id=user_id,
        question_id=int(event["question_bank_id"]),
        result=result,
        score=score,
        reviewed_at=timestamp,
        updated_at=correction_time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    conn.execute(
        "UPDATE practice_review_events SET rating = ?, score = ?, corrected_at = ? "
        "WHERE id = ?",
        (rating, score, correction_time.strftime("%Y-%m-%d %H:%M:%S"), event_id),
    )
    return int(event["question_bank_id"]), _review_payload(
        result, score=score, timestamp=timestamp, event_id=event_id
    )
