"""The value card: multiples, quality, the reverse DCF."""
import json
import re
from pathlib import Path

import pytest

from finance import valuation
from finance.fetchers import tradingview as tv

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def scan():
    return tv.parse_scan(json.loads((FIXTURES / "tradingview_scan.json").read_text()))


def test_present_value_matches_the_textbook_example():
    # $100 a year at 9%: next year worth 91.7, the year after 84.2.
    assert 100 / 1.09 == pytest.approx(91.74, abs=0.01)
    one_year = valuation.dcf_value(100, 0, 9, terminal=0, years=1) - (100 / 0.09) / 1.09
    assert one_year == pytest.approx(100 / 1.09, abs=0.01)


def test_zero_growth_dcf_is_a_perpetuity():
    # No growth now or ever: value = FCF / r.
    assert valuation.dcf_value(100, 0, 10, terminal=0) == pytest.approx(1000, rel=1e-6)


def test_implied_growth_round_trips():
    ev = valuation.dcf_value(1e9, 12.0, 9.0)
    assert valuation.implied_growth(1e9, ev, 9.0) == pytest.approx(12.0, abs=0.1)


def test_implied_growth_needs_positive_cash_flow():
    assert valuation.implied_growth(-5e8, 1e10, 9.0) is None
    assert "negative" in valuation.read_implied(None, 30)


def test_negative_implied_growth_is_described_as_shrinking():
    text = valuation.read_implied(-3.0, 2.0)
    assert "SHRANK about 3%" in text


def test_cost_of_capital_uses_adjusted_beta_and_the_funding_mix():
    row = {"beta": 2.0, "market_cap": 80, "debt": 20}
    out = valuation.cost_of_capital(row, risk_free=4.0)
    beta = 0.67 * 2.0 + 0.33
    assert out["beta"] == round(beta, 2)
    expected = 0.8 * (4.0 + beta * 5) + 0.2 * 5.5 * 0.79
    assert out["wacc"] == round(expected, 1)
    assert valuation.cost_of_capital({"beta": 9, "market_cap": 1}, 9)["wacc"] == valuation.WACC_CAP


def test_industry_medians_skip_losses_and_small_groups():
    scan = {f"S{i}": {"industry": "Big", "pe": pe, "gross_margin": 50.0}
            for i, pe in enumerate([10, 20, 30, -5, 40])}
    scan["LONE"] = {"industry": "Tiny", "pe": 15}
    med = valuation.industry_medians(scan, min_n=4)
    assert med["Big"]["pe"] == 25.0          # median of 10,20,30,40 - the loss is not "small"
    assert "Tiny" not in med


def test_profile_for_a_real_company(scan):
    card = valuation.profile(scan["MCD"], {"pe": 25.0}, risk_free=4.2)
    ids = {item["id"] for group in card["groups"] for item in group["items"]}
    assert {"market_cap", "ev", "fcf", "pe", "earnings_yield", "fcf_yield", "roic"} <= ids
    pe = next(i for g in card["groups"] for i in g["items"] if i["id"] == "pe")
    assert pe["typical_text"] == "25.0x"
    assert "years of earnings" in pe["read"]
    assert [c["id"] for c in card["first_three"]] == ["revenue_growth", "operating_margin", "roic"]
    assert card["dcf"]["implied_growth"] is not None


def test_a_loss_maker_reads_as_expectations(scan):
    card = valuation.profile(scan["NET"], {}, risk_free=4.2)
    pe = next(i for g in card["groups"] for i in g["items"] if i["id"] == "pe")
    assert pe["text"] == "no profit"
    assert "expectations" in card["verdict"] or "proving" in card["verdict"]


def test_never_calls_anything_cheap_or_expensive(scan):
    for symbol in scan:
        text = json.dumps(valuation.profile(scan[symbol], {}, 4.2)).lower()
        for word in ("cheap", "expensive", "undervalued", "overvalued", "bargain", "buy", "sell"):
            assert not re.search(rf"\b{word}\b", text), (symbol, word)
