"""TradingView: fundamentals from the scanner, headlines per symbol."""
import json
import urllib.error
from pathlib import Path

from finance.fetchers import tradingview as tv

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_scan_rows_are_keyed_in_nasdaq_spelling_with_named_fields():
    rows = tv.parse_scan(load("tradingview_scan.json"))
    assert {"MDB", "QURE", "MCD", "NET", "BRK/B"} <= set(rows)
    mcd = rows["MCD"]
    assert mcd["tv_symbol"] == "NYSE:MCD"
    assert mcd["industry"] == "Restaurants"
    assert mcd["fcf"] > 0 and mcd["ocf"] > mcd["fcf"]   # FCF = OCF - CapEx
    assert mcd["capex"] < 0
    # Unix timestamps become ISO dates.
    assert len(mcd["earnings_last"]) == 10 and mcd["earnings_last"][4] == "-"


def test_scan_drops_rows_with_the_wrong_column_count():
    data = {"data": [{"s": "NYSE:X", "d": [1, 2]}]}
    assert tv.parse_scan(data) == {}


def test_nan_and_non_numbers_become_none():
    assert tv._round(float("nan")) is None
    assert tv._round("12") is None
    assert tv._round(True) is None
    assert tv._round(1.23456) == 1.2346


def test_tv_symbol_prefers_the_exchange_from_the_scan():
    assert tv.tv_symbol("MDB", {"tv_symbol": "NASDAQ:MDB"}) == "NASDAQ:MDB"
    assert tv.tv_symbol("BRK/B") == "BRK.B"


def test_headlines_drop_law_firm_ads_and_sort_newest_first():
    items = tv.parse_headlines(load("tradingview_headlines.json"))
    titles = [h["title"] for h in items]
    assert not any("SueWallSt" in t for t in titles)
    assert any("Huntington" in t for t in titles)
    assert [h["published_ts"] for h in items] == sorted(
        (h["published_ts"] for h in items), reverse=True)
    assert all(h["url"].startswith("http") for h in items)


def test_lawyer_ads_are_recognised():
    for title in ("INVESTOR ALERT: Pomerantz Law Firm Investigates Claims On Behalf of Investors",
                  "Rosen Law Firm Encourages uniQure N.V. Investors to Inquire",
                  "Shareholder Alert: class action filed against XYZ"):
        assert tv.LAWYER_AD_RE.search(title), title
    assert not tv.LAWYER_AD_RE.search("uniQure Plunges on Additional Data From Huntington's Study")


def test_headlines_many_stops_after_repeated_refusals():
    calls = []

    def refuse(symbol):
        calls.append(symbol)
        raise urllib.error.HTTPError("u", 429, "Too Many", {}, None)

    symbols = {f"S{i}": f"NYSE:S{i}" for i in range(10)}
    out, failures = tv.headlines_many(symbols, workers=1, pause=0, fetch=refuse)
    assert out == {}
    assert len(calls) == tv.GIVE_UP_AFTER
    assert sum(1 for _, why in failures if "skipped" in why) == 10 - tv.GIVE_UP_AFTER


def test_headlines_many_isolates_one_bad_symbol():
    def fetch(symbol):
        if symbol == "NYSE:BAD":
            raise ValueError("boom")
        return [{"title": symbol}]

    out, failures = tv.headlines_many({"A": "NYSE:A", "BAD": "NYSE:BAD"}, pause=0, fetch=fetch)
    assert set(out) == {"A"}
    assert failures and failures[0][0] == "BAD"
