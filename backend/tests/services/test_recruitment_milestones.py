from datetime import date

import pytest

from app.services.recruitment_milestones import (
    BATCH_LABELS,
    compute_urgency,
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
    names = [m.name for m in ms]
    assert names == ["主批高峰", "补录收尾"]
    assert [m.kind for m in ms] == ["peak", "horizon"]

def test_summer_intern_2027_uses_previous_year_window():
    ms = get_milestones(2027, "summer_intern")
    assert [m.date.year for m in ms] == [2026, 2026, 2026]
    names = [m.name for m in ms]
    assert names == ["投递高峰", "投递窗口关闭", "实习开始"]
    assert [m.kind for m in ms] == ["peak", "window_close", "horizon"]

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
