"""Nasdaq's quote API: the screener, per-symbol history, and the refusal breaker.

Fixtures are trimmed copies of real responses captured on 2026-09-27.
"""
import json
import urllib.error
from datetime import date
from pathlib import Path

import pytest

from finance.fetchers import nasdaq
from finance.fetchers.nasdaq import NasdaqHistoryFetcher, clean_name, parse_history, \
    parse_screener

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


# ------------------------------------------------------------------ screener

def test_screener_rows_become_numbers_not_display_strings():
    rows = {r["symbol"]: r for r in parse_screener(load("nasdaq_screener.json"))}
    net = rows["NET"]
    assert isinstance(net["price"], float) and net["price"] > 0
    assert isinstance(net["market_cap"], float) and net["market_cap"] > 1e9
    assert net["name"] == "Cloudflare"
    assert net["sector"] and net["industry"]


def test_share_class_symbols_survive_the_screener():
    rows = {r["symbol"] for r in parse_screener(load("nasdaq_screener.json"))}
    assert "BRK/B" in rows and {"GOOG", "GOOGL"} <= rows


def test_a_row_without_a_price_is_dropped():
    data = {"data": {"rows": [{"symbol": "X", "lastsale": "NA", "name": "X Inc."},
                              {"symbol": "Y", "lastsale": "$1.00", "name": "Y Inc.",
                               "marketCap": "", "pctchange": ""}]}}
    rows = parse_screener(data)
    assert [r["symbol"] for r in rows] == ["Y"]
    assert rows[0]["market_cap"] == 0.0 and rows[0]["pct_today"] is None


@pytest.mark.parametrize("raw,clean", [
    ("Cloudflare, Inc. Class A Common Stock", "Cloudflare"),
    ("NVIDIA Corporation Common Stock", "NVIDIA"),
    ("Alphabet Inc. Class C Capital Stock", "Alphabet"),
    ("Arm Holdings plc American Depositary Shares", "Arm"),
    ("Taiwan Semiconductor Manufacturing Company Ltd.", "Taiwan Semiconductor Manufacturing"),
    ("Micron Technology, Inc. Common Stock", "Micron Technology"),
])
def test_security_titles_become_the_names_people_use(raw, clean):
    assert clean_name(raw) == clean


# ------------------------------------------------------------------- history

def test_stock_history_parses_dollar_strings_oldest_first():
    rows = parse_history(load("nasdaq_history_net.json"), "stk:NET")
    assert rows and rows == sorted(rows, key=lambda o: o.on)
    assert all(o.series_id == "stk:NET" and o.source == "nasdaq" for o in rows)
    assert all(isinstance(o.value, float) and o.value > 0 for o in rows)


def test_etf_history_parses_the_unprefixed_number_format():
    rows = parse_history(load("nasdaq_history_spy.json"), "mkt:SPY")
    assert rows and all(o.value > 100 for o in rows)


def test_an_unknown_symbol_is_an_error_not_an_empty_success():
    # Nasdaq answers 200 with data: null for a symbol it does not know.
    with pytest.raises(ValueError, match="Symbol not exists"):
        parse_history(load("nasdaq_history_unknown.json"), "stk:ZZZZQ")


def fake_get(responses, calls=None):
    def get(url, timeout, headers):
        if calls is not None:
            calls.append(url)
        for key, value in responses.items():
            if f"/quote/{key}/" in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"unexpected url {url}")
    return get


def test_one_request_feeds_every_series_that_shares_a_symbol(monkeypatch):
    monkeypatch.setattr(nasdaq, "get_json", fake_get({"IWM": load("nasdaq_history_spy.json")}))
    fetcher = NasdaqHistoryFetcher({"IWM": (["rut", "mkt:IWM"], "etf")}, pause=0, workers=1)
    out = fetcher.fetch()
    by_series = {o.series_id for o in out}
    assert by_series == {"rut", "mkt:IWM"}
    assert len(out) == 2 * len(parse_history(load("nasdaq_history_spy.json"), "x"))


def test_history_already_stored_only_asks_for_recent_weeks(monkeypatch):
    calls = []
    monkeypatch.setattr(nasdaq, "get_json", fake_get({"NET": load("nasdaq_history_net.json")}, calls))
    today = date(2026, 9, 27)
    NasdaqHistoryFetcher({"NET": ("stk:NET", "stocks")}, since={"stk:NET": date(2026, 9, 20)},
                         pause=0, workers=1, today=today).fetch()
    NasdaqHistoryFetcher({"NET": ("stk:NET", "stocks")}, pause=0, workers=1, today=today).fetch()
    incremental, full = calls
    # A week of overlap before the last stored close, so late corrections land.
    assert "fromdate=2026-09-13" in incremental
    assert "fromdate=2025-08-23" in full


def test_share_classes_are_requested_in_the_history_endpoints_format(monkeypatch):
    calls = []
    monkeypatch.setattr(nasdaq, "get_json", fake_get({"BRK.B": load("nasdaq_history_net.json")}, calls))
    NasdaqHistoryFetcher({"BRK/B": ("stk:BRK/B", "stocks")}, pause=0, workers=1).fetch()
    assert "/quote/BRK.B/" in calls[0]


# ----------------------------------------------------------- refusal breaker

@pytest.mark.parametrize("workers", [1, 3])
def test_a_wholesale_refusal_stops_the_run_instead_of_grinding(monkeypatch, workers):
    """A blocked source must not turn a failed fetch into a ten-minute one.

    Yahoo 429'd every run from GitHub's runners; each symbol exhausting its
    retries before giving up would have cost minutes of sleeping per run.
    """
    attempts = []

    def always_429(url, timeout, headers):
        attempts.append(url)
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(nasdaq, "get_json", always_429)
    fetcher = NasdaqHistoryFetcher({f"SYM{i}": (f"s{i}", "etf") for i in range(12)},
                                   pause=0, sleep=lambda s: None, workers=workers)
    assert fetcher.fetch() == []
    assert fetcher.rate_limited
    assert sum("skipped" in why for _, why in fetcher.failures) >= 12 - 3 * workers
    assert len(fetcher.failures) == 12


def test_a_single_bad_symbol_does_not_trip_the_breaker(monkeypatch):
    monkeypatch.setattr(nasdaq, "get_json", fake_get({
        "BAD": urllib.error.HTTPError("u", 404, "Not Found", {}, None),
        "GOOD": load("nasdaq_history_spy.json")}))
    fetcher = NasdaqHistoryFetcher({"BAD": ("b", "etf"), "GOOD": ("g", "etf")},
                                   pause=0, sleep=lambda s: None, workers=1)
    assert fetcher.fetch() and not fetcher.rate_limited
    assert [sym for sym, _ in fetcher.failures] == ["BAD"]


# ---------------------------------------------------------------------- IPOs

def test_ipo_calendar_keeps_operating_companies_and_drops_spacs():
    rows = nasdaq.parse_ipos(load("nasdaq_ipos.json"))
    symbols = {r["symbol"] for r in rows}
    # York Space Systems and VenHub are companies; the "... Acquisition Corp"
    # listings are blank-cheque shells, and "NBRGU" is a unit, not shares.
    assert symbols == {"YSS", "VHUB"}
    yss = next(r for r in rows if r["symbol"] == "YSS")
    assert yss["name"] == "York Space Systems" and yss["priced"] == "2026-01-29"
