"""How much this moves markets - a different question from "do I want to read it".

In the sibling tech-news project, crowd votes carry most of the ranking. Here
they carry almost none: a Federal Reserve statement has no upvotes and reprices
every asset on earth, while a Reddit thread about it has three hundred. So
`impact` is built from what actually predicts a market reaction, and it is kept
deliberately separate from `rank`'s relevance score. Two axes, because a desk
genuinely uses both:

    impact    = how big a deal is this for markets, for anyone
    relevance = would THIS person, with THIS portfolio, act differently

An item can be high on one and low on the other, and collapsing them into one
number destroys the information. The page shows both.

The five ingredients, in order of how much they contribute:

1. **Publisher tier.** A primary source publishing the thing itself (a central
   bank statement, an agency release, a company filing) outranks any amount of
   commentary about it. This is the single strongest signal available for free.
2. **Policy language.** Verbs and nouns that denote a decision with a price
   attached - cuts rates, imposes tariffs, downgrades, defaults, intervenes.
   Language about a decision is not the same as language about a topic, and
   this is where the difference is encoded.
3. **Scheduled-release mentions.** A story about CPI, payrolls or the FOMC is
   attached to an event the whole market is positioned around.
4. **Cross-source agreement.** Thirty outlets carrying one sentence is what a
   genuinely market-moving sentence looks like. This is also the only ingredient
   that needs the whole day's rows, which is why the module works on batches.
5. **Freshness, decayed by horizon.** A day-horizon item is worthless by
   tomorrow; a structural one is not. One decay curve for both would either
   bury the durable items or keep stale tape at the top, so there are three.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone

# --- 1. publisher tier ----------------------------------------------------
# Tier is set by the fetcher (feeds.json for RSS, hard-coded for the crowd
# sources). The gap between 1 and 2 is intentionally large: it is the gap
# between the decision and a report of the decision.
TIER_POINTS = {1: 30, 2: 14, 3: 8, 4: 0}

# --- 2. policy and price language ----------------------------------------
# Weighted by how reliably each one has coincided with a repricing. The top
# group is a decision with a number attached; the second is a decision without
# one; the third is a material corporate or market event.
DECISION_PATTERNS = (
    (26, r"\b(?:cuts?|raises?|hikes?|lowers?|lifts?) (?:rates?|the target|interest rates?)\b"
         r"|\b(?:rate cut|rate hike|basis[- ]point (?:cut|hike|move))\b"
         r"|\bholds? rates? steady\b|\bkeeps? rates? unchanged\b"
         r"|\bemergency (?:cut|meeting|facility|lending)\b"
         r"|\bintervene[sd]?\b|\bintervention\b"
         r"|\bdefault(?:s|ed)?\b|\bmoratorium\b"),
    (20, r"\btariffs? (?:on|of|to)\b|\bimposes?\b|\bban(?:s|ned)\b"
         r"|\bsanctions? (?:on|against)\b|\bexport controls?\b"
         r"|\bshutdown\b|\bdebt ceiling\b|\bdowngrade[sd]?\b"
         r"|\bunexpectedly\b|\bsurprise[sd]?\b|\bhotter than expected\b"
         r"|\bcooler than expected\b|\bmisses? (?:estimates|expectations)\b"
         r"|\bcuts? (?:guidance|forecast|outlook)\b|\bprofit warning\b"
         r"|\bhalts?\b|\bsuspends?\b|\bbankrupt\w*\b|\bchapter 11\b"),
    (12, r"\bacquires?\b|\bacquisition\b|\bmerger\b|\btakeover\b"
         r"|\bbuyback\b|\bstake\b|\bipo\b|\bspin-?off\b"
         r"|\brecord (?:high|low)\b|\ball-?time high\b"
         r"|\bworst (?:day|week|month)\b|\bbest (?:day|week|month)\b"
         r"|\bbeats? (?:estimates|expectations)\b|\braises? guidance\b"
         r"|\bauction\b|\brefunding\b|\bissuance\b"),
)
COMPILED_DECISIONS = tuple((points, re.compile(body, re.I))
                           for points, body in DECISION_PATTERNS)

# --- 3. the scheduled releases the whole market is positioned around ------
BIG_RELEASE_RE = re.compile(
    r"\b(?:cpi|core cpi|pce|core pce|ppi|payrolls?|nonfarm|jobs report|"
    r"unemployment rate|jobless claims|fomc|dot plot|"
    r"fed (?:decision|minutes|chair|statement)|rate decision|"
    r"gdp|ism|retail sales|jackson hole|beige book|"
    r"treasury (?:auction|refunding))\b",
    re.I,
)

# Routine institutional housekeeping. A central bank or a regulator publishes a
# great deal that is procedurally necessary and financially inert - enforcement
# actions against one small bank, merger approvals, appointments, requests for
# comment. Without this, tier 1 alone carries them to the top of the page, which
# is exactly what happened the first time this ran.
ADMIN_RE = re.compile(
    r"\b(?:enforcement actions?|consent orders?|cease and desist|"
    r"civil money penalt(?:y|ies)|announces? approval|approves? (?:the )?application|"
    r"application (?:by|of|to)\b|"
    r"seeks? comment|requests? comment|request for comment|comment period|"
    r"proposed rule|notice of proposed|proposal to modif\w+|regulatory burden|"
    r"joint readout|readout of|"
    r"appoint(?:s|ed|ment)|names? new|elects?|to (?:retire|step down)|"
    r"technical (?:amendment|correction)|availability of|"
    r"publishes? (?:the )?(?:agenda|schedule)|"
    r"conferences?|symposi(?:um|a)|workshops?|call for papers|"
    r"annual report|semiannual report|holiday schedule)\b",
    re.I,
)

# Categories that mean "this matched no finance vocabulary at all". Several of
# these feeds carry a publication's whole front page, so a non-trivial share of
# what arrives is not financial news.
OFFTOPIC_CATEGORIES = {"other", ""}

# Items whose titles are structurally low-information, whatever the source.
# The finance-specific ones matter: a "stocks to watch" list and a daily
# market-wrap headline are the bulk of the volume from the wires, and neither
# contains a fact.
FILLER_RE = re.compile(
    r"\b(?:sponsored|advertisement|promoted|"
    r"stocks? to watch|stocks? making the biggest moves|"
    r"what to watch|things to know|here'?s what|"
    r"top (?:\d+ )?(?:stocks?|picks?|plays?)|best (?:stocks?|etfs?)|"
    r"jim cramer|cramer|analyst says|price target|"
    r"should you buy|is it time to buy|"
    r"open thread|daily discussion|weekly discussion|rate my portfolio|"
    r"newsletter|roundup|digest|live updates?|"
    r"how much you need|millionaire|retire early)\b",
    re.I,
)

# --- 5. decay, per horizon -----------------------------------------------
# Half-lives in hours. Tape decays in half a day, a setup over a few days, a
# structural change over a fortnight - and even then it is floored, because a
# tariff regime announced last month is still the reason a sector is repricing.
HALF_LIFE = {"day": 10.0, "week": 60.0, "months": 336.0}
DECAY_FLOOR = {"day": 0.0, "week": 0.10, "months": 0.45}


def hours_old(row: dict, now: datetime = None) -> float:
    now = now or datetime.now(timezone.utc)
    stamp = row.get("published_ts") or row.get("first_seen")
    if not stamp:
        return 48.0
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return 48.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (now - when).total_seconds() / 3600.0)


def freshness(hours: float, horizon: str) -> float:
    half = HALF_LIFE.get(horizon, HALF_LIFE["week"])
    floor = DECAY_FLOOR.get(horizon, DECAY_FLOOR["week"])
    return floor + (1.0 - floor) * 0.5 ** (hours / half)


def cluster_sources(rows: list) -> dict:
    """{row id: set of sources that carried this same story}."""
    members = {}
    for row in rows:
        key = row.get("cluster_key")
        if key:
            members.setdefault(key, set()).add(row["source"])
    return {
        row["id"]: members.get(row.get("cluster_key") or "", {row["source"]})
        for row in rows
    }


def _text(row: dict) -> str:
    return " ".join([row.get("title") or "", (row.get("summary") or "")[:300]])


def score_row(row: dict, sources: set, horizon: str, now: datetime = None,
              category: str = "") -> tuple:
    """(0-100, one-line explanation) for one row. Pure function of its inputs."""
    text = _text(row)
    why = []
    score = 8.0  # a floor, so an unremarkable item is not indistinguishable
                 # from one that was actively penalised

    tier = int(row.get("tier") or 3)
    score += TIER_POINTS.get(tier, 8)
    if tier <= 1:
        why.append("primary source")

    category = category or row.get("category") or ""
    if category in OFFTOPIC_CATEGORIES:
        # Applied before the tier bonus can be inherited by a front-page story
        # about citrus farming that happens to come from a tier-2 outlet.
        score -= 22
        why.append("no market subject matched")

    for points, pattern in COMPILED_DECISIONS:
        match = pattern.search(text)
        if match:
            score += points
            why.append(f"“{match.group(0).strip().lower()}”")
            # First (highest-weighted) match only: a headline containing three
            # decision words is not three times the decision.
            break

    if BIG_RELEASE_RE.search(text):
        score += 14
        why.append("scheduled release the market trades")

    if len(sources) > 1:
        # Capped at three extra outlets. Beyond that the marginal outlet is
        # syndication, not corroboration.
        score += min(18, 7 * (len(sources) - 1))
        why.append(f"carried by {len(sources)} sources")

    age = hours_old(row, now)
    score *= 0.45 + 0.55 * freshness(age, horizon)
    if age <= 8:
        why.append("fresh")

    if FILLER_RE.search(row.get("title") or ""):
        score -= 28
        why.append("low-information format")
    elif ADMIN_RE.search(row.get("title") or ""):
        # Large enough to cancel most of a tier-1 bonus. A supervisory notice
        # about one small bank is published by the same institution, through the
        # same feed, as an FOMC statement, and nothing else in this function can
        # tell them apart.
        score -= 34
        why.append("routine institutional notice")

    # A crowd thread is evidence of attention, not of importance, so it lifts
    # the score a little and can never carry it.
    popularity = row.get("popularity")
    if popularity is not None and popularity >= 60:
        score += 6
        why.append("widely discussed")

    return round(max(0.0, min(100.0, score)), 1), ", ".join(why[:3]) or "routine coverage"


def impact_scores(rows: list, horizons: dict = None, now: datetime = None) -> dict:
    """{row id: (impact, reason, horizon)} for every row.

    `horizons` is {row id: horizon} from `categorize.horizon`, passed in rather
    than recomputed so the caller can let an LLM-assigned horizon win.
    """
    agreement = cluster_sources(rows)
    horizons = horizons or {}
    out = {}
    for row in rows:
        horizon = horizons.get(row["id"]) or row.get("horizon") or "week"
        impact, reason = score_row(row, agreement.get(row["id"], {row["source"]}),
                                   horizon, now, row.get("category") or "")
        out[row["id"]] = (impact, reason, horizon)
    return out
