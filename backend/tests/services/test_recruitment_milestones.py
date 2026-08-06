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
    assert windows[2].weight == 1.0

def test_weights():
    windows = get_season_windows(2027)
    assert [round(w.weight, 2) for w in windows] == [0.67, 0.5, 1.0, 0.83]

def test_urgency_at_peak_within_window():
    windows = get_season_windows(2027)
    result = compute_urgency(windows, date(2026, 10, 15), "standard")
    assert result["urgency"] == pytest.approx(0.8, abs=0.001)

def test_urgency_base_floor_outside_windows():
    windows = get_season_windows(2027)
    result = compute_urgency(windows, date(2027, 1, 15), "standard")
    assert result["urgency"] == pytest.approx(0.2, abs=0.001)

def test_urgency_ramp_toward_peak():
    windows = get_season_windows(2027)
    early = compute_urgency(windows, date(2026, 9, 1), "standard")["urgency"]
    late = compute_urgency(windows, date(2026, 10, 1), "standard")["urgency"]
    assert late > early

def test_pace_offsets():
    windows = get_season_windows(2027)
    peak = date(2026, 10, 15)
    easy = compute_urgency(windows, peak, "easy")["urgency"]
    standard = compute_urgency(windows, peak, "standard")["urgency"]
    hard = compute_urgency(windows, peak, "hard")["urgency"]
    assert easy < standard < hard
    assert easy == pytest.approx(0.5, abs=0.001)
    assert hard == pytest.approx(1.0, abs=0.001)

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
    windows = get_season_windows(2027)
    result = compute_urgency(windows, date(2026, 9, 10), "standard")
    assert result["current_window"]["name"] == "秋招正式批"

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
