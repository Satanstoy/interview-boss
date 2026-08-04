from datetime import datetime, timedelta

import pytest

from app.services.practice_scheduler import ReviewState, schedule_review


BASE_TIME = datetime(2026, 8, 4, 9, 0, 0)


def test_first_good_review_creates_a_three_day_interval():
    result = schedule_review(ReviewState(), "good", now=BASE_TIME)

    assert result.review_count == 1
    assert result.proficiency == 1
    assert result.interval_days == pytest.approx(3)
    assert result.next_review_at == BASE_TIME + timedelta(days=3)
    assert result.state == "learning"


def test_again_moves_a_question_to_relearning_with_a_short_interval():
    state = ReviewState(
        state="review",
        proficiency=4,
        review_count=5,
        lapse_count=1,
        interval_days=12,
        ease_factor=2.5,
    )

    result = schedule_review(state, "again", now=BASE_TIME)

    assert result.review_count == 6
    assert result.lapse_count == 2
    assert result.proficiency == 3
    assert result.state == "relearning"
    assert result.interval_days == pytest.approx(0.02)
    assert result.next_review_at == BASE_TIME + timedelta(minutes=28.8)


def test_easy_grows_faster_than_hard_and_can_reach_mastered_state():
    state = ReviewState(
        state="review",
        proficiency=4,
        review_count=4,
        interval_days=10,
        ease_factor=2.3,
    )

    hard = schedule_review(state, "hard", now=BASE_TIME)
    easy = schedule_review(state, "easy", now=BASE_TIME)

    assert easy.interval_days > hard.interval_days
    assert easy.proficiency == 5
    assert easy.state == "mastered"


def test_invalid_rating_is_rejected():
    with pytest.raises(ValueError, match="rating"):
        schedule_review(ReviewState(), "forgotten", now=BASE_TIME)
