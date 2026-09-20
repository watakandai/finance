from datetime import date

import pytest

from finance import indicators
from finance.metrics import (
    change_kind, moving_average, percentile, shift_months, snapshot,
    summarize, transform, value_asof, zscore,
)


def monthly(start, values):
    out, d = [], start
    for v in values:
        out.append((d, float(v)))
        d = shift_months(d, 1)
    return out


def test_shift_months_clamps_to_a_short_month():
    assert shift_months(date(2026, 3, 31), -1) == date(2026, 2, 28)
    assert shift_months(date(2024, 3, 31), -1) == date(2024, 2, 29)


def test_value_asof_looks_up_by_date_not_by_row_offset():
    values = [(date(2026, 1, 1), 1.0), (date(2026, 6, 1), 2.0)]
    assert value_asof(values, date(2026, 3, 1)) == 1.0
    assert value_asof(values, date(2026, 6, 1)) == 2.0
    assert value_asof(values, date(2025, 1, 1)) is None


def test_yoy_is_computed_against_the_same_month_a_year_earlier():
    values = monthly(date(2025, 1, 1), [100 * 1.0025 ** i for i in range(24)])
    out = transform(values, "yoy")
    assert out[-1][1] == pytest.approx(3.04, abs=0.01)


def test_three_month_annualised_compounds_rather_than_multiplying_by_four():
    values = monthly(date(2025, 1, 1), [100 * 1.0025 ** i for i in range(12)])
    out = transform(values, "ann3")
    # 1.0025**12 - 1 = 3.04%, not 4 x the quarterly 0.75%.
    assert out[-1][1] == pytest.approx(3.04, abs=0.01)


def test_chg1_is_a_difference_and_avg4_is_a_trailing_mean():
    values = [(date(2026, 1, d), float(d)) for d in (1, 8, 15, 22, 29)]
    assert [v for _, v in transform(values, "chg1")] == [7.0, 7.0, 7.0, 7.0]
    assert transform(values, "avg4")[-1][1] == pytest.approx(18.5)


def test_a_rate_changes_absolutely_and_a_price_changes_proportionally():
    assert change_kind("%", "ust_10y") == "abs"
    assert change_kind("", "spx") == "pct"
    # A financial conditions index is centred on zero, where a percentage
    # change divides by nothing.
    assert change_kind("index", "nfci") == "abs"
    # A difference series is always absolute, whatever its unit.
    assert change_kind("k", "payrolls", "chg1") == "abs"


def test_zscore_and_percentile_return_none_rather_than_a_fake_zero():
    flat = [(date(2026, 1, i + 1), 5.0) for i in range(30)]
    assert zscore(flat) is None          # no variation to compare against
    assert percentile(flat) == 50.0      # ties share their span
    assert zscore(flat[:5]) is None      # too short


def test_moving_average_refuses_a_window_it_cannot_fill():
    values = [(date(2026, 9, i + 1), 1.0) for i in range(20)]
    assert moving_average(values, 10) == pytest.approx(1.0)
    assert moving_average(values, 200) is None


def test_summarize_reports_nothing_rather_than_a_zero_for_a_missing_series():
    assert summarize(indicators.BY_ID["core_pce"], [], date(2026, 9, 19)) == {}


def test_summarize_applies_the_scale_so_claims_read_in_thousands():
    spec = indicators.BY_ID["claims"]
    start = date(2026, 8, 6).toordinal()
    values = [(date.fromordinal(start + 7 * i), 200_000.0) for i in range(12)]
    out = summarize(spec, values, date(2026, 10, 25))
    assert out["value"] == pytest.approx(200.0)
    assert out["unit"] == "k"


def test_a_monthly_series_reports_no_one_day_change():
    values = monthly(date(2024, 1, 1), [100 + i for i in range(30)])
    out = summarize(indicators.BY_ID["core_pce"], values, date(2026, 6, 19))
    assert "1d" not in out["changes"] and "1w" not in out["changes"]
    assert "1m" in out["changes"]


def test_a_daily_price_series_gets_trend_context():
    values = [(date.fromordinal(date(2025, 1, 1).toordinal() + i), 5000 + i * 2.0)
              for i in range(600)]
    out = summarize(indicators.BY_ID["spx"], values, date(2026, 8, 24))
    assert out["vs_ma200"] > 0
    assert out["off_high_52w"] == pytest.approx(0.0)
    assert len(out["spark"]) <= 61


def test_the_sparkline_always_ends_on_the_value_printed_beside_it():
    values = [(date.fromordinal(date(2024, 1, 1).toordinal() + i), float(i))
              for i in range(700)]
    out = summarize(indicators.BY_ID["spx"], values, date(2025, 12, 1))
    assert out["spark"][-1][1] == out["value"]


def test_snapshot_reports_percentage_moves_including_year_to_date():
    values = [(date(2026, 1, 2), 100.0), (date(2026, 6, 1), 110.0),
              (date(2026, 9, 18), 120.0)]
    out = snapshot(values, date(2026, 9, 19))
    assert out["changes"]["ytd"] == pytest.approx(20.0)
