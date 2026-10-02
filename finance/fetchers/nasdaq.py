"""Prices for individual stocks and ETFs, from Nasdaq's public quote API.

This replaced Yahoo's chart endpoint, which 429'd every run from GitHub's
runners - the cross-asset section of the page was empty for its first week of
daily runs because of it. Nasdaq serves the same data with no key, and it
offers something Yahoo never did: the whole US listing in one request.

Two endpoints:

- `screener()` - every US-listed stock (~7,000 rows) with today's price, daily
  move, volume, market cap, sector and industry, in a single response. This is
  what makes the stock lists possible without one request per company.
- `history()` - daily closes for one symbol. Needed for anything the screener
  cannot say on its own: the 1-month move, the 52-week high, how far a stock
  has fallen from it.

The API sits behind Akamai and expects to be called like a browser - a browser
user agent plus an Origin/Referer from nasdaq.com. Without those it hangs until
the timeout rather than refusing, which is why the headers are not optional.
"""
from __future__ import annotations
import threading
import time
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from ..models import Observation
from .base import BROWSER_AGENT, get_json

SCREENER_URL = ("https://api.nasdaq.com/api/screener/stocks"
                "?tableonly=true&limit=10000&download=true")
IPO_URL = "https://api.nasdaq.com/api/ipo/calendar?date={month}"
HISTORY_URL = ("https://api.nasdaq.com/api/quote/{sym}/historical"
               "?assetclass={cls}&fromdate={start}&limit={limit}")
HEADERS = {
    "User-Agent": BROWSER_AGENT,
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}

# Same policy as the LLM ranker: a short wait clears a burst limit, three
# consecutive refusals mean a block that will not clear this run.
RETRY_WAITS = (2, 6, 15)
GIVE_UP_AFTER = 3


def _get(url: str, timeout: int, sleep) -> dict:
    for wait in RETRY_WAITS + (None,):
        try:
            return get_json(url, timeout, HEADERS)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or wait is None:
                raise
            sleep(wait)


# ----------------------------------------------------------------- screener

def screener(timeout: int = 40, sleep=time.sleep) -> list:
    """Every US-listed stock, one dict per symbol. See `parse_screener`."""
    return parse_screener(_get(SCREENER_URL, timeout, sleep))


def parse_screener(data: dict) -> list:
    """Clean rows from a screener response.

    Nasdaq sends every number as a display string ("$172.84", "4.549%",
    "48728583125.00") and uses "" or "NA" for unknowns. Rows missing a price
    are dropped: a stock that did not trade is not something to list.
    """
    rows = (((data or {}).get("data") or {}).get("rows")) or []
    out = []
    for row in rows:
        symbol = (row.get("symbol") or "").strip().upper()
        price = _num(row.get("lastsale"))
        if not symbol or price is None:
            continue
        out.append({
            "symbol": symbol,
            "name": clean_name(row.get("name") or ""),
            "price": price,
            "pct_today": _num(row.get("pctchange")),
            "volume": int(_num(row.get("volume")) or 0),
            "market_cap": _num(row.get("marketCap")) or 0.0,
            "sector": (row.get("sector") or "").strip(),
            "industry": (row.get("industry") or "").strip(),
        })
    return out


# Legal-entity and share-class boilerplate. Nasdaq's names are the security's
# formal title ("Cloudflare, Inc. Class A Common Stock"), and nobody - least of
# all a beginner reading a list - thinks of a company that way.
_NAME_TAIL = (
    " american depositary shares", " american depositary share", " ads",
    " class a common stock", " class b common stock", " class c capital stock",
    " class a ordinary shares", " ordinary shares", " common stock",
    " common shares", " capital stock", " depositary shares", " sponsored",
    " series a", " series b", " series c", " adr",
)
_NAME_SUFFIX = (
    " (the)", ", inc.", " inc.", " inc", ", corp.", " corp.", " corporation", " corp",
    " holdings", " holding", ", ltd.", " ltd.", " ltd", " plc", " n.v.",
    " s.a.", " co.", " company", " limited", " group", ",",
)


def clean_name(name: str) -> str:
    text = " ".join(name.split())
    lower = text.lower()
    for tail in _NAME_TAIL:
        idx = lower.find(tail)
        if idx > 0:
            text, lower = text[:idx], lower[:idx]
    changed = True
    while changed:
        changed = False
        for suffix in _NAME_SUFFIX:
            if lower.endswith(suffix) and len(text) > len(suffix) + 1:
                text, lower = text[: -len(suffix)].rstrip(), lower[: -len(suffix)].rstrip()
                changed = True
    return text.strip(" ,.")


def _num(value):
    if value is None:
        return None
    text = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
    if not text or text.upper() in ("NA", "N/A", "--"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


# --------------------------------------------------------------------- IPOs

# Blank-cheque shells: companies that exist only to buy another company, and
# whose units trade under a U/W/R suffix. They are most of the IPO calendar by
# count and none of it by interest.
SPAC_RE = __import__("re").compile(
    r"acquisition|merger|blank check|capital (?:corp|investment)|spac\b", __import__("re").I)


def recent_ipos(months: int = 12, today: date = None, timeout: int = 25,
                pause: float = 0.3, sleep=time.sleep) -> list:
    """[{symbol, name, priced}] for operating companies that listed recently.

    A hand-written list of tech companies cannot know about one that listed
    last month, so this is how new names reach the tech-favourites search.
    """
    today = today or date.today()
    out, seen = [], set()
    year, month = today.year, today.month
    for i in range(months):
        if i and pause:
            sleep(pause)
        data = _get(IPO_URL.format(month=f"{year}-{month:02d}"), timeout, sleep)
        out.extend(r for r in parse_ipos(data) if r["symbol"] not in seen
                   and not seen.add(r["symbol"]))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


def parse_ipos(data: dict) -> list:
    rows = ((((data or {}).get("data") or {}).get("priced") or {}).get("rows")) or []
    out = []
    for row in rows:
        symbol = (row.get("proposedTickerSymbol") or "").strip().upper()
        name = (row.get("companyName") or "").strip()
        if not symbol or not name or SPAC_RE.search(name):
            continue
        if len(symbol) >= 5 and symbol[-1] in "UWR":
            continue  # a unit, warrant or right, not the shares themselves
        try:
            priced = datetime.strptime((row.get("pricedDate") or "").strip(), "%m/%d/%Y").date()
        except ValueError:
            priced = None
        out.append({"symbol": symbol, "name": clean_name(name),
                    "priced": priced.isoformat() if priced else ""})
    return out


# ------------------------------------------------------------------ history

class NasdaqHistoryFetcher:
    """Daily closes for a set of symbols, stored as observations.

    `symbol_map` is {symbol: (series_ids, assetclass)} where assetclass is
    "stocks" or "etf" - Nasdaq routes the two differently and answers the wrong
    one with an empty table rather than an error. `series_ids` is one id or a
    list: IWM is both the small-cap indicator and a row in the cross-asset
    table, and one request should feed both.

    `since` is {series_id: last stored date}. A symbol with history already in
    the database only asks for the last few weeks, which turns a 400-row
    request into a 20-row one - the difference between a polite daily job and a
    heavy one when the list is a hundred-odd symbols long.
    """

    name = "nasdaq"

    def __init__(self, symbol_map: dict, since: dict = None, days: int = 400,
                 timeout: int = 25, pause: float = 0.3, sleep=time.sleep,
                 today: date = None, workers: int = 3):
        self.symbol_map = symbol_map
        self.since = since or {}
        self.days = days
        self.timeout = timeout
        self.pause = pause
        self.sleep = sleep
        self.today = today or date.today()
        # A few requests in flight at once. Each one is ~1.5s of network latency,
        # so a hundred symbols one at a time is minutes of waiting; three at a
        # time is a gentle load that does not look like a burst. The refusal
        # breaker below still applies across all of them.
        self.workers = max(1, workers)
        self.failures: list[tuple[str, str]] = []
        self.rate_limited = False
        self._lock = threading.Lock()
        self._refusals = 0

    def _start(self, series_ids) -> date:
        # The oldest "last stored" date among the ids, so none of them gaps.
        known = [self.since.get(sid) for sid in series_ids]
        last = None if any(k is None for k in known) else min(known)
        full = self.today - timedelta(days=self.days)
        if last:
            # A week of overlap, so a late correction to the last stored close
            # is picked up rather than left stale.
            return max(full, last - timedelta(days=7))
        return full

    def fetch(self) -> list:
        self.failures, self.rate_limited, self._refusals = [], False, 0
        jobs = sorted(self.symbol_map.items())
        if self.workers == 1:
            results = [self._one(i, job) for i, job in enumerate(jobs)]
        else:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                results = list(pool.map(lambda pair: self._one(*pair), enumerate(jobs)))
        out = [obs for rows in results for obs in rows]
        # Failures arrive in completion order under threads; sort for stable logs.
        self.failures.sort()
        return out

    def _one(self, i: int, job) -> list:
        symbol, (series_ids, cls) = job
        if isinstance(series_ids, str):
            series_ids = [series_ids]
        if self.rate_limited:
            with self._lock:
                self.failures.append((symbol, "skipped (rate limited)"))
            return []
        if i >= self.workers and self.pause:
            self.sleep(self.pause)
        start = self._start(series_ids)
        limit = max(10, (self.today - start).days + 5)
        # The screener writes share classes as BRK/B; the history endpoint only
        # knows BRK.B.
        url = HISTORY_URL.format(sym=urllib.parse.quote(symbol.replace("/", ".")),
                                 cls=cls, start=start.isoformat(), limit=limit)
        try:
            rows = parse_history(_get(url, self.timeout, self.sleep), series_ids[0])
        except Exception as exc:
            with self._lock:
                self.failures.append((symbol, f"{type(exc).__name__}: {exc}"))
                if getattr(exc, "code", None) in (403, 429):
                    self._refusals += 1
                    if self._refusals >= GIVE_UP_AFTER:
                        self.rate_limited = True
                else:
                    self._refusals = 0
            return []
        with self._lock:
            self._refusals = 0
        out = list(rows)
        for extra in series_ids[1:]:
            out.extend(Observation(extra, o.on, o.value, o.source) for o in rows)
        return out


def parse_history(data: dict, series_id: str) -> list:
    """[Observation] from one historical response, oldest first.

    Stocks come back as "$225.07", ETFs as "771.35", dates as MM/DD/YYYY. An
    unknown symbol is not an HTTP error here: the API answers 200 with
    `data: null` and a status message, which is surfaced as an error so it lands
    in the failure list instead of silently producing nothing.
    """
    block = (data or {}).get("data")
    if not block:
        message = (((data or {}).get("status") or {}).get("bCodeMessage") or [{}])
        text = message[0].get("errorMessage") if message and isinstance(message[0], dict) else ""
        raise ValueError(text or "no data for symbol")
    rows = ((block.get("tradesTable") or {}).get("rows")) or []
    out = []
    for row in rows:
        close = _num(row.get("close"))
        try:
            on = datetime.strptime((row.get("date") or "").strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        if close is None:
            continue
        out.append(Observation(series_id=series_id, on=on, value=close, source="nasdaq"))
    out.sort(key=lambda o: o.on)
    return out
