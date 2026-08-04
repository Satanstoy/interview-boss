"""Persistence for flashcard review feedback."""

from __future__ import annotations

from datetime import datetime

from app.services.practice_scheduler import schedule_review, state_from_row


def record_review(
    conn,
    *,
    user_id: int,
    question_id: int,
    rating: str,
    score: int | None = None,
    source: str = "flashcard",
    now: datetime | None = None,
) -> dict:
    """Atomically update a user's state and append an auditable review event."""

    reviewed_at = (now or datetime.utcnow()).replace(microsecond=0)
    current = conn.execute(
        "SELECT * FROM user_question_review WHERE user_id = ? AND question_bank_id = ?",
        (user_id, question_id),
    ).fetchone()
    result = schedule_review(state_from_row(current), rating, now=reviewed_at)
    timestamp = reviewed_at.strftime("%Y-%m-%d %H:%M:%S")
    next_review_at = result.next_review_at.strftime("%Y-%m-%d %H:%M:%S")
    difficulty = max(
        0.1,
        min(1.0, 0.7 - result.proficiency * 0.1 + (0.15 if rating == "again" else 0)),
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
            timestamp,
            next_review_at,
            result.interval_days,
            result.ease_factor,
            result.interval_days,
            difficulty,
            timestamp,
        ),
    )
    review_row = conn.execute(
        "SELECT id FROM user_question_review WHERE user_id = ? AND question_bank_id = ?",
        (user_id, question_id),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO practice_review_events
            (user_id, question_bank_id, review_id, rating, score, source, reviewed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, question_id, review_row["id"], rating, score, source, timestamp),
    )
    return {
        "state": result.state,
        "proficiency": result.proficiency,
        "review_count": result.review_count,
        "lapse_count": result.lapse_count,
        "last_rating": result.last_rating,
        "last_score": score,
        "last_reviewed_at": timestamp,
        "next_review_at": next_review_at,
        "interval_days": result.interval_days,
        "ease_factor": result.ease_factor,
        "algorithm": "sm2_lite",
        "has_been_practiced": True,
    }
