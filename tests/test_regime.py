from datetime import date, timedelta

import pytest

from finance import regime
from finance.metrics import shift_months
from finance.regime import assess, sahm_gap


def m(series_id, value, label=None, **kw):
    return {series_id: {"id": series_id, "label": label or series_id, "value": value,
                        "unit": "", "decimals": 2, "as_of": "2026-09-18",
                        "changes": kw.pop("changes", {}), "family": "x", "tier": 1,
                        **kw}}


def merge(*dicts):
    out = {}
    for d in dicts:
        out.update(d)
    return out


# ------------------------------------------------------------------ inflation

def test_inflation_at_target_is_a_tailwind():
    read = regime.inflation(merge(m("core_pce", 2.1), m("core_pce_3m", 2.0)))
    assert read["score"] == 2 and "target" in read["state"]


def test_momentum_turning_up_outranks_a_falling_annual_rate():
    # The configuration that repeatedly catches markets leaning the wrong way:
    # y/y still falling, 3-month rate already turning.
    read = regime.inflation(merge(m("core_pce", 2.6), m("core_pce_3m", 3.6)))
    assert read["score"] == -2 and read["state"] == "re-accelerating"


def test_sticky_above_target_is_a_headwind():
    read = regime.inflation(merge(m("core_pce", 3.3), m("core_pce_3m", 3.2)))
    assert read["score"] == -2 and "sticky" in read["state"]


def test_slipping_long_run_expectations_cap_an_otherwise_good_read():
    good = merge(m("core_pce", 2.1), m("core_pce_3m", 2.0))
    read = regime.inflation(merge(good, m("breakeven_10y", 3.1)))
    assert read["score"] <= -1 and "expectations" in read["state"]


def test_a_read_with_no_data_says_so_rather_than_inventing_a_state():
    read = regime.inflation({})
    assert read["state"] == "no data" and read["missing"]


# --------------------------------------------------------------------- growth

def monthly(start, values):
    """[(date, value)] one per month, which is how UNRATE arrives."""
    out, d = [], start
    for v in values:
        out.append((d, float(v)))
        d = shift_months(d, 1)
    return out


def test_the_sahm_gap_measures_the_rise_off_the_prior_years_low():
    flat = monthly(date(2025, 1, 1), [3.6] * 18)
    assert sahm_gap(flat) == pytest.approx(0.0, abs=1e-9)
    rising = monthly(date(2025, 1, 1), [3.6] * 15 + [4.2, 4.3, 4.4])
    assert sahm_gap(rising) > 0.5


def test_the_sahm_gap_refuses_a_series_too_short_to_have_a_prior_year():
    assert sahm_gap([(date(2026, 1, 1), 4.0)]) is None
    assert sahm_gap(monthly(date(2026, 1, 1), [4.0] * 10)) is None


def test_a_triggered_sahm_rule_makes_growth_a_headwind():
    unrate = monthly(date(2025, 1, 1), [3.6] * 15 + [4.3, 4.4, 4.5])
    read = regime.growth(m("unemployment", 4.5), {"unemployment": unrate})
    assert read["score"] < 0 and "Sahm" in read["state"]


def test_hiring_below_breakeven_slows_the_growth_read():
    read = regime.growth(merge(m("payrolls", 40), m("claims", 210)), {})
    assert "below breakeven" in read["state"]


# --------------------------------------------------------------------- policy

def test_restrictive_means_the_rate_relative_to_inflation_not_its_level():
    tight = regime.policy(merge(m("fed_funds", 5.5), m("core_pce", 2.0),
                                m("ust_2y", 5.5)))
    easy = regime.policy(merge(m("fed_funds", 5.5), m("core_pce", 6.0),
                               m("ust_2y", 5.5)))
    assert "restrictive" in tight["state"] and "restrictive" not in easy["state"]


def test_the_two_year_against_funds_is_read_as_the_priced_path():
    cutting = regime.policy(merge(m("fed_funds", 5.0), m("core_pce", 3.0),
                                  m("ust_2y", 4.0)))
    assert "pricing cuts" in cutting["state"]
    hiking = regime.policy(merge(m("fed_funds", 3.0), m("core_pce", 3.0),
                                 m("ust_2y", 4.0)))
    assert "pricing hikes" in hiking["state"]


# ---------------------------------------------------------------------- rates

def test_the_curve_read_names_which_end_moved():
    bull_steepen = regime.rates(merge(
        m("curve_2s10s", 0.4),
        m("ust_10y", 4.0, changes={"1m": -0.2}),
        m("ust_2y", 3.4, changes={"1m": -0.6})))
    assert "bull steepening" in bull_steepen["state"]
    bear_steepen = regime.rates(merge(
        m("curve_2s10s", 0.4),
        m("ust_10y", 4.8, changes={"1m": 0.5}),
        m("ust_2y", 4.4, changes={"1m": 0.1})))
    assert "bear steepening" in bear_steepen["state"]


def test_a_fast_rise_in_the_ten_year_is_a_headwind_regardless_of_level():
    read = regime.rates(merge(m("curve_2s10s", 0.5),
                              m("ust_10y", 4.8, changes={"1m": 0.6}),
                              m("ust_2y", 4.3, changes={"1m": 0.55})))
    assert read["score"] < 0


# --------------------------------------------------------------------- credit

def test_direction_from_a_tight_base_overrides_the_level():
    tight_stable = regime.credit(m("hy_spread", 2.8, changes={"1m": 0.0}))
    tight_widening = regime.credit(m("hy_spread", 2.8, changes={"1m": 0.7}))
    assert tight_stable["score"] > 0
    assert tight_widening["score"] < 0 and "widening fast" in tight_widening["state"]


def test_investment_grade_widening_too_escalates_the_read():
    read = regime.credit(merge(m("hy_spread", 4.0, changes={"1m": 0.3}),
                               m("ig_spread", 1.2, changes={"1m": 0.2})))
    assert "investment grade" in read["state"]


# ----------------------------------------------------------------- assembly

def test_assess_returns_all_seven_reads_in_causal_order():
    out = assess({}, {}, {})
    assert [r["id"] for r in out["reads"]] == list(regime.ORDER)
    assert out["disclaimer"]


def test_every_read_explains_the_mechanism_and_what_to_watch():
    for read in assess({}, {}, {})["reads"]:
        assert read["why"] and read["means"] and read["watch"]
        assert read["stance"] in {"tailwind", "mild tailwind", "neutral",
                                  "mild headwind", "headwind"}


def test_the_tension_line_names_credit_disagreeing_with_equities():
    summaries = merge(
        m("hy_spread", 3.2, changes={"1m": 0.6}),      # credit widening fast
        m("vix", 12.0), m("spx", 6000, vs_ma200=5.0),  # equities calm
    )
    out = assess(summaries, {}, {})
    assert "credit" in out["tension"].lower()


def test_the_summary_reads_as_a_chain_in_the_documented_order():
    out = assess({}, {}, {})
    assert out["summary"].index("inflation") < out["summary"].index("credit")
    assert out["summary"].index("credit") < out["summary"].index("risk")
