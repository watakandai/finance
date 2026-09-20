"""Daily closes for anything priced in a market, from Yahoo's chart endpoint.

FRED carries the S&P and the VIX, but it carries them a day or two late and it
does not carry gold, copper, futures or an ETF. A curator whose headline
market numbers are stale by a day is describing yesterday, so prices come from
here and macro comes from FRED.

No key, no crumb: the `chart` endpoint is public. It does insist on a browser
user agent, which is the only reason `BROWSER_AGENT` exists.

It also rate-limits bursts with a 429, so requests are spaced out and a 429 is
waited out rather than treated as a failure. Twenty-six symbols spaced by a
second is half a minute once a day, which is the polite way to use somebody
else's free endpoint - and when it refuses anyway, every headline market series
here also has a FRED id, so the dashboard degrades to yesterday's close instead
of going blank.
"""
from __future__ import annotations
import time
import urllib.error
import urllib.parse
from datetime import datetime, timezone

from ..models import Observation
from .base import BROWSER_AGENT, get_json

CHART_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
             "?range={range}&interval=1d")

# Waits after a 429, in seconds. Yahoo's limit is short-window, so a handful of
# seconds clears it; three tries and then give up on that symbol.
RETRY_WAITS = (2, 6, 15)

# After this many symbols in a row have exhausted their retries with a 429, stop
# asking. A wholesale block does not clear in twenty seconds, and grinding
# through the remaining symbols turns a failed fetch into a ten-minute one - in
# a daily workflow that is the difference between a degraded run and a timed-out
# job.
GIVE_UP_AFTER = 3


class YahooFetcher:
    """Daily closes for a list of Yahoo symbols.

    `symbol_map` is {Yahoo symbol: this project's series id}. Symbols that back
    no indicator (the snapshot ETFs) map to a `mkt:` id, which keeps them in
    the same observations table without pretending they are macro series.
    """

    name = "yahoo"

    def __init__(self, symbol_map: dict, range: str = "2y", timeout: int = 25,
                 pause: float = 1.0, sleep=time.sleep):
        self.symbol_map = symbol_map
        self.range = range
        self.timeout = timeout
        self.pause = pause
        self.sleep = sleep
        self.failures: list[tuple[str, str]] = []
        self.rate_limited = False

    def fetch(self) -> list:
        out, self.failures = [], []
        self.rate_limited = False
        consecutive_429s = 0
        for i, (symbol, series_id) in enumerate(sorted(self.symbol_map.items())):
            if self.rate_limited:
                self.failures.append((symbol, "skipped (rate limited)"))
                continue
            if i and self.pause:
                self.sleep(self.pause)
            url = CHART_URL.format(sym=urllib.parse.quote(symbol), range=self.range)
            try:
                out.extend(parse_chart(self._get(url), series_id))
                consecutive_429s = 0
            except Exception as exc:
                self.failures.append((symbol, f"{type(exc).__name__}: {exc}"))
                if getattr(exc, "code", None) == 429:
                    consecutive_429s += 1
                    if consecutive_429s >= GIVE_UP_AFTER:
                        self.rate_limited = True
                else:
                    consecutive_429s = 0
        return out

    def _get(self, url: str) -> dict:
        for wait in RETRY_WAITS + (None,):
            try:
                return get_json(url, self.timeout, {"User-Agent": BROWSER_AGENT})
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or wait is None:
                    raise
                self.sleep(wait)


def parse_chart(data: dict, series_id: str) -> list:
    """[Observation] from one chart response.

    Yahoo returns parallel arrays with `null` on days a given symbol did not
    trade, and its last row during market hours is the live price rather than a
    close. Both are kept as-is: an intraday value on today's date is what makes
    the dashboard current, and it is overwritten by the real close on the next
    run because observations are keyed by (series, date).
    """
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        error = ((data.get("chart") or {}).get("error") or {}).get("description")
        raise ValueError(error or "no chart result")
    block = result[0]
    stamps = block.get("timestamp") or []
    quotes = (block.get("indicators") or {}).get("quote") or [{}]
    closes = quotes[0].get("close") or []
    out = []
    for stamp, close in zip(stamps, closes):
        if close is None:
            continue
        # Yahoo timestamps the open of each session in exchange-local time;
        # taken as UTC the date is right for every market this tracks.
        on = datetime.fromtimestamp(stamp, timezone.utc).date()
        out.append(Observation(series_id=series_id, on=on, value=float(close),
                               source="yahoo"))
    return out
