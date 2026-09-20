"""What to track, and why each one matters.

This is the knowledge file. Every other module is plumbing around it: the
fetcher reads `fred` ids from here, `metrics` applies the `transform`,
`regime` reads the results, the page renders `why` next to the number, and the
LLM prompt is handed the same text so its explanations and the page's cannot
drift apart.

It is written the way a macro desk actually watches the tape rather than the
way a data catalogue is organised, so three things are deliberate:

- **Each entry says what a MOVE means, not what the series is.** "Core PCE is
  the Fed's preferred inflation measure" is a definition; "a 3-month
  annualised rate above 3% has historically been what stops a cutting cycle"
  is a decision input. The second is what belongs here.
- **Tier 1 is short.** Fourteen series move whole markets on release; the rest
  explain or confirm. A dashboard that treats sixty numbers as equals is a
  catalogue, and a catalogue is what you already have.
- **The `family` groupings are the causal chain**, in order: inflation -> what
  the Fed does -> where rates go -> what credit and liquidity do -> what risk
  assets can pay for. Growth and the dollar feed in at the sides. Reading the
  families top to bottom is reading the transmission mechanism, which is the
  thing worth learning once.

`transform` is what `metrics` applies before anything is compared:
  level  - the number as published (a yield, a spread, an index level)
  yoy    - percent change against the same period 12 observations back
  ann3   - 3-month change, annualised (the "is it cooling NOW" read that a
           year-over-year rate takes months to show)
  chg1   - change against the previous observation, in native units
  avg4   - 4-observation average (weekly claims, which are too noisy raw)
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Series:
    id: str
    label: str
    family: str
    fred: str = ""              # FRED series id, "" for a market quote
    quote: str = ""             # Yahoo symbol, for prices FRED publishes late
    transform: str = "level"
    # Multiplier applied to the raw value before anything else. FRED publishes
    # weekly claims in persons (196,000) and the Fed's balance sheet in millions
    # (6,746,548), and nobody reads either at that scale - so the series is
    # rescaled once, here, rather than formatted differently in three places.
    scale: float = 1.0
    unit: str = ""              # rendered after the number: %, pts, k, $bn
    tier: int = 2
    cadence: str = "monthly"    # daily | weekly | monthly | quarterly
    release: str = ""           # calendar event id this number arrives with
    why: str = ""
    up_means: str = ""
    down_means: str = ""
    watch: str = ""             # the level or threshold desks actually anchor on
    # Which direction is "risk-friendly", for colour only. `none` means a move
    # is not good or bad on its own - most of the interesting ones are this.
    good: str = "none"          # up | down | none
    decimals: int = 2
    lookback_days: int = 1825   # window for z-scores and percentiles (5y)


FAMILIES = {
    "inflation": "Inflation",
    "policy": "Monetary policy",
    "rates": "Rates & the curve",
    "credit": "Credit & financial conditions",
    "liquidity": "Liquidity",
    "labor": "Labour market",
    "growth": "Growth & the consumer",
    "risk": "Risk appetite",
    "dollar": "Dollar & FX",
    "commodities": "Commodities",
    "housing": "Housing",
    "fiscal": "Fiscal",
}

SERIES = (
    # ---------------------------------------------------------------- inflation
    Series(
        id="core_pce", label="Core PCE inflation", family="inflation",
        fred="PCEPILFE", transform="yoy", unit="% y/y", tier=1, release="pce",
        why="The Fed targets 2% on the PCE deflator, and it is core PCE - food "
            "and energy stripped out - that the FOMC's own projections forecast. "
            "Every other inflation number is ultimately a guess at this one.",
        up_means="Later and fewer rate cuts. Pushes the whole yield curve up and "
                 "compresses what investors will pay for distant earnings.",
        down_means="Room for the Fed to cut without losing credibility, which is "
                   "the single most reliable tailwind for long-duration assets.",
        watch="2% is the target. Above ~2.8% y/y the committee has historically "
              "stopped easing; below ~2.3% cuts get justified on inflation alone.",
        good="down",
    ),
    Series(
        id="core_pce_3m", label="Core PCE, 3-month annualised", family="inflation",
        fred="PCEPILFE", transform="ann3", unit="% ann.", tier=1, release="pce",
        why="A year-over-year rate is an average of twelve months, so it keeps "
            "reporting last spring for most of a year. The 3-month annualised "
            "rate is the same data asked 'what is inflation doing right now', and "
            "it is what turns a Fed pause into a cut two meetings early.",
        up_means="Momentum is re-accelerating even if the annual rate is still "
                 "falling. This is the read that has repeatedly caught the market "
                 "leaning the wrong way.",
        down_means="Disinflation is live, not a base effect.",
        watch="Sustained prints under 2.5% annualised are what the committee has "
              "called 'further progress'; over 3.5% is a policy problem.",
        good="down",
    ),
    Series(
        id="core_cpi", label="Core CPI inflation", family="inflation",
        fred="CPILFESL", transform="yoy", unit="% y/y", tier=1, release="cpi",
        why="Two weeks earlier than PCE and far more heavily traded, so it is the "
            "print that actually moves a given day. Shelter is about a third of "
            "it and lags reality by roughly a year, which is why CPI and PCE can "
            "disagree for quarters at a time.",
        up_means="Immediate repricing of the Fed path; the front end of the curve "
                 "moves first and hardest.",
        down_means="Relief rally in both bonds and equities, usually within the "
                   "same minute the number crosses.",
        watch="The monthly change matters more than the level: 0.2% keeps a "
              "cutting cycle alive, 0.4% ends the conversation.",
        good="down",
    ),
    Series(
        id="headline_cpi", label="Headline CPI inflation", family="inflation",
        fred="CPIAUCSL", transform="yoy", unit="% y/y", release="cpi",
        why="What households actually experience, and therefore what drives "
            "surveys, wage demands and politics. The Fed looks past it; voters "
            "and bond vigilantes do not.",
        up_means="Political pressure and higher inflation expectations even when "
                 "core is behaving.",
        down_means="Real incomes rise, which supports consumption without needing "
                   "the Fed to do anything.",
        watch="Gaps versus core are almost always energy. Check oil before "
              "concluding anything about underlying inflation.",
        good="down",
    ),
    Series(
        id="ppi", label="PPI final demand", family="inflation",
        fred="PPIFIS", transform="yoy", unit="% y/y", release="ppi", tier=3,
        why="Costs upstream of the consumer, and the source of several PCE "
            "components that CPI does not measure. A useful early read on "
            "margins: when PPI runs below CPI, companies are keeping the "
            "difference.",
        up_means="Margin pressure, and pipeline inflation that reaches PCE later.",
        down_means="Margin relief - often good for equities even when demand is soft.",
        watch="The healthcare and portfolio-management components feed PCE "
              "directly; a hot PPI can move PCE forecasts the same morning.",
        good="down",
    ),
    Series(
        id="breakeven_10y", label="10-year breakeven inflation", family="inflation",
        fred="T10YIE", transform="level", unit="%", tier=2, cadence="daily",
        why="What the bond market itself prices for average inflation over ten "
            "years - nominal yield minus the TIPS yield. Unlike a survey it is "
            "money at risk, and unlike a print it updates every second.",
        up_means="The market doubts the Fed will hold the line, or expects a "
                 "supply shock. Nominal bonds lose, real assets win.",
        down_means="Either credibility, or a demand scare. Check oil and credit "
                   "spreads to tell which - both falling together means demand.",
        watch="2-2.5% is the Fed's comfort zone. Above 2.75% the Fed has "
              "historically talked hawkish regardless of the spot data.",
        good="none",
    ),
    Series(
        id="breakeven_5y5y", label="5y5y forward breakeven", family="inflation",
        fred="T5YIFR", transform="level", unit="%", cadence="daily", tier=3,
        why="Expected inflation for the five years starting five years from now: "
            "far enough out that today's oil price and today's cycle wash out. "
            "This is the cleanest available measure of whether the Fed still owns "
            "the anchor.",
        up_means="Anchor slipping - the most serious inflation signal there is, "
                 "and the one that justifies policy staying tight into weakness.",
        down_means="Long-run credibility intact, whatever the spot prints say.",
        watch="A move outside roughly 2-2.5% is the thing to care about; wiggles "
              "inside it are noise.",
        good="none",
    ),
    Series(
        id="avg_hourly_earnings", label="Average hourly earnings", family="inflation",
        fred="CES0500000003", transform="yoy", unit="% y/y", release="jobs", tier=3,
        why="Wages are the input to services inflation, which is the sticky half. "
            "Pay growth running far above productivity growth has to end up in "
            "either prices or margins.",
        up_means="Services inflation stays sticky; the Fed's job is not finished.",
        down_means="Disinflation becomes self-sustaining rather than a goods-price "
                   "story.",
        watch="Roughly 3.5% y/y is consistent with 2% inflation given trend "
              "productivity. Persistently above 4% is not.",
        good="down",
    ),

    # ------------------------------------------------------------------- policy
    Series(
        id="fed_funds", label="Fed funds (effective)", family="policy",
        fred="DFF", transform="level", unit="%", tier=1, cadence="daily",
        release="fomc",
        why="The price of overnight money, and the anchor every other discount "
            "rate is built on. It is set by eight scheduled decisions a year, "
            "which is why an FOMC date is the most predictable market-moving "
            "event on the calendar.",
        up_means="Tighter policy: higher hurdle rate for every investment, and a "
                 "direct hit to the multiple on long-duration cash flows.",
        down_means="Easier policy, but read WHY it is easing - cuts into a "
                   "recession and cuts into a soft landing are different trades.",
        watch="Compare to core inflation: funds minus core PCE is the real policy "
              "rate, and that difference, not the level, is what 'restrictive' means.",
        good="none",
    ),
    Series(
        id="fed_target_upper", label="Fed funds target (upper)", family="policy",
        fred="DFEDTARU", transform="level", unit="%", cadence="daily", tier=3,
        release="fomc",
        why="The committee's stated ceiling. Worth tracking alongside the "
            "effective rate because a persistent gap between them is a money-"
            "market plumbing signal, not a policy one.",
        up_means="A hike has landed.", down_means="A cut has landed.",
        watch="The effective rate drifting to the top of the band is an early "
              "sign that reserves are getting scarce.",
        good="none",
    ),
    Series(
        id="sofr", label="SOFR (overnight repo)", family="policy",
        fred="SOFR", transform="level", unit="%", cadence="daily", tier=3,
        why="What secured overnight funding actually costs. It is the plumbing "
            "gauge: a spike means collateral or reserves are short, which has "
            "twice forced the Fed to act between meetings.",
        up_means="Funding stress. Small moves are quarter-end noise; a sustained "
                 "spread over the funds target is not.",
        down_means="Ample reserves.",
        watch="SOFR printing above the top of the funds target band, especially "
              "away from quarter-end.",
        good="down",
    ),
    Series(
        id="fed_balance_sheet", label="Fed balance sheet", family="liquidity",
        fred="WALCL", transform="level", unit="$bn", cadence="weekly", tier=2, scale=0.001, decimals=0,
        why="The quantity side of policy. Shrinking it drains reserves from the "
            "banking system, which tightens conditions without touching the "
            "policy rate - and the market usually notices the effect before the "
            "cause.",
        up_means="Reserves added. Historically supportive of risk assets, "
                 "whatever the stated reason.",
        down_means="Quantitative tightening is draining liquidity; the effect is "
                   "slow and then sudden, as 2019's repo squeeze showed.",
        watch="The weekly change matters more than the level. Watch it together "
              "with reserve balances and the Treasury cash account.",
        good="up",
    ),
    Series(
        id="reserves", label="Bank reserve balances", family="liquidity",
        fred="WRESBAL", transform="level", unit="$bn", cadence="weekly", tier=2, scale=0.001, decimals=0,
        why="The actual buffer in the system, and the variable the Fed says it is "
            "steering when it decides how far quantitative tightening can go. "
            "Scarce reserves are how a liquidity drain becomes a market event.",
        up_means="More cushion; funding markets calm.",
        down_means="The system is running closer to the edge. This is the series "
                   "to watch when people argue about when QT has to stop.",
        watch="Reserves falling while the Treasury cash account rises is a drain "
              "with a known end date - and a known reversal.",
        good="up",
    ),
    Series(
        id="rrp", label="Overnight reverse repo", family="liquidity",
        fred="RRPONTSYD", transform="level", unit="$bn", cadence="daily", tier=3,
        why="Cash parked at the Fed overnight by money funds. For two years it "
            "was the shock absorber that let the Treasury issue heavily without "
            "draining bank reserves. Near zero, that cushion is gone and new "
            "issuance hits reserves directly.",
        up_means="Idle cash rebuilding - usually a sign bills are cheap relative "
                 "to the Fed's floor.",
        down_means="The buffer is being spent. Once empty, liquidity drains show "
                   "up in reserves and then in risk assets.",
        watch="How close it is to zero, not the change.",
        good="none",
    ),
    Series(
        id="tga", label="Treasury General Account", family="liquidity",
        fred="WTREGEN", transform="level", unit="$bn", cadence="weekly", tier=3, scale=0.001, decimals=0,
        why="The government's own checking account. When it fills - tax dates, a "
            "rebuild after a debt-ceiling fight - cash leaves the private system; "
            "when it is spent down, liquidity returns. It is the most predictable "
            "liquidity swing there is, because the schedule is published.",
        up_means="Liquidity leaving the private system.",
        down_means="Liquidity returning.",
        watch="Mid-April and mid-quarter tax dates, and any post-debt-ceiling "
              "rebuild.",
        good="down",
    ),
    Series(
        id="m2", label="M2 money supply", family="liquidity",
        fred="M2SL", transform="yoy", unit="% y/y", tier=3,
        why="A slow, much-abused aggregate - but its 2020-21 surge and 2022-23 "
            "contraction did bracket the inflation wave, and it remains a useful "
            "sanity check on liquidity narratives built from weekly noise.",
        up_means="Nominal spending power growing.",
        down_means="Historically rare and associated with disinflation, sometimes "
                   "with recession.",
        watch="Direction over quarters. Anyone trading this weekly is fooling "
              "themselves.",
        good="none",
    ),

    # -------------------------------------------------------------------- rates
    Series(
        id="ust_2y", label="2-year Treasury yield", family="rates",
        fred="DGS2", transform="level", unit="%", tier=1, cadence="daily",
        why="The market's forecast of average policy over two years. It is the "
            "cleanest read on what traders think the Fed will do, and it moves "
            "before the Fed does - every cutting cycle in living memory was "
            "priced here first.",
        up_means="The market is pulling cuts out or adding hikes. Front-end pain, "
                 "and pressure on anything financed short.",
        down_means="Cuts being priced in. Good for bonds; for equities it depends "
                   "entirely on whether growth data is falling too.",
        watch="2-year minus fed funds is the implied path: materially below the "
              "funds rate means the market expects cuts.",
        good="none",
    ),
    Series(
        id="ust_10y", label="10-year Treasury yield", family="rates",
        fred="DGS10", transform="level", unit="%", tier=1, cadence="daily",
        why="The global discount rate. Mortgages, corporate hurdle rates and "
            "equity valuations are all quoted off it. Since 2022 the correlation "
            "has flipped: a fast rise in the 10-year is now an equity event, not "
            "a hedge.",
        up_means="Multiples compress, long-duration growth equities and housing "
                 "hurt first. Whether it is a growth or an inflation move decides "
                 "if it is survivable.",
        down_means="Supportive for valuations - unless it is falling because "
                   "growth is, in which case earnings are the bigger problem.",
        watch="Speed over level. Roughly 50bp in a month has historically been "
              "enough to break an equity rally regardless of where it started.",
        good="none",
    ),
    Series(
        id="ust_30y", label="30-year Treasury yield", family="rates",
        fred="DGS30", transform="level", unit="%", cadence="daily", tier=3,
        why="Where fiscal credibility shows up. The long end is priced by buyers "
            "who care about deficits and issuance rather than the next meeting, "
            "so a long end rising while the front end falls is a term-premium "
            "story - the bond market charging more to fund the government.",
        up_means="Term premium rebuilding. Historically the hardest kind of rate "
                 "rise for equities to absorb.",
        down_means="Confidence in long-run inflation and issuance.",
        watch="30-year rising on a day the 2-year falls. That specific pattern is "
              "the fiscal-stress tell.",
        good="none",
    ),
    Series(
        id="real_10y", label="10-year real yield (TIPS)", family="rates",
        fred="DFII10", transform="level", unit="%", tier=2, cadence="daily",
        why="The nominal yield with expected inflation taken out - the actual "
            "cost of long-term money. It is the correct discount rate for equity "
            "cash flows, and it separates 'rates rose because of growth' from "
            "'rates rose because of inflation fear'.",
        up_means="Genuine tightening. This is the variable that has done most of "
                 "the damage to long-duration equities and to gold.",
        down_means="Real easing, even if headline yields are unchanged.",
        watch="Above roughly 2% real, historically, is where valuation-sensitive "
              "assets start to struggle.",
        good="down",
    ),
    Series(
        id="curve_2s10s", label="2s10s curve", family="rates",
        fred="T10Y2Y", transform="level", unit="pp", tier=1, cadence="daily",
        why="Ten-year yield minus two-year. Inversion has preceded every US "
            "recession since the 1960s, but the more useful signal is the "
            "re-steepening: recessions have tended to arrive as the curve "
            "un-inverts, not while it is inverted.",
        up_means="Steepening. Bull steepening (front end falling) means cuts are "
                 "coming; bear steepening (long end rising) means term premium or "
                 "inflation risk.",
        down_means="Flattening or inverting - policy tight relative to growth. "
                   "Squeezes bank margins and anything borrowing short to lend long.",
        watch="Which end is doing the moving. The level alone tells you much less "
              "than the composition.",
        good="none",
    ),
    Series(
        id="curve_3m10y", label="3m10y curve", family="rates",
        fred="T10Y3M", transform="level", unit="pp", cadence="daily", tier=3,
        why="The version of the curve the New York Fed's own recession model "
            "uses, and the one least contaminated by expectations about the very "
            "front end.",
        up_means="Normalising.", down_means="Deeper inversion.",
        watch="Sign changes rather than wiggles.",
        good="none",
    ),
    Series(
        id="mortgage_30y", label="30-year mortgage rate", family="housing",
        fred="MORTGAGE30US", transform="level", unit="%", cadence="weekly", tier=2,
        why="How monetary policy reaches most households. It also gates the "
            "existing-home market through lock-in: owners holding 3% loans do not "
            "list at 7%, so supply, transactions and everything downstream of "
            "them freeze.",
        up_means="Affordability and transaction volumes fall; builders, brokers, "
                 "lenders and home-improvement demand all feel it.",
        down_means="The most direct channel for a rate cut to reach the real "
                   "economy, with roughly a two-quarter lag.",
        watch="6% is roughly where refinancing waves and normal turnover restart.",
        good="down",
    ),

    # ------------------------------------------------------------------- credit
    Series(
        id="hy_spread", label="High-yield OAS", family="credit",
        fred="BAMLH0A0HYM2", transform="level", unit="pp", tier=1, cadence="daily",
        why="The extra yield demanded to lend to junk-rated companies. This is "
            "the market's honest opinion about default risk, and it is the single "
            "best early-warning gauge on this list: credit has led equities into "
            "every serious drawdown, and it does not do false positives quietly.",
        up_means="Risk being repriced. A move through 500bp has historically "
                 "coincided with equity drawdowns rather than preceded them by "
                 "much - which is exactly why the direction matters daily.",
        down_means="Credit is open: companies can refinance, which removes the "
                   "mechanism by which a slowdown becomes a default cycle.",
        watch="Roughly 300bp is complacent, 500bp is stress, 800bp+ is a crisis. "
              "The rate of change matters more than the level.",
        good="down",
    ),
    Series(
        id="ig_spread", label="Investment-grade OAS", family="credit",
        fred="BAMLC0A0CM", transform="level", unit="pp", tier=2, cadence="daily",
        why="The same question asked of the companies that actually fund the "
            "economy. When investment-grade spreads widen, the problem has "
            "stopped being idiosyncratic.",
        up_means="Stress reaching quality borrowers - a genuine escalation.",
        down_means="Funding conditions benign.",
        watch="Widening at the same time as high yield is a market event; high "
              "yield alone is usually an energy or single-name story.",
        good="down",
    ),
    Series(
        id="nfci", label="Chicago Fed financial conditions", family="credit",
        fred="NFCI", transform="level", unit="index", cadence="weekly", tier=2,
        why="One number summarising 105 measures of risk, credit and leverage. "
            "Useful precisely because it is hard to talk yourself out of: it "
            "aggregates the plumbing you would otherwise cherry-pick from.",
        up_means="Conditions tightening versus history - a headwind that operates "
                 "with a lag of quarters.",
        down_means="Conditions loosening. Note that loosening conditions are what "
                   "make a central bank keep policy tighter for longer.",
        watch="Zero is average since 1971. Positive is tighter than average.",
        good="down",
    ),
    Series(
        id="stlfsi", label="St. Louis Fed financial stress", family="credit",
        fred="STLFSI4", transform="level", unit="index", cadence="weekly", tier=3,
        why="A second, differently-built stress index. Two independent gauges "
            "agreeing is worth far more than either one moving alone.",
        up_means="Stress building.", down_means="Calm.",
        watch="Zero is the historical average; sustained positive readings are rare.",
        good="down",
    ),
    Series(
        id="loan_standards", label="Banks tightening C&I standards", family="credit",
        fred="DRTSCILM", transform="level", unit="% net", cadence="quarterly", tier=3,
        why="The Fed asks loan officers directly whether they are making it "
            "harder to borrow. Quarterly and slow, but it is the mechanism by "
            "which rate rises actually reach small business - and it leads "
            "business investment by two to three quarters.",
        up_means="Credit being rationed. Small and mid-cap earnings feel this "
                 "long before large caps do.",
        down_means="Credit opening up - a necessary condition for a capex recovery.",
        watch="Net percentages above ~20% tightening have accompanied every "
              "recent recession.",
        good="down",
    ),

    # -------------------------------------------------------------------- labor
    Series(
        id="payrolls", label="Nonfarm payroll change", family="labor",
        fred="PAYEMS", transform="chg1", unit="k", tier=1, release="jobs",
        decimals=0,
        why="The most-traded number in macro, and the one the Fed's employment "
            "mandate is written against. It is also heavily revised, which is why "
            "the three-month average is the honest read and the headline is the "
            "tradeable one.",
        up_means="A hot print pushes cuts further out - good for earnings, bad "
                 "for multiples. Which effect wins depends on where inflation is.",
        down_means="Cuts pulled forward. Below roughly zero, the market stops "
                   "treating weakness as good news and starts pricing recession.",
        watch="Breakeven job growth - enough to hold unemployment flat - is "
              "roughly 100k and has been falling with immigration. Compare to the "
              "3-month average, not to last month.",
        good="none",
    ),
    Series(
        id="unemployment", label="Unemployment rate", family="labor",
        fred="UNRATE", transform="level", unit="%", tier=1, release="jobs",
        decimals=1,
        why="Half of the Fed's mandate, and the input to the only recession rule "
            "with a decent record: the Sahm rule fires when the 3-month average "
            "rises half a point above its low of the prior year. Labour markets "
            "do not deteriorate gently.",
        up_means="The Fed's reaction function flips from inflation to jobs. Cuts "
                 "get faster and bigger, and earnings estimates start falling.",
        down_means="Tight labour market, wage pressure, less urgency to ease.",
        watch="The rise off the 12-month low, not the level. Half a point is the "
              "line.",
        good="down",
    ),
    Series(
        id="claims", label="Initial jobless claims (4wk avg)", family="labor",
        fred="ICSA", transform="avg4", unit="k", tier=1, cadence="weekly", scale=0.001,
        release="claims", decimals=0,
        why="The highest-frequency read on the labour market: weekly, barely "
            "revised, and a genuine leading indicator because firms file before "
            "they show up in a monthly survey. This is how you find out a turn is "
            "happening without waiting three weeks.",
        up_means="Layoffs broadening. Sustained rises have preceded every "
                 "unemployment-rate turn.",
        down_means="Firms are holding onto workers, whatever the survey data says.",
        watch="Use the 4-week average - the weekly number is seasonal noise. A "
              "move above roughly 260k has historically marked genuine "
              "deterioration.",
        good="down",
    ),
    Series(
        id="continuing_claims", label="Continuing claims", family="labor",
        fred="CCSA", transform="level", unit="k", cadence="weekly", tier=2, scale=0.001,
        decimals=0, release="claims",
        why="Initial claims say whether people are losing jobs; continuing claims "
            "say whether they are finding new ones. In a low-firing, low-hiring "
            "labour market this is the half that is actually deteriorating.",
        up_means="Re-employment is getting harder - the slow way a labour market "
                 "cracks.",
        down_means="Displaced workers are being absorbed.",
        watch="Rising continuing claims with flat initial claims is the classic "
              "late-cycle signature.",
        good="down",
    ),
    Series(
        id="job_openings", label="Job openings (JOLTS)", family="labor",
        fred="JTSJOL", transform="level", unit="k", tier=3, release="jolts",
        decimals=0,
        why="Vacancies per unemployed worker is the measure the Fed leaned on to "
            "argue it could cool wages without mass layoffs - the 'Beveridge "
            "curve' bet. Watching openings fall without unemployment rising is "
            "watching that bet pay off.",
        up_means="Labour demand still strong; wage pressure persists.",
        down_means="Cooling without firing, if unemployment holds. Once openings "
                   "are back to normal, further cooling has to come from layoffs.",
        watch="Openings per unemployed worker near 1.0 is a balanced market.",
        good="none",
    ),
    Series(
        id="quits", label="Quits rate", family="labor",
        fred="JTSQUR", transform="level", unit="%", tier=3, release="jolts",
        decimals=1,
        why="Workers quit when they are confident of something better. It leads "
            "wage growth by a couple of quarters and is a cleaner confidence read "
            "than any survey, because it costs something to be wrong.",
        up_means="Job-switching wage premium returning; services inflation "
                 "stickier.",
        down_means="Workers sitting tight - falling wage pressure, and a household "
                   "sector that will spend more cautiously.",
        watch="Roughly 2.3% is the pre-pandemic norm; below it is a cautious "
              "labour market.",
        good="none",
    ),
    Series(
        id="participation", label="Labour force participation", family="labor",
        fred="CIVPART", transform="level", unit="%", tier=3, release="jobs",
        decimals=1,
        why="Determines whether a falling unemployment rate is good news. People "
            "leaving the workforce lowers the rate without anyone getting a job, "
            "and it changes how much employment growth the economy needs.",
        up_means="More supply of labour - disinflationary, and allows faster "
                 "growth without wage pressure.",
        down_means="A tighter effective labour market than the headline suggests.",
        watch="Prime-age (25-54) participation is the version not distorted by "
              "demographics.",
        good="up",
    ),
    Series(
        id="u6", label="U-6 underemployment", family="labor",
        fred="U6RATE", transform="level", unit="%", tier=3, release="jobs",
        decimals=1,
        why="Includes part-time-for-economic-reasons and discouraged workers. When "
            "U-6 rises faster than U-3, the labour market is weakening in hours "
            "before it weakens in headcount - which is how this cycle has tended "
            "to do it.",
        up_means="Slack building beneath the headline.",
        down_means="Genuine full employment.",
        watch="The U-6 minus U-3 gap, not either level.",
        good="down",
    ),

    # ------------------------------------------------------------------- growth
    Series(
        id="gdp_growth", label="Real GDP growth", family="growth",
        fred="A191RL1Q225SBEA", transform="level", unit="% ann.", tier=2,
        cadence="quarterly", release="gdp", decimals=1,
        why="The scoreboard, published so late that it mostly confirms what "
            "markets already traded. Its value is in the composition: growth "
            "driven by consumption and investment is durable, growth driven by "
            "inventories and net exports is not.",
        up_means="Earnings support, less need for easing.",
        down_means="Earnings estimates come down; the Fed's employment mandate "
                   "starts to bind.",
        watch="Final domestic demand strips out the noisy components and is the "
              "number worth reading.",
        good="up",
    ),
    Series(
        id="gdp_now", label="Atlanta Fed GDPNow", family="growth",
        fred="GDPNOW", transform="level", unit="% ann.", tier=2, cadence="weekly",
        decimals=1,
        why="A running estimate of the current quarter, rebuilt every time a "
            "monthly input lands. It is the antidote to GDP's publication lag: "
            "mechanical, transparent and updated before the fact rather than "
            "after.",
        up_means="Incoming data is running hotter than consensus.",
        down_means="The current quarter is tracking below what equity analysts "
                   "have in their models.",
        watch="Early-quarter readings are noisy by construction. It gets useful "
              "once several months of inputs are in.",
        good="up",
    ),
    Series(
        id="retail_sales", label="Retail sales", family="growth",
        fred="RSAFS", transform="yoy", unit="% y/y", tier=2, release="retail",
        why="Two thirds of the US economy is consumption, and this is the "
            "monthly read on it. Nominal, so compare to inflation: sales growing "
            "3% with 3% inflation means real volumes are flat.",
        up_means="The consumer is absorbing higher rates. Supports earnings and "
                 "keeps the Fed cautious.",
        down_means="Demand destruction reaching the consumer - and the consumer "
                   "is what has held this cycle up.",
        watch="The 'control group' excluding autos, gas and building materials is "
              "what feeds GDP.",
        good="up",
    ),
    Series(
        id="real_consumption", label="Real consumer spending", family="growth",
        fred="PCEC96", transform="yoy", unit="% y/y", tier=3, release="pce",
        why="Retail sales with inflation removed and services included - the "
            "honest version of whether consumption is growing.",
        up_means="Real demand growing; earnings revisions tend to follow.",
        down_means="Volumes falling even if revenue lines still grow.",
        watch="Compare to real disposable income: spending growing faster means "
              "the savings rate is falling, which cannot continue indefinitely.",
        good="up",
    ),
    Series(
        id="indpro", label="Industrial production", family="growth",
        fred="INDPRO", transform="yoy", unit="% y/y", tier=3,
        why="Manufacturing is a sixth of the economy but a much larger share of "
            "its volatility, and it turns earlier. It is also the part most "
            "exposed to tariffs, the dollar and global demand.",
        up_means="Goods cycle recovering - usually good for cyclicals, energy and "
                 "industrial metals.",
        down_means="Goods recession, which has repeatedly happened without a "
                   "broader one.",
        watch="Manufacturing weakness alongside strong services has been this "
              "cycle's normal state, not a warning.",
        good="up",
    ),
    Series(
        id="sentiment", label="U. Michigan sentiment", family="growth",
        fred="UMCSENT", transform="level", unit="index", tier=3, release="umich",
        decimals=1,
        why="Consumers' own view. A weak forecaster of spending - people spend "
            "when they have income, not when they feel good - but its inflation "
            "expectations component is watched closely by the Fed, and it is "
            "increasingly a read on politics.",
        up_means="Confidence improving, marginally supportive of discretionary "
                 "spending.",
        down_means="Historically a poor recession signal on its own. Do not trade "
                   "it alone.",
        watch="The 1-year and 5-10 year inflation expectation sub-indices matter "
              "more than the headline.",
        good="up",
    ),

    # --------------------------------------------------------------------- risk
    Series(
        id="spx", label="S&P 500", family="risk",
        fred="SP500", quote="^GSPC", transform="level", unit="", tier=1,
        cadence="daily", decimals=0,
        why="The benchmark, and also a policy input: the Fed watches financial "
            "conditions, and equity prices are a large part of them. Its level "
            "relative to its own 200-day average is the crudest useful trend "
            "filter in existence.",
        up_means="Wealth effect, easier financial conditions - which paradoxically "
                 "allows the Fed to stay tighter for longer.",
        down_means="Tightening conditions. A drawdown that reaches credit spreads "
                   "is the kind that changes Fed behaviour.",
        watch="Distance from the 200-day average, and whether breadth confirms - "
              "an index carried by five names is a different market.",
        good="up",
    ),
    Series(
        id="ndx", label="Nasdaq 100", family="risk",
        quote="^NDX", transform="level", unit="", tier=2, cadence="daily",
        decimals=0,
        why="The long-duration end of equities, and today the concentrated bet on "
            "AI capital spending. Its ratio to the S&P is the cleanest available "
            "read on whether the market is paying for growth or for cash flow.",
        up_means="Duration and growth in favour - usually falling real yields, or "
                 "a capex story strong enough to override them.",
        down_means="Either rates rising or the capex story being questioned. Which "
                   "one matters enormously for what else to expect.",
        watch="Nasdaq versus equal-weight S&P. A widening gap is narrowing "
              "leadership.",
        good="up",
    ),
    Series(
        id="rut", label="Russell 2000", family="risk",
        quote="^RUT", transform="level", unit="", tier=3, cadence="daily",
        decimals=0,
        why="Small caps carry floating-rate debt, borrow from banks rather than "
            "bond markets, and earn domestically. They are therefore the purest "
            "expression of 'will the domestic economy and credit hold up'.",
        up_means="Broad-based confidence, easing credit, or expected rate cuts "
                 "into a growing economy.",
        down_means="The market disbelieves the soft landing, however well the "
                   "index level reads.",
        watch="Russell versus S&P is the single best breadth check available for "
              "free.",
        good="up",
    ),
    Series(
        id="vix", label="VIX", family="risk",
        fred="VIXCLS", quote="^VIX", transform="level", unit="", tier=1,
        cadence="daily", decimals=1,
        why="The price of one month of S&P options - the market's own estimate of "
            "how much it is about to move. It is mean-reverting and usually low, "
            "which is exactly why a sustained rise matters: it means hedging has "
            "become expensive because someone needs it.",
        up_means="Demand for protection. Spikes are usually the end of a move "
                 "rather than the start, but a grind higher from a low base is a "
                 "regime change.",
        down_means="Complacency. Persistent lows have historically been when "
                   "leverage builds up, which is what makes the next shock larger.",
        watch="Below 15 is calm, above 25 is stress, above 35 is a liquidity "
              "event. The shape of the futures curve says more than the level.",
        good="down",
    ),

    # ------------------------------------------------------------------- dollar
    Series(
        id="dollar_broad", label="Broad dollar index", family="dollar",
        fred="DTWEXBGS", quote="DX-Y.NYB", transform="level", unit="index",
        tier=2, cadence="daily", decimals=1,
        why="The dollar is the global funding currency, so its price is a global "
            "financial condition. A strong dollar tightens conditions everywhere, "
            "squeezes emerging markets, cuts the foreign earnings of US "
            "multinationals and pushes commodity prices down.",
        up_means="Global tightening. Bad for emerging markets, commodities and "
                 "roughly 40% of S&P revenue.",
        down_means="A global easing impulse, and usually the start of "
                   "international equities outperforming.",
        watch="Why it is moving: rate differentials, growth differentials or a "
              "safe-haven bid all point to different trades.",
        good="none",
    ),
    Series(
        id="eurusd", label="EUR/USD", family="dollar",
        fred="DEXUSEU", transform="level", unit="", cadence="daily", tier=3,
        decimals=4,
        why="The largest single weight in the dollar index, and mostly a story "
            "about the gap between Fed and ECB policy.",
        up_means="Dollar weakening against the euro.",
        down_means="Dollar strength or European weakness.",
        watch="The 2-year yield spread between Germany and the US explains most "
              "of it.",
        good="none",
    ),
    Series(
        id="usdjpy", label="USD/JPY", family="dollar",
        fred="DEXJPUS", transform="level", unit="", cadence="daily", tier=3,
        decimals=1,
        why="The world's carry trade. Cheap yen funding finances leveraged "
            "positions everywhere, so a sharp yen rally has repeatedly forced "
            "global de-leveraging - August 2024 being the clearest recent case.",
        up_means="Yen weakening: carry trade profitable, leverage building.",
        down_means="Carry unwinding. Fast yen strength is a global risk event "
                   "regardless of what Japan intended.",
        watch="The speed of a move, and Bank of Japan or Ministry of Finance "
              "comments about intervention.",
        good="none",
    ),

    # -------------------------------------------------------------- commodities
    Series(
        id="wti", label="WTI crude", family="commodities",
        fred="DCOILWTICO", quote="CL=F", transform="level", unit="$", tier=2,
        cadence="daily", decimals=2,
        why="The fastest route from geopolitics to headline inflation to consumer "
            "spending. An oil spike is a tax on consumption and an inflation "
            "problem at the same time, which is the one combination monetary "
            "policy handles worst.",
        up_means="Headline inflation up, real incomes down, central banks "
                 "cornered. Energy equities are the hedge.",
        down_means="Disinflationary and supportive of consumption - unless it is "
                   "falling because global demand is.",
        watch="Whether it is moving on supply (geopolitics, OPEC) or demand "
              "(China, global growth). The same price move means opposite things.",
        good="none",
    ),
    Series(
        id="brent", label="Brent crude", family="commodities",
        fred="DCOILBRENTEU", transform="level", unit="$", cadence="daily", tier=3,
        decimals=2,
        why="The international benchmark, and the one that prices most of the "
            "world's physical barrels. A widening Brent-WTI spread is usually a "
            "US logistics or export story.",
        up_means="Global supply tightness.", down_means="Global demand softness.",
        watch="The spread to WTI.",
        good="none",
    ),
    Series(
        id="gold", label="Gold", family="commodities",
        quote="GC=F", transform="level", unit="$", tier=2, cadence="daily",
        decimals=1,
        why="Historically gold traded on real yields - it pays no coupon, so a "
            "higher real yield is a higher cost of holding it. When it rallies "
            "*with* real yields, the driver is something else: central bank "
            "reserve buying, fiscal worry, or hedging against the dollar itself.",
        up_means="Either falling real yields or a bid for something outside the "
                 "dollar system. The second is the more interesting signal.",
        down_means="Rising real yields, or risk appetite returning.",
        watch="Gold versus the 10-year real yield. A broken relationship is the "
              "message.",
        good="none",
    ),
    Series(
        id="copper", label="Copper", family="commodities",
        quote="HG=F", transform="level", unit="$", cadence="daily", tier=3,
        decimals=2,
        why="Industrial demand in one price - construction, grids, vehicles, data "
            "centres. Electrification has made it a structural story as well as a "
            "cyclical one, which cuts both ways for its signal value.",
        up_means="Global industrial demand, especially Chinese, firming.",
        down_means="Goods-side demand weakening.",
        watch="Copper versus gold is a decent proxy for growth expectations, and "
              "it tends to track the 10-year yield.",
        good="up",
    ),
    Series(
        id="bitcoin", label="Bitcoin", family="risk",
        quote="BTC-USD", transform="level", unit="$", cadence="daily", tier=3,
        decimals=0,
        why="Tracked here as a liquidity and risk-appetite gauge rather than on "
            "its own merits: it trades 24/7, holds no cash flows, and has been "
            "the highest-beta expression of marginal dollar liquidity. It often "
            "turns before equities on weekends and overnight.",
        up_means="Ample liquidity and appetite for risk.",
        down_means="Liquidity draining - frequently the first asset to show it.",
        watch="Its correlation to the Nasdaq. When they decouple, the move is "
              "crypto-specific and carries no macro information.",
        good="none",
    ),

    # ------------------------------------------------------------------ housing
    Series(
        id="housing_starts", label="Housing starts", family="housing",
        fred="HOUST", transform="level", unit="k", tier=3, release="housing",
        decimals=0,
        why="Residential construction is small in GDP but enormous in "
            "cyclicality, and it is the most rate-sensitive part of the economy. "
            "It has led most postwar recessions.",
        up_means="Rate relief reaching the real economy; good for materials, "
                 "labour demand and the mid-cycle story.",
        down_means="The rate channel is biting. Watch permits to see whether it "
                   "continues.",
        watch="Permits lead starts, and single-family leads multi-family.",
        good="up",
    ),
    Series(
        id="permits", label="Building permits", family="housing",
        fred="PERMIT", transform="level", unit="k", cadence="monthly", tier=3,
        release="housing", decimals=0,
        why="The intentions version of housing starts, and therefore the leading "
            "half of a leading indicator.",
        up_means="Builders committing capital - a genuine confidence signal "
                 "because it is expensive to be wrong.",
        down_means="Pipeline shrinking.",
        watch="Single-family permits specifically.",
        good="up",
    ),
    Series(
        id="home_prices", label="Case-Shiller home prices", family="housing",
        fred="CSUSHPINSA", transform="yoy", unit="% y/y", tier=3,
        why="Housing is most households' entire balance sheet, so prices drive "
            "the wealth effect far more broadly than equities do. The index is "
            "also a three-month average reported with a two-month lag - the "
            "slowest number on this list.",
        up_means="Wealth effect supports consumption; shelter inflation stays "
                 "sticky with a long lag.",
        down_means="Negative wealth effect and eventually falling shelter CPI.",
        watch="Remember the lag. This tells you about last quarter.",
        good="none",
    ),
    Series(
        id="existing_sales", label="Existing home sales", family="housing",
        fred="EXHOSLUSM495S", transform="level", unit="k", tier=3, release="housing", scale=0.001,
        decimals=0,
        why="Transaction volume, which is what actually generates economic "
            "activity - brokers, movers, renovations, appliances. Rate lock-in "
            "has held this near multi-decade lows regardless of demand.",
        up_means="The freeze thawing; a broad activity boost.",
        down_means="Lock-in intact.",
        watch="This is about mortgage rates, not about prices.",
        good="up",
    ),

    # ------------------------------------------------------------------- fiscal
    Series(
        id="deficit", label="Monthly federal deficit", family="fiscal",
        fred="MTSDS133FMS", transform="level", unit="$bn", tier=3, decimals=0, scale=0.001,
        why="Deficits have to be funded, and funding means Treasury issuance. "
            "Issuance sets the supply of duration the market must absorb, which "
            "is a direct input to the long end of the curve and to the term "
            "premium.",
        up_means="A larger deficit means more issuance and, at the margin, a "
                 "higher long-end yield.",
        down_means="Less supply pressure.",
        watch="Monthly numbers are wildly seasonal - use the 12-month rolling "
              "total. The quarterly refunding announcement is where issuance "
              "plans actually become news.",
        good="none",
    ),
    Series(
        id="federal_debt", label="Federal debt outstanding", family="fiscal",
        fred="GFDEBTN", transform="level", unit="$bn", cadence="quarterly", tier=3, scale=0.001,
        decimals=0,
        why="The stock behind the flow. It matters through interest expense: as "
            "low-coupon debt rolls into today's yields, debt service crowds out "
            "everything else and becomes a fiscal-political constraint.",
        up_means="More supply to absorb, more interest expense.",
        down_means="Rare.",
        watch="Interest expense as a share of revenue is the number that "
              "eventually forces a decision.",
        good="none",
    ),
)

BY_ID = {s.id: s for s in SERIES}
# One HTTP request per FRED id per run, so a series used twice (core PCE, as a
# level and as a 3-month annualised rate) is fetched once.
FRED_IDS = sorted({s.fred for s in SERIES if s.fred})
QUOTE_SYMBOLS = sorted({s.quote for s in SERIES if s.quote})

# Extra market symbols that back no single indicator but make the cross-asset
# snapshot meaningful. Leadership among these is how a desk reads what the
# market believes today: defensives over cyclicals is a growth scare, long
# bonds and gold together is a policy-easing bet, energy alone is a supply
# shock.
SNAPSHOT_SYMBOLS = (
    ("SPY", "S&P 500", "equity"),
    ("QQQ", "Nasdaq 100", "equity"),
    ("IWM", "Small caps", "equity"),
    ("EFA", "Developed ex-US", "equity"),
    ("EEM", "Emerging markets", "equity"),
    ("XLK", "Technology", "sector"),
    ("XLF", "Financials", "sector"),
    ("XLE", "Energy", "sector"),
    ("XLY", "Consumer discretionary", "sector"),
    ("XLP", "Consumer staples", "sector"),
    ("XLU", "Utilities", "sector"),
    ("XLV", "Health care", "sector"),
    ("TLT", "Long Treasuries", "bond"),
    ("LQD", "Investment-grade credit", "bond"),
    ("HYG", "High-yield credit", "bond"),
    ("GLD", "Gold", "commodity"),
)

# Pairs whose RATIO carries information neither leg carries alone. These are
# the reads that separate "stocks fell" from "stocks fell because the market
# now expects a recession".
RATIOS = (
    ("IWM", "SPY", "Small caps vs S&P",
     "Breadth and domestic-credit confidence. Falling means the rally is "
     "narrow and the market doubts the domestic economy."),
    ("XLY", "XLP", "Discretionary vs staples",
     "The cleanest risk-on/risk-off read inside equities: consumers' wants "
     "against their needs."),
    ("QQQ", "SPY", "Nasdaq vs S&P",
     "Whether the market is paying for duration and growth or for cash flow."),
    ("HYG", "LQD", "High yield vs investment grade",
     "Credit risk appetite with duration netted out."),
    ("GLD", "TLT", "Gold vs long bonds",
     "Two ways to own a hedge. Gold winning means the worry is fiscal or "
     "inflationary rather than a growth scare."),
)


def label(series_id: str) -> str:
    s = BY_ID.get(series_id)
    return s.label if s else series_id


def tier1() -> tuple:
    """The short list. What a desk actually reacts to on the day."""
    return tuple(s for s in SERIES if s.tier == 1)
