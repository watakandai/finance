"""FOMC meeting dates, scraped from the Fed's own calendar.

These are the most valuable dates in the file and the only ones this project
can state as fact: the Fed publishes the whole next year in advance, so a
scrape gives confirmed dates rather than an inference from a publication rule.

The parse is deliberately narrow - two CSS class names the page has used for
years - and fails loudly rather than guessing, because `calendar_rules`
carries a shipped copy of the same dates as a fallback. A silent partial parse
that produced three of eight meetings would be worse than no parse at all.

The decision, and therefore the market event, is the LAST day of a two-day
meeting: the statement lands at 14:00 ET with the press conference at 14:30.
Minutes follow three weeks later, which the Fed states on this same page, so
those are generated here too - they move rates less often than the statement
but they are where the argument inside the committee becomes visible.
"""
from __future__ import annotations
import calendar
import re
from datetime import date, timedelta

from ..models import CalEvent
from .base import get_text

URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

YEAR_RE = re.compile(r">(\d{4}) FOMC Meetings</a>(.*?)(?=<div class=\"panel panel-default\">|\Z)", re.S)
MEETING_RE = re.compile(
    r'fomc-meeting__month[^>]*>\s*(?:<strong>)?([A-Za-z]+)(?:/([A-Za-z]+))?(?:</strong>)?\s*</div>'
    r'.*?fomc-meeting__date[^>]*>\s*([^<]+?)\s*</div>',
    re.S,
)
# Both spellings: the page writes full names for single-month meetings and
# abbreviations for the ones that straddle a month end ("Apr/May").
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})


class FomcFetcher:
    """Confirmed FOMC decision dates, plus the minutes three weeks later."""

    name = "fomc"

    def __init__(self, timeout: int = 25):
        self.timeout = timeout

    def fetch(self) -> list:
        return parse(get_text(URL, self.timeout))


def parse(html_text: str) -> list:
    events = []
    for year_str, block in YEAR_RE.findall(html_text):
        year = int(year_str)
        for first_month, second_month, raw in MEETING_RE.findall(block):
            decided = _decision_date(year, first_month, second_month, raw)
            if not decided:
                continue
            # The asterisk on the page marks a meeting that also publishes the
            # Summary of Economic Projections - the dot plot. Those meetings
            # move the curve more than the others, because the committee is
            # publishing a forecast rather than only a decision.
            sep = "*" in raw
            notation = "notation" in raw.lower()
            events.append(CalEvent(
                event_id=f"fomc-{decided.isoformat()}",
                on=decided,
                title="FOMC decision" + (" + dot plot (SEP)" if sep else ""),
                kind="decision",
                importance=1,
                time_et="14:00" if not notation else "",
                indicator="fed_funds",
                detail=(
                    "Statement at 14:00 ET, Chair's press conference at 14:30. "
                    + ("This meeting also publishes the Summary of Economic "
                       "Projections - the dot plot - which reprices the whole "
                       "curve, not just the next meeting."
                       if sep else
                       "No projections at this meeting, so the statement wording "
                       "and the press conference carry all of the signal.")
                ) if not notation else "Notation vote - no press conference.",
                url=URL,
                estimated=False,
                source="federalreserve.gov",
            ))
            # Two Wednesdays before the meeting. The Beige Book is the
            # committee's own read on the twelve districts and is the last
            # scheduled Fed publication before the blackout period starts.
            beige = decided - timedelta(days=14)
            events.append(CalEvent(
                event_id=f"fomc-beige-{beige.isoformat()}",
                on=beige,
                title="Beige Book",
                kind="release",
                importance=3,
                time_et="14:00",
                detail="Anecdotal reports from the twelve Reserve Banks, two "
                       "weeks before the decision. Rarely moves a market, but it "
                       "is the last thing the Fed publishes before the "
                       "communications blackout, and its language often turns up "
                       "verbatim in the statement.",
                url=URL,
                estimated=False,
                source="federalreserve.gov",
            ))
            minutes = decided + timedelta(days=21)
            events.append(CalEvent(
                event_id=f"fomc-minutes-{minutes.isoformat()}",
                on=minutes,
                title="FOMC minutes",
                kind="release",
                importance=2,
                time_et="14:00",
                detail="Released three weeks after the decision. Where the range "
                       "of views inside the committee becomes visible - a hawkish "
                       "minority that did not make the statement shows up here.",
                url=URL,
                estimated=False,
                source="federalreserve.gov",
            ))
    return events


def _decision_date(year: int, first_month: str, second_month: str, raw: str):
    """The last day of the meeting, from a cell like "17-18*" or "30-1".

    The awkward case is a meeting that straddles a month end, which the page
    writes as `Apr/May` + `30-1`: the second day is day 1 of the SECOND month,
    and in a December/January case it is also the next year.
    """
    days = [int(d) for d in re.findall(r"\d+", raw)]
    if not days:
        return None
    start_month = MONTHS.get(first_month.strip().lower())
    if not start_month:
        return None
    if not second_month:
        return date(year, start_month, days[-1])
    end_month = MONTHS.get(second_month.strip().lower())
    if not end_month:
        return date(year, start_month, days[-1])
    end_year = year + 1 if end_month < start_month else year
    return date(end_year, end_month, days[-1])
