"""Three lists of stocks, built from where attention is and what prices did.

The request this answers, in the reader's words: "trending stocks, hot stocks
that are dipping, and stocks that aren't so popular but are popular among tech
people." Each list is a screen - a filter over data - and every row carries the
reason it passed the filter, because a ticker with no reason attached teaches a
beginner nothing and invites them to guess.

What these lists are NOT is a set of recommendations. A stock trending on
Stocktwits is being argued about, not endorsed; a stock down 30% from its high
fell for a reason the market already knows; a stock engineers write about may
have a great product and a bad business. The one-line note at the top of each
list says exactly that, in plain words, and the row data is built so the next
question - "why?" - is one click away.

Everything here is a pure function of fetched data, so it is tested without the
network. The fetching lives in `cli._cmd_stocks`.
"""
from __future__ import annotations
import math
from datetime import date, timedelta

from .metrics import value_asof

# Market-cap bands, in the words a newcomer would use. The boundaries are the
# conventional large/mid/small-cap lines, with "giant" added because the top
# forty US companies are now each larger than whole national stock markets and
# behave differently from a merely large one.
SIZE_BANDS = (
    (200e9, "giant"),
    (10e9, "large"),
    (2e9, "mid-size"),
    (300e6, "small"),
    (0, "tiny"),
)

# "Everyone has heard of it." Above this, a company cannot be "not so popular"
# however quiet the forums are.
FAMOUS_CAP = 150e9
# What counts as a dip: a sharp fall over the past month, or a stock well below
# its 52-week high that is STILL falling. The second condition matters: a stock
# that peaked a year ago and has been climbing for a month is recovering, not
# dipping, and listing it under "falling" would teach exactly the wrong thing.
DIP_OFF_HIGH = -15.0
DIP_ONE_MONTH = -10.0
# Reddit mention counts below this are a handful of posts, not attention.
MIN_REDDIT_MENTIONS = 10
# Engineers mentioning a company in fewer than this many HN titles a month is
# background noise, not attention.
MIN_HN_STORIES = 3
# Reddit rank at or above which a stock is already a retail-crowd favourite.
RETAIL_POPULAR_RANK = 30

LIST_NOTES = {
    "watchlist": {
        "title": "My watchlist",
        "what": "Tickers you chose to follow, checked every day: how the price is "
                "moving, how far it is from its high of the past year, the most "
                "relevant recent headline, and whether investors or engineers are "
                "talking about it.",
        "careful": "Watching a stock closely makes every move feel important. Most "
                   "daily moves are noise - the one-month change and the headline "
                   "tell you far more than today's number.",
    },
    "trending": {
        "title": "Trending right now",
        "what": "The stocks individual investors are talking about most today, on "
                "Stocktwits and Reddit, with a summary of what the conversation "
                "is about.",
        "careful": "Trending means people are arguing about it, not that it is a "
                   "good investment. Stocks often trend because something just "
                   "went very right or very wrong - and by the time a stock is "
                   "trending, the news is already in the price.",
    },
    "dipping": {
        "title": "Popular, but falling",
        "what": "Well-known or much-discussed stocks that are well below their "
                "highest price of the past year, or that dropped sharply in the "
                "last month.",
        "careful": "A dip is not automatically a discount. Prices usually fall "
                   "for a reason - a weak earnings report, a lost customer, a "
                   "bigger worry about the industry. Find out why before assuming "
                   "it will bounce back; plenty of stocks never return to their "
                   "old high.",
    },
    "compare": {
        "title": "Compare",
        "what": "What you pay for each company next to what it earns - the same table for "
                "a chip giant, a burger chain, a cloud company that loses money and a car "
                "maker priced on its future, plus your watchlist. Tap a row for its full "
                "value card.",
        "careful": "A high multiple is not 'expensive' and a low one is not 'cheap'. A high "
                   "P/E means the price expects a lot of growth; always read it next to the "
                   "growth rate. No single number decides anything.",
    },
    "tech": {
        "title": "Popular with tech people",
        "what": "Companies software engineers are writing about on Hacker News "
                "this month - mostly businesses that sell to developers and other "
                "companies, so most people have never heard of them - and that "
                "the retail stock forums are not talking about. Most come from a "
                "hand-picked list of tech companies. Ones marked \"found "
                "automatically\" come from a search of every listed tech company "
                "and recent tech IPO - check the headline shown to confirm it is "
                "really about the company.",
        "careful": "Engineers talk about products, outages and technology, not "
                   "about whether a stock is fairly priced. A company can have a "
                   "product developers love and still be a poor investment - or "
                   "already be priced as if everyone knows how good it is.",
    },
}


# ------------------------------------------------------------------ facts

def size_label(market_cap: float) -> str:
    for floor, label in SIZE_BANDS:
        if (market_cap or 0) >= floor:
            return label
    return "tiny"


def money(value: float) -> str:
    """$5.4 trillion / $128 billion / $840 million - never "5.41e12"."""
    value = float(value or 0)
    for unit, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if value >= unit:
            scaled = value / unit
            return f"${scaled:.1f} {word}" if scaled < 100 else f"${scaled:.0f} {word}"
    return f"${value:,.0f}"


def _pct(now, then):
    if now is None or not then:
        return None
    return round(100.0 * (now / then - 1.0), 1)


def stock_facts(row: dict, history: list, today: date = None) -> dict:
    """Price context for one stock: moves, 52-week high, how far off it.

    `row` is a screener row; `history` is [(date, close)] oldest first, possibly
    empty - a stock whose history failed to fetch still gets its screener facts,
    just not the ones that need a past.
    """
    today = today or date.today()
    out = {
        "symbol": row["symbol"],
        "name": row.get("name") or row["symbol"],
        "price": row.get("price"),
        "pct_today": row.get("pct_today"),
        "market_cap": row.get("market_cap") or 0,
        "cap_text": money(row.get("market_cap") or 0),
        "size": size_label(row.get("market_cap") or 0),
        "sector": row.get("sector") or "",
        "industry": row.get("industry") or "",
    }
    if not history:
        return out
    last_on, last = history[-1]
    out["as_of"] = last_on.isoformat()
    out["chg_1w"] = _pct(last, value_asof(history[:-1], last_on - timedelta(days=7)))
    out["chg_1m"] = _pct(last, value_asof(history[:-1], last_on - timedelta(days=30)))
    out["chg_3m"] = _pct(last, value_asof(history[:-1], last_on - timedelta(days=91)))
    year = [(d, v) for d, v in history if d > last_on - timedelta(days=365)]
    if len(year) >= 20:
        high_on, high = max(year, key=lambda p: p[1])
        out["high_52w"] = round(high, 2)
        out["high_on"] = high_on.isoformat()
        out["off_high"] = _pct(last, high)
    # A few points for a sparkline: one per week keeps the payload small and is
    # plenty to show whether a line went up or down.
    out["spark"] = [[d.isoformat(), round(v, 2)] for d, v in history[-180::5]]
    return out


# ------------------------------------------------------------------ lists

def _stock_rows(screener: dict, symbols) -> list:
    return [screener[s] for s in symbols if s in screener]


def trending(screener: dict, histories: dict, stocktwits: list, reddit: list,
             universe: dict = None, limit: int = 10, today: date = None) -> list:
    """What retail investors are discussing most, with why.

    Stocktwits' order first - it is already a blend of message volume and
    acceleration - then Reddit risers it missed: a ticker whose mentions at
    least doubled in a day, from a base high enough to mean something.
    Symbols the stock screener does not know (ETFs, crypto, OTC) drop out here,
    because a beginner list mixing "QQQ" and "BTC.X" in with companies is a
    list of things that are not like each other.
    """
    universe = universe or {}
    reddit_by = {r["symbol"]: r for r in reddit}
    out, seen = [], set()

    for entry in stocktwits:
        symbol = entry["symbol"]
        if symbol in seen or symbol not in screener:
            continue
        seen.add(symbol)
        row = stock_facts(screener[symbol], histories.get(symbol, []), today)
        badges = [f"#{entry['rank']} trending on Stocktwits"]
        red = reddit_by.get(symbol)
        if red and red["mentions"] >= MIN_REDDIT_MENTIONS:
            badges.append(_reddit_badge(red))
        row.update({
            "list": "trending",
            "why": entry.get("summary") or "",
            "why_source": "Stocktwits" if entry.get("summary") else "",
            "badges": badges,
            "what": (universe.get(symbol) or {}).get("what", ""),
        })
        out.append(row)

    risers = sorted(
        (r for r in reddit
         if r["symbol"] not in seen and r["symbol"] in screener
         and r["mentions"] >= 25
         and r.get("mentions_24h_ago") is not None
         and r["mentions"] >= 2 * max(1, r["mentions_24h_ago"])),
        key=lambda r: -r["mentions"])
    for red in risers:
        seen.add(red["symbol"])
        row = stock_facts(screener[red["symbol"]], histories.get(red["symbol"], []), today)
        row.update({
            "list": "trending",
            "why": (f"Reddit mentions jumped from {red['mentions_24h_ago']} to "
                    f"{red['mentions']} in a day."),
            "why_source": "",
            "badges": [_reddit_badge(red)],
            "what": (universe.get(red["symbol"]) or {}).get("what", ""),
        })
        out.append(row)
    return out[:limit]


# First words of company names that say nothing on their own. "American" is
# not American Airlines, and "Advanced" is not AMD.
GENERIC_FIRST_WORDS = {
    "american", "first", "general", "united", "global", "national", "international",
    "advanced", "applied", "boston", "texas", "western", "southern", "northern",
    "new", "the", "royal", "bank", "digital", "energy", "health", "micro",
    "strategy", "open", "block", "target", "visa", "match", "arm", "snap",
    "unity", "box", "zoom", "sea", "on", "super", "intuitive", "palo",
}
# Tickers that are ordinary words or letters, so a whole-word match on them in a
# headline would mostly find the word.
AMBIGUOUS_TICKERS = {"A", "AI", "ALL", "ARE", "BE", "CAN", "FOR", "IT", "NOW",
                     "ON", "ONE", "OPEN", "S", "SO", "U", "UP", "YOU", "TV", "EU",
                     "CEO", "GDP", "CPI", "FED", "IPO", "ETF", "USA", "NET", "APP",
                     "KEY", "LOW", "FAST", "MAIN", "WELL", "PLAY", "RUN", "GO"}


# Tickers that collide with stock-forum vocabulary. ApeWisdom counts a ticker
# every time its letters appear, so "IP" (intellectual property), "DTE" (days to
# expiry), "DD" (due diligence) and "ALL" rank highly without anyone discussing
# International Paper, DTE Energy, DoorDash's old ticker or Allstate. Their
# Reddit counts are dropped; their Stocktwits and price data are unaffected.
REDDIT_NOISE_TICKERS = AMBIGUOUS_TICKERS | {
    "IP", "DD", "DTE", "ATH", "EV", "PM", "AM", "OR", "EOD", "IMO", "EPS", "TA",
    "PT", "OP", "ER", "RH", "BIG", "LOVE", "HOLD", "BUY", "SELL", "CASH", "MOON",
    "YOLO", "FOMO", "RSI", "GAIN", "LOSS", "RIP", "HUGE", "TOP", "BEAT", "WIN",
    "NEXT", "REAL", "FUN", "PUMP", "CALL", "PUT", "HAS", "SEE", "ANY", "OUT",
    "NICE", "FREE", "CAR", "HOME", "PLAN", "LIFE", "TECH", "NVDL", "WSB",
    "TP", "JUST", "SO", "VERY", "GOOD", "BAD", "EDIT", "POST", "MAKE", "TIME",
    # Not a word, but a wrong join: Reddit's "BYD" is the Chinese carmaker (which
    # trades over the counter as BYDDY), while BYD on a US exchange is Boyd
    # Gaming. Joining the two would pin electric-car chatter on a casino company.
    "BYD",
}


def clean_reddit(reddit: list) -> list:
    return [r for r in reddit if r["symbol"] not in REDDIT_NOISE_TICKERS]


def headline_for(row: dict, items: list):
    """The most market-relevant recent news item about this company, or None.

    Matched on the company's name - the full cleaned name, or its first word
    when that word is distinctive - and on the ticker when the ticker is not
    also an English word. Among matches, the highest-impact item wins, because
    the point is to answer "why is this moving", and a primary-source or
    widely-carried story answers that better than a passing mention.
    """
    import re as _re
    name = (row.get("name") or "").strip()
    terms = []
    if len(name) >= 3:
        terms.append(name)
    first = name.split()[0] if name else ""
    if len(first) >= 4 and first.lower() not in GENERIC_FIRST_WORDS:
        terms.append(first)
    symbol = row.get("symbol") or ""
    if len(symbol) >= 3 and symbol not in AMBIGUOUS_TICKERS and symbol.isalpha():
        terms.append(symbol)
    if not terms:
        return None
    pattern = _re.compile(r"(?<![\w])(?:" + "|".join(_re.escape(t) for t in terms)
                          + r")(?![\w])")
    matches = [it for it in items if pattern.search(it.get("title") or "")]
    if not matches:
        return None
    best = max(matches, key=lambda it: (it.get("impact") or 0,
                                        it.get("published_ts") or ""))
    return {
        "title": best["title"],
        "url": best.get("url") or best.get("discussion_url") or "",
        "source": best.get("source") or "",
        "published_ts": best.get("published_ts") or "",
    }


def _reddit_badge(red: dict) -> str:
    before = red.get("mentions_24h_ago")
    trend = f" (was {before})" if before is not None and before != red["mentions"] else ""
    return f"{red['mentions']} Reddit mentions today{trend}"


def hot_reasons(symbol: str, screener: dict, stocktwits: list, reddit: list,
                hn: dict) -> list:
    """Why a stock counts as "hot" - every reason that applies, in plain words."""
    reasons = []
    for entry in stocktwits:
        if entry["symbol"] == symbol:
            reasons.append(f"trending on Stocktwits (#{entry['rank']})")
            break
    for red in reddit:
        if red["symbol"] == symbol and red["rank"] <= RETAIL_POPULAR_RANK:
            reasons.append(f"#{red['rank']} most-mentioned on Reddit")
            break
    if (screener.get(symbol) or {}).get("market_cap", 0) >= SIZE_BANDS[0][0]:
        reasons.append("one of the largest companies on US exchanges")
    stories = (hn.get(symbol) or {}).get("stories", 0)
    if stories >= 5:
        reasons.append(f"in {stories} Hacker News headlines this month")
    return reasons


def dipping(screener: dict, histories: dict, stocktwits: list, reddit: list,
            hn: dict, universe: dict = None, limit: int = 12,
            today: date = None) -> list:
    """Stocks with a reason to be well known that are well off their high.

    Sorted by the fall over the past month, biggest first - that is the dip.
    How far below the 52-week high it sits, and when that high was set, are
    shown alongside, because "down 12% this month, 60% below a peak a year ago"
    and "down 12% this month from a record last week" are different stories.
    """
    universe = universe or {}
    out = []
    for symbol in candidates(screener, stocktwits, reddit, hn):
        reasons = hot_reasons(symbol, screener, stocktwits, reddit, hn)
        if not reasons:
            continue
        facts = stock_facts(screener[symbol], histories.get(symbol, []), today)
        if not is_dipping(facts):
            continue
        facts.update({
            "list": "dipping",
            "why": _dip_sentence(facts),
            "why_source": "",
            "badges": reasons,
            "what": (universe.get(symbol) or {}).get("what", ""),
        })
        out.append(facts)
    out.sort(key=lambda r: (r.get("chg_1m") if r.get("chg_1m") is not None else 0,
                            r.get("off_high") or 0))
    return out[:limit]


def is_dipping(facts: dict) -> bool:
    one_month, off_high = facts.get("chg_1m"), facts.get("off_high")
    if one_month is None:
        return False  # without a recent move there is no way to call it a dip
    if one_month <= DIP_ONE_MONTH:
        return True
    return off_high is not None and off_high <= DIP_OFF_HIGH and one_month < 0


def _dip_sentence(facts: dict) -> str:
    bits = []
    if facts.get("off_high") is not None and facts.get("high_on"):
        when = date.fromisoformat(facts["high_on"]).strftime("%b %-d")
        bits.append(f"{abs(facts['off_high']):.0f}% below its 52-week high "
                    f"(set {when})")
    if facts.get("chg_1m") is not None and facts["chg_1m"] < 0:
        bits.append(f"down {abs(facts['chg_1m']):.0f}% in the past month")
    return ("Now " + " and ".join(bits) + ".") if bits else ""


def candidates(screener: dict, stocktwits: list, reddit: list, hn: dict,
               reddit_top: int = RETAIL_POPULAR_RANK) -> list:
    """Every symbol worth fetching price history for, deduplicated, stable order.

    The giant companies are included by market cap from the screener, one symbol
    per company - Alphabet trades as GOOG and GOOGL, and listing both would be
    listing the same business twice.
    """
    out, seen = [], set()
    reddit = clean_reddit(reddit)

    def add(symbol):
        if symbol in screener and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)

    for entry in stocktwits:
        add(entry["symbol"])
    for red in reddit:
        if red["rank"] <= reddit_top:
            add(red["symbol"])
    by_name = {}
    for row in screener.values():
        if row.get("market_cap", 0) >= SIZE_BANDS[0][0]:
            best = by_name.get(row["name"])
            if best is None or row.get("volume", 0) > best.get("volume", 0):
                by_name[row["name"]] = row
    for row in sorted(by_name.values(), key=lambda r: -r["market_cap"]):
        add(row["symbol"])
    for symbol, counts in sorted(hn.items(), key=lambda kv: -kv[1].get("points", 0)):
        if counts.get("stories", 0) >= MIN_HN_STORIES:
            add(symbol)
    return out


# ------------------------------------------------------------- discovery
#
# tech_universe.json is precise but closed: a company engineers start talking
# about that nobody wrote into it can never appear. Discovery closes the gap by
# searching Hacker News for every technical listed company, plus every recent
# tech IPO - the names a hand-written list cannot know yet.
#
# Two earlier versions of this were thrown away, and the reasons are the design:
#
# - Scanning a month of headlines for all ~7,000 listed names matched ordinary
#   words and people: its top "tech favourites" were Trump Media (from
#   "Trump"), Union Pacific ("union") and a coal miner ("Alpha").
# - Restricting to technical sectors with a capitalisation test still passed
#   "Graham" (Paul Graham) and "Opera" (a cartoon title).
#
# What survives is a per-company search with two checks computed from the
# search results themselves (see social.count_mentions): the name must stand
# alone rather than inside a longer proper noun, and must not be mostly used as
# a lower-case word. Anything found this way is labelled on the page with the
# headline that triggered it, so a reader can judge the match.

# Which listed companies discovery considers. Technology and telecom outright;
# any other sector only when its industry is technical (chips, aerospace,
# instruments, machinery - robotics and space companies live there).
DISCOVERY_SECTORS = {"Technology", "Telecommunications"}
DISCOVERY_INDUSTRY_RE = __import__("re").compile(
    r"electr|semicond|aerospace|computer|software|machinery|instrument|"
    r"telecom|internet|data processing", __import__("re").I)
# Established companies need real size to be worth a look; a new listing is
# interesting smaller, because it has not had time to grow into the index.
DISCOVERY_MIN_CAP = 1e9
IPO_MIN_CAP = 3e8
# Generic trailing words that headlines drop: "Silicon Motion Technology" is
# written "Silicon Motion". Stripped only while two words remain - "Spectrum"
# alone is a word, "Silicon Motion" is a name.
NAME_TAIL_WORDS = {"international", "technologies", "technology", "systems",
                   "software", "networks", "solutions", "labs", "platforms",
                   "semiconductor", "semiconductors", "communications",
                   "holdings", "group", "global", "worldwide", "enterprises"}
# Proper nouns that are company names but mostly mean something else on HN.
DISCOVERY_STOPWORDS = {
    "america", "american", "apollo", "atlas", "mercury", "phoenix", "genesis",
    "orion", "nova", "titan", "summit", "pioneer", "frontier", "liberty", "eagle",
    "delta", "quantum", "integer", "strategy", "match", "block", "bandwidth",
    "national", "global", "united", "general", "first", "federal", "public",
}
# What a discovered company must show. Higher than the curated list's floor,
# because a person has not checked the name.
DISCOVERY_MIN_STORIES = 3
DISCOVERY_MIN_POINTS = 30


def search_name(name: str) -> str:
    words = name.split()
    while len(words) > 2 and words[-1].lower() in NAME_TAIL_WORDS:
        words = words[:-1]
    return " ".join(words)


def _technical(row: dict) -> bool:
    return bool(row.get("sector") in DISCOVERY_SECTORS
                or DISCOVERY_INDUSTRY_RE.search(row.get("industry") or ""))


def discovery_candidates(screener: dict, universe: dict, ipos: list = None) -> list:
    """[{ticker, query, ipo}] - listed tech companies the universe does not cover.

    One entry per company (Alphabet trades as GOOG and GOOGL; the busier share
    class wins), recent IPOs first so they survive any cap on the list.
    """
    ipo_dates = {i["symbol"]: i.get("priced", "") for i in (ipos or [])}
    by_name = {}
    for row in screener.values():
        symbol = row["symbol"]
        cap = row.get("market_cap", 0)
        is_ipo = symbol in ipo_dates
        name = search_name(row.get("name") or "")
        if (symbol in universe or not _technical(row) or len(name) < 4
                or name.lower() in DISCOVERY_STOPWORDS
                or cap < (IPO_MIN_CAP if is_ipo else DISCOVERY_MIN_CAP)):
            continue
        best = by_name.get(name)
        if best is None or row.get("volume", 0) > screener[best["ticker"]].get("volume", 0):
            by_name[name] = {"ticker": symbol, "query": name, "ipo": ipo_dates.get(symbol, "")}
    return sorted(by_name.values(), key=lambda c: (c["ticker"] not in ipo_dates, c["query"]))


def accept_discovered(counts: dict) -> bool:
    """Whether an automatically-searched company really is being talked about."""
    standalone = counts.get("standalone", 0)
    return (standalone >= DISCOVERY_MIN_STORIES
            and counts.get("standalone_points", 0) >= DISCOVERY_MIN_POINTS
            and counts.get("lower", 0) * 3 <= standalone)


def discovered(counts_by_ticker: dict, candidates: list) -> dict:
    """{ticker: counts} for the candidates that pass, tagged as automatic."""
    ipo = {c["ticker"]: c.get("ipo", "") for c in candidates}
    out = {}
    for ticker, counts in counts_by_ticker.items():
        if ticker in ipo and accept_discovered(counts):
            out[ticker] = {**counts, "found": "auto", "ipo": ipo[ticker],
                           # Report the conservative numbers, not the raw ones.
                           "stories": counts["standalone"],
                           "points": counts["standalone_points"]}
    return out


def _month(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%b %Y")
    except ValueError:
        return iso


def tech_favourites(screener: dict, histories: dict, hn: dict, reddit: list,
                    universe: dict, limit: int = 10, today: date = None) -> list:
    """Companies engineers write about that Wall Street's retail crowd doesn't.

    Four filters, each doing one job: enough Hacker News stories to be real
    attention; below the size where everyone already knows the name; not a
    household consumer brand (marked in tech_universe.json - HN mentions those
    as products, "posted on Reddit", not as companies); and not already a
    Reddit favourite. What is left is ordered by HN attention, with
    story points counted on a log scale so one viral post does not outrank a
    month of steady discussion.
    """
    retail = {r["symbol"] for r in reddit if r["rank"] <= RETAIL_POPULAR_RANK}
    rows = []
    for symbol, counts in hn.items():
        if symbol not in screener or counts.get("stories", 0) < MIN_HN_STORIES:
            continue
        if screener[symbol].get("market_cap", 0) >= FAMOUS_CAP or symbol in retail:
            continue
        if (universe.get(symbol) or {}).get("consumer"):
            continue
        attention = counts["stories"] + 3.0 * math.log1p(counts.get("points", 0))
        facts = stock_facts(screener[symbol], histories.get(symbol, []), today)
        headline = counts.get("top_title") or ""
        auto = counts.get("found") == "auto"
        facts.update({
            "list": "tech",
            "found": "auto" if auto else "curated",
            "attention": round(attention, 1),
            "why": (f"In {counts['stories']} Hacker News headlines this month"
                    + (f"; the most discussed: “{headline}”" if headline else "")
                    + "."),
            "why_source": "Hacker News",
            "why_url": counts.get("top_url") or "",
            "badges": [f"{counts['stories']} HN stories",
                       f"{counts.get('points', 0):,} points"]
                      + ([f"listed {_month(counts['ipo'])}"] if counts.get("ipo") else [])
                      + (["found automatically"] if auto else []),
            "what": (universe.get(symbol) or {}).get("what", ""),
        })
        rows.append(facts)
    rows.sort(key=lambda r: -r["attention"])
    return rows[:limit]


def attach_news(rows: list, items: list) -> list:
    """Give every row its most relevant recent headline.

    A row whose list gave it no explanation (Stocktwits only summarises its top
    few) gets the headline as its "why" - "in the news: ..." is a far better
    answer to a beginner's first question than an empty line.
    """
    for row in rows:
        news = headline_for(row, items) if items else None
        if news:
            row["news"] = news
            if not row.get("why"):
                row["why"] = f"In the news: {news['title']}"
                row["why_source"] = news["source"]
                row["why_url"] = news["url"]
    return rows


def synthetic_row(entry: dict, history: list) -> dict:
    """A screener-shaped row for a symbol the stock screener does not carry.

    That is every ETF, which is the likeliest thing a beginner adds. Price and
    today's move come from the last two closes; there is no market cap for a
    fund, so it gets none rather than a made-up one.
    """
    last = history[-1][1] if history else None
    prev = history[-2][1] if len(history) >= 2 else None
    return {
        "symbol": entry["symbol"],
        "name": entry.get("name") or entry["symbol"],
        "price": last,
        "pct_today": _pct(last, prev),
        "market_cap": 0,
        "sector": "Fund" if entry.get("kind") == "etf" else "",
        "industry": "",
    }


def screener_key(symbol: str, screener: dict) -> str:
    """The screener writes share classes as BRK/B; people type BRK.B."""
    if symbol in screener:
        return symbol
    alt = symbol.replace(".", "/")
    return alt if alt in screener else ""


def watchlist_rows(entries: list, screener: dict, histories: dict, stocktwits: list,
                   reddit: list, hn: dict, universe: dict = None,
                   today: date = None) -> list:
    """A full card for every ticker on the reader's own list, in their order.

    No filters: the reader chose these, so every one is shown whatever it did.
    The badges say where attention is, if anywhere, which is itself informative
    - a holding nobody is discussing is usually a calm one.
    """
    universe = universe or {}
    twits = {t["symbol"]: t for t in stocktwits}
    reds = {r["symbol"]: r for r in clean_reddit(reddit)}
    out = []
    for entry in entries:
        symbol = entry["symbol"]
        key = screener_key(symbol, screener)
        history = histories.get(symbol) or histories.get(key) or []
        base = dict(screener[key]) if key else synthetic_row(entry, history)
        base["symbol"] = symbol
        facts = stock_facts(base, history, today)
        badges = []
        if entry.get("kind") == "etf":
            badges.append("fund (ETF)")
        twit = twits.get(symbol) or twits.get(key)
        if twit:
            badges.append(f"#{twit['rank']} trending on Stocktwits")
        red = reds.get(symbol) or reds.get(key)
        if red and red["mentions"] >= MIN_REDDIT_MENTIONS:
            badges.append(_reddit_badge(red))
        counts = hn.get(symbol) or hn.get(key) or {}
        if counts.get("stories"):
            badges.append(f"{counts['stories']} Hacker News stories this month")
        what = (universe.get(symbol) or universe.get(key) or {}).get("what", "")
        if not what and entry.get("kind") == "etf":
            what = "A fund (ETF): one purchase buys a basket of many stocks or bonds."
        facts.update({
            "list": "watchlist",
            "why": (twit or {}).get("summary") or "",
            "why_source": "Stocktwits" if (twit or {}).get("summary") else "",
            "badges": badges,
            "what": what,
            "kind": entry.get("kind", "stock"),
            "added": entry.get("added", ""),
        })
        out.append(facts)
    return out


# The companies in the comparison table, always - a fixed reference set
# spanning the shapes a business can take (a chip giant, a burger chain, a
# loss-making cloud company, a car maker priced on its future) so any stock
# on the lists can be read against them. The watchlist is added to it.
REFERENCE = ("NVDA", "AMD", "META", "GOOGL", "MU", "MCD", "SBUX", "NET", "TSLA")
COMPARE_FIELDS = ("price", "eps", "pe", "ps", "p_fcf", "fcf_yield", "revenue_growth",
                  "gross_margin", "operating_margin", "roic", "debt_to_equity", "beta")


def compare_row(symbol: str, tv_row: dict) -> dict:
    """One row of the comparison table: what you pay, and what you get."""
    cap, fcf = tv_row.get("market_cap"), tv_row.get("fcf")
    row = {"symbol": symbol, "name": tv_row.get("name") or symbol,
           "industry": tv_row.get("industry") or ""}
    for field in COMPARE_FIELDS:
        row[field] = tv_row.get(field)
    row["fcf_yield"] = round(fcf / cap * 100, 2) if fcf is not None and cap else None
    if row["p_fcf"] is None and fcf and fcf > 0 and cap:
        row["p_fcf"] = round(cap / fcf, 1)
    if row["ps"] is None and tv_row.get("revenue") and cap:
        row["ps"] = round(cap / tv_row["revenue"], 1)
    return row


def build(screener: dict, histories: dict, stocktwits: list, reddit: list,
          hn: dict, universe: dict, items: list = None, today: date = None,
          watchlist: list = None, tv: dict = None, peers: dict = None,
          medians: dict = None, headlines: dict = None, risk_free: float = 4.2) -> dict:
    """All the lists plus the notes that explain them - the stocks.json body.

    `items` is recent news (dicts with title/url/source/impact), used only to
    explain rows; the lists themselves never depend on it. `tv`, `peers`,
    `medians` and `headlines` are the TradingView layer: fundamentals per
    symbol, market/industry moves, industry medians, and per-symbol news.
    Without them the lists still build - just without "why it fell" and the
    value card.
    """
    items = items or []
    reddit = clean_reddit(reddit)
    lists = {
        "watchlist": attach_news(watchlist_rows(
            watchlist or [], screener, histories, stocktwits, reddit, hn,
            universe, today=today), items),
        "trending": attach_news(trending(screener, histories, stocktwits, reddit,
                                         universe, today=today), items),
        "dipping": attach_news(dipping(screener, histories, stocktwits, reddit,
                                       hn, universe, today=today), items),
        "tech": attach_news(tech_favourites(screener, histories, hn, reddit,
                                            universe, today=today), items),
    }
    profiles = {}
    if tv:
        from . import drops as drop_mod, valuation
        for rows in lists.values():
            for row in rows:
                symbol = row["symbol"]
                tv_row = tv.get(symbol)
                if not tv_row:
                    continue
                if symbol not in profiles:
                    profiles[symbol] = valuation.profile(
                        tv_row, (medians or {}).get(tv_row.get("industry")), risk_free)
                row["earnings_next"] = tv_row.get("earnings_next") or ""
                history = histories.get(symbol) or []
                if drop_mod.needs_explaining(row, history):
                    row["fell"] = drop_mod.explain(
                        symbol, row, history, tv_row, peers or {},
                        (headlines or {}).get(symbol) or [], today=today)
    compare = []
    if tv:
        from . import valuation
        mine = [e["symbol"] for e in watchlist or []]
        for symbol in list(REFERENCE) + [m for m in mine if m not in REFERENCE]:
            tv_row = tv.get(symbol)
            if not tv_row:
                continue
            compare.append(dict(compare_row(symbol, tv_row), mine=symbol in mine))
            if symbol not in profiles:
                profiles[symbol] = valuation.profile(
                    tv_row, (medians or {}).get(tv_row.get("industry")), risk_free)
    return {"notes": LIST_NOTES, "lists": lists, "compare": compare,
            "profiles": {k: v for k, v in profiles.items() if v}}


def explain_targets(screener: dict, histories: dict, symbols, limit: int = 40,
                    today: date = None) -> list:
    """The symbols whose fall is worth explaining, worst first, capped - so the
    per-symbol headline requests stay a few dozen a day."""
    from .drops import needs_explaining
    out = []
    for symbol in symbols:
        if symbol not in screener:
            continue
        history = histories.get(symbol) or []
        facts = stock_facts(screener[symbol], history, today)
        if needs_explaining(facts, history):
            out.append((facts.get("chg_1m") or 0, symbol))
    return [s for _, s in sorted(out)[:limit]]
