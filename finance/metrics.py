"""Turning a column of numbers into the two or three facts worth knowing.

A dashboard that prints the latest value of sixty series is a worse version of
FRED. What makes a number decision-useful is context, and context here is
exactly four questions:

1. **What is it now** - the level, after the transform its indicator asks for.
2. **Which way is it going** - over a day, a month, a quarter, a year.
3. **Is this unusual** - a z-score and a percentile against its own history,
   which is the only way "high-yield spreads are 2.7%" becomes "tighter than
   93% of the last five years".
4. **When does it change next** - which the calendar answers.

Two decisions in here are worth knowing about:

- **Everything is looked up by DATE, never by row offset.** A year ago is
  `today - 365 days`, not "twelve rows back", because series have gaps -
  holidays in daily data, a missed survey month, a revision that adds a row -
  and index arithmetic on a gapped series silently compares the wrong periods.
- **A change is absolute for a rate and proportional for a price.** The 10-year
  going from 4.0% to 4.5% is "up 50bp", not "up 12.5%"; the S&P doing the same
  thing is a percentage. Getting this backwards is the most common way a
  finance dashboard produces numbers that are technically correct and
  completely unreadable.
"""
from __future__ import annotations
import math
from datetime import date, timedelta

# Series whose unit is an index number but which are read as levels, so a
# change in them is a difference rather than a percentage. Financial-conditions
# indices are centred on zero, where a percentage change is meaningless (and
# divides by zero on the way through).
LEVEL_INDICES = {"nfci", "stlfsi", "sentiment", "loan_standards", "gdp_now",
                 "gdp_growth"}

# Windows each series is measured over, as (label, days), chosen per cadence.
# A monthly series has no "1 day ago", and reporting one anyway just prints the
# same number under four labels - which reads as four confirmations of a move
# that was measured once.
WINDOWS_BY_CADENCE = {
    "daily": (("1d", 1), ("1w", 7), ("1m", 30), ("3m", 91), ("1y", 365)),
    "weekly": (("1w", 7), ("1m", 30), ("3m", 91), ("1y", 365)),
    "monthly": (("1m", 31), ("3m", 92), ("6m", 183), ("1y", 366)),
    "quarterly": (("3m", 92), ("1y", 366)),
}


def shift_months(d: date, months: int) -> date:
    """`d` moved by whole months, clamped to the end of a short month."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, [31, 29 if _leap(year) else 28, 31, 30, 31, 30, 31, 31,
                      30, 31, 30, 31][month - 1])
    return date(year, month, day)


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def value_asof(values: list, when: date):
    """The last value on or before `when`, or None if the series starts later.

    `values` is [(date, value)] oldest first - the shape `db.series_values`
    returns. Linear scan from the end: series are at most a few thousand rows
    and the answer is almost always within the last few.
    """
    for on, value in reversed(values):
        if on <= when:
            return value
    return None


def change_kind(unit: str, series_id: str = "", transform_kind: str = "") -> str:
    """"abs" for a rate or a centred index, "pct" for a price or a quantity.

    A `chg1` series is always absolute, whatever its unit: it is already a
    difference, and the percentage change of a difference ("payroll growth is up
    671%") is a number nobody can interpret.
    """
    if transform_kind == "chg1" or series_id in LEVEL_INDICES:
        return "abs"
    unit = (unit or "").strip()
    return "abs" if ("%" in unit or unit in ("pp", "bp")) else "pct"


def transform(values: list, kind: str) -> list:
    """Apply an indicator's transform, returning [(date, value)] again.

    The output is a series, not a single number, because the page draws a
    sparkline of the transformed value - a chart of the CPI *index* is a
    straight line up and to the right and says nothing, while a chart of its
    year-over-year rate is the whole story.
    """
    if not values:
        return []
    if kind == "level":
        return list(values)
    if kind == "yoy":
        out = []
        for on, value in values:
            prior = value_asof(values, shift_months(on, -12))
            if prior:
                out.append((on, 100.0 * (value / prior - 1.0)))
        return out
    if kind == "ann3":
        out = []
        for on, value in values:
            prior = value_asof(values, shift_months(on, -3))
            if prior and prior > 0:
                # Compounded, not multiplied by four: a 0.5% quarterly rise is
                # 2.02% annualised, and for inflation the difference between
                # those two conventions is regularly the difference between a
                # print that reads on-target and one that does not.
                out.append((on, 100.0 * ((value / prior) ** 4 - 1.0)))
        return out
    if kind == "chg1":
        return [(values[i][0], values[i][1] - values[i - 1][1])
                for i in range(1, len(values))]
    if kind == "avg4":
        out = []
        for i in range(len(values)):
            window = [v for _, v in values[max(0, i - 3): i + 1]]
            out.append((values[i][0], sum(window) / len(window)))
        return out
    raise ValueError(f"unknown transform {kind!r}")


def zscore(values: list, since: date = None):
    """How many standard deviations the latest value sits from its own mean.

    Returns None rather than 0.0 for a flat or too-short series: "no variation
    to compare against" is not the same claim as "exactly average".
    """
    sample = [v for on, v in values if since is None or on >= since]
    if len(sample) < 12:
        return None
    mean = sum(sample) / len(sample)
    var = sum((v - mean) ** 2 for v in sample) / (len(sample) - 1)
    sd = math.sqrt(var)
    if sd <= 1e-12:
        return None
    return (sample[-1] - mean) / sd


def percentile(values: list, since: date = None):
    """Where the latest value falls in its own distribution, 0-100."""
    sample = [v for on, v in values if since is None or on >= since]
    if len(sample) < 12:
        return None
    latest = sample[-1]
    below = sum(1 for v in sample if v < latest)
    equal = sum(1 for v in sample if v == latest)
    # Ties share their span, so a series pinned at one value reads 50 rather
    # than 0 or 100.
    return 100.0 * (below + 0.5 * equal) / len(sample)


def moving_average(values: list, days: int):
    """Mean of the last `days` calendar days, or None if the window is thin."""
    if not values:
        return None
    cutoff = values[-1][0] - timedelta(days=days)
    sample = [v for on, v in values if on > cutoff]
    # Half a window is the floor: a "200-day average" over 30 observations is
    # a different statistic wearing the same name.
    if len(sample) < max(5, days // 4):
        return None
    return sum(sample) / len(sample)


def summarize(series, values: list, today: date = None) -> dict:
    """Everything the page and the LLM need about one indicator.

    `series` is an `indicators.Series`; `values` is its raw stored history.
    Returns {} when there is nothing to say, so a source that failed today
    drops out of the dashboard instead of rendering as a zero.
    """
    today = today or date.today()
    if not values:
        return {}
    if series.scale != 1.0:
        values = [(on, v * series.scale) for on, v in values]
    shaped = transform(values, series.transform)
    if not shaped:
        return {}
    on, value = shaped[-1]
    kind = change_kind(series.unit, series.id, series.transform)
    lookback = today - timedelta(days=series.lookback_days)

    changes = {}
    windows = WINDOWS_BY_CADENCE.get(series.cadence, WINDOWS_BY_CADENCE["monthly"])
    for label, days in windows:
        prior = value_asof(shaped[:-1], on - timedelta(days=days))
        if prior is None:
            continue
        if kind == "pct" and abs(prior) > 1e-12:
            changes[label] = round(100.0 * (value / prior - 1.0), 2)
        elif kind == "abs":
            changes[label] = round(value - prior, 4)

    out = {
        "id": series.id,
        "label": series.label,
        "family": series.family,
        "tier": series.tier,
        "unit": series.unit,
        "decimals": series.decimals,
        "cadence": series.cadence,
        "release": series.release,
        "good": series.good,
        "as_of": on.isoformat(),
        "value": round(value, 4),
        "change_kind": kind,
        "changes": changes,
        "why": series.why,
        "up_means": series.up_means,
        "down_means": series.down_means,
        "watch": series.watch,
        # Enough points for a sparkline. Daily series are thinned rather than
        # truncated so a year of trend still fits in ~60 points.
        "spark": _spark(shaped, today),
    }
    z = zscore(shaped, lookback)
    if z is not None:
        out["z"] = round(z, 2)
    p = percentile(shaped, lookback)
    if p is not None:
        out["pct_rank"] = round(p, 1)
    out["lookback_years"] = round(series.lookback_days / 365.25, 1)

    if series.cadence == "daily":
        ma200 = moving_average(shaped, 200)
        if ma200:
            out["ma200"] = round(ma200, 4)
            if abs(ma200) > 1e-12:
                out["vs_ma200"] = round(100.0 * (value / ma200 - 1.0), 2)
        year = [v for d, v in shaped if d > on - timedelta(days=365)]
        if len(year) > 30:
            high, low = max(year), min(year)
            out["high_52w"], out["low_52w"] = round(high, 4), round(low, 4)
            if high > 1e-12:
                out["off_high_52w"] = round(100.0 * (value / high - 1.0), 2)
    return out


SPARK_POINTS = 60


def _spark(shaped: list, today: date) -> list:
    """Up to 60 [date, value] pairs over the last two years, evenly thinned."""
    cutoff = today - timedelta(days=730)
    window = [(on, v) for on, v in shaped if on >= cutoff] or shaped[-SPARK_POINTS:]
    step = max(1, -(-len(window) // SPARK_POINTS))
    thinned = window[::step]
    # Always keep the true last point: thinning by stride can drop it, and a
    # sparkline whose end does not match the number printed beside it is worse
    # than no sparkline.
    if thinned[-1] != window[-1]:
        thinned.append(window[-1])
    return [[on.isoformat(), round(v, 4)] for on, v in thinned]


def snapshot(values: list, today: date = None) -> dict:
    """Percentage moves over the standard windows, for a market price.

    Used for the cross-asset table, where the question is only "what has moved
    and over what horizon" - no transform, no z-score, no explanation.
    """
    today = today or date.today()
    if not values:
        return {}
    on, value = values[-1]
    out = {"as_of": on.isoformat(), "value": round(value, 4), "changes": {}}
    for label, days in (("1d", 1), ("1w", 7), ("1m", 30), ("3m", 91), ("1y", 365)):
        prior = value_asof(values[:-1], on - timedelta(days=days))
        if prior and abs(prior) > 1e-12:
            out["changes"][label] = round(100.0 * (value / prior - 1.0), 2)
    # Anchored on the last close of the PREVIOUS year, not on 1 January: no
    # market trades on New Year's Day, so a 1 January anchor finds nothing and
    # silently drops the YTD column every year. A series with no prior-year
    # history falls back to its own first print of this year, which is the
    # honest reading of "year to date" for something that started mid-year.
    ytd = value_asof(values[:-1], date(on.year - 1, 12, 31))
    if ytd is None:
        this_year = [v for d, v in values[:-1] if d.year == on.year]
        ytd = this_year[0] if this_year else None
    if ytd and abs(ytd) > 1e-12:
        out["changes"]["ytd"] = round(100.0 * (value / ytd - 1.0), 2)
    return out
