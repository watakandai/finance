"""Who is talking about which stock: retail traders, and technologists.

Three sources, deliberately kept apart because they measure different crowds:

- **Stocktwits trending** - the thirty symbols retail traders are discussing
  most right now, each with a one-paragraph summary of *why*. That summary is
  the most beginner-useful thing in this whole project: it turns "MU is up 6%"
  into "Micron reported earnings and people are arguing about AI memory
  demand".
- **ApeWisdom** - mention counts across the big stock subreddits, now and
  24 hours ago. The change is the signal: a ticker going from 30 mentions to 95
  in a day is trending in a way a steady 95 is not.
- **Hacker News** - how often a company appears in story titles on the site
  where software engineers talk. This is the "popular among tech people"
  signal, and it is interesting precisely because it is uncorrelated with the
  other two: engineers write about Cloudflare's outage post-mortem, not its
  share price.

All three are free and keyless. None of them is a reason to own anything;
they are a map of where attention is, which is what the stock lists on the page
are for.
"""
from __future__ import annotations
import html
import re
import time
import urllib.parse

from .base import get_json

STOCKTWITS_URL = "https://api.stocktwits.com/api/2/trending/symbols.json"
APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}"
HN_URL = ("https://hn.algolia.com/api/v1/search?query={q}&tags=story"
          "&restrictSearchableAttributes=title&typoTolerance=false"
          "&numericFilters=created_at_i>{since}&hitsPerPage=100")



# ---------------------------------------------------------------- Stocktwits

def stocktwits_trending(timeout: int = 20) -> list:
    return parse_stocktwits(get_json(STOCKTWITS_URL, timeout))


def parse_stocktwits(data: dict) -> list:
    """[{symbol, title, score, summary, sector, watchers}] in trending order.

    Crypto (BTC.X) and anything Stocktwits does not class as an equity or ETF
    keep their row here; the list builder drops what it cannot price.
    """
    out = []
    for rank, row in enumerate((data or {}).get("symbols") or [], 1):
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        trends = row.get("trends") or {}
        out.append({
            "symbol": symbol,
            "title": (row.get("title") or "").strip(),
            "rank": rank,
            "score": float(row.get("trending_score") or 0.0),
            # Stocktwits' own generated summary of the discussion. Stored as
            # data and shown attributed; it is their text, not this project's.
            "summary": _tidy(trends.get("summary") or ""),
            "watchers": int(row.get("watchlist_count") or 0),
            "kind": (row.get("instrument_class") or "").strip().lower(),
        })
    return out


# ----------------------------------------------------------------- ApeWisdom

def apewisdom(pages: int = 2, timeout: int = 20, pause: float = 0.5,
              sleep=time.sleep) -> list:
    """The most-mentioned tickers across the big stock subreddits."""
    out = []
    for page in range(1, pages + 1):
        if page > 1 and pause:
            sleep(pause)
        out.extend(parse_apewisdom(get_json(APEWISDOM_URL.format(page=page), timeout)))
    return out


def parse_apewisdom(data: dict) -> list:
    out = []
    for row in (data or {}).get("results") or []:
        symbol = (row.get("ticker") or "").strip().upper()
        if not symbol:
            continue
        out.append({
            "symbol": symbol,
            # ApeWisdom HTML-escapes its names ("S&amp;P 500").
            "name": html.unescape(row.get("name") or "").strip(),
            "rank": int(row.get("rank") or 0),
            "rank_24h_ago": _int(row.get("rank_24h_ago")),
            "mentions": int(row.get("mentions") or 0),
            "mentions_24h_ago": _int(row.get("mentions_24h_ago")),
            "upvotes": int(row.get("upvotes") or 0),
        })
    return out


# --------------------------------------------------------------- Hacker News

def hn_mentions(universe: list, days: int = 30, timeout: int = 20,
                pause: float = 0.1, sleep=time.sleep, now: float = None,
                workers: int = 4) -> dict:
    """{ticker: {stories, points, top_title, top_url, top_points}} for a universe.

    One search per company, over story titles only. Two things make the count
    honest:

    - `typoTolerance=false`. Algolia is fuzzy by default, so "Datadog" matched
      "Datalog" and "Oklo" matched "Oslo" in the first probe of this.
    - A case-sensitive whole-word check on every returned title. Company names
      are proper nouns; requiring the capital letter is what stops "zoom in on"
      counting as Zoom and "unity of purpose" counting as Unity.

    A handful of searches run at once - Algolia's HN index is built for far more
    than this, and a hundred sequential round-trips is a minute of waiting.
    """
    since = int((now or time.time()) - days * 86400)
    failures = []

    def one(company):
        if pause:
            sleep(pause)
        query = company.get("query") or company["name"]
        url = HN_URL.format(q=urllib.parse.quote(query), since=since)
        try:
            hits = (get_json(url, timeout) or {}).get("hits") or []
        except Exception as exc:
            failures.append((company["ticker"], f"{type(exc).__name__}: {exc}"))
            return None
        return company["ticker"], count_mentions(hits, company.get("match") or query)

    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, universe))
    else:
        results = [one(c) for c in universe]
    hn_mentions.failures = sorted(failures)
    return dict(r for r in results if r)


_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9&.'+-]*")


def count_mentions(hits: list, term: str) -> dict:
    """How many titles name the company, and how confidently.

    Besides the plain count, two numbers exist for the automatic-discovery path,
    where the name has not been checked by a person:

    - `standalone` - titles where the name is not glued to a capitalised word in
      front of it. "Paul Graham" and "IBM Quantum" are other proper nouns that
      happen to contain a company's name; "Nokia" at the start of a title, or
      "on Garmin", is the company. (A Title Case headline capitalises every
      word, so it fails this test and is simply not counted - conservative on
      purpose.)
    - `lower` - titles using the name as an ordinary lower-case word. Algolia's
      search is case-insensitive, so these come back in the same results, and a
      name that is mostly a word ("quantum", "block") shows itself here.
    """
    pattern = re.compile(rf"(?<![\w.]){re.escape(term)}(?![\w])")
    lower_pattern = re.compile(rf"(?<![\w.]){re.escape(term.lower())}(?![\w])")
    matched = [h for h in hits if pattern.search(h.get("title") or "")]
    alone = [h for h in matched if _standalone(h.get("title") or "", pattern)]
    lower = (0 if term.islower() else
             sum(1 for h in hits if lower_pattern.search(h.get("title") or "")))
    top = max(matched, key=lambda h: int(h.get("points") or 0)) if matched else {}
    return {
        "stories": len(matched),
        "points": sum(int(h.get("points") or 0) for h in matched),
        "standalone": len(alone),
        "standalone_points": sum(int(h.get("points") or 0) for h in alone),
        "lower": lower,
        "top_title": (top.get("title") or "").strip(),
        "top_points": int(top.get("points") or 0),
        # The HN thread rather than the outbound link: the discussion is the
        # "why tech people care" part.
        "top_url": (f"https://news.ycombinator.com/item?id={top['objectID']}"
                    if top.get("objectID") else ""),
    }


def _standalone(title: str, pattern) -> bool:
    for match in pattern.finditer(title):
        before = _WORD_RE.findall(title[:match.start()])
        if not before or not before[-1][:1].isupper():
            return True
    return False


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()
