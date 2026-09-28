"""The same readings, explained for someone new to all of this.

Everything else in this package is written for a reader who already knows what
a credit spread is. This module is the translation layer for one who does not:
it takes the computed regime and adds, to every read, a plain label, one
sentence on what the thing even is, the current reading in everyday words with
the real numbers in it, and what it means for somebody who owns stocks or an
index fund.

Three rules the text follows, because a beginner page that breaks them is worse
than the expert one:

- **Every number is anchored.** "3.3%" means nothing alone; "prices are rising
  3.3% a year, against the Fed's goal of 2%" is something a person can hold.
- **Every term is defined where it is used**, or not used. No "real policy
  rate"; instead "the Fed's rate minus inflation".
- **Mechanism, not instruction.** "High interest rates tend to weigh on stocks,
  because..." is teachable. "Sell your stocks" is advice this project does not
  give. Nothing here tells the reader what to do with their money.

Kept separate from `regime` on purpose: the expert logic never has to know this
exists, and the plain text can be rewritten freely without touching a single
threshold.
"""
from __future__ import annotations

STANCE = {
    2: "Helping stocks",
    1: "Slightly helping stocks",
    0: "Neutral",
    -1: "Slightly hurting stocks",
    -2: "Hurting stocks",
}

READS = {
    "inflation": {
        "short": "prices",
        "label": "Prices (inflation)",
        "what": "How fast the prices of everyday things are rising. The US "
                "central bank - the Federal Reserve, or \"the Fed\" - aims for "
                "about 2% a year.",
        "why_you": "Inflation decides what the Fed does with interest rates, and "
                   "interest rates affect the value of almost everything you can "
                   "invest in. That makes this the first domino.",
    },
    "growth": {
        "short": "jobs and the economy",
        "label": "Jobs & the economy",
        "what": "Whether companies are hiring or laying people off, and whether "
                "the economy is growing.",
        "why_you": "Company profits come from people having jobs and spending "
                   "money. When jobs start disappearing, profits usually follow - "
                   "and so do stock prices.",
    },
    "policy": {
        "short": "the Fed's interest rate",
        "label": "The Fed & interest rates",
        "what": "The interest rate the Fed sets, which is the starting point for "
                "every other interest rate - mortgages, car loans, savings "
                "accounts.",
        "why_you": "When borrowing is expensive, companies and people spend less "
                   "and investors will pay less for stocks. When the Fed cuts "
                   "rates, the opposite tends to happen.",
    },
    "rates": {
        "short": "long-term interest rates",
        "label": "Long-term interest rates",
        "what": "What the US government pays to borrow for 10 years (the "
                "\"10-year Treasury yield\"). It sets the price of mortgages and "
                "is the yardstick every other investment is compared against.",
        "why_you": "If a safe government bond pays 5% a year, a risky stock has to "
                   "promise a lot more to be worth owning. So when long-term "
                   "rates rise quickly, stock prices usually fall - tech and "
                   "growth stocks most of all.",
    },
    "credit": {
        "short": "company borrowing",
        "label": "Company borrowing",
        "what": "How much extra interest lenders demand to lend to riskier "
                "companies, compared with lending to the government.",
        "why_you": "Lenders get paid before shareholders, so they watch for "
                   "trouble closely. When they start demanding a lot more "
                   "interest, it has usually been an early warning for stocks.",
    },
    "liquidity": {
        "short": "money in the system",
        "label": "Money in the system",
        "what": "How much cash is sloshing around the banking system, mostly "
                "controlled by the Fed buying or selling bonds.",
        "why_you": "More money in the system tends to push up prices of stocks and "
                   "other investments; draining it tends to do the opposite. It "
                   "works slowly, then sometimes suddenly.",
    },
    "risk": {
        "short": "investor mood",
        "label": "Investor mood",
        "what": "Whether investors are feeling confident or nervous right now, "
                "judged by how stocks are trending and how much people pay to "
                "protect against a fall.",
        "why_you": "This tells you what investors already believe, not what "
                   "happens next. It is most useful when it disagrees with the "
                   "other six cards.",
    },
}

TENSIONS = {
    "equities_ignore_credit":
        "Stock investors look calm, but lenders are getting nervous about "
        "companies' ability to repay debt. In the past, when these two "
        "disagreed, the lenders were usually right.",
    "equities_ignore_jobs":
        "Stocks are holding up even though the job market is weakening. That "
        "only works out if the Fed cuts interest rates before company profits "
        "start to fall.",
    "cuts_priced_into_inflation":
        "Investors are counting on the Fed cutting interest rates, but prices "
        "are still rising faster than the Fed wants. One bad inflation report "
        "could undo those hopes quickly.",
    "stagflation":
        "The economy is slowing while prices are still rising too fast. This is "
        "the hardest situation for the Fed, because the usual fix for one makes "
        "the other worse - it is why stocks and bonds both fell in 2022.",
    "nervous_without_cause":
        "Stock investors are nervous, but the economy and lenders look fine. "
        "Historically, falls that lenders don't confirm have tended to recover.",
    "consistent":
        "All the signals roughly agree with each other, so there is no obvious "
        "mismatch between what the data says and what investors are betting on. "
        "That makes the next big data release matter more than usual.",
}


def _v(summaries: dict, key: str):
    entry = summaries.get(key) or {}
    return entry.get("value")


def _chg(summaries: dict, key: str, window: str = "1m"):
    return ((summaries.get(key) or {}).get("changes") or {}).get(window)


def _rank_word(summaries: dict, key: str) -> str:
    """Where a value sits against its own last five years, in words."""
    rank = (summaries.get(key) or {}).get("pct_rank")
    if rank is None:
        return ""
    if rank >= 90:
        return "near the highest of the last five years"
    if rank >= 70:
        return "higher than usual for the last five years"
    if rank <= 10:
        return "near the lowest of the last five years"
    if rank <= 30:
        return "lower than usual for the last five years"
    return "about normal for the last five years"


def now_text(read: dict, summaries: dict, series: dict = None) -> str:
    """The current reading of one card, in a sentence or two with real numbers."""
    rid, score = read["id"], read["score"]
    fn = _NOW.get(rid)
    if not fn:
        return ""
    try:
        return fn(read, summaries, series or {}) or ""
    except (TypeError, ValueError, KeyError):
        return ""


def _now_inflation(read, s, _):
    core = _v(s, "core_pce") or _v(s, "core_cpi")
    fast = _v(s, "core_pce_3m")
    if core is None:
        return "No inflation data this run."
    base = f"Prices are rising about {core:.1f}% a year, against the Fed's goal of 2%."
    if read["state"].startswith("re-accelerating"):
        return base + (f" Worse, the last three months ran faster ({fast:.1f}% a year)"
                       " - inflation is speeding up again.")
    if read["state"].startswith("cooling"):
        return base + (f" The good news: the last three months ran slower "
                       f"({fast:.1f}% a year), so it is heading the right way.")
    if read["score"] >= 2:
        return base + " That is close enough for the Fed to relax."
    return base + " It is not slowing much, which keeps the Fed cautious."


def _now_growth(read, s, series):
    bits = []
    unemployment = _v(s, "unemployment")
    if unemployment is not None:
        bits.append(f"{unemployment:.1f}% of people looking for work can't find it")
    payrolls = _v(s, "payrolls")
    if payrolls is not None:
        if payrolls < 0:
            bits.append(f"employers cut {abs(payrolls):.0f},000 jobs last month")
        else:
            bits.append(f"employers added {payrolls:.0f},000 jobs last month")
    claims = _v(s, "claims")
    if claims is not None:
        bits.append(f"about {claims:.0f},000 people a week are filing for "
                    "unemployment benefits")
    head = {2: "The job market looks strong.", 1: "The job market looks healthy.",
            0: "The job market is mixed.", -1: "The job market is cooling.",
            -2: "The job market is getting weaker."}[max(-2, min(2, read["score"]))]
    if "Sahm" in read["state"]:
        head += (" Unemployment has risen enough that it has triggered a warning "
                 "sign that has come before every US recession since 1960.")
    return head + (" Right now " + ", ".join(bits) + "." if bits else "")


def _now_policy(read, s, _):
    funds = _v(s, "fed_funds")
    two = _v(s, "ust_2y")
    if funds is None:
        return "No Fed data this run."
    text = f"The Fed's main interest rate is {funds:.2f}%."
    core = _v(s, "core_pce") or _v(s, "core_cpi")
    if core is not None:
        gap = funds - core
        if gap > 1.5:
            text += (f" That's well above inflation ({core:.1f}%), so borrowing is "
                     "genuinely expensive - the Fed is deliberately slowing things "
                     "down.")
        elif gap > 0.5:
            text += (f" That's a bit above inflation ({core:.1f}%), so the Fed is "
                     "gently leaning on the brakes.")
        else:
            text += (f" That's close to or below inflation ({core:.1f}%), so money "
                     "is cheap in real terms.")
    if two is not None:
        diff = two - funds
        if diff < -0.25:
            text += (" Bond traders are betting the Fed will cut rates over the "
                     "next couple of years.")
        elif diff > 0.25:
            text += (" Bond traders are betting the Fed will raise rates over the "
                     "next couple of years.")
        else:
            text += " Bond traders expect it to stay roughly where it is."
    return text


def _now_rates(read, s, _):
    ten = _v(s, "ust_10y")
    if ten is None:
        return "No bond data this run."
    text = f"The 10-year government bond pays {ten:.2f}% a year"
    level = _rank_word(s, "ust_10y")
    text += f" - {level}." if level else "."
    change = _chg(s, "ust_10y")
    if change is not None and abs(change) >= 0.15:
        direction = "up" if change > 0 else "down"
        text += f" That's {direction} from about {ten - change:.2f}% a month ago"
        text += (" - a fast rise, which tends to pressure stock prices." if change > 0.4
                 else ".")
    mortgage = _v(s, "mortgage_30y")
    if mortgage is not None:
        text += f" A 30-year mortgage costs about {mortgage:.2f}%."
    return text


def _now_credit(read, s, _):
    hy = _v(s, "hy_spread")
    if hy is None:
        return "No lending data this run."
    text = (f"Lenders charge riskier companies about {hy:.1f} percentage points "
            "more interest than they charge the US government")
    level = _rank_word(s, "hy_spread")
    text += f" - {level}." if level else "."
    if read["score"] > 0:
        text += " Lenders are relaxed, so companies can borrow easily."
    elif read["score"] < 0:
        text += (" Lenders are getting more cautious, which has often been an "
                 "early warning for stocks.")
    return text


def _now_liquidity(read, s, _):
    change = _chg(s, "fed_balance_sheet", "3m")
    if change is None:
        return "No Fed balance-sheet data this run."
    if change < -1.0:
        return ("The Fed is slowly pulling money out of the financial system "
                f"(its holdings fell {abs(change):.1f}% in three months). That is a "
                "gentle headwind that works over months.")
    if change > 1.0:
        return ("The Fed is adding money to the financial system (its holdings "
                f"rose {change:.1f}% in three months), which tends to support prices.")
    return "The amount of money in the system is roughly steady - not a big factor right now."


def _now_risk(read, s, _):
    bits = []
    vs_ma = (s.get("spx") or {}).get("vs_ma200")
    if vs_ma is not None:
        where = "above" if vs_ma >= 0 else "below"
        bits.append(f"the S&P 500 (the 500 biggest US companies) is {abs(vs_ma):.0f}% "
                    f"{where} its average price of the past 200 days")
    vix = _v(s, "vix")
    if vix is not None:
        mood = ("calm" if vix < 15 else "normal" if vix < 20
                else "nervous" if vix < 30 else "fearful")
        bits.append(f"the \"fear gauge\" (VIX) is {vix:.0f}, which is {mood}")
    head = {2: "Investors are confident.", 1: "Investors are fairly confident.",
            0: "Investors are neither confident nor nervous.",
            -1: "Investors are a little nervous.", -2: "Investors are nervous."}[
        max(-2, min(2, read["score"]))]
    return head + (" Right now " + " and ".join(bits) + "." if bits else "")


_NOW = {
    "inflation": _now_inflation,
    "growth": _now_growth,
    "policy": _now_policy,
    "rates": _now_rates,
    "credit": _now_credit,
    "liquidity": _now_liquidity,
    "risk": _now_risk,
}


def lede(reads: list) -> str:
    """Two or three sentences a beginner can read in ten seconds."""
    by_id = {r["id"]: r for r in reads}
    helping = [READS[r["id"]]["short"] for r in reads if r["score"] > 0 and r["id"] in READS]
    hurting = [READS[r["id"]]["short"] for r in reads if r["score"] < 0 and r["id"] in READS]
    total = sum(r["score"] for r in reads)
    if total >= 2:
        head = "Overall, conditions are fairly good for stocks right now."
    elif total <= -2:
        head = "Overall, conditions are fairly tough for stocks right now."
    else:
        head = "Overall, conditions for stocks are mixed - some things help, some hurt."
    parts = [head]
    if helping:
        parts.append("Helping: " + _join(helping) + ".")
    if hurting:
        parts.append("Holding things back: " + _join(hurting) + ".")
    inflation = by_id.get("inflation")
    if inflation and inflation["score"] < 0:
        parts.append("The biggest single thing to watch is inflation, because it "
                     "decides whether the Fed can lower interest rates.")
    return " ".join(parts)


def _join(words: list) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def annotate(regime: dict, summaries: dict, series: dict = None) -> dict:
    """Add the beginner layer to an assessed regime, in place, and return it."""
    for read in regime.get("reads") or []:
        info = READS.get(read["id"], {})
        read["plain"] = {
            "label": info.get("label", read["label"]),
            "stance": STANCE[max(-2, min(2, read["score"]))],
            "what": info.get("what", ""),
            "why_you": info.get("why_you", ""),
            "now": now_text(read, summaries, series),
        }
    regime["plain"] = {
        "lede": lede(regime.get("reads") or []),
        "tension": TENSIONS.get(regime.get("tension_key", ""), ""),
    }
    return regime


# ------------------------------------------------------------------ calendar

# One line per scheduled event: what it is, and why anyone cares, in words a
# newcomer can follow. Keyed by the event id's prefix (calendar_rules' rule ids,
# and the fomc fetcher's "fomc-", "fomc-minutes-", "fomc-beige-").
EVENTS = {
    "fomc-minutes": ("Fed meeting notes",
                     "Detailed notes from the Fed's last meeting. They show how much "
                     "the officials disagreed, which hints at what they'll do next."),
    "fomc-beige": ("Fed's economy survey (Beige Book)",
                   "The Fed's collection of stories from businesses around the "
                   "country. Rarely moves markets, but shows what the Fed is hearing."),
    "fomc": ("Fed interest-rate decision",
             "The Fed announces whether it is raising, cutting or holding interest "
             "rates. This is usually the single biggest scheduled event for markets."),
    "cpi": ("Inflation report (CPI)",
            "The government's monthly measure of how fast prices are rising. A "
            "higher-than-expected number usually pushes stocks down."),
    "ppi": ("Wholesale prices (PPI)",
            "How fast prices are rising for businesses. It often hints at where "
            "consumer prices will go next."),
    "jobs": ("Jobs report",
             "The government's monthly count of how many jobs were added and the "
             "unemployment rate. One of the most-watched numbers of the month."),
    "claims": ("Weekly unemployment claims",
               "How many people applied for unemployment benefits last week - the "
               "fastest signal of whether layoffs are picking up."),
    "pce": ("The Fed's favourite inflation measure (PCE)",
            "A second, broader inflation report. It's the one the Fed actually "
            "targets, so it matters for interest-rate decisions."),
    "retail": ("Retail sales",
               "How much Americans spent in shops and online last month. Consumer "
               "spending is about two-thirds of the US economy."),
    "ism_mfg": ("Factory survey",
                "A survey of factory managers. Above 50 means manufacturing is "
                "growing; below 50 means it's shrinking."),
    "ism_svcs": ("Services survey",
                 "The same survey for service businesses (restaurants, banks, "
                 "software...), which are most of the economy."),
    "gdp": ("Economic growth (GDP)",
            "How much the whole US economy grew last quarter. Important, but it "
            "comes out late, so markets usually know roughly what it will say."),
    "jolts": ("Job openings",
              "How many jobs employers are trying to fill. Fewer openings means "
              "the job market is cooling."),
    "umich_prelim": ("Consumer mood survey",
                     "A survey of how confident people feel about their finances "
                     "and where they think prices are heading."),
    "confidence": ("Consumer confidence",
                   "Another survey of how confident people feel, focused more on "
                   "jobs."),
    "housing": ("New home construction",
                "How many new homes builders started. Housing is very sensitive to "
                "interest rates, so it often slows first."),
    "refunding": ("Government borrowing plans",
                  "The US Treasury says how much it plans to borrow and how. Big "
                  "borrowing plans can push interest rates up."),
    "auction_10y": ("10-year bond sale",
                    "The government sells new 10-year bonds. Weak demand can push "
                    "interest rates up the same day."),
    "auction_30y": ("30-year bond sale",
                    "The government sells new 30-year bonds - the ones most "
                    "sensitive to worries about government debt."),
    "earnings_open": ("Earnings season begins",
                      "Big banks report their quarterly profits first, kicking off "
                      "weeks of companies reporting results."),
    "opex": ("Options expire",
             "A monthly technical event that can make prices jumpy for a day. It "
             "doesn't tell you anything about the economy."),
    "quad_witching": ("Big quarterly options expiry",
                      "A larger version of the monthly options expiry, plus index "
                      "reshuffles. Lots of trading, very little meaning."),
    "jackson_hole": ("Fed's annual conference (Jackson Hole)",
                     "Where Fed chairs have often signalled big changes in "
                     "direction. Watched closely every August."),
}
# Longest prefix first, so "fomc-minutes" wins over "fomc".
_EVENT_PREFIXES = sorted(EVENTS, key=len, reverse=True)


def event_plain(event_id: str) -> dict:
    """{"title", "what"} for a calendar event id, or {} if unknown."""
    for prefix in _EVENT_PREFIXES:
        if event_id == prefix or event_id.startswith(prefix + "-"):
            title, what = EVENTS[prefix]
            return {"title": title, "what": what}
    return {}
