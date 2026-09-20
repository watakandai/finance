"""Macro time series from FRED, without an API key.

FRED's graph export - `fredgraph.csv?id=DGS10` - serves the same numbers as the
keyed API as plain CSV, which matters for two reasons: a fork of this repo
works with no credentials at all, and there is nothing to rotate or leak in
the daily workflow.

One request per series. FRED will happily return several at once, but it sends
them as a ZIP of separate CSVs with the per-series dates re-aligned into one
grid, which is exactly wrong for series published on different calendars -
a weekly and a monthly series merged onto one axis produce holes that look
like missing data rather than like different cadences.

`cosd` pins the start date. It is not optional: FRED's default graph window is
per-series (ten years for the S&P, three for high-yield spreads) and a z-score
computed over whatever window FRED happened to choose is not a z-score.
"""
from __future__ import annotations
import csv
import io
import time
from datetime import date, datetime, timedelta

from ..models import Observation
from .base import get_text

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"


class FredFetcher:
    """Fetches the FRED series behind a set of indicators.

    `series_map` is {FRED id: [this project's series ids]}, so PCEPILFE fetched
    once feeds both the year-over-year and the 3-month-annualised indicator.
    """

    name = "fred"

    def __init__(self, series_map: dict, years: int = 12, timeout: int = 30,
                 pause: float = 0.3, sleep=time.sleep):
        self.series_map = series_map
        self.years = years
        self.timeout = timeout
        # A courtesy gap between requests. Fifty-odd sequential calls to a free
        # public service deserve it, and FRED does throttle bursts.
        self.pause = pause
        self.sleep = sleep
        self.failures: list[tuple[str, str]] = []

    def fetch(self) -> list:
        start = (date.today() - timedelta(days=int(365.25 * self.years))).isoformat()
        out, self.failures = [], []
        for i, (fred_id, local_ids) in enumerate(sorted(self.series_map.items())):
            if i and self.pause:
                self.sleep(self.pause)
            try:
                text = get_text(CSV_URL.format(sid=fred_id, start=start), self.timeout)
            except Exception as exc:  # one dead series must not cost the other 53
                self.failures.append((fred_id, f"{type(exc).__name__}: {exc}"))
                continue
            rows = parse_csv(text, fred_id)
            if not rows:
                self.failures.append((fred_id, "no observations"))
                continue
            for local_id in local_ids:
                out.extend(
                    Observation(series_id=local_id, on=on, value=value, source="fred")
                    for on, value in rows
                )
        return out


def parse_csv(text: str, fred_id: str = "") -> list:
    """[(date, value)] from a fredgraph CSV, oldest first.

    FRED writes "." for a missing observation - a market holiday, a series that
    starts later than the window. Those rows are dropped rather than
    interpolated: a holiday is not a value, and carrying the previous number
    forward would invent trading days that did not exist.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    # The date column has been named both DATE and observation_date; take the
    # value from the last column instead of matching on the series id, because
    # FRED lowercases and suffixes some of them.
    if len(header) < 2:
        return []
    out = []
    for row in reader:
        if len(row) < 2:
            continue
        raw = (row[-1] or "").strip()
        if not raw or raw == ".":
            continue
        try:
            on = datetime.strptime(row[0].strip(), "%Y-%m-%d").date()
            value = float(raw)
        except ValueError:
            continue
        out.append((on, value))
    out.sort()
    return out
