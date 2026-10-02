"""Why did it fall: the split, the bad day, the catalyst."""
from datetime import date, timedelta

from finance import drops

TODAY = date(2026, 10, 1)


def daily(values, end=TODAY):
    start = end - timedelta(days=len(values) - 1)
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def test_classify_specific_before_general():
    assert drops.classify("uniQure Plunges on Additional Data From Huntington's Disease Study") == "clinical"
    assert drops.classify("MongoDB Price Target Cut to $415 by DA Davidson") == "analyst"
    assert drops.classify("Acme lowers full-year outlook") == "guidance"
    assert drops.classify("Corteva completes spin-off of seed business") == "spinoff"
    assert drops.classify("Adobe Reports Record Q3 Fiscal 2026 Results") == "earnings"
    assert drops.classify("MongoDB Ups Buyback Authorization by $1B") == "buyback"


def test_classify_avoids_the_false_matches_found_on_live_data():
    # "Bank" is not a ban, "Time to buy" is not a takeover, "Corp. Sec." is not the SEC.
    assert drops.classify("Deutsche Bank Makes a Contrarian Call on Netflix") == ""
    assert drops.classify("Home Depot Drops 12%: Time to Buy or Stay Cautious?") == ""
    assert drops.classify("Home Depot EVP, Gen. Counsel & Corp. Sec. Sold Shares") == "insider"
    assert drops.classify("Corteva Announces Final Results Of Private Exchange Offers") == ""
    assert drops.classify("HD Stock Falls 11%. Does the Pullback Offer Opportunity?") == ""


def test_round_ups_that_do_not_name_the_company_count_only_as_macro():
    assert drops.classify("Week ahead: earnings season begins", mentions=False) == ""
    assert drops.classify("Tariffs grip retailers", mentions=False) == "macro"


def test_name_pattern_uses_two_words_when_the_first_is_ordinary():
    pattern = drops.name_pattern("HD", "Home Depot, Inc.")
    assert pattern.search("Home Depot cuts forecast")
    assert not pattern.search("Home sales fall")
    assert drops.name_pattern("QURE", "uniQure N.V.").search("UniQure insists drug on track")


def test_peer_stats_cap_weights_the_market_and_takes_industry_medians():
    scan = {
        "BIG": {"perf_1m": 10.0, "market_cap": 900, "industry": "Soft", "sector": "Tech"},
        "SMALL": {"perf_1m": -50.0, "market_cap": 100, "industry": "Soft", "sector": "Tech"},
        "MID": {"perf_1m": -2.0, "market_cap": 100, "industry": "Soft", "sector": "Tech"},
    }
    stats = drops.peer_stats(scan)
    assert stats["market_1m"] == round((900 * 10 - 100 * 50 - 100 * 2) / 1100, 1)
    assert stats["industries"]["Soft"]["median_1m"] == -2.0
    assert stats["industries"]["Soft"]["top"][0]["symbol"] == "BIG"


def test_biggest_day_finds_the_worst_close_to_close_move():
    history = daily([100, 101, 99, 70, 72, 71])
    day = drops.biggest_day(history)
    assert day["chg"] == round((70 / 99 - 1) * 100, 1)
    assert day["on"] == (TODAY - timedelta(days=2)).isoformat()


def test_whose_story_is_it():
    assert drops.kind_of_fall(drops.decompose(-20, -18, -2)) == "industry"
    assert drops.kind_of_fall(drops.decompose(-10, -9, -8)) == "market"
    assert drops.kind_of_fall(drops.decompose(-30, -3, 1)) == "company"
    assert drops.kind_of_fall(drops.decompose(5, 0, 1)) == "day"


def test_explain_links_a_one_day_crash_to_earnings_and_that_days_news():
    closes = [100.0] * 25 + [98, 97, 60, 61, 60, 59]
    history = daily(closes)
    crash_day = history[-4][0].isoformat()
    earnings = (history[-4][0] - timedelta(days=1)).isoformat()
    tv_row = {"industry": "Software", "sector": "Tech", "earnings_last": earnings,
              "eps_surprise": 12.0, "perf_1m": -41.0}
    peers = {"market_1m": 1.0,
             "industries": {"Software": {"n": 30, "median_1m": -3.0, "top": [
                 {"symbol": "ACME", "name": "Acme", "perf_1m": -41.0},
                 {"symbol": "PEER", "name": "Peer", "perf_1m": -3.0}]}}}
    headlines = [
        {"title": "Acme cuts full-year outlook as customers delay deals", "on": crash_day,
         "url": "u1", "source": "Reuters"},
        {"title": "Acme stock plunges", "on": crash_day, "url": "u2", "source": "Benzinga"},
        {"title": "Rival launches competing product", "on": "2026-09-05", "url": "u3",
         "source": "X"},
    ]
    facts = {"name": "Acme", "chg_1m": -41.0}
    out = drops.explain("ACME", facts, history, tv_row, peers, headlines, today=TODAY)
    assert out["kind"] == "company"
    assert out["confidence"] == "clear"
    assert out["earnings_linked"] is True
    assert out["causes"][0]["type"] == "guidance"
    assert out["evidence"][0]["title"].startswith("Acme cuts")
    assert [p["symbol"] for p in out["peers"]] == ["PEER"]
    assert "Most of it came in one day" in out["summary"]
    assert "versus what analysts expected" in out["summary"]


def test_explain_says_unclear_rather_than_guessing():
    history = daily([100 - i for i in range(31)])  # a slow slide, no bad day
    out = drops.explain("SLOW", {"name": "Slow", "chg_1m": -30.0}, history,
                        {"industry": "X"}, {"market_1m": 0.0}, [], today=TODAY)
    assert out["confidence"] == "unclear"
    assert "No headline clearly explains it" in out["summary"]


def test_a_stock_up_on_the_month_with_one_bad_day_is_described_as_such():
    history = daily([100] * 20 + [130, 131, 120, 125, 126, 127, 128, 129, 130, 131, 132])
    out = drops.explain("UP", {"name": "Up", "chg_1m": 32.0}, history,
                        {"industry": "X"}, {"market_1m": 0.0}, [], today=TODAY)
    assert out["kind"] == "day"
    assert out["summary"].startswith("Up is up 32% over the month")


def test_needs_explaining():
    assert drops.needs_explaining({"chg_1m": -12.0})
    assert not drops.needs_explaining({"chg_1m": -3.0}, daily([100, 99, 98]))
    assert drops.needs_explaining({"chg_1m": 2.0}, daily([100, 90, 100]))
