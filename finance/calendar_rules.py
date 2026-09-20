"""The economic calendar, generated from publication rules.

Why this module exists at all: what moves a market this week is mostly on a
schedule published weeks ago. A curator that only reads news is always
reacting, and half of the value of watching macro is knowing that CPI lands on
Tuesday and that the position you are about to take has a known event risk
inside it.

Why it is rules rather than a feed: there is no free, machine-readable US
economic calendar. The BLS blocks automated clients outright, Census publishes
its schedule only through JavaScript, and the commercial calendars all want a
key. What there IS, is a publication rule per release that has held for
decades - claims every Thursday, payrolls the first Friday, ISM the first
business day - and those rules reconstruct the calendar to within a day or two.

So every date generated here carries `estimated=True`, and the page renders it
with a `~`. That flag is the whole design: it is honest about a date being this
project's inference, it lets `db.upsert_events` let a confirmed date (the FOMC
scrape) overwrite an inferred one and never the reverse, and it means a reader
who is about to trade around a print knows to check the agency's own page. An
approximate calendar clearly marked as approximate is useful; one presented as
fact is a trap.
"""
from __future__ import annotations
import calendar
from datetime import date, timedelta

from .models import CalEvent

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)
WEEKDAYS = {"monday": MON, "tuesday": TUE, "wednesday": WED, "thursday": THU,
            "friday": FRI, "saturday": SAT, "sunday": SUN}


# --------------------------------------------------------------- date maths

def easter(year: int) -> date:
    """Western Easter Sunday (Anonymous Gregorian computus).

    Needed only for Good Friday, which is not a federal holiday but is a US
    market holiday - so a release lands on it and an options expiry does not.
    """
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = ((h + m - 7 * n + 114) % 31) + 1
    return date(year, month, day)


def nth_weekday(year: int, month: int, n: int, weekday: int) -> date:
    """The nth given weekday of a month; n=-1 means the last one."""
    if n > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))
    last = date(year, month, calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def federal_holidays(year: int) -> set:
    """US federal holidays, with the weekend-observance shift applied.

    Statistical agencies do not publish on these, so they move a release. The
    shift matters: July 4th on a Saturday closes the Friday, which is exactly
    the case where a naive "first business day" is wrong.
    """
    fixed = [(1, 1), (6, 19), (7, 4), (11, 11), (12, 25)]
    out = set()
    for month, day in fixed:
        d = date(year, month, day)
        if d.weekday() == SAT:
            d -= timedelta(days=1)
        elif d.weekday() == SUN:
            d += timedelta(days=1)
        out.add(d)
    out.add(nth_weekday(year, 1, 3, MON))    # MLK Day
    out.add(nth_weekday(year, 2, 3, MON))    # Washington's Birthday
    out.add(nth_weekday(year, 5, -1, MON))   # Memorial Day
    out.add(nth_weekday(year, 9, 1, MON))    # Labor Day
    out.add(nth_weekday(year, 10, 2, MON))   # Columbus Day
    out.add(nth_weekday(year, 11, 4, THU))   # Thanksgiving
    return out


def market_holidays(year: int) -> set:
    """Federal holidays as they apply to equity markets.

    Two differences, both real: the exchanges close on Good Friday and stay
    open on Columbus Day and Veterans Day.
    """
    out = {d for d in federal_holidays(year)
           if d not in {nth_weekday(year, 10, 2, MON), _observed(year, 11, 11)}}
    out.add(easter(year) - timedelta(days=2))
    return out


def _observed(year: int, month: int, day: int) -> date:
    d = date(year, month, day)
    if d.weekday() == SAT:
        return d - timedelta(days=1)
    if d.weekday() == SUN:
        return d + timedelta(days=1)
    return d


def is_business_day(d: date, holidays: set = None) -> bool:
    return d.weekday() < SAT and d not in (holidays or federal_holidays(d.year))


def nth_business_day(year: int, month: int, n: int) -> date:
    """The nth business day of a month; n=-1 means the last one."""
    holidays = federal_holidays(year)
    days = [date(year, month, day)
            for day in range(1, calendar.monthrange(year, month)[1] + 1)]
    business = [d for d in days if is_business_day(d, holidays)]
    return business[n - 1] if n > 0 else business[n]


def nearest_business_day(d: date, prefer: tuple = ()) -> date:
    """The closest business day to `d`, optionally preferring certain weekdays.

    `prefer` exists because the agencies do not publish on arbitrary days: CPI
    has landed on a Tuesday, Wednesday or Thursday almost every month for
    years, so nudging towards those is a better guess than rounding a weekend
    to the nearest Monday.
    """
    holidays = federal_holidays(d.year)
    for delta in (0, 1, -1, 2, -2, 3, -3):
        candidate = d + timedelta(days=delta)
        if not is_business_day(candidate, holidays):
            continue
        if not prefer or candidate.weekday() in prefer:
            return candidate
    for delta in (0, 1, -1, 2, -2, 3, -3, 4, -4):
        candidate = d + timedelta(days=delta)
        if is_business_day(candidate, holidays):
            return candidate
    return d


def month_iter(start: date, months: int):
    """(year, month) for `months` months beginning with `start`'s month."""
    year, month = start.year, start.month
    for _ in range(months):
        yield year, month
        month += 1
        if month > 12:
            year, month = year + 1, 1


# ------------------------------------------------------------------- rules
#
# `when` is read by `_dates_for`:
#   ("day", d, prefer)         nearest business day to day `d` of the month
#   ("nth_weekday", n, wd)     nth weekday; n=-1 is the last
#   ("business_day", n)        nth business day; n=-1 is the last
#   ("weekly", wd)             every week on that weekday
#   ("week_of", d, wd)         that weekday in the week containing day `d`.
#                              Used for the auction pair: an "nth Wednesday /
#                              nth Thursday" pair silently inverts in a month
#                              that starts on a Thursday, and a 30-year auction
#                              listed before the 10-year is simply wrong.
# `months` restricts a rule to certain calendar months.
#
# `detail` is the part a reader actually needs: not what the release is, but
# why the market cares and what specifically to look at when it lands.

RULES = (
    {
        "id": "cpi", "title": "CPI (consumer prices)", "importance": 1,
        "time_et": "08:30", "indicator": "core_cpi", "kind": "release",
        "when": ("day", 12, (TUE, WED, THU)),
        "detail": "The most heavily traded number of the month. Watch the "
                  "month-over-month core rate, not the annual headline: 0.2% "
                  "keeps a cutting cycle alive and 0.4% ends the argument. "
                  "Shelter is a third of the index and lags reality by about a "
                  "year, so a surprise usually comes from services elsewhere.",
        "rule": "BLS publishes the prior month between roughly the 10th and 15th",
        "url": "https://www.bls.gov/schedule/news_release/cpi.htm",
    },
    {
        "id": "ppi", "title": "PPI (producer prices)", "importance": 2,
        "time_et": "08:30", "indicator": "ppi", "kind": "release",
        "when": ("day", 15, (TUE, WED, THU)),
        "detail": "Costs upstream of the consumer, and the source of several PCE "
                  "components CPI does not measure - so a hot PPI moves core PCE "
                  "forecasts the same morning. Also the cleanest monthly read on "
                  "corporate margins.",
        "rule": "BLS publishes a day or two after CPI",
        "url": "https://www.bls.gov/schedule/news_release/ppi.htm",
    },
    {
        "id": "jobs", "title": "Employment Situation (payrolls)", "importance": 1,
        "time_et": "08:30", "indicator": "payrolls", "kind": "release",
        "when": ("nth_weekday", 1, FRI),
        "detail": "Payrolls, unemployment rate, participation and average hourly "
                  "earnings in one release, which is why it can move rates twice "
                  "in opposite directions inside a minute. The revisions to the "
                  "prior two months frequently matter more than the headline; the "
                  "3-month average is the honest read.",
        "rule": "BLS publishes on the first Friday of the month",
        "url": "https://www.bls.gov/schedule/news_release/empsit.htm",
    },
    {
        "id": "claims", "title": "Initial jobless claims", "importance": 2,
        "time_et": "08:30", "indicator": "claims", "kind": "release",
        "when": ("weekly", THU),
        "detail": "The only weekly read on the labour market, barely revised, and "
                  "a genuine leading indicator - firms file before a monthly "
                  "survey can see it. Use the 4-week average; the weekly number "
                  "is seasonal noise.",
        "rule": "Department of Labor publishes every Thursday",
        "url": "https://www.dol.gov/ui/data.pdf",
    },
    {
        "id": "pce", "title": "Personal income & outlays (core PCE)", "importance": 1,
        "time_et": "08:30", "indicator": "core_pce", "kind": "release",
        "when": ("business_day", -1),
        "detail": "The Fed's actual target measure, and the one its own forecasts "
                  "are written in. It arrives two weeks after CPI, so the surprise "
                  "is usually small - but when PCE and CPI disagree, PCE is the "
                  "one policy follows.",
        "rule": "BEA publishes near the end of the month for the prior month",
        "url": "https://www.bea.gov/data/personal-consumption-expenditures-price-index",
    },
    {
        "id": "retail", "title": "Retail sales", "importance": 2,
        "time_et": "08:30", "indicator": "retail_sales", "kind": "release",
        "when": ("day", 16, (TUE, WED, THU)),
        "detail": "Two thirds of the economy is consumption and this is the "
                  "monthly read on it. Nominal, so compare it to inflation, and "
                  "look at the control group that feeds GDP rather than the "
                  "headline.",
        "rule": "Census publishes mid-month for the prior month",
        "url": "https://www.census.gov/retail/index.html",
    },
    {
        "id": "ism_mfg", "title": "ISM manufacturing PMI", "importance": 2,
        "time_et": "10:00", "kind": "release",
        "when": ("business_day", 1),
        "detail": "A survey, so it is fast rather than accurate - and because it "
                  "is a diffusion index, 50 is the line between expansion and "
                  "contraction. The prices-paid component is an early inflation "
                  "read the Fed watches.",
        "rule": "ISM publishes on the first business day of the month",
        "url": "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/",
    },
    {
        "id": "ism_svcs", "title": "ISM services PMI", "importance": 2,
        "time_et": "10:00", "kind": "release",
        "when": ("business_day", 3),
        "detail": "Services are the larger and stickier half of the economy, and "
                  "the half where this cycle's inflation has lived. A services "
                  "PMI holding above 50 while manufacturing sits below it has "
                  "been the normal state, not a warning.",
        "rule": "ISM publishes on the third business day of the month",
        "url": "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/",
    },
    {
        "id": "gdp", "title": "GDP (advance estimate)", "importance": 2,
        "time_et": "08:30", "indicator": "gdp_growth", "kind": "release",
        "when": ("nth_weekday", -1, THU), "months": (1, 4, 7, 10),
        "detail": "Published so late that it mostly confirms what has already "
                  "traded. The value is in the composition: consumption and "
                  "investment are durable, inventories and net exports are not.",
        "rule": "BEA publishes the advance estimate in the last week of the "
                "month following the quarter",
        "url": "https://www.bea.gov/data/gdp/gross-domestic-product",
    },
    {
        "id": "jolts", "title": "JOLTS job openings", "importance": 3,
        "time_et": "10:00", "indicator": "job_openings", "kind": "release",
        "when": ("day", 9, (TUE, WED, THU)),
        "detail": "Vacancies per unemployed worker is the measure behind the "
                  "Fed's bet that it could cool wages without mass layoffs. Two "
                  "months stale, so it settles arguments rather than starting "
                  "them.",
        "rule": "BLS publishes about six weeks after the reference month",
        "url": "https://www.bls.gov/jlt/",
    },
    {
        "id": "umich_prelim", "title": "U. Michigan sentiment (preliminary)",
        "importance": 3, "time_et": "10:00", "indicator": "sentiment",
        "kind": "release", "when": ("nth_weekday", 2, FRI),
        "detail": "A weak forecaster of spending but a closely watched one, "
                  "because its inflation-expectations components are cited in Fed "
                  "speeches. Read those sub-indices, not the headline.",
        "rule": "University of Michigan publishes the preliminary reading on the "
                "second Friday",
        "url": "http://www.sca.isr.umich.edu/",
    },
    {
        "id": "confidence", "title": "Conference Board consumer confidence",
        "importance": 3, "time_et": "10:00", "kind": "release",
        "when": ("nth_weekday", -1, TUE),
        "detail": "More labour-market-weighted than the Michigan survey, so the "
                  "'jobs hard to get' component is the part with signal - it "
                  "tracks the unemployment rate with a short lead.",
        "rule": "Conference Board publishes on the last Tuesday of the month",
        "url": "https://www.conference-board.org/topics/consumer-confidence",
    },
    {
        "id": "housing", "title": "Housing starts & building permits",
        "importance": 3, "time_et": "08:30", "indicator": "housing_starts",
        "kind": "release", "when": ("day", 17, (TUE, WED, THU)),
        "detail": "The most rate-sensitive part of the economy, and it has led "
                  "most postwar recessions. Permits lead starts, and "
                  "single-family leads multi-family.",
        "rule": "Census publishes around the 17th",
        "url": "https://www.census.gov/construction/nrc/index.html",
    },
    {
        "id": "refunding", "title": "Treasury quarterly refunding", "importance": 2,
        "time_et": "08:30", "kind": "release",
        "when": ("nth_weekday", 1, WED), "months": (2, 5, 8, 11),
        "detail": "Where the government says how much duration it intends to sell "
                  "and at which maturities. In 2023 this single announcement "
                  "turned the long end around - issuance composition, not just "
                  "the deficit, is what sets the term premium.",
        "rule": "Treasury announces in the first week of February, May, August "
                "and November",
        "url": "https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding",
    },
    {
        "id": "auction_10y", "title": "10-year Treasury auction", "importance": 3,
        "time_et": "13:00", "indicator": "ust_10y", "kind": "auction",
        "when": ("week_of", 9, WED),
        "detail": "A weak auction - a high yield versus the pre-auction market, "
                  "poor bid-to-cover, dealers left holding the paper - is how "
                  "supply pressure becomes a same-day equity event.",
        "rule": "Treasury auctions the 10-year mid-month, usually the Wednesday "
                "of the week containing the 9th",
        "url": "https://www.treasurydirect.gov/auctions/upcoming/",
    },
    {
        "id": "auction_30y", "title": "30-year Treasury auction", "importance": 3,
        "time_et": "13:00", "indicator": "ust_30y", "kind": "auction",
        "when": ("week_of", 9, THU),
        "detail": "The long bond has the thinnest genuine demand of any Treasury, "
                  "so it is where fiscal scepticism shows up first.",
        "rule": "Treasury auctions the 30-year the day after the 10-year",
        "url": "https://www.treasurydirect.gov/auctions/upcoming/",
    },
    {
        "id": "earnings_open", "title": "Earnings season opens (big banks)",
        "importance": 2, "time_et": "before open", "kind": "earnings",
        "when": ("day", 14, (TUE, WED, THU, FRI)), "months": (1, 4, 7, 10),
        "detail": "The large banks report first and their loan-loss provisions, "
                  "net interest margins and consumer-credit commentary are the "
                  "earliest bottom-up read on credit for the whole quarter.",
        "rule": "The largest banks report in the second week of January, April, "
                "July and October",
        "url": "",
    },
    {
        "id": "opex", "title": "Monthly options expiry", "importance": 3,
        "time_et": "16:00", "kind": "market", "when": ("nth_weekday", 3, FRI),
        "detail": "Large open interest rolling off can move the index mechanically "
                  "and usually releases volatility that dealer hedging had been "
                  "suppressing. It is flow, not information - do not read it as a "
                  "signal about anything.",
        "rule": "Third Friday of every month",
        "url": "",
    },
    {
        "id": "quad_witching", "title": "Quarterly expiry & index rebalance",
        "importance": 2, "time_et": "16:00", "kind": "market",
        "when": ("nth_weekday", 3, FRI), "months": (3, 6, 9, 12),
        "detail": "Index futures, index options, stock options and single-stock "
                  "futures all expire together, alongside S&P index rebalancing. "
                  "One of the highest-volume days of the year, and the price "
                  "action carries even less information than usual.",
        "rule": "Third Friday of March, June, September and December",
        "url": "",
    },
    {
        "id": "jackson_hole", "title": "Jackson Hole symposium", "importance": 2,
        "time_et": "", "kind": "decision",
        "when": ("nth_weekday", 4, THU), "months": (8,),
        "detail": "The Kansas City Fed's annual conference, and traditionally "
                  "where a Chair signals a change of framework rather than of "
                  "rates - the 2020 average-inflation-targeting shift and the "
                  "2022 'pain' speech both landed here.",
        "rule": "Late August, usually the last full week - the Kansas City Fed "
                "announces the exact dates",
        "url": "https://www.kansascityfed.org/research/jackson-hole-economic-symposium/",
    },
)

BY_RULE_ID = {r["id"]: r for r in RULES}


def _dates_for(rule: dict, year: int, month: int) -> list:
    kind, *args = rule["when"]
    if kind == "day":
        day, prefer = args[0], (args[1] if len(args) > 1 else ())
        capped = min(day, calendar.monthrange(year, month)[1])
        return [nearest_business_day(date(year, month, capped), prefer)]
    if kind == "nth_weekday":
        return [nth_weekday(year, month, args[0], args[1])]
    if kind == "business_day":
        return [nth_business_day(year, month, args[0])]
    if kind == "week_of":
        anchor = date(year, month, min(args[0], calendar.monthrange(year, month)[1]))
        monday = anchor - timedelta(days=anchor.weekday())
        return [monday + timedelta(days=args[1])]
    if kind == "weekly":
        first = nth_weekday(year, month, 1, args[0])
        out, d = [], first
        while d.month == month:
            out.append(d)
            d += timedelta(days=7)
        return out
    raise ValueError(f"unknown recurrence {kind!r}")


def generate(start: date = None, months: int = 4, rules=RULES) -> list:
    """Every rules-derived event from `start` for `months` calendar months.

    Four months by default: long enough that the next FOMC, the next quarterly
    refunding and the next earnings season are all visible, short enough that
    the dates are still worth guessing at.
    """
    start = start or date.today()
    out = []
    for year, month in month_iter(start, months):
        for rule in rules:
            if rule.get("months") and month not in rule["months"]:
                continue
            for when in _dates_for(rule, year, month):
                if when < start:
                    continue
                out.append(CalEvent(
                    event_id=f"{rule['id']}-{when.isoformat()}",
                    on=when,
                    title=rule["title"],
                    kind=rule.get("kind", "release"),
                    importance=rule.get("importance", 3),
                    time_et=rule.get("time_et", ""),
                    indicator=rule.get("indicator", ""),
                    # The rule is part of the detail on purpose: a reader who
                    # can see WHY this project thinks the date is the 13th can
                    # judge how much to trust it.
                    detail=rule["detail"] + f" (Date inferred: {rule['rule']}.)",
                    url=rule.get("url", ""),
                    estimated=True,
                    source="rule",
                ))
    out.sort(key=lambda e: (e.on, e.importance, e.title))
    return out
