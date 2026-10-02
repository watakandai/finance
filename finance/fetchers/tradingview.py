"""Fundamentals, earnings dates and per-company headlines, from TradingView.

Nasdaq says what a price did; TradingView says what the company IS - its
earnings, sales, margins, debt and what analysts expect - and keeps a
per-symbol news stream that goes back weeks. Those two things are what turn
"down 30% this month" into an explanation: the stock fell the day after an
earnings report, or the whole industry fell with it, or three banks cut their
price targets the same morning.

Two public endpoints, both keyless and both what tradingview.com's own pages
call, so they are UNOFFICIAL - TradingView can change or close them, and
everything that uses them fails soft:

- `scan()` - the screener: one POST returns every US stock above a size floor
  with any of several hundred fields. One request covers the whole market,
  which is what makes "how did this stock's industry do?" answerable.
- `headlines()` - the news TradingView files under one symbol (Dow Jones,
  Reuters, Benzinga, press releases, analyst actions), newest first. One GET
  per symbol, so it is only called for the stocks that need explaining.

Volume is deliberately small - one scan and a few dozen headline requests a
day - and nothing is redistributed beyond short excerpts on a personal page.
"""
from __future__ import annotations
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .base import BROWSER_AGENT, get_json

SCAN_URL = "https://scanner.tradingview.com/america/scan"
NEWS_URL = ("https://news-headlines.tradingview.com/v2/headlines"
            "?client=web&lang=en&symbol={symbol}")
STORY_URL = "https://www.tradingview.com{path}"
HEADERS = {
    "User-Agent": BROWSER_AGENT,
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}

# Screener field -> our name. Grouped by the question each answers, which is
# also how the page shows them. Percent fields are already in percent.
COLUMNS = {
    # identity and today
    "name": "ticker",
    "description": "name",
    "close": "price",
    "change": "pct_today",
    "sector": "sector",
    "industry": "industry",
    "market_cap_basic": "market_cap",
    # how it has moved
    "Perf.W": "perf_1w",
    "Perf.1M": "perf_1m",
    "Perf.3M": "perf_3m",
    "Perf.YTD": "perf_ytd",
    "Perf.Y": "perf_1y",
    "relative_volume_10d_calc": "rel_volume",
    "beta_1_year": "beta",
    "Volatility.M": "volatility_m",
    "RSI": "rsi",
    "SMA50": "sma50",
    "SMA200": "sma200",
    # what you pay for it
    "price_earnings_ttm": "pe",
    "non_gaap_price_to_earnings_per_share_forecast_next_fy": "forward_pe",
    "price_earnings_growth_ttm": "peg",
    "price_sales_current": "ps",
    "enterprise_value_ebitda_ttm": "ev_ebitda",
    "enterprise_value_current": "ev",
    "price_free_cash_flow_ttm": "p_fcf",
    "price_book_fq": "pb",
    "dividend_yield_recent": "dividend_yield",
    # what the business does with it
    "earnings_per_share_diluted_ttm": "eps",
    "earnings_per_share_diluted_yoy_growth_ttm": "eps_growth",
    "earnings_per_share_forecast_next_fy": "eps_next_fy",
    "total_revenue_ttm": "revenue",
    "total_revenue_yoy_growth_ttm": "revenue_growth",
    "gross_margin_ttm": "gross_margin",
    "operating_margin_ttm": "operating_margin",
    "net_margin_ttm": "net_margin",
    "net_income_ttm": "net_income",
    "ebitda_ttm": "ebitda",
    "cash_f_operating_activities_ttm": "ocf",
    "capital_expenditures_ttm": "capex",
    "free_cash_flow_ttm": "fcf",
    "free_cash_flow_margin_ttm": "fcf_margin",
    "return_on_equity_fq": "roe",
    "return_on_invested_capital_fq": "roic",
    # how fragile it is
    "debt_to_equity_fq": "debt_to_equity",
    "current_ratio_fq": "current_ratio",
    "total_debt_fq": "debt",
    "cash_n_short_term_invest_fq": "cash",
    "total_shares_outstanding_fundamental": "shares",
    # earnings and the analysts
    "earnings_release_date": "earnings_last",
    "earnings_release_next_date": "earnings_next",
    "eps_surprise_percent_fq": "eps_surprise",
    "revenue_surprise_percent_fq": "revenue_surprise",
    "recommendation_mark": "analyst_mark",
    "price_target_average": "target_avg",
    "price_target_high": "target_high",
    "price_target_low": "target_low",
}
DATE_FIELDS = {"earnings_last", "earnings_next"}
TEXT_FIELDS = {"ticker", "name", "sector", "industry"}

RETRY_WAITS = (2, 6, 15)
GIVE_UP_AFTER = 3


def _post(url: str, payload: dict, timeout: int, sleep) -> dict:
    body = json.dumps(payload).encode()
    for wait in RETRY_WAITS + (None,):
        req = urllib.request.Request(url, data=body, method="POST", headers={
            **HEADERS, "Content-Type": "application/json",
            "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or wait is None:
                raise
            sleep(wait)


# ------------------------------------------------------------------ scanner

def scan(min_cap: float = 3e8, tickers: list = None, timeout: int = 60,
         sleep=time.sleep) -> dict:
    """{symbol: fields} for every US stock above `min_cap`, or for `tickers`.

    Symbols come back in Nasdaq's spelling (BRK/B, not BRK.B), so a row joins
    straight onto the Nasdaq screener.
    """
    payload = {"columns": list(COLUMNS), "range": [0, 8000]}
    if tickers:
        payload["symbols"] = {"tickers": list(tickers)}
    else:
        payload.update({
            "markets": ["america"],
            "filter": [
                {"left": "market_cap_basic", "operation": "greater", "right": min_cap},
                # "dr" = depositary receipts: foreign companies listed here
                # (Alibaba, Novartis, Nokia), which a beginner thinks of as stocks.
                {"left": "type", "operation": "in_range", "right": ["stock", "dr"]},
                # Listed on a US exchange - NOT "primary listing", which would
                # drop Novartis and Nokia, whose home market is abroad.
                {"left": "exchange", "operation": "in_range",
                 "right": ["NYSE", "NASDAQ", "AMEX", "CBOE"]},
            ],
            "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        })
    return parse_scan(_post(SCAN_URL, payload, timeout, sleep))


def parse_scan(data: dict) -> dict:
    out = {}
    names = list(COLUMNS.values())
    for row in (data or {}).get("data") or []:
        values = row.get("d") or []
        if len(values) != len(names):
            continue
        rec = {}
        for key, value in zip(names, values):
            if key in DATE_FIELDS:
                rec[key] = _date(value)
            elif key in TEXT_FIELDS:
                rec[key] = (value or "").strip() if isinstance(value, str) else ""
            else:
                rec[key] = _round(value)
        exchange, _, ticker = (row.get("s") or "").partition(":")
        ticker = (rec.get("ticker") or ticker).upper()
        if not ticker:
            continue
        rec["tv_symbol"] = row.get("s") or ""
        rec["exchange"] = exchange
        out[ticker.replace(".", "/")] = rec
    return out


def tv_symbol(symbol: str, row: dict = None) -> str:
    """The EXCHANGE:TICKER form the news endpoint wants."""
    if row and row.get("tv_symbol"):
        return row["tv_symbol"]
    return symbol.replace("/", ".")


def _round(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value:  # NaN
        return None
    return round(float(value), 4) if abs(value) < 1e6 else round(float(value))


def _date(value) -> str:
    if not isinstance(value, (int, float)) or value <= 0:
        return ""
    return datetime.fromtimestamp(value, timezone.utc).date().isoformat()


# ---------------------------------------------------------------- headlines

# Law-firm press releases are written AFTER a stock falls, to recruit
# plaintiffs. They are an effect of the drop, never its cause, and a beginner
# reading "INVESTOR ALERT: class action" would reasonably think it was the news.
LAWYER_AD_RE = re.compile(
    r"law firm|investor alert|shareholder alert|investors? (?:who|with) (?:lost|losses)"
    r"|class action (?:lawsuit )?(?:filed|deadline|reminder)|lead plaintiff"
    r"|deadline alert|investigation notice|notifies investors|on behalf of .* investors|encourages .* investors|reminds .* investors"
    r"|rosen|pomerantz|levi & korsinsky|bragar|faruqi|glancy|bronstein|schall"
    r"|suewallst|kessler topaz|robbins geller|gross law|portnoy|frank r\. cruz|howard g\. smith",
    re.I)


def headlines(symbol: str, timeout: int = 20) -> list:
    return parse_headlines(get_json(NEWS_URL.format(
        symbol=urllib.parse.quote(symbol, safe=":")), timeout, HEADERS))


def parse_headlines(data: dict) -> list:
    """[{title, on, published_ts, source, url}] newest first, lawyer ads removed."""
    out, seen = [], set()
    for item in (data or {}).get("items") or []:
        title = re.sub(r"\s+", " ", (item.get("title") or "")).strip()
        published = item.get("published")
        if not title or not isinstance(published, (int, float)):
            continue
        if LAWYER_AD_RE.search(title):
            continue
        key = title.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        when = datetime.fromtimestamp(published, timezone.utc)
        path = item.get("storyPath") or ""
        out.append({
            "title": title,
            "on": when.date().isoformat(),
            "published_ts": when.isoformat(timespec="seconds"),
            "source": item.get("source") or item.get("provider") or "",
            "url": item.get("link") or (STORY_URL.format(path=path) if path else ""),
        })
    out.sort(key=lambda h: h["published_ts"], reverse=True)
    return out


def headlines_many(symbols: dict, workers: int = 3, pause: float = 0.2,
                   timeout: int = 20, fetch=None) -> tuple:
    """({symbol: headlines}, [(symbol, why)]) for {symbol: tv_symbol}.

    Bounded concurrency and the same circuit breaker as the Nasdaq history
    fetcher: three refusals in a row mean a block, and the rest of the run
    should not keep knocking.
    """
    fetch = fetch or (lambda s: headlines(s, timeout))
    out, failures = {}, []
    lock = threading.Lock()
    refusals = [0]

    def one(item):
        symbol, tv = item
        with lock:
            if refusals[0] >= GIVE_UP_AFTER:
                failures.append((symbol, "skipped after repeated refusals"))
                return
        try:
            got = fetch(tv)
            with lock:
                out[symbol] = got
                refusals[0] = 0
        except urllib.error.HTTPError as exc:
            with lock:
                if exc.code in (403, 429):
                    refusals[0] += 1
                failures.append((symbol, f"HTTP {exc.code}"))
        except Exception as exc:  # one bad symbol never sinks the rest
            with lock:
                failures.append((symbol, f"{type(exc).__name__}: {exc}"))
        if pause:
            time.sleep(pause)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, symbols.items()))
    return out, failures
