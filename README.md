# Finance Curator

A daily market page that tries to answer one question: **what changed, and does
it matter to me?**

Most finance feeds answer a different one — what happened, loudly. This one
pulls three things that have to be read together and puts them on one page:

- **What is true now.** 60 macro and market series from FRED and Yahoo, each
  turned into a level, its momentum, and where it sits in its own five-year
  distribution — with a plain-English note on *why it matters* and what a move
  in it means.
- **What state the market is in.** Seven regime reads — inflation, growth,
  policy, rates, credit, liquidity, risk — computed from those series in the
  order causation runs, plus an explicit line on **where the reads disagree**,
  which is the only place a view can be wrong in a useful way.
- **What is scheduled.** An economic calendar, because what moves a market this
  week was published weeks ago.

Then it ranks the news against all of it, on two separate axes: **market
impact** (how big a deal is this for anyone) and **relevance** (would *you*,
with your horizon and holdings, act differently), scored by an LLM reading a
plain-English profile you write in [`profile.md`](profile.md).

A GitHub Action runs it every weekday morning before the 08:30 ET releases and
pushes the result to GitHub Pages.

> **Not investment advice.** Everything here describes public data and the
> mechanisms by which it has historically reached asset prices. Nothing on the
> page tells you what to buy, sell or hold, and the LLM prompts explicitly
> forbid it — a model that tries to be helpful that way scores worse, not
> better.

**[PLAYBOOK.md](PLAYBOOK.md) is the companion document**: how to read the
market, which numbers move it and why, the four growth/inflation regimes, how
policy reaches a portfolio through four different channels, and what to ignore.
The code automates the reasoning in it; the reasoning is worth reading once on
its own.

Built as a sibling to [sfevents](https://github.com/watakandai/sfevents) and
[technews](https://github.com/watakandai/technews), sharing their shape:
standard-library Python, a cached SQLite database, a two-layer ranker, and a
static page committed to `docs/`.

---

## How it works

```
data   ->  FRED (54 series) + Yahoo (25 symbols)  ->  SQLite observations
       ->  federalreserve.gov FOMC calendar (confirmed dates)
       ->  publication rules (everything else, marked estimated)
news   ->  28 feeds + Reddit                      ->  SQLite items
rank   ->  crowd popularity (where any exists)
       ->  categories + horizon (keyword pass)
       ->  market impact (free, always)
       ->  relevance + category + horizon + assets (LLM, new items only)
brief  ->  regime + top news + calendar           ->  one paragraph
export ->  docs/data/{items,market}.json          ->  GitHub Pages
```

### Two axes, not one

The sibling projects rank on one number. Finance needs two, because they come
apart constantly:

| | |
| --- | --- |
| **Impact** | How much this moves markets, for anybody. Publisher tier, decision language ("cuts rates", "imposes tariffs"), whether it names a scheduled release the whole market trades, cross-source agreement, and freshness decayed by horizon. |
| **Relevance** | Whether *you* would act differently. An LLM reading `profile.md`, told what is already true (the regime and the current readings) so it can tell a print that confirms the consensus from one that breaks it. |

A Federal Reserve statement has no upvotes and reprices every asset on earth; a
Reddit thread about it has three hundred. Collapsing those into one number
destroys the information, so the page shows both.

### Horizon: how long an item stays relevant

Every item is filed as `day`, `week` or `months`, and the page groups by that by
default. It is deliberately *not* "when does this first move a price" — an FOMC
decision moves the tape at 14:00 and still sets the discount rate in six months,
so it is `months`. The question a curator has to answer is "will I still care
about this next month", because that is what decides whether it is worth reading
carefully today. It is also why the durable bucket is at the top of the page and
the day's tape is at the bottom.

### The calendar, and the `~`

There is no free, machine-readable US economic calendar. The BLS blocks
automated clients outright (HTTP 403), Census publishes its schedule only
through JavaScript, and the commercial ones want a key. What does exist is a
publication rule per release that has held for decades — claims every Thursday,
payrolls the first Friday, ISM the first business day — and those reconstruct
the calendar to within a day or two.

So every rules-derived date is marked `estimated` and the page renders it with a
`~`. FOMC dates are scraped from the Fed's own calendar page and are confirmed;
the database refuses to let an estimated date overwrite a confirmed one. An
approximate calendar clearly marked as approximate is useful. One presented as
fact is a trap.

### Why the numbers are computed this way

Three decisions in [`finance/metrics.py`](finance/metrics.py) do most of the
work:

- **Everything is looked up by date, never by row offset.** "A year ago" is
  `today - 365 days`. Series have gaps — holidays, a missed survey month, a
  revision that adds a row — and index arithmetic on a gapped series silently
  compares the wrong periods.
- **A change is absolute for a rate and proportional for a price.** The 10-year
  going 4.0% → 4.5% is "up 50bp", not "up 12.5%". Getting this backwards is the
  most common way a finance dashboard produces numbers that are technically
  correct and unreadable.
- **3-month annualised sits next to year-over-year.** An annual rate is an
  average of twelve months and keeps reporting last spring. The momentum read is
  what turns a Fed pause into a cut two meetings early.

Revisions overwrite: observations are keyed by `(series, date)` and the latest
vintage wins, because the revised figure is the one that is true. News does the
opposite — crowd counts merge with `MAX`, so a story's peak attention is never
erased by a later read at a lower rank.

### The regime reads

[`finance/regime.py`](finance/regime.py) computes seven states in the order
causation runs:

```
inflation → policy → rates → credit → liquidity → risk
            ↑
          growth
```

Each returns a state in plain words, a score from -2 to +2, the evidence it was
computed from, and — the part that matters — the **mechanism** by which that
state reaches asset prices. Every threshold is a named constant with a comment
saying where it comes from (the Fed's 2% target, Sahm's half a point, the
500bp high-yield level), because an unexplained threshold is indistinguishable
from a made-up one.

The most useful output is `tension`: where the reads disagree with each other.
Equities calm while credit widens, or the market pricing cuts while inflation is
still above target, is the only kind of situation where the page can tell you
something the price has not.

### The sources

| Source | What it adds | Key needed |
| --- | --- | --- |
| **FRED** (54 series) | every macro series: inflation, labour, rates, credit spreads, liquidity, housing, fiscal | no — the graph CSV export is public |
| **Yahoo Finance** (25 symbols) | today's prices, plus gold, copper, bitcoin and the sector ETFs FRED does not carry | no |
| **federalreserve.gov** | confirmed FOMC dates for two years ahead | no |
| **6 primary feeds** | the Fed, BEA, SEC, ECB — the thing itself, not a report of it | no |
| **11 wire/major outlets** | WSJ, FT, Economist, CNBC, MarketWatch, NY Fed and BoE research | no |
| **11 analysis feeds** | Calculated Risk, Fed Guy, Macro Compass, Ritholtz, Wolf Street and others | no |
| **Reddit** (7 subreddits) | the only real crowd signal here; sentiment and positioning | optional |

Adding a publication is one line in
[`finance/feeds.json`](finance/feeds.json). Adding a metric is one entry in
[`finance/indicators.py`](finance/indicators.py) — including the text explaining
why it matters, which the page and the LLM prompt both read from the same place
so they cannot drift apart.

**Known gaps, stated plainly:**

- The **BLS blocks automated clients**, so CPI and payrolls arrive through the
  wires rather than from the agency. The numbers themselves come from FRED,
  which is unaffected.
- **No consensus forecasts.** Markets trade the surprise, not the level, and
  there is no free machine-readable consensus. The page gives percentile,
  z-score and momentum context instead, which is usually enough to know whether
  a number is news.
- **Yahoo rate-limits bursts.** A blocked run gives up after three consecutive
  429s rather than grinding for ten minutes; headline market series fall back to
  FRED (a day stale) and the snapshot keeps whatever history is already cached.
- **No non-US central bank calendar.** ECB and BoJ dates are published but not
  in any form worth scraping, so only their news is covered, not their schedule.

---

## Setup

### 1. Write your profile

```bash
cp profile.example.md profile.md   # then edit it
```

This file **is** the prompt. The section that matters most is *what I am trying
to decide* — the ranker scores each item on whether it moves one of those open
questions. HTML comments are stripped before sending, so notes-to-self are safe.

Do not put account numbers or balances in it. Approximate percentages are all
the ranker needs.

### 2. Run it locally

```bash
python -m finance.cli --db /tmp/finance.db data
```

```bash
python -m finance.cli --db /tmp/finance.db news
```

```bash
python -m finance.cli --db /tmp/finance.db rank
```

```bash
python -m finance.cli --db /tmp/finance.db brief
```

```bash
python -m finance.cli --db /tmp/finance.db export --out-dir docs/data
```

Then open the page through any static server:

```bash
python -m http.server 8778 --directory docs
```

The first `data` run fetches twelve years of history and takes several minutes;
later runs are incremental against the cached database.

There are two terminal views that need no browser:

```bash
python -m finance.cli --db /tmp/finance.db dash
```

```bash
python -m finance.cli --db /tmp/finance.db calendar --days 21
```

To rank against your profile you need a key (the free tier is plenty):

```bash
GEMINI_API_KEY=... python -m finance.cli --db /tmp/finance.db rank --llm
```

### 3. Publish it

Push to GitHub, then **Settings → Pages → Source: `main` / `/docs`**.

Add under **Settings → Secrets and variables → Actions**:

| Kind | Name | Needed? | Why |
| --- | --- | --- | --- |
| Variable | `RANKER_PROVIDER` | for profile ranking | `gemini`, `anthropic`, `groq` or `ollama`. Unset = impact + heuristic only |
| Secret | `GEMINI_API_KEY` | for profile ranking | [aistudio.google.com](https://aistudio.google.com/apikey) |
| Secret | `GROQ_API_KEY` | recommended | Free fallback when the primary 503s or runs out of quota — [console.groq.com](https://console.groq.com/keys) |
| Secret | `ANTHROPIC_API_KEY` | optional | Claude as a paid fallback (or primary). Skipped when unset |
| Variable | `RANKER_FALLBACK` | optional | Fallback order for whatever the primary leaves unscored. Default `groq,anthropic,ollama`; providers without a key are skipped, and `ollama` is a small model (`OLLAMA_MODEL`, default `qwen3.5:4b`) the workflow runs on the runner's CPU |
| Secret | `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | recommended | Reddit 429s anonymous CI traffic; a free "script" app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) fixes it and adds real upvote counts |

Optional tuning variables: `RANKER_LIMIT`, `RANKER_BATCH_SIZE` (default 40),
`RANKER_MIN_INTERVAL` (default 8s), `HISTORY_YEARS` (12), `CALENDAR_MONTHS` (4),
`EXPORT_DAYS` (10), `PRUNE_DAYS` (45).

The workflow runs at 11:00 UTC (7am ET) on weekdays — before the 08:30 releases,
because the point of the calendar is to be read *before* the things on it
happen. Run it by hand from the Actions tab for a provider override, a
"re-score everything" toggle, or an item cap.

### Cost

Gemini Flash on a day of ~650 items, of which ~150 are new: roughly four
ranking requests plus one for the brief. Comfortably inside the free tier.
`RANKER_LIMIT` caps it if you want a hard ceiling.

**Without a key the site still works completely.** The regime reads, every
metric, the calendar and the impact scores are all computed locally — only the
personalised relevance score and the written brief need a model.

---

## The page

`docs/index.html` is one file, no build step, no dependencies:

- **Brief** — what state the market is in, what changed, where the reads
  disagree, and what would change it
- **Regime** — seven tiles; click any one for its evidence, why it matters and
  the mechanism
- **Cross-asset** — what is leading, plus the five ratios (small caps vs S&P,
  discretionary vs staples, gold vs long bonds…) that say *why*
- **Calendar** — what is scheduled, with `~` on inferred dates and a note on
  what to look at when each one lands
- **Metrics** — every series with momentum, percentile and a sparkline; click a
  row for why it matters and what a move means
- **News** — grouped by horizon, with both scores, filter chips, search, read
  state, and <kbd>j</kbd>/<kbd>k</kbd>/<kbd>o</kbd>/<kbd>space</kbd> navigation

Dark mode, a usable phone layout, and everything it remembers lives in
`localStorage` — nothing is uploaded, and every read is guarded so a private
window still works.

---

## Tests

```bash
python -m pytest tests/ -q
```

150 tests, no network. Parser tests run against captured real responses in
`tests/fixtures/` so they assert against the shapes these services actually
return. The LLM tests use a stub provider and cover batching, a failed batch, a
per-minute 429 retry, a daily quota stopping the run, and the caching that keeps
a second run free. The pipeline test runs rank → brief → export end to end
against a temporary database.

## Layout

```
finance/
  cli.py             data / news / rank / brief / export / list / dash / calendar / prune
  indicators.py      THE knowledge file: 60 series, and why each one matters
  metrics.py         level -> context: momentum, z-score, percentile, sparkline
  regime.py          the seven reads and the mechanism behind each
  calendar_rules.py  publication rules -> an economic calendar, honestly marked
  categorize.py      the news taxonomy, and the horizon classifier
  impact.py          how much this moves markets
  rank.py            heuristic + LLM relevance, provider plumbing
  brief.py           the daily brief, computed or written
  popularity.py      per-source crowd normalization (a minor input here)
  normalize.py       URL canonicalization and story identity
  db.py              SQLite: items, observations, events, state
  feeds.json         the news sources - add outlets here
  fetchers/          fred, yahoo, rss, reddit, fomc
docs/                the published site (index.html + data/*.json)
profile.md           your situation and open questions. This file is the prompt.
PLAYBOOK.md          how to read the market, and what each number means
```
