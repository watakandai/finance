"""Seven questions that decide what a portfolio is exposed to.

Sixty indicators do not constitute a view. What experienced macro investors
actually carry in their heads is a small set of states, and almost every
market move is one of them changing:

    inflation -> what the Fed does -> where rates go
       -> what credit costs -> what liquidity there is -> what risk pays

That chain is the order of the reads below, because it is the order causation
runs in. Growth feeds in at the top (it is half of the Fed's mandate) and risk
appetite sits at the bottom (it is the output, not an input).

Each read returns the same shape: a `state` in plain words, a `score` from -2
(headwind for risk assets) to +2 (tailwind), the `evidence` it was computed
from, and - the part that matters - `means`, which explains the MECHANISM by
which this state reaches asset prices. That is deliberately not a
recommendation: the mechanism is knowable and worth learning, while what
anybody should own depends on things this file cannot see.

Thresholds are written as named constants with a comment saying where they come
from, because an unexplained threshold is indistinguishable from a made-up one.
Every one of them is a level that shows up in Fed communication, in the
academic rules (Sahm), or in the historical record of where a variable's
behaviour changed.
"""
from __future__ import annotations
from datetime import date, timedelta

from . import metrics as M

# --- thresholds ------------------------------------------------------------
TARGET = 2.0            # the Fed's stated PCE inflation objective
STICKY_ABOVE = 2.8      # above this y/y, the committee has not eased
NEAR_TARGET = 2.4       # below this, cuts get justified on inflation alone
MOMENTUM_GAP = 0.4      # 3m-annualised minus y/y that counts as a turn
NEUTRAL_REAL = 0.5      # r* estimates cluster around 0.5-1.0% real
PATH_GAP = 0.25         # 2-year minus funds that counts as priced-in cuts
BREAKEVEN_HIGH = 2.75   # above this the Fed has talked hawkish regardless of spot
SAHM_TRIGGER = 0.50     # 3m-avg unemployment above its prior-12m low
CLAIMS_ELEVATED = 260   # thousands, 4-week average
PAYROLLS_BREAKEVEN = 100  # thousands/month to hold unemployment flat
HY_TIGHT = 3.00         # percentage points of OAS: complacent
HY_STRESS = 5.00        # the level that has accompanied equity drawdowns
VIX_CALM = 15.0
VIX_STRESS = 25.0

STATE_WORDS = {2: "tailwind", 1: "mild tailwind", 0: "neutral",
               -1: "mild headwind", -2: "headwind"}

DISCLAIMER = (
    "These are readings of public data and descriptions of how each one has "
    "historically transmitted to asset prices. They are not advice about what "
    "to buy, sell or hold."
)


def _get(summaries: dict, key: str, field: str = "value"):
    entry = summaries.get(key) or {}
    return entry.get(field)


def _ev(summaries: dict, key: str, note: str = "") -> dict:
    """One evidence row: the number, its unit, and why it is being cited."""
    entry = summaries.get(key)
    if not entry:
        return {}
    return {
        "id": key,
        "label": entry["label"],
        "value": entry["value"],
        "unit": entry["unit"],
        "decimals": entry.get("decimals", 2),
        "as_of": entry["as_of"],
        "changes": entry.get("changes", {}),
        "pct_rank": entry.get("pct_rank"),
        "note": note,
    }


def _read(rid, label, score, state, evidence, why, means, watch, missing=()) -> dict:
    return {
        "id": rid,
        "label": label,
        "score": score,
        "stance": STATE_WORDS[max(-2, min(2, score))],
        "state": state,
        "evidence": [e for e in evidence if e],
        "why": why,
        "means": means,
        "watch": watch,
        # Named explicitly rather than silently degrading: a read computed from
        # half its inputs should say so, because the alternative is a confident
        # sentence built on a missing series.
        "missing": list(missing),
    }


# ---------------------------------------------------------------- inflation

def inflation(summaries: dict) -> dict:
    yoy = _get(summaries, "core_pce") or _get(summaries, "core_cpi")
    fast = _get(summaries, "core_pce_3m")
    breakeven = _get(summaries, "breakeven_10y")
    missing = [k for k in ("core_pce", "core_pce_3m") if k not in summaries]

    if yoy is None:
        return _read("inflation", "Inflation", 0, "no data", [],
                     _WHY["inflation"], "Cannot read the most important input "
                     "to the Fed's reaction function.", "Next CPI and PCE prints.",
                     missing)

    # Momentum against the annual rate is the actual question. A y/y rate that
    # is still falling while the 3-month rate turns up is the configuration
    # that has repeatedly caught markets leaning the wrong way.
    turning_up = fast is not None and fast - yoy > MOMENTUM_GAP
    turning_down = fast is not None and yoy - fast > MOMENTUM_GAP

    if yoy <= NEAR_TARGET and not turning_up:
        score, state = 2, "at or near target"
    elif turning_up and yoy > TARGET:
        score, state = -2, "re-accelerating"
    elif yoy >= STICKY_ABOVE and not turning_down:
        score, state = -2, "sticky above target"
    elif turning_down:
        score, state = 1, "cooling"
    else:
        score, state = -1, "above target, little momentum either way"

    if breakeven is not None and breakeven > BREAKEVEN_HIGH:
        # Expectations slipping is more serious than any single print, because
        # it is what forces policy to stay tight into weakness.
        score = min(score, -1)
        state += "; long-run expectations elevated"

    means = (
        "Inflation is the constraint on everything else: it sets how much room "
        "the Fed has, and the Fed sets the discount rate on every asset. "
    ) + (
        "With inflation near target, weak growth data reads as good news for "
        "bonds and for long-duration equities, because the Fed is free to "
        "respond to it."
        if score > 0 else
        "While inflation is above target, weak growth data is not rescued by "
        "the Fed quickly, so bonds and equities can fall together - the "
        "correlation that made 2022 unusual."
    )
    return _read(
        "inflation", "Inflation", score, state,
        [_ev(summaries, "core_pce", "the Fed's target measure"),
         _ev(summaries, "core_pce_3m", "momentum, not the annual average"),
         _ev(summaries, "core_cpi", "earlier and more heavily traded"),
         _ev(summaries, "breakeven_10y", "what the bond market prices")],
        _WHY["inflation"], means,
        "CPI and core PCE prints; the dot plot at SEP meetings.", missing)


# ------------------------------------------------------------------- growth

def growth(summaries: dict, series: dict) -> dict:
    claims = _get(summaries, "claims")
    unrate_series = series.get("unemployment") or []
    payrolls = _get(summaries, "payrolls")
    retail = _get(summaries, "retail_sales")
    gdp_now = _get(summaries, "gdp_now")
    missing = [k for k in ("claims", "payrolls", "unemployment") if k not in summaries]

    sahm = sahm_gap(unrate_series)
    score, notes = 0, []
    if sahm is not None:
        if sahm >= SAHM_TRIGGER:
            score -= 2
            notes.append("Sahm rule triggered")
        elif sahm >= SAHM_TRIGGER / 2:
            score -= 1
            notes.append("unemployment drifting up off its low")
    if claims is not None:
        if claims / 1000.0 >= CLAIMS_ELEVATED:
            score -= 1
            notes.append("claims elevated")
        elif claims / 1000.0 < CLAIMS_ELEVATED * 0.8:
            score += 1
            notes.append("claims low")
    if payrolls is not None:
        if payrolls < 0:
            score -= 2
            notes.append("payrolls contracting")
        elif payrolls < PAYROLLS_BREAKEVEN:
            score -= 1
            notes.append("hiring below breakeven")
        elif payrolls > PAYROLLS_BREAKEVEN * 1.75:
            score += 1
            notes.append("hiring strong")
    if gdp_now is not None and gdp_now < 0.5:
        score -= 1
        notes.append("nowcast near stall speed")

    score = max(-2, min(2, score))
    state = {2: "expanding solidly", 1: "expanding", 0: "mixed",
             -1: "slowing", -2: "deteriorating"}[score]
    if notes:
        state += " (" + ", ".join(notes[:3]) + ")"

    means = (
        "Growth decides earnings, and jointly with inflation it decides which "
        "way the Fed leans. "
    ) + (
        "Deteriorating labour data is the one thing that reliably overrides an "
        "inflation problem in the Fed's reaction function - and it takes "
        "earnings estimates down with it, which is why 'bad news is good news' "
        "stops working at exactly this point."
        if score < 0 else
        "Solid growth supports earnings but removes the urgency to ease, so "
        "the market has to pay for earnings rather than for rate cuts."
    )
    return _read(
        "growth", "Growth & labour", score, state,
        [_ev(summaries, "claims", "weekly, barely revised, leads everything"),
         _ev(summaries, "unemployment",
             f"Sahm gap {sahm:+.2f}pp off the 12-month low" if sahm is not None
             else "half the Fed's mandate"),
         _ev(summaries, "payrolls", "3-month average is the honest read"),
         _ev(summaries, "retail_sales", "two thirds of the economy"),
         _ev(summaries, "gdp_now", "current quarter, rebuilt as data lands")],
        _WHY["growth"], means,
        "Weekly claims every Thursday; payrolls on the first Friday.", missing)


def sahm_gap(unrate: list):
    """3-month average unemployment minus its lowest 3-month average of the
    prior 12 months.

    Claudia Sahm's rule: half a percentage point has marked the start of every
    US recession since 1960 and produced very few false positives, which is
    more than can be said for any other single number here. Implemented over
    dates rather than row offsets so a gap in the series cannot shift the
    window.
    """
    if len(unrate) < 15:
        return None
    def avg3(idx):
        window = [v for _, v in unrate[max(0, idx - 2): idx + 1]]
        return sum(window) / len(window) if window else None

    current = avg3(len(unrate) - 1)
    if current is None:
        return None
    cutoff = unrate[-1][0] - timedelta(days=370)
    prior = [avg3(i) for i, (on, _) in enumerate(unrate)
             if on >= cutoff and i >= 2 and i < len(unrate) - 1]
    prior = [p for p in prior if p is not None]
    if not prior:
        return None
    return current - min(prior)


# ------------------------------------------------------------------- policy

def policy(summaries: dict) -> dict:
    funds = _get(summaries, "fed_funds")
    core = _get(summaries, "core_pce") or _get(summaries, "core_cpi")
    two_year = _get(summaries, "ust_2y")
    missing = [k for k in ("fed_funds", "ust_2y") if k not in summaries]

    real_rate = None if (funds is None or core is None) else funds - core
    implied = None if (funds is None or two_year is None) else two_year - funds

    if real_rate is None:
        stance = "unknown"
        score = 0
    elif real_rate > NEUTRAL_REAL + 1.0:
        stance, score = "clearly restrictive", -1
    elif real_rate > NEUTRAL_REAL:
        stance, score = "mildly restrictive", 0
    elif real_rate > -0.5:
        stance, score = "roughly neutral", 1
    else:
        stance, score = "accommodative", 2

    if implied is not None:
        if implied < -PATH_GAP:
            stance += ", market pricing cuts"
            score += 1
        elif implied > PATH_GAP:
            stance += ", market pricing hikes"
            score -= 1
    score = max(-2, min(2, score))

    means = (
        "The real policy rate - funds minus core inflation - is what "
        "'restrictive' actually means; the nominal level on its own says "
        "nothing. The 2-year yield minus the funds rate is the market's own "
        "forecast of the path, and it moves months before the Fed does. "
    ) + (
        "With cuts priced in, a hot inflation print does double damage: it "
        "removes expected easing as well as raising the discount rate."
        if implied is not None and implied < -PATH_GAP else
        "With little easing priced in, a weak data run has room to rally bonds "
        "without needing the Fed to say anything."
    )
    detail = []
    if real_rate is not None:
        detail.append(f"real policy rate {real_rate:+.2f}pp vs ~{NEUTRAL_REAL}pp neutral")
    if implied is not None:
        detail.append(f"2-year {implied:+.2f}pp vs funds")
    return _read(
        "policy", "Monetary policy", score, stance + (
            " (" + "; ".join(detail) + ")" if detail else ""),
        [_ev(summaries, "fed_funds", "the anchor for every discount rate"),
         _ev(summaries, "ust_2y", "the market's forecast of the path"),
         _ev(summaries, "sofr", "funding plumbing; a spike forces Fed action")],
        _WHY["policy"], means,
        "Eight scheduled FOMC decisions a year; the SEP meetings move the curve "
        "most.", missing)


# -------------------------------------------------------------------- rates

def rates(summaries: dict) -> dict:
    curve = _get(summaries, "curve_2s10s")
    ten = summaries.get("ust_10y") or {}
    two = summaries.get("ust_2y") or {}
    real = _get(summaries, "real_10y")
    missing = [k for k in ("curve_2s10s", "ust_10y") if k not in summaries]

    d10 = (ten.get("changes") or {}).get("1m")
    d2 = (two.get("changes") or {}).get("1m")
    shape = "inverted" if (curve is not None and curve < 0) else "positive"
    move = ""
    if d10 is not None and d2 is not None:
        steepening = d10 - d2
        if steepening > 0.10:
            move = "bear steepening" if d10 > 0 else "steepening"
        elif steepening < -0.10:
            move = "bull flattening" if d10 < 0 else "flattening"
        if d10 < -0.10 and d2 < -0.10 and steepening > 0.10:
            move = "bull steepening"

    score = 0
    if curve is not None and curve < 0:
        score -= 1
    if d10 is not None and d10 > 0.40:
        # Speed, not level: roughly 50bp in a month has broken equity rallies
        # from every starting point.
        score -= 1
    elif d10 is not None and d10 < -0.40:
        score += 1
    if real is not None and real > 2.0:
        score -= 1
    score = max(-2, min(2, score))

    state = f"{shape} curve" + (f", {move}" if move else "")
    means = (
        "The 10-year is the discount rate for everything, and WHICH END of the "
        "curve moves tells you why. Bull steepening (front end falling) is the "
        "market pricing cuts and has historically been the best environment for "
        "bonds and for small caps. Bear steepening (long end rising) is term "
        "premium or fiscal risk and is the hardest kind of rate rise for "
        "equities to absorb, because the discount rate goes up without any "
        "growth to pay for it."
    )
    return _read(
        "rates", "Rates & the curve", score, state,
        [_ev(summaries, "curve_2s10s", "which end is moving is the signal"),
         _ev(summaries, "ust_10y", "the global discount rate"),
         _ev(summaries, "real_10y", "nominal minus expected inflation"),
         _ev(summaries, "ust_30y", "where fiscal credibility prices")],
        _WHY["rates"], means,
        "Auctions and the quarterly refunding announcement; every inflation "
        "print.", missing)


# ------------------------------------------------------------------- credit

def credit(summaries: dict) -> dict:
    hy = summaries.get("hy_spread") or {}
    level = hy.get("value")
    rank = hy.get("pct_rank")
    change_1m = (hy.get("changes") or {}).get("1m")
    ig_change = ((summaries.get("ig_spread") or {}).get("changes") or {}).get("1m")
    nfci = _get(summaries, "nfci")
    missing = [k for k in ("hy_spread", "ig_spread") if k not in summaries]

    if level is None:
        return _read("credit", "Credit", 0, "no data", [], _WHY["credit"],
                     "Losing sight of the best early-warning gauge available.",
                     "Daily spread data.", missing)

    if level >= HY_STRESS:
        score, state = -2, "stressed"
    elif level <= HY_TIGHT:
        score, state = 1, "wide open, arguably complacent"
    else:
        score, state = 0, "normal"
    # Direction overrides level. Spreads widening from a tight base is the
    # early warning; spreads tight and stable is not information.
    if change_1m is not None and change_1m > 0.5:
        score -= 2
        state += ", widening fast"
    elif change_1m is not None and change_1m > 0.2:
        score -= 1
        state += ", widening"
    elif change_1m is not None and change_1m < -0.2:
        score += 1
        state += ", tightening"
    if ig_change is not None and ig_change > 0.15:
        score -= 1
        state += "; investment grade widening too"
    score = max(-2, min(2, score))
    if rank is not None:
        state += f" ({rank:.0f}th percentile of the last 5 years)"

    means = (
        "Credit decides whether a slowdown becomes a default cycle. While "
        "spreads are tight, weak companies refinance and nothing breaks; when "
        "they widen, refinancing stops and the slowdown feeds itself. Credit "
        "has led equities into every serious drawdown, and high-yield spreads "
        "widening while investment grade follows is the specific pattern that "
        "distinguishes a market event from a single-sector problem."
    )
    return _read(
        "credit", "Credit & conditions", score, state,
        [_ev(summaries, "hy_spread", "the best early-warning gauge here"),
         _ev(summaries, "ig_spread", "widening here means it is not idiosyncratic"),
         _ev(summaries, "nfci", "105 measures in one number"),
         _ev(summaries, "loan_standards", "how rate rises reach small business")],
        _WHY["credit"], means,
        "Daily spreads; bank earnings for loan-loss provisions; the quarterly "
        "loan officer survey.", missing)


# ---------------------------------------------------------------- liquidity

def liquidity(summaries: dict) -> dict:
    balance = summaries.get("fed_balance_sheet") or {}
    reserves = summaries.get("reserves") or {}
    rrp = _get(summaries, "rrp")
    missing = [k for k in ("fed_balance_sheet", "reserves") if k not in summaries]

    bs_3m = (balance.get("changes") or {}).get("3m")
    res_3m = (reserves.get("changes") or {}).get("3m")
    score, notes = 0, []
    if bs_3m is not None:
        if bs_3m < -1.0:
            score -= 1
            notes.append("balance sheet shrinking")
        elif bs_3m > 1.0:
            score += 1
            notes.append("balance sheet growing")
    if res_3m is not None:
        if res_3m < -3.0:
            score -= 1
            notes.append("reserves draining")
        elif res_3m > 3.0:
            score += 1
            notes.append("reserves building")
    if rrp is not None and rrp < 50:
        # With the reverse-repo cushion gone, Treasury issuance drains bank
        # reserves directly instead of money-fund cash.
        notes.append("reverse-repo cushion effectively empty")
    score = max(-2, min(2, score))
    state = {2: "expanding", 1: "easing", 0: "flat",
             -1: "draining", -2: "draining quickly"}[score]
    if notes:
        state += " (" + ", ".join(notes[:3]) + ")"

    means = (
        "Liquidity is the quantity side of policy, and it works with a lag and "
        "then all at once: reserves fall slowly for months and then a funding "
        "market seizes, as repo did in September 2019. It is also the most "
        "predictable thing on this page, because Treasury's cash schedule and "
        "the Fed's runoff caps are both published in advance."
    )
    return _read(
        "liquidity", "Liquidity", score, state,
        [_ev(summaries, "fed_balance_sheet", "the quantity side of policy"),
         _ev(summaries, "reserves", "the system's actual buffer"),
         _ev(summaries, "rrp", "the cushion that absorbed issuance"),
         _ev(summaries, "tga", "government cash: fills and drains on a schedule")],
        _WHY["liquidity"], means,
        "The Fed's H.4.1 every Thursday; tax dates; any change to runoff caps.",
        missing)


# --------------------------------------------------------------------- risk

def risk(summaries: dict, ratios: dict = None) -> dict:
    vix = summaries.get("vix") or {}
    level = vix.get("value")
    spx = summaries.get("spx") or {}
    vs_ma = spx.get("vs_ma200")
    ratios = ratios or {}
    missing = [k for k in ("vix", "spx") if k not in summaries]

    score, notes = 0, []
    if level is not None:
        if level >= VIX_STRESS:
            score -= 2
            notes.append("volatility elevated")
        elif level <= VIX_CALM:
            score += 1
            notes.append("volatility low")
    if vs_ma is not None:
        if vs_ma > 2:
            score += 1
            notes.append("index above its 200-day average")
        elif vs_ma < -2:
            score -= 1
            notes.append("index below its 200-day average")
    # Leadership. Two ratios, both 3-month, because they answer different
    # questions: breadth (small caps) and intent (wants vs needs).
    breadth = (ratios.get("IWM/SPY") or {}).get("3m")
    appetite = (ratios.get("XLY/XLP") or {}).get("3m")
    for value, good, bad in ((breadth, "breadth broadening", "narrow leadership"),
                             (appetite, "cyclical leadership", "defensive leadership")):
        if value is None:
            continue
        if value > 2:
            score += 1
            notes.append(good)
        elif value < -2:
            score -= 1
            notes.append(bad)
    score = max(-2, min(2, score))
    state = {2: "risk-on", 1: "constructive", 0: "mixed",
             -1: "cautious", -2: "risk-off"}[score]
    if notes:
        state += " (" + ", ".join(notes[:3]) + ")"

    means = (
        "Risk appetite is the output of everything above, which makes it a poor "
        "input: it tells you what is already priced, not what happens next. Its "
        "use is as a cross-check - when leadership disagrees with the index "
        "(defensives leading a rising market, small caps lagging a rally), the "
        "index is usually the part that is wrong. Low volatility is also not "
        "safety: it is when leverage accumulates, which is what makes the next "
        "shock larger."
    )
    return _read(
        "risk", "Risk appetite", score, state,
        [_ev(summaries, "vix", "the price of protection"),
         _ev(summaries, "spx", f"{vs_ma:+.1f}% vs its 200-day average"
             if vs_ma is not None else "the benchmark"),
         _ev(summaries, "rut", "small caps: domestic economy and floating-rate debt"),
         _ev(summaries, "bitcoin", "highest-beta read on marginal liquidity")],
        _WHY["risk"], means,
        "Nothing scheduled - this one reacts to the others.", missing)


_WHY = {
    "inflation": "Inflation sets how much room the Fed has, and the Fed sets the "
                 "discount rate applied to every future cash flow on earth. It "
                 "is first in the chain because everything else is downstream "
                 "of it.",
    "growth": "Growth drives earnings, and the labour half of it is the other "
              "side of the Fed's mandate. When labour data deteriorates, the "
              "Fed's reaction function flips from fighting inflation to "
              "defending employment - which is the single most important "
              "regime change there is.",
    "policy": "The policy rate is the price of money and the base of every "
              "valuation. What matters is not its level but its level relative "
              "to inflation, and what the market already expects it to do next.",
    "rates": "Long yields are where policy expectations, inflation "
             "expectations and the government's borrowing needs are priced "
             "together. Equities discount off them, so the composition of a "
             "rate move decides whether it is survivable.",
    "credit": "Credit is the transmission belt. A slowdown with open credit "
              "markets is a slowdown; a slowdown with closed ones is a "
              "recession. It also happens to lead equities.",
    "liquidity": "The quantity of reserves in the system determines how much "
                 "leverage the market can carry. Liquidity drains are slow, "
                 "scheduled and knowable in advance - and then abrupt when "
                 "something breaks.",
    "risk": "What the market currently believes, as revealed by what it is "
            "paying for. Most useful when it contradicts the fundamentals "
            "above, because that gap is where positioning risk lives.",
}


# ---------------------------------------------------------------- assembly

ORDER = ("inflation", "growth", "policy", "rates", "credit", "liquidity", "risk")


def assess(summaries: dict, series: dict = None, ratios: dict = None) -> dict:
    """All seven reads, plus an overall summary sentence.

    `summaries` is {series id: metrics.summarize output}; `series` is the raw
    {id: [(date, value)]} history, needed for the calculations that are not a
    single latest value (the Sahm gap); `ratios` is {"IWM/SPY": {"3m": ...}}.
    """
    series = series or {}
    reads = [
        inflation(summaries),
        growth(summaries, series),
        policy(summaries),
        rates(summaries),
        credit(summaries),
        liquidity(summaries),
        risk(summaries, ratios),
    ]
    by_id = {r["id"]: r for r in reads}
    total = sum(r["score"] for r in reads)
    return {
        "reads": [by_id[k] for k in ORDER if k in by_id],
        "score": total,
        "stance": _overall(total),
        "summary": _summary(by_id),
        "tension": _tension(by_id),
        "disclaimer": DISCLAIMER,
    }


def _overall(total: int) -> str:
    if total >= 5:
        return "supportive"
    if total >= 2:
        return "mildly supportive"
    if total <= -5:
        return "hostile"
    if total <= -2:
        return "mildly hostile"
    return "balanced"


def _summary(by_id: dict) -> str:
    """One sentence in the order causation runs, so it reads as a chain."""
    parts = []
    for key in ORDER:
        read = by_id.get(key)
        if not read:
            continue
        # Only the head of each state - the parenthetical evidence belongs on
        # the tile, not in a sentence meant to be read in one breath.
        head = read["state"].split(" (")[0].split(";")[0]
        parts.append(f"{read['label'].split(' &')[0].lower()} {head}")
    return "; ".join(parts) + "."


def _tension(by_id: dict) -> str:
    """The most useful thing on the page: where the reads disagree.

    A market is only mispriced relative to fundamentals when the two disagree,
    so naming the disagreement is more actionable than any single state. The
    pairs checked are the ones with a real historical record of resolving in
    the fundamental's favour.
    """
    risk_score = (by_id.get("risk") or {}).get("score", 0)
    credit_score = (by_id.get("credit") or {}).get("score", 0)
    growth_score = (by_id.get("growth") or {}).get("score", 0)
    inflation_score = (by_id.get("inflation") or {}).get("score", 0)
    policy_score = (by_id.get("policy") or {}).get("score", 0)

    if risk_score > 0 and credit_score < 0:
        return ("Equities are priced for calm while credit spreads widen. Credit "
                "has led equities at every serious turn, so this gap usually "
                "closes in credit's direction.")
    if risk_score > 0 and growth_score < 0:
        return ("Risk appetite is holding up while the labour data deteriorates. "
                "That combination is sustainable only if the market is right that "
                "the Fed will ease before earnings estimates fall.")
    if inflation_score < 0 and policy_score > 0:
        return ("The market is pricing easing while inflation is still above "
                "target. A single hot print removes both the expected cuts and "
                "the multiple that was built on them.")
    if growth_score < 0 and inflation_score < 0:
        return ("Growth slowing with inflation still above target is the one "
                "configuration monetary policy cannot fix quickly - it is why "
                "bonds and equities fell together in 2022.")
    if risk_score < 0 and credit_score >= 0 and growth_score >= 0:
        return ("Equities are nervous while credit and the data are fine. "
                "Drawdowns that credit does not confirm have historically been "
                "the recoverable kind.")
    return ("The reads are broadly consistent with each other, which means the "
            "market is priced roughly where the data says it should be - and "
            "the next scheduled release matters more than usual.")
