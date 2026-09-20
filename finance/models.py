"""The three shapes this project moves around.

A finance curator is not one feed, it is two planes that have to be read
together, plus the schedule that connects them:

- `Item` is news - a Fed statement, a wire story, a bank's note, a Reddit
  thread. Flat and source-agnostic for the same reason as in the sibling
  technews project: dedupe, impact scoring, ranking and the page all work on
  the union rather than on per-source special cases.
- `Observation` is one number in one time series on one date. CPI, the 10-year
  yield, high-yield spreads and the S&P all land here, which is what lets
  `metrics` and `regime` compute over them without caring who published them.
- `CalEvent` is something scheduled - a CPI print, an FOMC decision, an
  auction. This is the plane most news readers miss: what moves a market this
  week is usually on a calendar published weeks ago.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class Item:
    """One piece of news, from any source."""

    source: str
    source_id: str  # stable dedupe key within a source (id, permalink, guid)
    title: str
    # Where the story actually lives. For an aggregator this is the outbound
    # article, NOT the comment thread - that is what makes the same story
    # carried by four outlets collapse into one row.
    url: str = ""
    discussion_url: str = ""
    author: str = ""
    published: datetime | None = None
    summary: str = ""
    # Raw crowd signal in whatever unit the source counts in. Never compared
    # across sources directly - `popularity` normalizes per source. Most
    # finance sources publish none at all, which is why `impact` exists.
    points: int = 0
    comments: int = 0
    metric: str = "points"
    rank: int = 0
    tags: list[str] = field(default_factory=list)
    image: str = ""
    # Editorial tier of the publisher, set by the fetcher and used by
    # `impact`. 1 = primary source (a central bank, a statistical agency, a
    # company filing): the thing itself, not a report about it.
    tier: int = 3

    def __post_init__(self) -> None:
        if not self.url:
            self.url = self.discussion_url


@dataclass
class Observation:
    """One value of one series on one date.

    `series_id` is this project's own id (see `indicators.SERIES`), not the
    provider's, so the same series could be re-sourced without touching the
    stored history.
    """

    series_id: str
    on: date
    value: float
    source: str = ""


@dataclass
class CalEvent:
    """Something scheduled that markets trade around.

    `estimated` is load-bearing and must never be quietly dropped. An FOMC
    date scraped from the Fed's own calendar is a fact; "CPI lands around the
    12th" is this project's own inference from the publication rule, and the
    page marks the two differently because acting on a guessed date is worse
    than having no date.
    """

    event_id: str  # stable across re-generation: "cpi-2026-10-13"
    on: date
    title: str
    kind: str  # release | decision | auction | market | earnings
    # 1 = reliably moves the whole market, 2 = moves a sector or sets up a 1,
    # 3 = context.
    importance: int = 2
    time_et: str = ""
    indicator: str = ""  # the metric id this release updates, when there is one
    detail: str = ""
    url: str = ""
    estimated: bool = True
    source: str = ""
