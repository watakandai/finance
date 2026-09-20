# How to read the market: the mechanism, not the noise

This is the reasoning the rest of this repository automates. It is written to be
read once properly and then skimmed, and it deliberately contains no
recommendations — only the machinery, so that you can apply your own judgement
to your own situation.

> Nothing here is investment advice. It is a description of how public data has
> historically transmitted to asset prices.

---

## 1. One equation explains most of it

The price of any asset is the cash it will produce, discounted back to today:

```
price  =  expected cash flows  /  (1 + discount rate)^time
```

Two things can therefore move any price: the **numerator** (growth, earnings,
demand) or the **denominator** (interest rates, risk premia). Almost every
market move is one of those two, and almost every mistake comes from
misattributing which.

That is why interest rates dominate this repository. The discount rate is set,
at the short end, by a committee of twelve people eight times a year, and at the
long end by a market that is guessing what that committee will do plus what
inflation will be plus how much government debt it has to absorb. Everything in
`finance/indicators.py` is either an input to that guess or a consequence of it.

**Duration is the single most useful word to internalise.** An asset's duration
is how far in the future its cash flows sit. A 30-year bond, a profitless
software company and a data-centre buildout that earns nothing for four years
are all long-duration: their value is mostly in distant cash flows, so a change
in the discount rate hits them hardest. A cash-generating utility, a bank's loan
book and a short Treasury bill are short-duration. When you read "rates up, tech
down", duration is the whole mechanism.

---

## 2. The chain, in the order causation runs

```
inflation  →  what the Fed does  →  where rates go  →  what credit costs
           →  how much liquidity there is  →  what risk assets can pay for

growth feeds the top of the chain (it is half the Fed's mandate)
risk appetite is the output, not an input
```

`finance/regime.py` computes one read per link, in exactly this order, because
reading them in this order is reading the transmission mechanism. Some
consequences of taking the chain seriously:

- **A weak growth number is good news or bad news depending on where inflation
  is.** With inflation at target, weak data means the Fed can ease, so bonds
  rally and long-duration equities are rescued. With inflation above target, the
  Fed cannot ease quickly, so bonds and equities fall together — which is what
  made 2022 feel unprecedented to anyone who had only invested since 2009.
- **Credit leads equities.** Equity holders are paid last; lenders are paid
  first and get to demand information. When high-yield spreads widen while
  equities are calm, the two have historically converged in credit's direction.
- **Liquidity works slowly and then suddenly.** Reserves drain for months with
  no visible effect, and then a funding market seizes — September 2019's repo
  spike, March 2023's regional banks. The series that show it (reserves, the
  reverse-repo facility, the Treasury's cash account) are published weekly and
  almost nobody reads them.
- **Risk appetite is a cross-check, not a signal.** It tells you what is already
  priced. It is most useful when it *disagrees* with the fundamentals above,
  because that gap is where positioning risk lives.

---

## 3. The numbers that actually move markets

Every indicator in this repository carries its own `why`, `up_means`,
`down_means` and `watch` — you can read them on the page, next to the number.
These are the fourteen that reprice assets on release, and what a *surprise* in
each one does.

| Number | Why it moves markets | What to look at, not the headline |
| --- | --- | --- |
| **Core PCE** | The Fed's actual target. Its own forecasts are written in this unit. | The 3-month annualised rate. The annual rate is an average of twelve months and keeps reporting last spring. |
| **Core CPI** | Two weeks earlier than PCE and far more heavily traded, so it moves the day. | The monthly change. 0.2% keeps a cutting cycle alive; 0.4% ends the argument. Shelter is a third of it and lags reality by about a year. |
| **Payrolls** | The most-traded number in macro, and half the Fed's mandate. | The 3-month average and the revisions to the prior two months. Breakeven hiring is roughly 100k and falling. |
| **Unemployment rate** | Input to the only recession rule with a decent record. | Its rise off the prior 12-month low. Half a point (the Sahm rule) has preceded every US recession since 1960. |
| **Initial claims** | Weekly, barely revised, genuinely leading — firms file before a survey can see it. | The 4-week average. The weekly print is seasonal noise. |
| **Fed funds + the 2-year yield** | Funds is the anchor; the 2-year is the market's forecast of it, and it moves months earlier. | Funds minus core inflation (the *real* rate) is what "restrictive" means. The 2-year minus funds is the path the market has already priced. |
| **10-year yield** | The global discount rate: mortgages, hurdle rates, equity multiples. | Speed, not level. Roughly 50bp in a month has broken equity rallies from any starting point. And *which end* of the curve moved. |
| **10-year real yield (TIPS)** | The nominal rate with inflation expectations removed — the true cost of long money. | It separates "rates rose on growth" from "rates rose on inflation fear". Above ~2% real, valuation-sensitive assets have struggled. |
| **2s10s curve** | Inversion has preceded every postwar US recession. | Which leg is moving. Bull steepening (front end falling) prices cuts; bear steepening (long end rising) prices term premium and is harder for equities to absorb. |
| **High-yield OAS** | The market's honest opinion on default risk, and the best early-warning gauge available free. | Direction from a tight base, not the level. ~300bp is complacent, 500bp is stress. Investment-grade widening too means it is no longer idiosyncratic. |
| **Financial conditions (NFCI)** | 105 measures in one number you cannot cherry-pick. | Zero is the historical average. Loosening conditions are what let a central bank stay tight for longer. |
| **Fed balance sheet & reserves** | The quantity side of policy; drains tighten conditions without touching the rate. | The weekly change, alongside the reverse-repo balance and the Treasury's cash account. |
| **Dollar index** | The global funding currency, so its price is a global financial condition. | *Why* it is moving: rate differentials, growth differentials and a safe-haven bid imply different things. |
| **Oil** | The fastest route from geopolitics to headline inflation to consumer spending. | Supply-driven (OPEC, conflict) or demand-driven (China, global growth). The same price move means opposite things. |

**Two secondary reads worth the same attention as the list above.** First,
**equity leadership**: small caps versus the S&P is the cheapest breadth check
there is, and discretionary versus staples is the cleanest risk-on/risk-off read
inside equities. Second, the **earnings of the largest banks**, which arrive
first each quarter and contain loan-loss provisions and consumer-credit
commentary — the earliest bottom-up read on credit for the whole quarter.

---

## 4. How a release actually moves a price

**The market trades the surprise, not the number.** A 3.0% inflation print with
consensus at 3.0% is a non-event; the same print against a 2.7% consensus is a
repricing. This is the single most common error in reading financial news: the
headline states a level, and the market traded a difference.

This repository does not carry a consensus figure — there is no free,
machine-readable source for one. What it gives you instead is context: the
percentile and z-score of every series against its own history, the 3-month
momentum next to the annual rate, and the regime read the print will either
confirm or break. That is usually enough to know whether a number is news.

**Then ask, in this order:**

1. **Is it a level or a change?** Sticky 3% inflation and inflation falling
   through 3% are different worlds.
2. **What did the components do?** Headline minus core is almost always energy.
   A payroll beat driven by government hiring says less about the private
   economy. GDP driven by inventories reverses next quarter.
3. **What got revised?** Payrolls and retail sales are heavily revised. A beat
   that comes with a large downward revision to the prior month is frequently a
   miss wearing a disguise.
4. **What is the second-order effect?** A hot print does not just raise the
   discount rate; it also removes the rate cuts the market had already priced
   in. That double effect is why hot inflation data hits long-duration assets
   harder than the move in yields alone suggests.

---

## 5. Four regimes, and why the same news flips sign

Growth and inflation, each rising or falling, give four states. It is a crude
frame and still explains more than most commentary:

| | **Inflation rising** | **Inflation falling** |
| --- | --- | --- |
| **Growth rising** | Policy tightens into strength. Real assets, energy and short-duration cash flows have done better than long bonds. Cyclicals over duration. | The comfortable one. Falling discount rates and rising cash flows at once — historically the best regime for equities, and especially for long duration. |
| **Growth falling** | The hard one. Policy cannot rescue growth without abandoning inflation, so bonds and equities can fall together (2022). Historically the regime where cash and commodities earned their place. | The classic slowdown. Bonds do the work: the Fed can ease, and duration is the asset that pays. Credit is where the risk is. |

Two things to notice. First, **the same headline means opposite things in
different quadrants** — "unemployment up" is a bond rally in the right-hand
column and a stagflation scare in the top-left. Second, **the quadrant can
change faster than the data**, because what matters is the market's expectation,
which is why the 2-year yield and breakeven inflation are worth watching daily
while GDP is worth watching quarterly.

---

## 6. Policy: the thing that actually decides your returns

You said policy is usually your biggest factor. It reaches a portfolio through
four distinct channels, and conflating them is how people get surprised.

**Monetary policy — the discount rate.** Eight scheduled decisions a year, fully
on the calendar, and the market has already priced a path before each one. The
decision itself is rarely the news; the *statement wording* and the projections
are. Mechanism: policy rate → the whole curve → every valuation, with the
longest-duration assets moving most.

**Fiscal policy — supply and demand for money.** Two sub-channels that behave
differently. *Spending and tax* changes flow into growth and corporate earnings
with a lag of quarters. *Issuance* — how much duration the Treasury sells and at
what maturity — hits the long end of the curve immediately. The quarterly
refunding announcement turned the long end around in 2023 on composition alone,
with no change to the deficit. Watch the refunding announcement, not just the
deficit number.

**Trade policy — a supply shock with a political timetable.** Tariffs raise
input costs (margin pressure, or passed-through inflation), invite retaliation
(revenue risk for exporters), and re-route supply chains over years. They are
the clearest example of a *months-horizon* item: the announcement moves the tape
for a day, and the repricing of the affected sectors takes quarters. They also
put a central bank in the worst position it can be in — higher prices and weaker
growth at the same time.

**Regulatory policy — sector-specific and slow.** Antitrust, bank capital
rules, energy permitting, drug pricing. It rarely moves an index and frequently
re-rates an industry permanently.

The practical instruction: when you read a policy story, ask **which channel,
and over what horizon**. That is exactly the question `horizon` in
`finance/categorize.py` is trying to answer mechanically, and why the page
groups news by how long it stays relevant rather than by when it was published.

---

## 7. The daily routine this repo encodes

What people who do this professionally actually do, in order:

1. **Look at the calendar before the news.** What is scheduled this week decides
   what today's positioning means. → the Calendar section.
2. **Check what changed in the regime, not what happened.** Seven reads, not
   sixty numbers. → the Regime tiles.
3. **Find the tension.** Where do the reads disagree with each other, or with
   what the market is priced for? That gap is the only place an edge can exist.
   → the "where the reads disagree" line.
4. **Read the surprises, skip the recaps.** A release that broke the consensus
   matters; "stocks closed lower" does not. → impact scoring, and the penalty
   on market-wrap formats.
5. **Write down what would change your mind.** A view you cannot falsify is a
   feeling. → each regime read carries its own `watch`.

---

## 8. What to ignore, and why

- **Price targets and "top picks".** A number with no mechanism attached is not
  information. `impact.FILLER_RE` exists to push these off the page.
- **Single-month data points.** Almost every monthly series is noisier than its
  own trend. One print is a data point; three are a signal.
- **Narrative fitted after the fact.** "Stocks fell on rate worries" is written
  after the close, from the close. If the same explanation would have been used
  for the opposite outcome, it explains nothing.
- **Forecasts of the level of an index.** Nobody has demonstrated an ability to
  do this. Forecasts of a *mechanism* ("if the Fed cuts, the front end falls
  first") are a different and much more useful thing.
- **Anything urging speed.** The mechanisms in this document operate over
  quarters. Urgency in financial media is a business model, not information.

## 9. Traps that catch careful people

- **Level versus change.** "Rates are high" is not a forecast. Markets price
  changes in expectations, and expectations are already in the 2-year yield.
- **Base effects.** A year-over-year rate can fall purely because the number
  twelve months ago was large. The 3-month annualised rate is the antidote, and
  it is why this repo computes both.
- **Assuming the correlation regime is fixed.** Bonds hedged equities from 1998
  to 2021 because inflation was not a constraint. When it is, they do not. The
  hedge you own is conditional on a regime.
- **Confusing volatility with risk.** A low VIX is when leverage accumulates,
  which makes the next shock larger, not smaller.
- **Revisions.** The number you traded may not be the number that happened. Only
  the latest vintage is stored here, deliberately: the revised figure is the one
  that is true.
- **Reading a guessed date as a fact.** Most of the economic calendar here is
  inferred from publication rules because no free machine-readable calendar
  exists. Anything marked `~` is this project's inference — check the agency's
  own page before you trade around it.

---

## Where each idea lives in the code

| Idea | Where |
| --- | --- |
| The indicator list, and why each matters | `finance/indicators.py` |
| Level → context (z-score, percentile, momentum) | `finance/metrics.py` |
| The seven-link chain | `finance/regime.py` |
| "Where the reads disagree" | `regime._tension` |
| Market impact versus personal relevance | `finance/impact.py` and `finance/rank.py` |
| How long an item stays relevant | `categorize.horizon` |
| What is scheduled, and how confident the date is | `finance/calendar_rules.py` |
