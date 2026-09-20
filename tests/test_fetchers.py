"""Parser tests against captured real responses.

No network: each test reads a fixture that is a trimmed copy of what the
service actually returns, so the assertions are about the shapes these APIs
really produce rather than about a shape this project imagined.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from finance.calendar_rules import FRI, MON, THU, TUE, WED, easter, federal_holidays, \
    generate, market_holidays, nearest_business_day, nth_business_day, nth_weekday
from finance.fetchers.fomc import parse as parse_fomc, _decision_date
from finance.fetchers.fred import parse_csv
from finance.fetchers.rss import RSSFetcher
from finance.fetchers.yahoo import parse_chart

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name, binary=False):
    path = FIXTURES / name
    return path.read_bytes() if binary else path.read_text()


# ---------------------------------------------------------------------- FRED

def test_fred_csv_parses_dates_and_values_oldest_first():
    rows = parse_csv(fixture("fred_dgs10.csv"))
    assert rows
    assert all(isinstance(on, date) for on, _ in rows)
    assert rows == sorted(rows)
    assert all(0 < value < 30 for _, value in rows)  # a yield, in percent


def test_fred_missing_observations_are_dropped_not_interpolated():
    # FRED writes "." for a market holiday. Carrying the previous value forward
    # would invent trading days that did not exist.
    text = "observation_date,X\n2026-01-01,.\n2026-01-02,3.5\n2026-01-05,3.6\n"
    assert parse_csv(text) == [(date(2026, 1, 2), 3.5), (date(2026, 1, 5), 3.6)]


def test_fred_csv_survives_junk_rows_and_an_empty_body():
    assert parse_csv("observation_date,X\nnot-a-date,1\n2026-01-02,oops\n") == []
    assert parse_csv("") == []
    assert parse_csv("observation_date\n") == []


def test_a_monthly_fred_series_is_dated_on_the_first_of_its_month():
    rows = parse_csv(fixture("fred_unrate.csv"))
    assert rows and all(on.day == 1 for on, _ in rows)


# --------------------------------------------------------------------- Yahoo

def test_yahoo_chart_skips_days_the_symbol_did_not_trade():
    data = json.loads(fixture("yahoo_gspc.json"))
    out = parse_chart(data, "spx")
    closes = [o.value for o in out]
    assert len(out) == 4          # five timestamps, one null close
    assert None not in closes
    assert all(o.series_id == "spx" and o.source == "yahoo" for o in out)
    assert out == sorted(out, key=lambda o: o.on)


def test_yahoo_raises_with_the_providers_own_message_when_there_is_no_result():
    with pytest.raises(ValueError, match="No data found"):
        parse_chart({"chart": {"result": [], "error": {"description": "No data found"}}}, "x")


# ----------------------------------------------------------------------- RSS

def test_rss_items_carry_the_feeds_tier_through_to_the_item():
    items = RSSFetcher("fed_press", "http://x", tier=1).parse(fixture("fed_press.xml", True))
    assert items
    assert all(it.tier == 1 and it.source == "fed_press" for it in items)
    assert all(it.title and it.url for it in items)
    assert any(it.published for it in items)


def test_rss_prefers_the_feeds_own_guid_over_the_url_for_identity():
    items = RSSFetcher("fed_press", "http://x").parse(fixture("fed_press.xml", True))
    # A publisher that rewrites URLs must not re-enter as a duplicate row.
    assert all(it.source_id for it in items)


def test_rss_reports_no_crowd_signal_rather_than_a_fabricated_one():
    items = RSSFetcher("fed_press", "http://x").parse(fixture("fed_press.xml", True))
    assert all(it.metric == "" and it.points == 0 for it in items)
    assert [it.rank for it in items] == list(range(1, len(items) + 1))


# ---------------------------------------------------------------------- FOMC

def test_fomc_scrape_finds_eight_confirmed_decisions_a_year():
    events = parse_fomc(fixture("fomc_calendar.html"))
    decisions = [e for e in events if e.kind == "decision"]
    for year in (2026, 2027):
        assert len([e for e in decisions if e.on.year == year]) == 8
    assert all(e.estimated is False for e in events)


def test_the_decision_is_dated_on_the_last_day_of_the_meeting():
    events = parse_fomc(fixture("fomc_calendar.html"))
    dates = {e.on for e in events if e.kind == "decision"}
    assert date(2026, 3, 18) in dates    # the page writes "17-18*"
    assert date(2026, 3, 17) not in dates


def test_a_meeting_straddling_a_month_end_lands_in_the_second_month():
    assert _decision_date(2024, "Apr", "May", "30-1") == date(2024, 5, 1)
    assert _decision_date(2019, "Dec", "Jan", "31-1") == date(2020, 1, 1)
    events = parse_fomc(fixture("fomc_calendar.html"))
    assert date(2024, 5, 1) in {e.on for e in events if e.kind == "decision"}


def test_projection_meetings_are_marked_because_they_move_the_curve_more():
    events = parse_fomc(fixture("fomc_calendar.html"))
    sep = [e for e in events if e.kind == "decision" and "dot plot" in e.title]
    assert len([e for e in sep if e.on.year == 2026]) == 4


def test_minutes_and_beige_book_are_derived_from_each_decision():
    events = parse_fomc(fixture("fomc_calendar.html"))
    by_date = {e.on: e for e in events}
    assert by_date[date(2026, 4, 8)].title == "FOMC minutes"   # 18 Mar + 21d
    assert by_date[date(2026, 3, 4)].title == "Beige Book"     # 18 Mar - 14d


# ------------------------------------------------------------------ calendar

def test_easter_and_the_market_only_good_friday_holiday():
    assert easter(2027) == date(2027, 3, 28)
    # Good Friday closes the exchanges but is not a federal holiday.
    assert date(2027, 3, 26) in market_holidays(2027)
    assert date(2027, 3, 26) not in federal_holidays(2027)


def test_a_weekend_holiday_is_observed_on_the_adjacent_weekday():
    # 4 July 2026 is a Saturday, so the federal holiday moves to the Friday.
    assert date(2026, 7, 3) in federal_holidays(2026)


def test_nth_business_day_skips_the_new_year_holiday():
    assert nth_business_day(2027, 1, 1) == date(2027, 1, 4)   # 1 Jan is a Friday
    assert nth_business_day(2026, 8, -1) == date(2026, 8, 31)


def test_nearest_business_day_prefers_the_weekdays_an_agency_actually_uses():
    # 12 October 2026 is a Monday; CPI prefers Tue/Wed/Thu.
    assert nearest_business_day(date(2026, 10, 12), (TUE, WED, THU)) == date(2026, 10, 13)


def test_generated_events_are_all_marked_estimated_and_carry_their_rule():
    events = generate(date(2026, 10, 1), months=1)
    assert events
    assert all(e.estimated for e in events)
    assert all("Date inferred:" in e.detail for e in events)


def test_payrolls_land_on_the_first_friday_and_claims_every_thursday():
    events = generate(date(2026, 10, 1), months=1)
    jobs = [e for e in events if e.title.startswith("Employment Situation")]
    assert [e.on for e in jobs] == [date(2026, 10, 2)]
    claims = [e.on for e in events if e.title == "Initial jobless claims"]
    assert claims and all(d.weekday() == THU for d in claims)


def test_the_auction_pair_never_inverts_even_when_a_month_starts_on_a_thursday():
    # October 2026 starts on a Thursday: an "nth Wednesday / nth Thursday" pair
    # would list the 30-year before the 10-year.
    events = generate(date(2026, 10, 1), months=1)
    ten = next(e.on for e in events if e.title.startswith("10-year"))
    thirty = next(e.on for e in events if e.title.startswith("30-year"))
    assert ten < thirty


def test_nothing_is_generated_before_the_start_date():
    events = generate(date(2026, 10, 20), months=1)
    assert all(e.on >= date(2026, 10, 20) for e in events)


# ------------------------------------------------- the quote circuit breaker

def test_a_wholesale_rate_limit_stops_the_run_instead_of_grinding(monkeypatch):
    """A blocked quote source must not turn a failed fetch into a ten-minute one.

    Each symbol exhausts three retries before giving up, so without the breaker
    twenty-five blocked symbols cost ten minutes of sleeping - in a daily
    workflow that is the difference between a degraded run and a timed-out job.
    """
    import urllib.error

    from finance.fetchers import yahoo

    attempts = []

    def always_429(url, timeout, headers):
        attempts.append(url)
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(yahoo, "get_json", always_429)
    fetcher = yahoo.YahooFetcher({f"SYM{i}": f"s{i}" for i in range(10)},
                                 pause=0, sleep=lambda s: None)
    assert fetcher.fetch() == []
    assert fetcher.rate_limited
    # Three symbols x four attempts each, then the rest are skipped untried.
    assert len(attempts) == yahoo.GIVE_UP_AFTER * (len(yahoo.RETRY_WAITS) + 1)
    assert sum("skipped" in why for _, why in fetcher.failures) == 7


def test_a_single_bad_symbol_does_not_trip_the_breaker(monkeypatch):
    import urllib.error

    from finance.fetchers import yahoo

    def one_bad(url, timeout, headers):
        if "BAD" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return json.loads(fixture("yahoo_gspc.json"))

    monkeypatch.setattr(yahoo, "get_json", one_bad)
    fetcher = yahoo.YahooFetcher({"BAD": "b", "GOOD": "g"}, pause=0,
                                 sleep=lambda s: None)
    out = fetcher.fetch()
    assert out and not fetcher.rate_limited
    assert len(fetcher.failures) == 1
