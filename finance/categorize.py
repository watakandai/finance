"""Two closed classifications: what a story is about, and how long it matters.

The taxonomy is fixed and small on purpose. Free-form tags from thirty sources
never line up ("Fed" / "FOMC" / "monetary policy"), so they cannot drive a
filter; a closed list can, and it is also what the LLM is constrained to
return, which keeps the model's categories and the keyword pass's identical.

The second classification is the one this project needs and a tech-news reader
does not: **horizon**. "Stocks closed lower" and "the administration announced
a tariff regime" are both news, but one is noise by Thursday and the other is
still repricing assets in six months. Sorting a finance feed without that
distinction produces a list where the day's tape drowns the things that
actually compound - which is the exact failure mode this project exists to fix.

Two passes for each, same split as the ranker: keywords run always and free,
the LLM overwrites them when it runs. The keyword pass is not a fallback
nobody sees - it is what classifies the long tail the LLM never gets sent.
"""
from __future__ import annotations
import re

CATEGORIES = {
    "monetary_policy": "Monetary policy",
    "inflation": "Inflation",
    "labor": "Jobs & labour",
    "growth": "Growth & consumer",
    "rates": "Rates & Treasuries",
    "credit": "Credit & banks",
    "fiscal": "Fiscal, tax & tariffs",
    "geopolitics": "Geopolitics",
    "regulation": "Regulation & legal",
    "earnings": "Earnings",
    "tech_capex": "AI & tech capex",
    "energy": "Energy",
    "commodities": "Commodities",
    "fx": "Currencies",
    "global_macro": "Global macro",
    "housing": "Housing",
    "equities": "Equity market",
    "positioning": "Positioning & flows",
    "crypto": "Crypto",
    "frameworks": "Frameworks & explainers",
    "other": "Everything else",
}

# Priority order, highest first. Not alphabetical and not a specificity metric,
# just the order in which an item matching several buckets should be filed.
#
# `monetary_policy` is first because a Fed story that also mentions inflation,
# rates and stocks is a Fed story - the decision is the news and everything
# else in the headline is context. `frameworks` is second because an explainer
# about how to read CPI is not a CPI story: it does not decay, and mixing the
# two would bury the teaching material under the prints. `equities` is near the
# bottom because "stocks" appears in a third of all headlines here and would
# otherwise swallow everything. `other` is absent: it is the fallback, never a
# match.
CATEGORY_ORDER = (
    "monetary_policy", "frameworks", "inflation", "labor", "fiscal",
    "geopolitics", "regulation", "tech_capex", "earnings", "credit", "rates",
    "housing", "energy", "commodities", "fx", "crypto", "global_macro",
    "positioning", "growth", "equities",
)


def _re(body: str) -> re.Pattern:
    r"""Compile one bucket's alternation, anchored at both ends.

    The trailing `(?!\w)` is doing the job you would expect `\b` to do, and the
    difference is worth the line: `\b(fed|...)\b` does not match "fed's" the
    way a stem plus a negative lookahead does, and terms ending in punctuation
    ("2s10s", "s&p") need the lookahead because `\b` requires a word character
    on the inside of the boundary.
    """
    return re.compile(rf"\b(?:{body})(?!\w)", re.I)


PATTERNS = {
    # Named officials count as much as the institution: "Powell said" never
    # says "monetary policy", and that headline is the whole reason this bucket
    # is first in the order.
    "monetary_policy":
        r"fed\w*|federal reserve|fomc|powell|central bank\w*|rate (?:cut|hike|"
        r"decision|path)s?|interest[- ]rate decision|monetary polic\w*|"
        r"dot plot|quantitative (?:easing|tightening)|qe|qt|taper\w*|"
        r"basis[- ]point (?:cut|hike)|beige book|jackson hole|"
        r"ecb|bank of japan|boj|bank of england|boe|pboc|lagarde|"
        r"hawkish|dovish|blackout period|balance sheet runoff",

    # Explainers and primers - the material that teaches rather than reports.
    # Deliberately matched on the SHAPE of the writing, because the subject can
    # be anything.
    "frameworks":
        r"primer|explainer|explained|what history says|historically|"
        r"how to read|how to think about|guide to|framework\w*|playbook\w*|lessons? from|"
        r"a (?:brief )?history of|why (?:does|do|is|are) \w+ matter|"
        r"anatomy of|deep dive|cheat sheet|mental model\w*|"
        r"chart of the (?:day|week)|long[- ]term returns|"
        r"asset allocation|diversification|expected returns|"
        r"portfolio rebalanc\w*|rebalanc\w+ (?:your |the |a )?portfolio|"
        r"risk premi(?:um|a)|compound\w* returns|index fund\w*|"
        r"dollar[- ]cost averaging|valuation framework",

    "inflation":
        r"inflation\w*|cpi|core cpi|pce|deflator|disinflation\w*|"
        r"deflation\w*|price pressures?|consumer prices?|producer prices?|ppi|"
        r"breakeven\w*|inflation expectations?|shelter costs?|"
        r"cost of living|price growth",

    "labor":
        r"payrolls?|nonfarm|jobs report|unemployment|jobless|"
        r"jobless claims|layoffs?|hiring|job openings?|jolts|"
        r"labo(?:u)?r market|wage growth|average hourly earnings|"
        r"quits rate|participation rate|employment situation|"
        r"job cuts?|workforce reduction",

    "fiscal":
        r"tariff\w*|trade war|section 232|section 301|"
        r"deficit\w*|budget|appropriations?|government shutdown|debt ceiling|"
        r"tax (?:cut|hike|bill|reform|credit)s?|stimulus|spending bill|"
        r"treasury (?:issuance|refunding|supply)|fiscal polic\w*|"
        r"congressional budget office|cbo|entitlement\w*|"
        r"subsid(?:y|ies)|chips act|inflation reduction act|ira",

    "geopolitics":
        r"sanction\w*|war\b|invasion|ceasefire|missile\w*|strait of hormuz|"
        r"red sea|nato|opec\+?|export ban\w*|export control\w*|"
        r"election\w*|referendum|coup|blockade|"
        r"taiwan|ukraine|russia|iran|israel|middle east|"
        r"geopolitic\w*|national security review",

    "regulation":
        r"sec\b|securities and exchange|cftc|finra|antitrust|monopol\w*|"
        r"doj\b|ftc\b|lawsuit\w*|settlement\w*|court|judge|appeal\w*|"
        r"regulat\w*|basel|capital requirements?|stress test\w*|"
        r"investigat\w*|subpoena\w*|fine[ds]?\b|penalt(?:y|ies)|"
        r"delist\w*|insider trading|probe",

    # The dominant equity driver of this cycle, and genuinely its own thing:
    # not "earnings" (it is spending, not profit) and not "tech news" (the
    # market question is the return on the capital).
    "tech_capex":
        r"capex|capital expenditure\w*|data ?cent(?:er|re)\w*|"
        r"ai (?:spend\w*|capex|infrastructure|buildout|bubble)|"
        r"hyperscaler\w*|compute (?:spend\w*|capacity|demand)|gpu\w*|"
        r"accelerator\w*|nvidia|tsmc|asml|semiconductor\w*|foundry|"
        r"power (?:demand|purchase agreement)|nuclear (?:deal|ppa)|"
        r"depreciation schedule\w*|useful life|circular (?:deal|financing)|"
        r"vendor financing|neocloud\w*",

    "earnings":
        r"earnings|eps\b|guidance|q[1-4] results?|quarterly results?|"
        r"beat\w* (?:estimates|expectations)|miss\w* (?:estimates|expectations)|"
        r"revenue growth|margins?|operating income|free cash flow|"
        r"buyback\w*|dividend\w*|profit warning|pre-?announce\w*|"
        r"analyst day|forward guidance|book[- ]to[- ]bill",

    "credit":
        r"credit spread\w*|high[- ]yield|junk bond\w*|investment[- ]grade|"
        r"default\w*|bankrupt\w*|chapter 11|restructur\w*|"
        r"downgrade[ds]?|upgrade[ds]?|moody'?s|s&p global ratings|fitch|"
        r"bank (?:failure|run|lending)|deposit\w*|loan loss\w*|"
        r"provision\w*|delinquenc\w*|charge[- ]off\w*|private credit|"
        r"leveraged loan\w*|clos?(?!\w)|regional bank\w*",

    "rates":
        r"treasur(?:y|ies)|yield\w*|10-year|two-year|30-year|bond market|"
        r"curve|2s10s|inversion|steepen\w*|flatten\w*|"
        r"auction\w*|bid[- ]to[- ]cover|term premium|duration|"
        r"tips\b|real yield\w*|jgb\w*|bund\w*|gilt\w*|"
        r"repo|sofr|bill\w* issuance",

    "housing":
        r"mortgage\w*|housing starts?|building permits?|home sales?|"
        r"home prices?|homebuilder\w*|case[- ]shiller|"
        r"rent\w*|apartment\w*|commercial real estate|cre\b|"
        r"office vacanc\w*|reit\w*|refinanc\w*",

    "energy":
        r"oil|crude|wti|brent|opec|barrel\w*|refiner(?:y|ies)|"
        r"natural gas|lng|diesel|gasoline|"
        r"electricity|power price\w*|grid|utilit(?:y|ies)|"
        r"pipeline\w*|drilling|rig count|spr\b|strategic petroleum",

    "commodities":
        r"gold|silver|copper|aluminium|aluminum|nickel|lithium|"
        r"iron ore|steel|wheat|corn|soybean\w*|coffee|cocoa|"
        r"commodit(?:y|ies)|futures curve|contango|backwardation|"
        r"critical mineral\w*|rare earth\w*",

    "fx":
        r"dollar|greenback|euro\b|yen\b|yuan|renminbi|sterling|"
        r"exchange rate\w*|currency|devalu\w*|peg\b|"
        r"intervention|carry trade|dxy|eur/usd|usd/jpy|"
        r"reserve currency|de-?dollari[sz]\w*",

    "crypto":
        r"bitcoin|btc|ethereum|eth\b|crypto\w*|stablecoin\w*|"
        r"digital asset\w*|tokeni[sz]\w*|defi|"
        r"coinbase|binance|etf inflow\w* .{0,12}bitcoin|"
        r"blockchain|on-?chain|halving",

    "global_macro":
        r"china|chinese economy|japan|eurozone|euro area|germany|"
        r"emerging market\w*|india|brazil|mexico|canada|uk economy|"
        r"imf|world bank|oecd|bis\b|"
        r"global growth|global trade|current account|"
        r"capital controls?|sovereign (?:debt|risk)",

    "positioning":
        r"positioning|fund flow\w*|inflow\w*|outflow\w*|"
        r"short interest|short squeeze|"
        r"sentiment survey|aaii|bull(?:ish)? sentiment|bear(?:ish)? sentiment|"
        r"put/call|put[- ]call|open interest|gamma|"
        r"cta\w*|systematic (?:funds?|strateg\w*)|risk parity|"
        r"margin debt|leverage(?:d)? (?:etf|position)\w*|"
        r"insider (?:buying|selling)|13f|hedge fund\w*",

    "growth":
        r"gdp|recession\w*|soft landing|hard landing|"
        r"consumer spending|retail sales|"
        r"industrial production|manufacturing|pmi|ism\b|"
        r"business investment|capacity utili[sz]ation|"
        r"nowcast\w*|leading indicator\w*|economic growth|"
        r"consumer confidence|sentiment index",

    "equities":
        r"s&p 500|nasdaq|dow jones|russell|stocks?|shares?|equit(?:y|ies)|"
        r"rally|rallies|selloff|sell-?off|correction|bear market|bull market|"
        r"drawdown\w*|all-?time high\w*|record high\w*|"
        r"breadth|market cap|valuation\w*|multiple\w*|p/e|"
        r"volatilit(?:y|ies)|vix|ipo\w*|"
        r"magnificent seven|mega-?cap\w*|small ?cap\w*",
}

COMPILED = {k: _re(v) for k, v in PATTERNS.items()}

# Sources whose every item belongs in one bucket regardless of wording. These
# are the primary publishers - the Fed's own feed is monetary policy even when
# a given release is about a bank merger.
SOURCE_HINTS = {
    "fed_press": "monetary_policy",
    "fed_speeches": "monetary_policy",
    "fed_testimony": "monetary_policy",
    "ecb": "monetary_policy",
    "sec": "regulation",
}


def categorize(item: dict, feed_hints: dict = None) -> str:
    """Best-effort category id for one item. Always returns something."""
    source = item.get("source") or ""
    hint = SOURCE_HINTS.get(source) or (feed_hints or {}).get(source, "")
    haystack = _haystack(item)
    matched = next((c for c in CATEGORY_ORDER if COMPILED[c].search(haystack)), "")
    if not matched:
        return hint or "other"
    if not hint or hint not in CATEGORY_ORDER:
        return matched
    # Both fired, so the priority order decides. This is what keeps a Fed
    # speech filed under monetary policy when a stray "stocks" in its summary
    # also matched equities.
    return min(matched, hint, key=CATEGORY_ORDER.index)


def _haystack(item: dict) -> str:
    tags = item.get("tags") or []
    return " ".join([
        item.get("title") or "",
        (item.get("summary") or "")[:400],
        " ".join(tags if isinstance(tags, list) else [str(tags)]),
    ])


def label(cat: str) -> str:
    return CATEGORIES.get(cat, CATEGORIES["other"])


# ----------------------------------------------------------------- horizon

# `horizon` answers "how long does this stay relevant", not "when does it first
# move a price". A Fed decision moves the tape at 14:00 and still sets the
# discount rate in six months, so it belongs in `months`: the question a
# curator has to answer is "will I care about this next month", because that is
# what decides whether it is worth reading carefully today.
HORIZONS = {
    "day": "Today's tape only",
    "week": "Days to weeks",
    "months": "Months and beyond",
}
HORIZON_ORDER = ("months", "week", "day")

# Language that dates an item to today's session. Almost all of it is about
# price action, which is exactly the content with the shortest shelf life.
DAY_RE = _re(
    r"today|toda?y'?s session|close[ds]?|closing|opened?|pre-?market|"
    r"intraday|this morning|overnight|"
    r"ros?e|f[ae]ll|falls|jump\w*|slid\w*|slip\w*|surg\w*|plung\w*|"
    r"tumbl\w*|climb\w*|sink\w*|sank|soar\w*|drop\w*|rebound\w*|"
    r"rise[sn]?|rising|advanc\w*|declin\w*|"
    r"gain(?:ed|s)?|lo(?:se|st|ses)|rall(?:y|ies|ied)|erased|pared|"
    r"extended (?:losses|gains)|"
    r"live updates?|markets? wrap|closing bell|opening bell|"
    r"stocks? (?:up|down|higher|lower)|dow (?:up|down)|"
    r"halted|circuit breaker"
)

# Language about a structural change: a new regime, a multi-year process, or a
# decision whose consequences arrive over quarters.
MONTHS_RE = _re(
    r"structural\w*|secular|multi-?year|decade\w*|long[- ]run|long[- ]term|"
    r"regime (?:change|shift)|paradigm|"
    r"tariff\w*|trade (?:deal|agreement|war)|treaty|"
    r"legislation|bill (?:passed|signed)|law|act\b|ruling|"
    r"demographic\w*|productivity growth|potential growth|r-?star|"
    r"capex cycle|buildout|supply chain\w*|reshoring|onshoring|"
    r"debt (?:sustainability|trajectory)|entitlement\w*|"
    r"framework review|mandate change|"
    r"appointed|nominat\w*|successor|chair(?:manship)?|term expires|"
    r"strategic (?:reserve|stockpile|partnership)|"
    r"five[- ]year plan|census|pension\w*|"
    r"primer|history of|expected returns|asset allocation"
)

# Language that points at a scheduled event or a setup rather than a print or a
# structural change. This is the default, so the pattern only has to catch the
# cases where "day" or "months" would otherwise win on a stray word.
WEEK_RE = _re(
    r"next week|this week|ahead of|awaits?|await(?:ing|ed)|"
    r"previews?|expect(?:ed|s|ations)? (?:to|for)|forecasts?|"
    r"due (?:on|this|next)|scheduled|"
    r"watch(?:ing)? for|in focus|set to report|will report|"
    r"positioning (?:ahead|for)|options market\w*|"
    r"earnings season|guidance cut|warned"
)


def horizon(item: dict, category: str = "") -> str:
    """How long this item is likely to matter: day, week or months.

    Order of resolution matters. A structural signal wins over price-action
    language, because a tariff story written as "stocks fell on the tariff news"
    is still a tariff story and will still matter in six months - whereas the
    reverse mistake files the most durable items in the bucket that is cleared
    every morning.

    `category` gates the `months` bucket. Several of these feeds are a
    publication's whole front page, so they carry general news, and the
    structural vocabulary is not finance-specific: "ravaged for decades",
    "changed over five decades". An item that matched no finance vocabulary at
    all has no durable market relevance by definition, and `months` is the one
    bucket where a false positive is expensive - it is the section a reader is
    told to take seriously.
    """
    category = category or item.get("category") or ""
    haystack = _haystack(item)
    if category == "other":
        return "day" if DAY_RE.search(haystack) else "week"
    if MONTHS_RE.search(haystack):
        return "months"
    if DAY_RE.search(haystack):
        # ...unless the item is explicitly about something still to come, which
        # is a setup rather than a report.
        return "week" if WEEK_RE.search(haystack) else "day"
    if WEEK_RE.search(haystack):
        return "week"
    # Primary sources default to the longest horizon they plausibly have: a
    # central bank or a regulator publishing something is a decision, not a
    # market report, and decisions outlive the session.
    return "months" if int(item.get("tier") or 3) <= 1 else "week"


def horizon_label(value: str) -> str:
    return HORIZONS.get(value, HORIZONS["week"])
