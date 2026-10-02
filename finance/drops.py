"""Why did it fall? An explanation built from evidence, not from a guess.

A beginner who sees "down 50% this month" asks one question, and the honest
answer has three parts that this module computes separately:

1. **How much of the fall was the stock at all?** A month's move splits into
   what the whole market did, what the company's industry did on top of that,
   and what is left - the part only this company can explain. A software
   stock down 20% in a month when software is down 17% is not a story about
   that company; it is a story about software.
2. **When did it happen?** Falls are rarely smooth. If most of a month's drop
   happened in one day, that day had a cause, and the news published that day
   is the best evidence of what it was. An earnings report two days earlier is
   better evidence still.
3. **What was said?** Headlines filed under the symbol, sorted into a small
   closed set of catalysts (trial results, earnings, guidance, analyst calls,
   legal trouble, new shares, leadership, competition, the economy), each with
   one sentence on why that kind of news moves a price.

The output says how sure it is. "Clear" means a single day carried most of
the fall and the news that day names a cause; "unclear" is a real answer and
the page says it rather than inventing one - markets sometimes fall on
nothing anyone wrote down.

Nothing here says what a fall means for the future of the price. That a
stock fell for a reason the market already knows is the whole point.
"""
from __future__ import annotations
import re
from datetime import date, timedelta
from statistics import median

WINDOW_DAYS = 31
# A fall worth explaining: a month's move, or a single bad day inside it.
EXPLAIN_MONTH = -8.0
EXPLAIN_DAY = -7.0
# Share of the month's fall that one day must carry to call it "the" day.
CONCENTRATED = 0.4
MIN_PEERS = 5
MARKET_TOP_N = 500   # cap-weighted over the largest 500 ~ the S&P 500

# (type, label, pattern, why this kind of news moves a price). First match
# wins, so the specific comes before the general: "trial data disappoint"
# is a trial story even though it also contains "disappoint".
CATALYSTS = (
    ("spinoff", "Split-off of a business",
     r"\b(?:spin-?offs?|spins? off|spun off|separation|split into|demerger|when-issued)\b",
     "Part of the company was split off and handed to shareholders as new shares. "
     "The old share price drops by roughly what that part was worth - holders now own "
     "two pieces, so the fall on the chart is not a loss in the same way."),
    ("insider", "An executive traded shares",
     r"\b(?:insiders?|sold shares|bought shares|(?:director|officer|ceo|cfo|evp) (?:sells|sold|buys|bought))\b",
     "An executive sold or bought shares. Executives sell for many personal reasons, "
     "so a sale alone says little; buying with their own money is rarer and usually "
     "read as confidence."),
    ("clinical", "Drug trial or regulator",
     r"\b(?:trials?|phase (?:[1-3]|i{1,3})|fda|study|studies|data (?:from|show\w*)|bla|nda"
     r"|crl|complete response|approval|readout|clinical)\b",
     "For a drug company most of the value rests on a few products, so a single "
     "study result or regulator decision can halve - or double - the price in a day."),
    ("guidance", "New forecast or targets",
     r"\b(?:guidance|outlook|forecasts?|warns?|investor day|analyst day"
     r"|(?:financial|long-term|updated) targets|targets call|lowers? .* (?:view|expectations))\b",
     "The company changed what it expects to earn next. A stock is valued on future "
     "profits, so a lower forecast lowers what the shares are worth today."),
    ("earnings", "Earnings report",
     r"\b(?:earnings|quarterly|(?:quarter|q[1-4]|fiscal|full-year|annual)\b[^.]{0,25}\bresults"
     r"|q[1-4] (?:sales|revenue|report)|eps|misses|beats|tops estimates|falls short)\b",
     "The company reported its quarterly results. Prices move on how results compare "
     "with what investors already expected, not on whether they were good."),
    ("analyst", "Analysts changed their view",
     r"\b(?:downgrad\w*|upgrad\w*|price targets?|initiat\w*|rating|outperform"
     r"|underperform|overweight|underweight|equal.weight|sector weight|neutral|maintains?"
     r"|reiterat\w*|starts (?:with|at))\b",
     "Analysts at banks changed their opinion. That does not change the business, "
     "but many funds follow these calls, so a downgrade can push the price."),
    ("legal", "Legal or regulatory trouble",
     r"\b(?:lawsuits?|sued|sues|probes?|investigat\w*|sec (?:probe|charges|inquiry)|ftc|doj"
     r"|antitrust|subpoena\w*"
     r"|fined?|fines|settlements?|recalls?|bans?|banned)\b",
     "Legal or regulatory trouble. The eventual cost is usually unknown, and markets "
     "mark down what they cannot measure."),
    ("dilution", "New shares sold",
     r"\b(?:offerings?|share sale|dilut\w*|convertible|private placement|at-the-market"
     r"|prices? .* shares|raises? \$)",
     "The company sold new shares or debt that can turn into shares. More shares "
     "means each existing share owns a smaller slice of the company."),
    ("management", "Leadership change",
     r"\b(?:ceo|cfo|chief executive|steps? down|resign\w*|departure|retir\w*|ousted"
     r"|succession|successor|fired)\b",
     "A change at the top. Investors dislike surprises in leadership because the "
     "strategy they were paying for may change with it."),
    ("buyback", "Buyback or dividend",
     r"\b(?:buybacks?|repurchases?|dividends?)\b",
     "The company is returning cash to shareholders. Usually read as confidence, so "
     "it tends to soften a fall rather than cause one."),
    ("deal", "Takeover or merger",
     r"\b(?:acquir\w*|acquisitions?|mergers?|takeover|buyout|agrees? to buy|to acquire"
     r"|bid for)\b",
     "A takeover or merger. A buyer's shares often fall when it pays a lot; the "
     "company being bought jumps toward the offer price."),
    ("competition", "Competition or disruption",
     r"\b(?:compet\w*|rivals?|threat\w*|disrupt\w*|agentic|ai agents?|openai|anthropic"
     r"|undercut\w*|price war|los(?:es|ing|t) (?:share|customers?|contracts?))\b",
     "Worry that a competitor - increasingly an AI tool - takes the business. It is "
     "a fear about future profits, so it hits companies valued on growth hardest."),
    ("macro", "The economy or policy",
     r"\b(?:tariffs?|interest rates?|the fed|inflation|recession|sanctions?|jobs report"
     r"|export (?:bans?|curbs?|controls?)|government shutdown|treasury yields?)\b",
     "A force bigger than the company - rates, trade policy, the economy - that "
     "moves whole groups of stocks together."),
)
_COMPILED = [(t, label, re.compile(p, re.I), why) for t, label, p, why in CATALYSTS]
# Headlines that only describe the fall ("Why is X stock sinking?"). Kept as
# evidence when nothing better exists, never counted as a cause.
MOVE_RE = re.compile(
    r"\b(?:plunge\w*|sink\w*|tumbl\w*|drops?|dropped|fall\w*|slid\w*|slump\w*"
    r"|sell-?off|crater\w*|worst day|declines?|shares? (?:down|lower)|stock is down"
    r"|why is)\b", re.I)
# Stock-tip clickbait ("Time to buy?", "Does the pullback offer opportunity?").
# This page never repeats buy/sell framing, including in quoted headlines.
TIP_RE = re.compile(
    r"\b(?:time to buy|should you (?:buy|sell)|buy the dip|(?:buy|sell) now|opportunity\?"
    r"|bargain|top pick|stocks? to (?:buy|watch)|is it a buy|undervalued|cheap\b"
    r"|room for (?:more|further) (?:gains|upside))", re.I)
# Tags that describe or soften a fall rather than cause it.
NOT_CAUSES = ("move", "buyback", "insider")
CATALYST_INFO = {t: {"label": label, "why": why} for t, label, _, why in CATALYSTS}


def classify(title: str, mentions: bool = True) -> str:
    """The catalyst type of one headline, "move" if it only describes the fall,
    or "" if it says nothing about either.

    `mentions` is whether the headline names the company. TradingView files
    market round-ups ("Week ahead: inflation data, ECB") under every symbol
    they touch; those can be evidence of a macro cause, never of a company one.
    """
    title = title or ""
    if TIP_RE.search(title):
        return ""
    for kind, _, pattern, _ in _COMPILED:
        if pattern.search(title):
            if not mentions and kind != "macro":
                return ""
            return kind
    if mentions and MOVE_RE.search(title):
        return "move"
    return ""


# Ordinary words that open company names ("Home Depot", "Dollar General"),
# which alone would match any headline using the word.
COMMON_FIRST_WORDS = {
    "home", "dollar", "best", "public", "marathon", "waste", "union", "capital",
    "data", "life", "power", "air", "cloud", "solar", "smart", "core", "rocket",
    "sun", "golden", "silver", "blue", "green", "red", "white", "black", "big",
    "great", "main", "west", "east", "north", "south", "pacific", "atlantic",
}


def name_pattern(symbol: str, name: str):
    """Matches a headline that names the company: its ticker, or the
    distinctive start of its name ("uniQure", "Home Depot", "MongoDB")."""
    from .stocks import GENERIC_FIRST_WORDS
    words = re.sub(r"[,.]|\b(?:inc|corp|corporation|ltd|plc|n\.?v|class [a-z])\b", " ",
                   name or "", flags=re.I).split()
    terms = []
    if words:
        first = words[0]
        if (first.lower() in GENERIC_FIRST_WORDS or first.lower() in COMMON_FIRST_WORDS
                or len(first) < 4):
            first = " ".join(words[:2])
        terms.append(re.escape(first).replace("\\ ", r"\s+"))
    if symbol and len(symbol) >= 2:
        terms.append(re.escape(symbol.replace("/", ".")))
    if not terms:
        return None
    return re.compile(r"(?<![\w])(?:" + "|".join(terms) + r")(?![\w])", re.I)


# ------------------------------------------------------------------ peers

def peer_stats(scan: dict, top_n: int = 5) -> dict:
    """Market, industry and sector one-month moves from one TradingView scan.

    The market figure is cap-weighted over the largest 500 companies, which is
    roughly what the S&P 500 did; industries use the median so one huge member
    cannot stand in for the group.
    """
    rows = [r for r in scan.values() if r.get("perf_1m") is not None]
    big = sorted(rows, key=lambda r: -(r.get("market_cap") or 0))[:MARKET_TOP_N]
    weight = sum(r.get("market_cap") or 0 for r in big)
    market = (sum((r.get("market_cap") or 0) * r["perf_1m"] for r in big) / weight
              if weight else None)

    def group(field):
        buckets = {}
        for sym, row in scan.items():
            if row.get("perf_1m") is None or not row.get(field):
                continue
            buckets.setdefault(row[field], []).append((sym, row))
        out = {}
        for name, members in buckets.items():
            members.sort(key=lambda m: -(m[1].get("market_cap") or 0))
            out[name] = {
                "n": len(members),
                "median_1m": round(median(m[1]["perf_1m"] for m in members), 1),
                "top": [{"symbol": s, "name": r.get("name") or s,
                         "perf_1m": round(r["perf_1m"], 1)}
                        for s, r in members[:top_n]],
            }
        return out

    return {"market_1m": round(market, 1) if market is not None else None,
            "industries": group("industry"), "sectors": group("sector")}


# ---------------------------------------------------------------- explain

def needs_explaining(facts: dict, history: list = None) -> bool:
    if (facts.get("chg_1m") or 0) <= EXPLAIN_MONTH:
        return True
    day = biggest_day(history or [])
    return bool(day and day["chg"] <= EXPLAIN_DAY)


def biggest_day(history: list, days: int = WINDOW_DAYS) -> dict:
    """The worst close-to-close day in the window, or {}."""
    if len(history) < 2:
        return {}
    start = history[-1][0] - timedelta(days=days)
    worst = None
    for (d0, v0), (d1, v1) in zip(history, history[1:]):
        if d1 <= start or not v0:
            continue
        chg = (v1 / v0 - 1) * 100
        if worst is None or chg < worst[1]:
            worst = (d1, chg)
    if worst is None:
        return {}
    return {"on": worst[0].isoformat(), "chg": round(worst[1], 1)}


def decompose(stock: float, industry: float, market: float) -> dict:
    """Split a month's move into market, industry-on-top, and company parts."""
    market = market if market is not None else 0.0
    industry = industry if industry is not None else market
    return {
        "total": round(stock, 1),
        "market": round(market, 1),
        "industry_extra": round(industry - market, 1),
        "company": round(stock - industry, 1),
    }


def kind_of_fall(parts: dict) -> str:
    """Whose story is this? The part that carries most of the fall."""
    total = parts["total"]
    if total >= 0:
        return "day"
    shared = parts["market"] + parts["industry_extra"]
    if shared <= 0.6 * total:  # the group fell at least 60% as much
        return "market" if parts["market"] <= 0.6 * total else "industry"
    return "company"


def explain(symbol: str, facts: dict, history: list, tv_row: dict, peers: dict,
            headlines: list, today: date = None) -> dict:
    """Everything the page needs to answer "why did this fall?" for one stock."""
    tv_row = tv_row or {}
    today = today or date.today()
    stock = facts.get("chg_1m")
    if stock is None:
        stock = tv_row.get("perf_1m") or 0.0
    industry_name = tv_row.get("industry") or ""
    sector_name = tv_row.get("sector") or ""
    group = (peers.get("industries") or {}).get(industry_name) or {}
    group_label = industry_name
    if group.get("n", 0) < MIN_PEERS:
        group = (peers.get("sectors") or {}).get(sector_name) or {}
        group_label = sector_name
    parts = decompose(stock, group.get("median_1m"), peers.get("market_1m"))
    kind = kind_of_fall(parts)

    day = biggest_day(history)
    window_start = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    earnings_on = tv_row.get("earnings_last") or ""
    earnings_in_window = earnings_on >= window_start if earnings_on else False
    earnings_linked = bool(day and earnings_in_window and _days_between(
        earnings_on, day["on"]) in (0, 1, 2, 3))

    recent = [h for h in headlines or [] if h.get("on", "") >= window_start]
    named = name_pattern(symbol, facts.get("name") or tv_row.get("name") or "")
    tagged = [dict(h, tag=classify(h["title"], bool(named and named.search(h["title"]))))
              for h in recent]
    near = [h for h in tagged
            if day and abs(_days_between(day["on"], h["on"])) <= 1]

    def causes(pool):
        seen = []
        for h in pool:
            if h["tag"] and h["tag"] not in NOT_CAUSES and h["tag"] not in seen:
                seen.append(h["tag"])
        return seen

    cause_types = causes(near) or causes(tagged)
    if earnings_linked and "earnings" not in cause_types and "guidance" not in cause_types:
        cause_types.insert(0, "earnings")

    concentrated = bool(day and stock < 0 and day["chg"] <= CONCENTRATED * stock)
    if (concentrated and (causes(near) or earnings_linked)) or (
            kind != "company" and abs(parts["company"]) < 5):
        confidence = "clear"
    elif cause_types or kind != "company":
        confidence = "likely"
    else:
        confidence = "unclear"

    evidence = _pick_evidence(near, tagged)
    peers_out = [p for p in group.get("top") or [] if p["symbol"] != symbol][:4]
    return {
        "kind": kind,
        "parts": parts,
        "group": group_label,
        "group_n": group.get("n", 0),
        "peers": peers_out,
        "biggest_day": day,
        "concentrated": concentrated,
        "earnings_on": earnings_on if earnings_in_window else "",
        "earnings_linked": earnings_linked,
        "eps_surprise": tv_row.get("eps_surprise") if earnings_in_window else None,
        "revenue_surprise": tv_row.get("revenue_surprise") if earnings_in_window else None,
        "causes": [{"type": t, **CATALYST_INFO[t]} for t in cause_types[:3]],
        "evidence": evidence,
        "confidence": confidence,
        "summary": summarize(symbol, facts.get("name") or symbol, parts, kind,
                             group_label, day, concentrated, earnings_linked,
                             earnings_on if earnings_in_window else "", tv_row,
                             cause_types, confidence),
    }


def _pick_evidence(near: list, tagged: list, limit: int = 4) -> list:
    """The headlines that best show the cause: the bad day's first, causes
    before descriptions, one per catalyst type where possible."""
    def rank(h):
        return (0 if h in near else 1,
                0 if h["tag"] not in ("", "move") else (1 if h["tag"] == "move" else 2))
    out, types = [], set()
    for h in sorted(tagged, key=rank):
        if not h["tag"]:
            continue
        if h["tag"] in types and h["tag"] != "move":
            continue
        types.add(h["tag"])
        out.append({k: h[k] for k in ("title", "url", "source", "on", "tag")})
        if len(out) >= limit:
            break
    return out


def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _fmt_day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}"


def summarize(symbol, name, parts, kind, group, day, concentrated, earnings_linked,
              earnings_on, tv_row, cause_types, confidence) -> str:
    """Two to four plain sentences, every number taken from the parts above."""
    total = parts["total"]
    group_move = parts["market"] + parts["industry_extra"]
    moved = f"fell {abs(total):.0f}%" if total < 0 else f"rose {total:.0f}%"
    out = []
    if total >= 0 and day:
        out.append(f"{name} is up {total:.0f}% over the month, but had a sharp one-day "
                   f"fall: {abs(day['chg']):.0f}% down on {_fmt_day(day['on'])}.")
        if cause_types:
            labels = [CATALYST_INFO[t]["label"].lower() for t in cause_types[:2]]
            out.append("The news around it points to " + " and ".join(labels) + ".")
        return " ".join(out)
    if kind == "market":
        out.append(f"Mostly the whole market: {name} fell {abs(total):.0f}% in a month "
                   f"while big US stocks overall moved {parts['market']:+.0f}%.")
    elif kind == "industry":
        out.append(f"Mostly its industry: the typical {group or 'peer'} stock moved "
                   f"{group_move:+.0f}% this month, and {name} {moved}. "
                   "When a whole group falls together the cause is usually shared - "
                   "a worry about the industry, not this company.")
    else:
        out.append(f"Mostly this company: {name} {moved} in a month while "
                   f"the typical {group or 'peer'} stock moved {group_move:+.0f}%, so "
                   f"about {abs(parts['company']):.0f} points of the fall are its own.")
    if day and concentrated:
        out.append(f"Most of it came in one day: {abs(day['chg']):.0f}% down on "
                   f"{_fmt_day(day['on'])}.")
    if earnings_linked:
        surprise = tv_row.get("eps_surprise")
        beat = (f" Profit came in {surprise:+.0f}% versus what analysts expected, so "
                "the fall was about what comes next more than the quarter itself."
                if surprise is not None and surprise > 0 else "")
        out.append(f"That was right after its earnings report on "
                   f"{_fmt_day(earnings_on)}.{beat}")
    if cause_types:
        labels = [CATALYST_INFO[t]["label"].lower() for t in cause_types[:2]]
        out.append("The news around it points to " + " and ".join(labels) + ".")
    elif confidence == "unclear":
        out.append("No headline clearly explains it - sometimes prices fall on "
                   "selling nobody announces.")
    return " ".join(out)
