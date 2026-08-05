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
