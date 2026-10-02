"""What could happen next, why, and how we will know.

Investing is a bet on a future nobody knows. The useful discipline is not
predicting one outcome but laying out the few that are plausible, the chain
of cause and effect behind each, and the measurable signs that would tell you
which one is arriving. That is what this module builds, in three layers:

1. **Four scenarios** - the classic growth-versus-inflation map professional
   macro investors use (Bridgewater's "four seasons"): growth holds or
   slows, inflation cools or stays hot. Every economy is always heading toward
   one of the four corners, and each corner has a well-documented pattern of
   which industries, bonds and currencies do well or badly. Each scenario
   carries SIGNPOSTS - thresholds on series this project already tracks - so
   "which way are we leaning" is computed from data each morning, not
   asserted.

2. **Second-order chains** - the knock-on effects that turn a headline into
   an industry story. Tariffs raise import costs (first order); retailers
   squeezed between costs and customers (second); supply chains move to
   Mexico and Vietnam over years (long run). A curated library of the chains
   that recur, each switched on when today's data or news triggers it, each
   saying what would break the chain.

3. **Hypotheses, tracked** - a prediction is only worth something if it is
   checked. Every active chain (and every model-written chain) leaves a
   falsifiable claim - "core inflation higher in 90 days" - with the value on
   the day it was made. When the date comes, it is scored against what
   happened. Over months this is the page's track record, and the honest
   answer to "does this reasoning work?"

Nothing here says what to do with money. Scenarios describe what tends to
happen to whom; the reader decides what it means for them.
"""
from __future__ import annotations
import re
from datetime import date, timedelta

# --------------------------------------------------------------- scenarios

# A signpost: (metric id, field, op, threshold, plain sentence). field is
# "value" or "chg_<window>" (the change over that window, in the metric's own
# change units - percentage points for rates, percent for prices).
SCENARIOS = (
    {
        "id": "soft_landing",
        "title": "Soft landing",
        "outcome": "right",
        "tagline": "Growth holds, inflation cools",
        "story": "Inflation drifts back toward the Fed's 2% goal without many people "
                 "losing their jobs. The Fed can cut rates slowly, borrowing gets "
                 "cheaper, and company profits keep growing.",
        "chain": [
            "Inflation cools while hiring continues",
            "The Fed can lower interest rates without fearing a rebound in prices",
            "Lower rates make borrowing cheaper and future profits worth more today",
            "Stocks broaden out: smaller and debt-heavy companies benefit most",
        ],
        "industries": [
            {"name": "Small companies", "dir": "+", "how": "They borrow at floating rates, so cuts lift their profits directly."},
            {"name": "Homebuilders & housing", "dir": "+", "how": "Mortgage rates fall, more people can afford to buy."},
            {"name": "Growth tech", "dir": "+", "how": "Profits far in the future are worth more when rates fall."},
            {"name": "Banks", "dir": "~", "how": "More lending, but a smaller gap between what they pay and earn on deposits."},
            {"name": "Cash & money funds", "dir": "-", "how": "Interest on savings falls with the Fed's rate."},
        ],
        "history": "1995 and 2019: the Fed cut a little, there was no recession, and stocks rose strongly.",
        "signposts": [
            ("core_pce_3m", "value", "<", 2.6, "Recent inflation (3-month pace) below 2.6%"),
            ("payrolls", "value", ">", 75, "Employers still adding over 75,000 jobs a month"),
            ("claims", "value", "<", 250, "Weekly layoff claims below 250,000"),
            ("gdp_now", "value", ">", 1.5, "Economy growing faster than 1.5% a year"),
            ("hy_spread", "value", "<", 4.0, "Risky-company borrowing costs calm (spread below 4 points)"),
        ],
    },
    {
        "id": "running_hot",
        "title": "Running hot",
        "outcome": "mixed",
        "tagline": "Growth strong, inflation comes back",
        "story": "The economy stays strong enough that prices start rising faster "
                 "again. Instead of cutting, the Fed holds rates high or raises them. "
                 "Profits grow, but the rates used to value them rise too.",
        "chain": [
            "Strong demand and tight hiring push wages and prices up",
            "The Fed keeps rates high - or raises them",
            "Bond yields rise, so future profits are worth less today",
            "Companies with profits now beat companies promising profits later",
        ],
        "industries": [
            {"name": "Energy & materials", "dir": "+", "how": "Commodity prices rise with demand and inflation."},
            {"name": "Banks & insurers", "dir": "+", "how": "Earn more on loans and invested premiums when rates are high."},
            {"name": "Industrials", "dir": "+", "how": "Strong orders while the economy runs hot."},
            {"name": "Unprofitable growth tech", "dir": "-", "how": "Valued on distant profits, which higher rates shrink most."},
            {"name": "Long-term bonds", "dir": "-", "how": "Their fixed payments are worth less when inflation and yields rise."},
            {"name": "Real estate", "dir": "-", "how": "Higher mortgage and borrowing costs."},
        ],
        "history": "2021-22 began this way: strong growth, inflation took off, and the Fed raised rates fast.",
        "signposts": [
            ("core_pce_3m", "value", ">", 3.0, "Recent inflation (3-month pace) above 3%"),
            ("payrolls", "value", ">", 150, "Employers adding over 150,000 jobs a month"),
            ("gdp_now", "value", ">", 2.5, "Economy growing faster than 2.5% a year"),
            ("breakeven_10y", "value", ">", 2.5, "Bond market expects inflation above 2.5%"),
            ("wti", "chg_3m", ">", 10, "Oil up more than 10% in three months"),
        ],
    },
    {
        "id": "stagflation",
        "title": "Stagflation",
        "outcome": "wrong",
        "tagline": "Growth slows, inflation stays high",
        "story": "The economy weakens but prices keep rising - often because of an "
                 "energy or supply shock. The Fed is stuck: cutting rates would feed "
                 "inflation, holding them hurts jobs. Stocks and bonds can fall together.",
        "chain": [
            "A cost shock (oil, tariffs, wages) keeps prices rising",
            "Households' money buys less, so they spend less",
            "The Fed can't cut to help, because inflation is still high",
            "Profits shrink while borrowing stays expensive - the worst mix for stocks and bonds",
        ],
        "industries": [
            {"name": "Energy", "dir": "+", "how": "Often the cause: high oil prices are their revenue."},
            {"name": "Consumer staples & utilities", "dir": "+", "how": "People keep buying food, soap and power; these hold up relatively."},
            {"name": "Gold", "dir": "+", "how": "Holds value when money is losing it and policy is boxed in."},
            {"name": "Retail & restaurants", "dir": "-", "how": "Squeezed between rising costs and customers spending less."},
            {"name": "Airlines & transport", "dir": "-", "how": "Fuel is a top cost, and travel demand falls."},
            {"name": "Long-term bonds", "dir": "-", "how": "Inflation erodes fixed payments, and rates can't fall."},
        ],
        "history": "The 1970s, and 2022: stocks and bonds fell together because the Fed was fighting inflation in a slowing economy.",
        "signposts": [
            ("core_pce_3m", "value", ">", 3.0, "Recent inflation (3-month pace) above 3%"),
            ("gdp_now", "value", "<", 1.0, "Economy growing slower than 1% a year"),
            ("unemployment", "chg_3m", ">", 0.2, "Unemployment up more than 0.2 points in three months"),
            ("wti", "chg_3m", ">", 15, "Oil up more than 15% in three months"),
            ("sentiment", "value", "<", 60, "Consumer confidence weak (below 60)"),
        ],
    },
    {
        "id": "downturn",
        "title": "Downturn",
        "outcome": "wrong",
        "tagline": "Growth slows, inflation falls",
        "story": "Hiring stops and layoffs rise. Inflation falls with demand, so the "
                 "Fed cuts rates quickly - but company profits fall first, and stocks "
                 "usually drop before the cuts help.",
        "chain": [
            "Companies stop hiring, then start laying off",
            "People spend less, so company sales and profits fall",
            "Inflation drops, so the Fed cuts rates fast",
            "Bonds rise; stocks fall first and recover once the cuts work",
        ],
        "industries": [
            {"name": "Long-term bonds", "dir": "+", "how": "Rates fall sharply, lifting bond prices."},
            {"name": "Health care & staples", "dir": "+", "how": "Demand barely changes in a recession."},
            {"name": "Consumer discretionary", "dir": "-", "how": "Travel, cars and shopping are the first things people cut."},
            {"name": "Banks & lenders", "dir": "-", "how": "More borrowers can't repay."},
            {"name": "Small & debt-heavy companies", "dir": "-", "how": "Least cushion when sales fall."},
            {"name": "Industrials & materials", "dir": "-", "how": "Orders and building slow down."},
        ],
        "history": "2001, 2008 and 2020: stocks fell 30-50% from their peak before recovering.",
        "signposts": [
            ("gdp_now", "value", "<", 1.0, "Economy growing slower than 1% a year"),
            ("payrolls", "value", "<", 50, "Employers adding fewer than 50,000 jobs a month"),
            ("claims", "value", ">", 260, "Weekly layoff claims above 260,000"),
            ("hy_spread", "value", ">", 4.5, "Risky-company borrowing costs jumping (spread above 4.5 points)"),
            ("core_pce_3m", "value", "<", 2.3, "Recent inflation (3-month pace) below 2.3%"),
        ],
    },
)
SCENARIO_IDS = tuple(s["id"] for s in SCENARIOS)


def metric_value(summaries: dict, metric: str, field: str = "value"):
    entry = summaries.get(metric) or {}
    if field == "value":
        value = entry.get("value")
    elif field.startswith("chg_"):
        value = (entry.get("changes") or {}).get(field[4:])
    else:
        value = None
    return value if isinstance(value, (int, float)) else None


def check_signpost(summaries: dict, post) -> dict:
    metric, field, op, threshold, text = post
    value = metric_value(summaries, metric, field)
    met = None if value is None else (value > threshold if op == ">" else value < threshold)
    entry = summaries.get(metric) or {}
    unit = entry.get("unit", "")
    shown = None
    if value is not None:
        shown = (f"{value:+.1f}" if field.startswith("chg_") else f"{value:.1f}") + (
            "%" if field.startswith("chg_") and entry.get("change_kind") == "pct" else
            "" if field.startswith("chg_") else (" " + unit if unit else ""))
    return {"metric": metric, "label": entry.get("label", metric), "field": field,
            "op": op, "threshold": threshold, "text": text, "value": value,
            "shown": shown, "met": met}


def evaluate(summaries: dict) -> list:
    """Each scenario with its signposts checked against today's readings, and
    a share of signposts met. Sorted by that share, highest first."""
    out = []
    for scenario in SCENARIOS:
        checks = [check_signpost(summaries, p) for p in scenario["signposts"]]
        known = [c for c in checks if c["met"] is not None]
        met = sum(1 for c in known if c["met"])
        out.append({
            **{k: v for k, v in scenario.items() if k != "signposts"},
            "signposts": checks,
            "met": met,
            "known": len(known),
            "share": round(met / len(known), 2) if known else 0.0,
        })
    out.sort(key=lambda s: -s["share"])
    return out


def lean_sentence(evaluated: list) -> str:
    if not evaluated or not evaluated[0]["known"]:
        return "Not enough data to say which way things lean."
    top, second = evaluated[0], evaluated[1] if len(evaluated) > 1 else None
    if second and second["share"] == top["share"] and top["met"]:
        return (f"Today's data fits \"{top['title']}\" and \"{second['title']}\" equally "
                f"({top['met']} of {top['known']} signs each). They share strong growth and "
                "differ on inflation, so the next inflation readings decide between them."
                if {top["id"], second["id"]} == {"soft_landing", "running_hot"} else
                f"Today's data fits \"{top['title']}\" and \"{second['title']}\" equally "
                f"({top['met']} of {top['known']} signs each), so the picture is not settled.")
    out = (f"Today's data fits \"{top['title']}\" best: {top['met']} of its "
           f"{top['known']} signs are showing.")
    if second and second["share"] >= top["share"] - 0.2 and second["met"]:
        out += (f" \"{second['title']}\" is close behind ({second['met']} of "
                f"{second['known']}), so the picture is not settled.")
    return out


# ------------------------------------------------------------------- chains

# The knock-on effects that recur. `test` is the falsifiable claim the chain
# makes, scored after `days`: (metric, field, direction, days, plain claim).
CHAINS = (
    {
        "id": "oil_shock",
        "title": "Oil gets expensive",
        "first": "Petrol, jet fuel, diesel and plastics cost more within weeks.",
        "second": "Airlines, truckers and chemical makers see margins squeezed; households spend more on fuel and less on everything else. Inflation readings rise, so the Fed is slower to cut.",
        "long_run": "Sustained high prices pay for new drilling (more supply later) and speed the shift to EVs, efficiency and renewables - which is why oil spikes tend to undo themselves over 1-2 years.",
        "industries": [
            {"name": "Oil & gas producers", "dir": "+", "how": "Selling price rises; costs mostly don't."},
            {"name": "Oilfield services", "dir": "+", "how": "Producers drill more when prices stay high."},
            {"name": "Airlines", "dir": "-", "how": "Fuel is ~25% of their costs."},
            {"name": "Trucking & delivery", "dir": "-", "how": "Diesel costs, passed on only with a lag."},
            {"name": "Chemicals & plastics", "dir": "-", "how": "Oil is both feedstock and energy."},
            {"name": "Retail & restaurants", "dir": "-", "how": "Customers have less left after filling the tank."},
        ],
        "breaks_if": "Prices fall back quickly (OPEC adds supply, demand weakens), or the economy is strong enough to absorb them.",
        "watch": ["wti", "breakeven_10y", "sentiment"],
        "test": ("headline_cpi", "value", "up", 90, "Headline inflation higher in three months"),
    },
    {
        "id": "rates_high",
        "title": "Rates stay high for longer",
        "first": "Mortgages, car loans, credit cards and company loans stay expensive.",
        "second": "Housing sales freeze (owners won't give up cheap old mortgages); companies that must refinance debt pay much more; profits expected far in the future are worth less today, so high-valuation stocks fall most.",
        "long_run": "A 'refinancing wall' as cheap pandemic-era debt matures: weaker borrowers default, banks holding commercial-property loans take losses. Savers and insurers earn more.",
        "industries": [
            {"name": "Banks & insurers", "dir": "+", "how": "Earn more on loans and on the bonds they hold."},
            {"name": "Money-market funds", "dir": "+", "how": "Cash pays 4-5% with no risk."},
            {"name": "Homebuilders & real estate", "dir": "-", "how": "Buyers can't afford the monthly payment."},
            {"name": "Small, indebted companies", "dir": "-", "how": "Floating-rate debt costs rise directly."},
            {"name": "Unprofitable tech", "dir": "-", "how": "Valued on distant profits, discounted at a higher rate."},
            {"name": "Regional banks", "dir": "-", "how": "Office and property loans go bad; old low-rate bonds lose value."},
        ],
        "breaks_if": "Inflation drops clearly and the Fed signals cuts, or something breaks in credit and forces cuts.",
        "watch": ["ust_10y", "mortgage_30y", "hy_spread"],
        "test": ("existing_sales", "value", "down", 90, "Home sales lower in three months"),
    },
    {
        "id": "rate_cuts",
        "title": "The Fed cuts rates",
        "first": "Short-term borrowing costs and savings rates fall.",
        "second": "Mortgage rates ease and housing activity picks up; floating-rate borrowers (small companies, private-equity-owned firms) get relief; the dollar tends to weaken, lifting US multinationals' overseas earnings.",
        "long_run": "Cheaper money encourages risk-taking - more IPOs, more speculation, more borrowing. If cuts come too early, inflation can return (the 1970s pattern).",
        "industries": [
            {"name": "Homebuilders", "dir": "+", "how": "Lower mortgage rates bring buyers back."},
            {"name": "Small companies", "dir": "+", "how": "Most of their debt is floating-rate."},
            {"name": "Utilities & REITs", "dir": "+", "how": "Their dividends look better as bond yields fall."},
            {"name": "Emerging markets", "dir": "+", "how": "A weaker dollar eases their dollar debts."},
            {"name": "Money-market funds", "dir": "-", "how": "Yields fall straight away."},
        ],
        "breaks_if": "The Fed is cutting BECAUSE of a recession - then falling profits outweigh cheaper money for a while.",
        "watch": ["fed_funds", "ust_2y", "mortgage_30y"],
        "test": ("mortgage_30y", "value", "down", 90, "Mortgage rates lower in three months"),
    },
    {
        "id": "sticky_inflation",
        "title": "Inflation won't come down",
        "first": "Prices keep rising faster than the Fed's 2% goal; wages chase them.",
        "second": "Companies that can raise prices without losing customers (strong brands, must-have software, monopolies) protect margins; companies that can't (low-margin retail, restaurants, contractors) get squeezed. The Fed holds rates high.",
        "long_run": "Expectations shift: workers demand bigger raises, companies raise prices pre-emptively - the hardest kind of inflation to stop, and the reason the Fed reacts strongly to early signs.",
        "industries": [
            {"name": "Companies with pricing power", "dir": "+", "how": "Can pass costs on without losing customers."},
            {"name": "Commodity producers", "dir": "+", "how": "Their products ARE the rising prices."},
            {"name": "Inflation-protected bonds (TIPS)", "dir": "+", "how": "Payments rise with inflation."},
            {"name": "Low-margin retail & restaurants", "dir": "-", "how": "Costs rise faster than they can raise prices."},
            {"name": "Long-term bonds", "dir": "-", "how": "Fixed payments lose real value."},
        ],
        "breaks_if": "Rent and wage growth cool (they lag by months), or demand weakens enough to force discounting.",
        "watch": ["core_pce_3m", "avg_hourly_earnings", "breakeven_5y5y"],
        "test": ("ust_2y", "value", "up", 60, "Two-year Treasury yield higher in two months"),
    },
    {
        "id": "jobs_weaken",
        "title": "The job market weakens",
        "first": "Hiring slows, then layoffs rise; people feel less secure.",
        "second": "Spending on extras (travel, eating out, new cars) is cut first; credit-card and auto-loan losses rise at lenders; wage growth slows, which cools services inflation and lets the Fed cut.",
        "long_run": "Unemployment tends to rise in a self-reinforcing way once it starts - which is why the 'Sahm rule' (a 0.5-point rise) has called every recession since 1970.",
        "industries": [
            {"name": "Discount retailers", "dir": "+", "how": "Shoppers trade down from pricier stores."},
            {"name": "Consumer staples & health care", "dir": "+", "how": "Spending on necessities barely moves."},
            {"name": "Staffing companies", "dir": "-", "how": "Temp hiring is the first thing cut."},
            {"name": "Card issuers & consumer lenders", "dir": "-", "how": "More borrowers fall behind."},
            {"name": "Travel, leisure & restaurants", "dir": "-", "how": "The first thing households trim."},
        ],
        "breaks_if": "Layoffs stay low - slower hiring without firing is a cooling, not a downturn.",
        "watch": ["claims", "unemployment", "payrolls"],
        "test": ("unemployment", "value", "up", 90, "Unemployment higher in three months"),
    },
    {
        "id": "tariffs",
        "title": "Tariffs and trade barriers",
        "first": "Imported goods and parts cost more; trading partners often retaliate.",
        "second": "Importers and retailers choose between raising prices (inflation) and eating the cost (lower margins); manufacturers using imported parts (autos, machinery) pay more; exporters lose foreign sales to retaliation (farm products, aircraft).",
        "long_run": "Supply chains move - to Mexico, Vietnam, India, or back to the US. That takes years and builds factories, warehouses and automation, but leaves goods structurally more expensive.",
        "industries": [
            {"name": "Domestic producers (steel, some manufacturing)", "dir": "+", "how": "Protected from cheaper imports."},
            {"name": "Factory construction & automation", "dir": "+", "how": "Firms build where the tariffs don't apply."},
            {"name": "Retailers & apparel", "dir": "-", "how": "Most goods are imported."},
            {"name": "Automakers", "dir": "-", "how": "Parts cross borders many times."},
            {"name": "Farm exporters & aerospace", "dir": "-", "how": "First targets of retaliation."},
        ],
        "breaks_if": "Deals or exemptions are announced, or tariffs are struck down in court.",
        "watch": ["core_cpi", "ppi", "dollar_broad"],
        "test": ("ppi", "value", "up", 90, "Producer prices higher in three months"),
    },
    {
        "id": "ai_capex",
        "title": "The AI spending boom",
        "first": "Big tech companies spend hundreds of billions a year on data centres and chips.",
        "second": "Chipmakers, memory makers and network gear sellers book record sales; data centres need huge amounts of power, so utilities, grid equipment, cooling and copper demand rise; software companies worry AI tools replace their products.",
        "long_run": "Either AI earns back the spending - productivity rises across the economy - or spending gets cut, and the suppliers who grew fastest fall hardest. Electricity prices for everyone may rise either way.",
        "industries": [
            {"name": "Semiconductors & memory", "dir": "+", "how": "Direct sellers of the chips."},
            {"name": "Utilities & grid equipment", "dir": "+", "how": "Data centres need new power plants and lines."},
            {"name": "Copper & electrical", "dir": "+", "how": "Wiring, cooling and transformers."},
            {"name": "Seat-based software", "dir": "-", "how": "If AI agents do the work, fewer human 'seats' are sold."},
            {"name": "The big spenders' cash flow", "dir": "-", "how": "Spending eats into free cash flow until it pays off."},
        ],
        "breaks_if": "Big tech cuts its spending plans, or AI revenue clearly fails to grow into the investment.",
        "watch": ["indpro", "copper", "ndx"],
        "test": ("copper", "value", "up", 90, "Copper price higher in three months"),
    },
    {
        "id": "strong_dollar",
        "title": "The dollar strengthens",
        "first": "US goods get more expensive abroad; imports get cheaper at home.",
        "second": "US multinationals earn less when foreign sales are converted back to dollars; countries and companies that borrowed in dollars find debts harder to repay; commodity prices (priced in dollars) tend to fall.",
        "long_run": "Persistent strength widens the trade deficit and draws political pressure (tariffs, calls for a weaker dollar).",
        "industries": [
            {"name": "Importers & US travelers", "dir": "+", "how": "Foreign goods and trips get cheaper."},
            {"name": "Domestic-only small companies", "dir": "+", "how": "No currency hit to their sales."},
            {"name": "US multinationals", "dir": "-", "how": "Foreign profits shrink in dollar terms."},
            {"name": "Emerging markets", "dir": "-", "how": "Dollar debts get heavier."},
            {"name": "Commodities & gold", "dir": "-", "how": "Priced in dollars, so tend to fall."},
        ],
        "breaks_if": "US rates fall faster than other countries', removing the reason to hold dollars.",
        "watch": ["dollar_broad", "eurusd", "usdjpy"],
        "test": ("gold", "value", "down", 90, "Gold lower in three months"),
    },
    {
        "id": "credit_stress",
        "title": "Borrowing gets harder",
        "first": "Lenders demand higher interest from riskier companies, or stop lending.",
        "second": "Weaker companies can't refinance and cut jobs and investment; private-equity-owned firms and private credit funds come under strain; banks tighten lending standards, slowing the whole economy.",
        "long_run": "A default cycle clears out weak firms over 1-2 years; survivors gain share. Credit has led stocks at most major turning points.",
        "industries": [
            {"name": "Strong-balance-sheet companies", "dir": "+", "how": "Can buy weaker rivals cheaply."},
            {"name": "Government bonds", "dir": "+", "how": "Investors run to safety."},
            {"name": "High-debt companies", "dir": "-", "how": "Refinancing costs jump or money is unavailable."},
            {"name": "Private equity & private credit", "dir": "-", "how": "Their model depends on cheap borrowing."},
            {"name": "Regional banks", "dir": "-", "how": "Loan losses rise."},
        ],
        "breaks_if": "Spreads narrow again quickly - a scare, not a cycle.",
        "watch": ["hy_spread", "loan_standards", "nfci"],
        "test": ("hy_spread", "value", "up", 60, "Junk-bond spreads wider in two months"),
    },
    {
        "id": "deficits",
        "title": "Big government deficits",
        "first": "The Treasury borrows more, selling more bonds.",
        "second": "To absorb all those bonds, investors demand higher long-term yields; mortgages and corporate borrowing follow them up. Spending itself boosts the industries it targets (defense, infrastructure, subsidised energy).",
        "long_run": "Interest on the debt grows into one of the largest budget items, crowding out other spending; worries about debt sustainability support gold and pressure the dollar.",
        "industries": [
            {"name": "Defense & infrastructure", "dir": "+", "how": "Direct recipients of the spending."},
            {"name": "Gold", "dir": "+", "how": "A hedge against governments' debt problems."},
            {"name": "Long-term bonds", "dir": "-", "how": "More supply pushes their prices down, yields up."},
            {"name": "Housing", "dir": "-", "how": "Mortgage rates track the 10-year yield."},
        ],
        "breaks_if": "Growth outpaces the debt, or the Fed or foreign buyers absorb the bonds without needing higher yields.",
        "watch": ["ust_30y", "deficit", "federal_debt"],
        "test": ("ust_30y", "value", "up", 90, "30-year Treasury yield higher in three months"),
    },
)
CHAIN_IDS = tuple(c["id"] for c in CHAINS)

NEWS_TRIGGERS = {
    "oil_shock": r"\b(?:oil|crude|opec|brent|gasoline)\b",
    "tariffs": r"\b(?:tariffs?|trade war|trade deal|import tax|duties|export controls?)\b",
    "ai_capex": r"\b(?:data cent(?:er|re)s?|capex|ai spending|hyperscalers?|gpus?|ai infrastructure)\b",
    "deficits": r"\b(?:deficit|debt ceiling|spending bill|tax cuts?|treasury auction|government shutdown)\b",
    "rate_cuts": r"\b(?:rate cuts?|cuts? rates|fed cut|easing)\b",
    "jobs_weaken": r"\b(?:layoffs?|job cuts|jobless|unemployment rises)\b",
    "credit_stress": r"\b(?:default|bankrupt\w*|private credit|credit crunch|downgraded to junk)\b",
}
# Impact decays with age, so a story from three days ago scores well under
# its first-day value; the floor is low and the count does the filtering.
NEWS_MIN_IMPACT = 15
NEWS_MIN_HITS = 3


def _read(regime: dict, rid: str) -> dict:
    return next((r for r in (regime or {}).get("reads") or [] if r["id"] == rid), {})


def active_chains(summaries: dict, regime: dict, items: list) -> list:
    """The chains today's data or news switches on, strongest first, each with
    the evidence that switched it on."""
    def v(metric, field="value"):
        return metric_value(summaries, metric, field)

    reasons = {}

    def add(cid, weight, why):
        reasons.setdefault(cid, []).append((weight, why))

    wti3 = v("wti", "chg_3m")
    if wti3 is not None and wti3 > 15:
        add("oil_shock", 3, f"Oil is up {wti3:.0f}% in three months (${v('wti'):.0f} a barrel).")
    policy, rates = _read(regime, "policy"), _read(regime, "rates")
    ust10 = v("ust_10y")
    if (policy.get("score", 0) < 0 or rates.get("score", 0) < 0) and ust10 is not None and ust10 > 4.0:
        add("rates_high", 3, f"The 10-year Treasury yield is {ust10:.2f}%, and the Fed's stance reads as restrictive.")
    ff1 = v("fed_funds", "chg_3m")
    if ff1 is not None and ff1 <= -0.2:
        add("rate_cuts", 3, f"The Fed's rate is down {abs(ff1):.2f} points in three months.")
    inflation = _read(regime, "inflation")
    if inflation.get("score", 0) < 0:
        add("sticky_inflation", 3, f"Inflation reads as {inflation.get('state', 'sticky')}.")
    unemp3 = v("unemployment", "chg_3m")
    claims = v("claims")
    if (unemp3 is not None and unemp3 >= 0.3) or (claims is not None and claims > 250):
        add("jobs_weaken", 3, "Unemployment or layoff claims are rising.")
    dollar3 = v("dollar_broad", "chg_3m")
    if dollar3 is not None and dollar3 > 3:
        add("strong_dollar", 2, f"The dollar is up {dollar3:.1f}% in three months.")
    hy1 = v("hy_spread", "chg_1m")
    hy = v("hy_spread") or 0
    if (_read(regime, "credit").get("score", 0) < 0 and hy1 is not None and hy1 > 0.3
            and hy >= 3.5) or hy > 4.5:
        add("credit_stress", 2, f"Junk-bond spreads widened {hy1:+.2f} points this month." if hy1 is not None else "Credit spreads are wide.")

    for cid, pattern in NEWS_TRIGGERS.items():
        rx = re.compile(pattern, re.I)
        hits = [it for it in items or []
                if (it.get("impact") or 0) >= NEWS_MIN_IMPACT and rx.search(it.get("title") or "")]
        if len(hits) >= NEWS_MIN_HITS:
            top = max(hits, key=lambda it: it.get("impact") or 0)
            add(cid, 1 + min(len(hits), 6) / 3,
                f"{len(hits)} recent headlines, e.g. \"{' '.join(top['title'].split())}\"")

    out = []
    for chain in CHAINS:
        if chain["id"] not in reasons:
            continue
        got = sorted(reasons[chain["id"]], key=lambda r: -r[0])
        out.append({"id": chain["id"], "strength": round(sum(w for w, _ in got), 1),
                    "why_now": [why for _, why in got][:3]})
    out.sort(key=lambda c: -c["strength"])
    return out


# --------------------------------------------------------------- hypotheses

MAX_HYPOTHESES = 120


def make_hypothesis(claim: str, metric: str, field: str, direction: str, days: int,
                    summaries: dict, source: str, today: date, origin: str = "") -> dict:
    """A falsifiable claim with the reading on the day it was made, or None if
    the metric has no reading to compare against."""
    baseline = metric_value(summaries, metric, field)
    if baseline is None or direction not in ("up", "down"):
        return None
    entry = summaries.get(metric) or {}
    return {
        "id": f"{today.isoformat()}:{origin or metric}:{metric}:{direction}",
        "made_on": today.isoformat(),
        "due_on": (today + timedelta(days=int(days))).isoformat(),
        "claim": claim,
        "metric": metric,
        "label": entry.get("label", metric),
        "field": field,
        "direction": direction,
        "baseline": baseline,
        "baseline_as_of": entry.get("as_of", ""),
        "source": source,
        "origin": origin,
        "status": "open",
    }


def chain_hypotheses(active: list, summaries: dict, existing: list, today: date,
                     cooldown_days: int = 30) -> list:
    """One hypothesis per newly active chain - not re-made while a recent one
    for the same chain is still running."""
    recent = {h.get("origin") for h in existing
              if h.get("source") == "rule" and
              h.get("made_on", "") >= (today - timedelta(days=cooldown_days)).isoformat()}
    out = []
    by_id = {c["id"]: c for c in CHAINS}
    for chain in active:
        if chain["id"] in recent:
            continue
        metric, field, direction, days, claim = by_id[chain["id"]]["test"]
        h = make_hypothesis(claim, metric, field, direction, days, summaries, "rule",
                            today, origin=chain["id"])
        if h:
            out.append(h)
    return out


def resolve(hypotheses: list, summaries: dict, today: date) -> list:
    """Score every hypothesis that has come due; track the rest 'so far'.

    The comparison waits for the metric to have a NEWER reading than the
    baseline: a monthly series checked before its next release would score
    every claim on unchanged data.
    """
    out = []
    for h in hypotheses:
        h = dict(h)
        entry = summaries.get(h["metric"]) or {}
        now = metric_value(summaries, h["metric"], h.get("field", "value"))
        fresh = entry.get("as_of", "") > h.get("baseline_as_of", "")
        if now is not None and fresh:
            moved = now - h["baseline"]
            h["latest"] = now
            h["latest_as_of"] = entry.get("as_of", "")
            h["so_far"] = ("on track" if (moved > 0) == (h["direction"] == "up") and moved != 0
                           else "against" if moved != 0 else "flat")
        if h["status"] == "open" and today.isoformat() >= h["due_on"]:
            if now is None or not fresh:
                if today.isoformat() >= (date.fromisoformat(h["due_on"]) + timedelta(days=45)).isoformat():
                    h["status"] = "unscored"
            else:
                h["status"] = "right" if h.get("so_far") == "on track" else "wrong"
                h["resolved_on"] = today.isoformat()
        out.append(h)
    return out


def merge(existing: list, new: list) -> list:
    ids = {h["id"] for h in existing}
    merged = existing + [h for h in new if h["id"] not in ids]
    merged.sort(key=lambda h: h["made_on"], reverse=True)
    return merged[:MAX_HYPOTHESES]


def scorecard(hypotheses: list) -> dict:
    done = [h for h in hypotheses if h["status"] in ("right", "wrong")]
    right = sum(1 for h in done if h["status"] == "right")
    by_source = {}
    for h in done:
        s = by_source.setdefault(h["source"], {"right": 0, "wrong": 0})
        s[h["status"]] += 1
    return {"scored": len(done), "right": right,
            "open": sum(1 for h in hypotheses if h["status"] == "open"),
            "by_source": by_source}


# ------------------------------------------------------------------ history

def record_lean(history: list, evaluated: list, today: date, keep: int = 180) -> list:
    """Append today's scenario shares (one entry per day) for the trend line."""
    entry = {"on": today.isoformat(),
             "shares": {s["id"]: s["share"] for s in evaluated}}
    history = [h for h in history or [] if h.get("on") != entry["on"]] + [entry]
    return history[-keep:]


# --------------------------------------------------------------- assemble

def build(summaries: dict, regime: dict, items: list, state: dict, today: date = None) -> dict:
    """The scenarios.json body (minus the model's text), and the new state.

    `state` is what the last run stored: {"hypotheses": [...], "lean": [...]}.
    """
    today = today or date.today()
    evaluated = evaluate(summaries)
    active = active_chains(summaries, regime, items)
    hyps = resolve(state.get("hypotheses") or [], summaries, today)
    hyps = merge(hyps, chain_hypotheses(active, summaries, hyps, today))
    lean = record_lean(state.get("lean") or [], evaluated, today)
    by_id = {c["id"]: c for c in CHAINS}
    return {
        "scenarios": evaluated,
        "lean": lean_sentence(evaluated),
        "lean_history": lean,
        "active": [{**by_id[a["id"]], **a} for a in active],
        "library": [c for c in CHAINS if c["id"] not in {a["id"] for a in active}],
        "hypotheses": hyps,
        "scorecard": scorecard(hyps),
    }
