"""What a company earns, what its shares cost, and what the price assumes.

Buying a share is buying a slice of a company, so the question is the one
you would ask buying a shop: what does it cost, and what does it earn? This
module turns one TradingView row into that answer, in the order the ideas
build on each other:

1. **The price of the whole company** - market cap (shares x price) and
   enterprise value (EV: market cap + debt - cash, the price including the
   debt you would inherit).
2. **Earning power** - revenue, net income, free cash flow (FCF: operating
   cash flow minus capital expenditure - the cash actually left over), and
   earnings per share (EPS).
3. **Price / earning power** - the multiples: P/E, its inverse the earnings
   yield, P/S for companies with no profit, P/FCF and its inverse the FCF
   yield, EV/EBITDA, and PEG, which divides P/E by growth.
4. **Quality** - margins (gross, operating, net), return on equity (ROE),
   return on invested capital (ROIC).
5. **Growth** - revenue and EPS growth, because a multiple means nothing
   without the growth rate next to it.
6. **Safety and risk** - debt/equity, the current ratio, beta.
7. **Expectations** - the forward P/E, the last earnings surprise, analysts'
   average target - and a reverse DCF: the yearly FCF growth that today's
   price implies, which is the most honest way to say "what is priced in".

Each metric carries a plain reading and the industry's typical value, so a
beginner sees "P/E 54 (software typically 38)" rather than a bare number.

The readings describe what a number MEANS - "the price rests on growth
expected later" - and never say a stock is cheap, expensive, or worth buying.
A high multiple is a statement about expectations, not a verdict.
"""
from __future__ import annotations
from statistics import median

# Inputs to the cost-of-capital estimate. Deliberately simple and shown on
# the page: the point of a DCF here is to make assumptions visible, not to
# pretend to precision.
EQUITY_RISK_PREMIUM = 5.0   # % a year investors want over Treasuries for stocks
DEBT_SPREAD = 1.5           # % over Treasuries a typical company borrows at
TAX_RATE = 21.0             # US federal corporate rate
TERMINAL_GROWTH = 3.0       # % a year forever after year 10 ~ nominal GDP
DCF_YEARS = 10
WACC_FLOOR, WACC_CAP = 6.0, 14.0

# The fields worth an industry median, for "typical in its industry".
PEER_FIELDS = ("pe", "forward_pe", "ps", "p_fcf", "ev_ebitda", "gross_margin",
               "operating_margin", "net_margin", "revenue_growth", "roic", "roe",
               "debt_to_equity", "beta")


def industry_medians(scan: dict, min_n: int = 5) -> dict:
    """{industry: {field: median}} over profitable-or-not peers alike.

    Multiples are taken only where positive: a negative P/E is not a small
    P/E, it is "no profit", and averaging it in would drag the typical value
    toward nonsense.
    """
    buckets = {}
    for row in scan.values():
        if row.get("industry"):
            buckets.setdefault(row["industry"], []).append(row)
    out = {}
    for industry, rows in buckets.items():
        if len(rows) < min_n:
            continue
        typical = {"n": len(rows)}
        for field in PEER_FIELDS:
            values = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
            if field in ("pe", "forward_pe", "ps", "p_fcf", "ev_ebitda"):
                values = [v for v in values if 0 < v < 1000]
            if len(values) >= min_n:
                typical[field] = round(median(values), 1)
        out[industry] = typical
    return out


# ---------------------------------------------------------------- helpers

def _num(row, key):
    value = (row or {}).get(key)
    return value if isinstance(value, (int, float)) else None


def money(value) -> str:
    if value is None:
        return "-"
    sign = "-" if value < 0 else ""
    v = abs(value)
    for size, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if v >= size:
            return f"{sign}${v / size:.1f} {word}"
    return f"{sign}${v:,.0f}"


def _pct(value, digits=0) -> str:
    return "-" if value is None else f"{value:.{digits}f}%"


def _x(value) -> str:
    return "-" if value is None else f"{value:.1f}x"


def _item(key, value, text, read="", tone="", typical=None, typical_text=""):
    out = {"id": key, "value": value, "text": text, "read": read, "tone": tone}
    if typical is not None:
        out["typical"] = typical
        out["typical_text"] = typical_text
    return out


# ------------------------------------------------------------------ reads

def read_pe(pe, growth):
    if pe is None or pe <= 0:
        return "No profit over the past year, so there is no P/E. Look at P/S and growth instead.", "na"
    years = f"At today's profit, the price equals about {pe:.0f} years of earnings."
    if pe < 12:
        return years + " The market expects little growth - or doubts the profit lasts.", "low"
    if pe < 25:
        return years + " A middle-of-the-road expectation.", "mid"
    if pe < 60:
        return years + " The price assumes profits keep growing for years.", "high"
    return years + " The price rests mostly on profits expected later, not today's.", "high"


def read_peg(peg):
    if peg is None or peg <= 0:
        return "", "na"
    if peg < 1:
        return "P/E is lower than the profit growth rate: the price asks for less than the growth delivers.", "low"
    if peg <= 2:
        return "P/E roughly in line with profit growth.", "mid"
    return "P/E well above the growth rate: the price assumes more than recent growth explains.", "high"


def read_margin(kind, value):
    if value is None:
        return "", "na"
    if kind == "gross":
        if value >= 60:
            return f"Keeps ${value:.0f} of every $100 of sales after the direct cost of the product - typical of software and chip design.", "good"
        if value >= 30:
            return f"Keeps ${value:.0f} of every $100 after the direct cost of what it sells.", "mid"
        return f"Only ${value:.0f} of every $100 is left after direct costs - typical of retail, food and manufacturing.", "low"
    if kind == "operating":
        if value < 0:
            return "Losing money on its main business once research, sales and overhead are paid - often spending to grow.", "bad"
        if value >= 25:
            return f"${value:.0f} of every $100 of sales is profit from the main business - very strong.", "good"
        return f"${value:.0f} of every $100 of sales is profit from the main business.", "mid"
    # net
    if value < 0:
        return "Loses money after every cost and tax.", "bad"
    return f"${value:.0f} of every $100 of sales is left after every cost and tax.", "good" if value >= 15 else "mid"


def read_roic(roic, wacc):
    if roic is None:
        return "", "na"
    if wacc is not None and roic > wacc:
        return (f"Earns {roic:.0f}% a year on the money put into the business - above the "
                f"~{wacc:.0f}% its investors require, so growth adds value."), "good"
    if roic < 0:
        return "Losing money on the capital invested - not yet creating value.", "bad"
    return (f"Earns {roic:.0f}% on invested money, below the ~{wacc or 0:.0f}% investors "
            "require - growth at this return does not add value yet."), "low"


def read_growth(value):
    if value is None:
        return "", "na"
    if value >= 30:
        return f"Sales up {value:.0f}% in a year - fast growth.", "good"
    if value >= 10:
        return f"Sales up {value:.0f}% in a year - healthy growth.", "good"
    if value >= 0:
        return f"Sales up {value:.0f}% in a year - slow growth.", "mid"
    return f"Sales down {abs(value):.0f}% in a year - shrinking.", "bad"


def read_debt(de, current):
    parts, tone = [], "mid"
    if de is not None:
        if de < 0.3:
            parts.append(f"Little debt (${de:.2f} borrowed per $1 of shareholder money).")
            tone = "good"
        elif de < 1.5:
            parts.append(f"Moderate debt (${de:.2f} per $1 of shareholder money).")
        else:
            parts.append(f"Heavy debt (${de:.2f} per $1 of shareholder money) - rising rates hurt more.")
            tone = "bad"
    if current is not None and current < 1:
        parts.append("Bills due within a year exceed assets that turn to cash within a "
                     "year - fine for businesses paid daily in cash (restaurants, shops), "
                     "a warning sign for others.")
    return " ".join(parts), tone


def read_beta(beta):
    if beta is None:
        return "", "na"
    if beta > 1.3:
        return f"Moves about {beta:.1f}x as much as the market - bigger swings both ways.", "high"
    if beta < 0.7:
        return f"Moves only about {beta:.1f}x as much as the market - calmer than most.", "low"
    return f"Moves about as much as the market ({beta:.1f}x).", "mid"


# -------------------------------------------------------------- the model

def cost_of_capital(row: dict, risk_free: float) -> dict:
    """WACC from the CAPM: the return investors require, weighted by how the
    company is funded. Every input is returned so the page can show its work."""
    raw = _num(row, "beta")
    # Blume's adjustment: measured betas drift toward 1 over time, so the
    # forward-looking estimate is pulled a third of the way there.
    beta = 0.67 * (raw if raw is not None else 1.0) + 0.33
    beta = min(max(beta, 0.5), 2.5)
    cost_equity = risk_free + beta * EQUITY_RISK_PREMIUM
    cost_debt = risk_free + DEBT_SPREAD
    equity = _num(row, "market_cap") or 0
    debt = max(_num(row, "debt") or 0, 0)
    total = equity + debt
    w_e = equity / total if total else 1.0
    wacc = w_e * cost_equity + (1 - w_e) * cost_debt * (1 - TAX_RATE / 100)
    return {
        "risk_free": round(risk_free, 2),
        "beta": round(beta, 2),
        "cost_equity": round(cost_equity, 1),
        "cost_debt": round(cost_debt, 1),
        "equity_weight": round(w_e * 100),
        "wacc": round(min(max(wacc, WACC_FLOOR), WACC_CAP), 1),
    }


def dcf_value(fcf: float, growth: float, wacc: float, terminal: float = TERMINAL_GROWTH,
              years: int = DCF_YEARS) -> float:
    """Present value of `years` of FCF growing at `growth`%, plus a terminal
    value growing at `terminal`% forever. Percent in, dollars out."""
    r, g, tg = wacc / 100, growth / 100, terminal / 100
    total, cash = 0.0, fcf
    for t in range(1, years + 1):
        cash *= 1 + g
        total += cash / (1 + r) ** t
    terminal_value = cash * (1 + tg) / (r - tg)
    return total + terminal_value / (1 + r) ** years


def implied_growth(fcf: float, ev: float, wacc: float) -> float:
    """The yearly FCF growth for ten years that makes the DCF equal today's EV.
    Bisection: dcf_value rises monotonically with growth."""
    if not fcf or fcf <= 0 or not ev or ev <= 0 or wacc <= TERMINAL_GROWTH:
        return None
    lo, hi = -50.0, 150.0
    if dcf_value(fcf, hi, wacc) < ev:
        return hi
    if dcf_value(fcf, lo, wacc) > ev:
        return lo
    for _ in range(80):
        mid = (lo + hi) / 2
        if dcf_value(fcf, mid, wacc) < ev:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 1)


def read_implied(growth, past_growth):
    if growth is None:
        return "Free cash flow is negative, so no growth rate makes a DCF match the price - the value rests on the company becoming cash-positive."
    if growth < 0:
        base = (f"Today's price would be justified even if free cash flow SHRANK about "
                f"{abs(growth):.0f}% a year for ten years - the market expects decline, or "
                "doubts today's cash flow lasts.")
    else:
        base = (f"To justify today's price, free cash flow would need to grow about "
                f"{growth:.0f}% a year for ten years.")
    if past_growth is None:
        return base
    if growth > past_growth + 10:
        return base + (f" Sales grew {past_growth:.0f}% last year, so the price assumes "
                       "growth stays strong - or speeds up - for a long time.")
    if growth < past_growth - 10:
        return base + (f" Sales grew {past_growth:.0f}% last year, so the price assumes "
                       "growth slows a lot - the market is skeptical it lasts.")
    return base + f" That is close to last year's {past_growth:.0f}% sales growth."


# --------------------------------------------------------------- assemble

def profile(row: dict, typical: dict = None, risk_free: float = 4.2) -> dict:
    """The full value-and-quality card for one stock, or {} with no data."""
    if not row or _num(row, "market_cap") is None:
        return {}
    typical = typical or {}
    cap = _num(row, "market_cap")
    price = _num(row, "price")
    revenue, net, fcf = _num(row, "revenue"), _num(row, "net_income"), _num(row, "fcf")
    ocf, capex = _num(row, "ocf"), _num(row, "capex")
    debt, cash = _num(row, "debt"), _num(row, "cash")
    ev = _num(row, "ev") or (cap + (debt or 0) - (cash or 0))
    pe, fpe, peg = _num(row, "pe"), _num(row, "forward_pe"), _num(row, "peg")
    ps = _num(row, "ps") or (cap / revenue if revenue else None)
    p_fcf = _num(row, "p_fcf") or (cap / fcf if fcf and fcf > 0 else None)
    fcf_yield = fcf / cap * 100 if fcf is not None and cap else None
    growth = _num(row, "revenue_growth")
    capital = cost_of_capital(row, risk_free)
    roic = _num(row, "roic")

    def typ(field, fmt):
        value = typical.get(field)
        return (value, fmt(value)) if value is not None else (None, "")

    pe_read, pe_tone = read_pe(pe, _num(row, "eps_growth"))
    peg_read, peg_tone = read_peg(peg)
    debt_read, debt_tone = read_debt(_num(row, "debt_to_equity"), _num(row, "current_ratio"))
    beta_read, beta_tone = read_beta(_num(row, "beta"))
    implied = implied_growth(fcf, ev, capital["wacc"])

    groups = [
        {"id": "size", "title": "What the whole company costs", "items": [
            _item("market_cap", cap, money(cap),
                  "Share price x number of shares: the price of buying every share."),
            _item("ev", ev, money(ev),
                  f"Market cap {money(cap)} + debt {money(debt or 0)} - cash {money(cash or 0)}: "
                  "the price including the debt a buyer would take on."),
        ]},
        {"id": "earning", "title": "What it earns", "items": [
            _item("revenue", revenue, money(revenue), "Money customers paid over the past year."),
            _item("net_income", net, money(net),
                  "What is left after every cost and tax." if (net or 0) >= 0
                  else "A loss: costs and taxes exceeded sales."),
            _item("fcf", fcf, money(fcf),
                  (f"Cash from the business {money(ocf)} minus investment in equipment "
                   f"{money(abs(capex))}: the cash actually left over - harder to dress "
                   "up than profit." if ocf is not None and capex is not None
                   else "Cash actually left over after investing in the business."),
                  "good" if (fcf or 0) > 0 else "bad"),
            _item("eps", _num(row, "eps"),
                  "-" if _num(row, "eps") is None else f"${_num(row, 'eps'):.2f}",
                  "Profit per share over the past year."),
        ]},
        {"id": "multiples", "title": "Price compared with earnings", "items": [
            _item("pe", pe, _x(pe) if pe and pe > 0 else
                  ("no profit" if (_num(row, "eps") or 0) <= 0 and _num(row, "eps") is not None
                   else "-"), pe_read, pe_tone, *typ("pe", _x)),
            _item("earnings_yield", 100 / pe if pe and pe > 0 else None,
                  _pct(100 / pe, 1) if pe and pe > 0 else "-",
                  "P/E flipped over: profit per $100 of share price - comparable to an "
                  "interest rate." if pe and pe > 0 else ""),
            _item("ps", ps, _x(ps), "Market cap / sales. Used for companies with no profit yet.",
                  "", *typ("ps", _x)),
            _item("p_fcf", p_fcf, _x(p_fcf) if p_fcf else "-",
                  "Market cap / free cash flow: years of today's cash to pay the price.",
                  "", *typ("p_fcf", _x)),
            _item("fcf_yield", fcf_yield, _pct(fcf_yield, 1),
                  (f"Every $100 of shares produces about ${fcf_yield:.1f} of free cash a year."
                   if fcf_yield and fcf_yield > 0 else "No free cash produced yet.")),
            _item("ev_ebitda", _num(row, "ev_ebitda"), _x(_num(row, "ev_ebitda")),
                  "EV / profit before interest, tax and depreciation: compares companies "
                  "with different debt and tax.", "", *typ("ev_ebitda", _x)),
            _item("peg", peg, f"{peg:.2f}" if peg and peg > 0 else "-", peg_read, peg_tone),
        ]},
        {"id": "quality", "title": "How good the business is", "items": [
            _item("gross_margin", _num(row, "gross_margin"), _pct(_num(row, "gross_margin")),
                  *read_margin("gross", _num(row, "gross_margin")), *typ("gross_margin", _pct)),
            _item("operating_margin", _num(row, "operating_margin"),
                  _pct(_num(row, "operating_margin")),
                  *read_margin("operating", _num(row, "operating_margin")),
                  *typ("operating_margin", _pct)),
            _item("net_margin", _num(row, "net_margin"), _pct(_num(row, "net_margin")),
                  *read_margin("net", _num(row, "net_margin")), *typ("net_margin", _pct)),
            _item("roe", _num(row, "roe"), _pct(_num(row, "roe")),
                  "Profit / shareholders' money. Misleading when buybacks have shrunk "
                  "shareholder equity to near zero or below."),
            _item("roic", roic, _pct(roic), *read_roic(roic, capital["wacc"]), *typ("roic", _pct)),
        ]},
        {"id": "growth", "title": "Is it growing", "items": [
            _item("revenue_growth", growth, _pct(growth), *read_growth(growth),
                  *typ("revenue_growth", _pct)),
            _item("eps_growth", _num(row, "eps_growth"), _pct(_num(row, "eps_growth")),
                  "Change in profit per share over a year."),
        ]},
        {"id": "risk", "title": "How fragile it is", "items": [
            _item("debt_to_equity", _num(row, "debt_to_equity"),
                  "-" if _num(row, "debt_to_equity") is None else f"{_num(row, 'debt_to_equity'):.2f}",
                  debt_read, debt_tone, *typ("debt_to_equity", lambda v: f"{v:.2f}")),
            _item("current_ratio", _num(row, "current_ratio"),
                  "-" if _num(row, "current_ratio") is None else f"{_num(row, 'current_ratio'):.2f}",
                  "Assets that turn to cash within a year / bills due within a year. "
                  "Below 1 means thin short-term cover."),
            _item("beta", _num(row, "beta"),
                  "-" if _num(row, "beta") is None else f"{_num(row, 'beta'):.2f}",
                  beta_read, beta_tone),
        ]},
        {"id": "expectations", "title": "What the price expects", "items": [
            _item("forward_pe", fpe, _x(fpe) if fpe and fpe > 0 else "-",
                  (f"Price / next year's expected profit. Lower than today's P/E of "
                   f"{pe:.0f}, so profit is expected to grow."
                   if fpe and pe and 0 < fpe < pe else
                   "Price / next year's expected profit."), "", *typ("forward_pe", _x)),
            _item("target_avg", _num(row, "target_avg"),
                  "-" if _num(row, "target_avg") is None else f"${_num(row, 'target_avg'):.0f}",
                  (f"Analysts' average 12-month target, {(_num(row, 'target_avg') / price - 1) * 100:+.0f}% "
                   f"from today (range ${_num(row, 'target_low') or 0:.0f}-${_num(row, 'target_high') or 0:.0f}). "
                   "Targets are opinions and are often wrong."
                   if _num(row, "target_avg") and price else "")),
        ]},
    ]
    for group in groups:
        # Missing data is left out; "no profit" is data and stays.
        group["items"] = [i for i in group["items"]
                          if i["value"] is not None or i["text"] == "no profit"]
    groups = [g for g in groups if g["items"]]

    first_three = [
        ("revenue_growth", "Is it growing?", read_growth(growth)),
        ("operating_margin", "Is it profitable while growing?",
         read_margin("operating", _num(row, "operating_margin"))),
        ("roic", "Does the money put in earn enough?", read_roic(roic, capital["wacc"])),
    ]
    strong = sum(1 for _, _, (_, tone) in first_three if tone == "good")
    weak = sum(1 for _, _, (_, tone) in first_three if tone in ("bad", "low"))
    rich = (pe or 0) > 40 or (pe is None or pe <= 0) and (ps or 0) > 10
    if strong == 3:
        verdict = ("All three are strong. Businesses like this usually carry higher "
                   "multiples, because the growth is real and profitable.")
    elif weak >= 2 and rich:
        verdict = ("Two or more are weak while the price multiple is high: the price "
                   "rests mainly on expectations of what the company becomes.")
    elif weak >= 2:
        verdict = "Two or more are weak - the business is still proving itself."
    else:
        verdict = "A mixed picture: some strengths, some open questions."

    return {
        "groups": groups,
        "first_three": [{"id": k, "question": q, "read": r, "tone": t}
                        for k, q, (r, t) in first_three],
        "verdict": verdict,
        "dcf": {
            **capital,
            "fcf": fcf,
            "ev": ev,
            "debt": debt or 0,
            "cash": cash or 0,
            "shares": _num(row, "shares"),
            "terminal_growth": TERMINAL_GROWTH,
            "years": DCF_YEARS,
            "implied_growth": implied,
            "read": read_implied(implied, growth),
        },
        "earnings_next": row.get("earnings_next") or "",
        "earnings_last": row.get("earnings_last") or "",
        "eps_surprise": _num(row, "eps_surprise"),
        "revenue_surprise": _num(row, "revenue_surprise"),
    }
