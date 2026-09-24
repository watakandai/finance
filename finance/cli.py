from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import brief as briefing
from . import categorize as categorizing
from . import indicators
from . import metrics as metrics_mod
from . import popularity as popularity_mod
from . import rank as ranking
from . import regime as regime_mod
from .calendar_rules import generate as generate_calendar
from .db import (
    count_events, count_items, count_observations, get_state, init_db,
    query_events, query_items, row_to_dict, series_values, set_categories,
    set_heuristic_scores, set_impact, set_llm_results, set_popularity,
    set_state, prune, unscored_items, upsert_events, upsert_items,
    upsert_observations,
)
from .fetchers.fomc import FomcFetcher
from .fetchers.fred import FredFetcher
from .fetchers.reddit import RedditFetcher
from .fetchers.rss import RSSFetcher
from .fetchers.yahoo import YahooFetcher
from .impact import impact_scores

DEFAULT_DB = Path.home() / ".finance" / "finance.db"
FEEDS_FILE = Path(__file__).parent / "feeds.json"

# Sources that can go quiet without erroring - a credentialed or rate-limited
# path where zero results means "something changed", not "slow news day".
FRAGILE_SOURCES = {"reddit", "yahoo"}

# Market symbols that back no indicator. The `mkt:` prefix keeps them in the
# observations table without pretending they are macro series.
SNAPSHOT_SERIES = {sym: f"mkt:{sym}" for sym, _, _ in indicators.SNAPSHOT_SYMBOLS}


def load_feeds():
    return json.loads(FEEDS_FILE.read_text()).get("feeds", [])


def feed_hints() -> dict:
    return {f["name"]: f.get("hint", "") for f in load_feeds() if f.get("hint")}


def build_news_fetchers() -> list:
    """Every news source, with its credentials resolved from the environment.

    Reddit is included unconditionally and decides for itself what to do without
    a key: it falls back to its public feed. A fork with no secrets at all still
    produces a full site.
    """
    fetchers = [RSSFetcher(f["name"], f["url"], tier=int(f.get("tier", 3)))
                for f in load_feeds()]
    fetchers.append(RedditFetcher(
        client_id=os.environ.get("REDDIT_CLIENT_ID", "").strip(),
        client_secret=os.environ.get("REDDIT_CLIENT_SECRET", "").strip(),
    ))
    return fetchers


def fred_series_map() -> dict:
    """{FRED id: [local series ids]} - one request per FRED id, not per indicator."""
    out = {}
    for series in indicators.SERIES:
        if series.fred:
            out.setdefault(series.fred, []).append(series.id)
    return out


def quote_symbol_map() -> dict:
    """{Yahoo symbol: local series id}, indicators plus snapshot-only symbols."""
    out = {series.quote: series.id for series in indicators.SERIES if series.quote}
    out.update(SNAPSHOT_SERIES)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Market news and macro dashboard curator")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    sub = parser.add_subparsers(dest="cmd", required=True)

    news = sub.add_parser("news", help="pull the latest from every news source")
    news.add_argument("--only", default="", help="comma-separated source names")

    data = sub.add_parser(
        "data", help="pull macro series, market prices and the calendar")
    data.add_argument("--years", type=int, default=12,
                      help="how much history to request from FRED")
    data.add_argument("--months", type=int, default=4,
                      help="how far ahead to generate the calendar")
    data.add_argument("--skip", default="",
                      help="comma-separated: fred, quotes, calendar")

    rank_parser = sub.add_parser(
        "rank", help="score news (impact and relevance; LLM optionally)")
    rank_parser.add_argument(
        "--llm", action="store_true",
        help="also score against profile.md (needs the provider's API key)")
    rank_parser.add_argument("--provider", choices=sorted(ranking.PROVIDERS),
                             default="gemini")
    rank_parser.add_argument(
        "--fallback", default="",
        help="comma-separated providers to try, in order, when --provider fails "
             "(e.g. groq,ollama); ones without a key are skipped")
    rank_parser.add_argument("--model", default=None)
    rank_parser.add_argument("--profile", default=str(ranking.DEFAULT_PROFILE))
    rank_parser.add_argument(
        "--limit", type=int, default=0,
        help="cap how many items go to the LLM this run (0 = all unscored)")
    rank_parser.add_argument("--batch-size", type=int, default=40)
    rank_parser.add_argument(
        "--min-interval", type=float, default=0,
        help="seconds between LLM requests, to stay under a per-minute limit")
    rank_parser.add_argument(
        "--window-days", type=int, default=7,
        help="only send items this recent to the LLM")
    rank_parser.add_argument("--rescore-all", action="store_true")

    brief_parser = sub.add_parser("brief", help="write the daily brief")
    brief_parser.add_argument("--llm", action="store_true")
    brief_parser.add_argument("--provider", choices=sorted(ranking.PROVIDERS),
                              default="gemini")
    brief_parser.add_argument(
        "--fallback", default="",
        help="comma-separated providers to try, in order, when --provider fails "
             "(e.g. groq,ollama); ones without a key are skipped")
    brief_parser.add_argument("--model", default=None)
    brief_parser.add_argument("--profile", default=str(ranking.DEFAULT_PROFILE))

    export = sub.add_parser("export", help="write the JSON the static page reads")
    export.add_argument("--out-dir", required=True)
    export.add_argument("--sort", choices=("score", "impact", "date"), default="score")
    export.add_argument("--days", type=int, default=10,
                        help="how much news history to publish")
    export.add_argument("--no-collapse", action="store_true")

    list_parser = sub.add_parser("list", help="print the ranked list to the terminal")
    list_parser.add_argument("--sort", choices=("score", "impact", "date"),
                             default="score")
    list_parser.add_argument("--limit", type=int, default=40)
    list_parser.add_argument("--category", default="")
    list_parser.add_argument("--horizon", default="")

    dash = sub.add_parser("dash", help="print the regime dashboard to the terminal")
    dash.add_argument("--family", default="")
    dash.add_argument("--all", action="store_true",
                      help="every tracked series, not just tiers 1 and 2")

    cal = sub.add_parser("calendar", help="print what is scheduled next")
    cal.add_argument("--days", type=int, default=21)
    cal.add_argument("--importance", type=int, default=3)

    prune_parser = sub.add_parser("prune", help="drop news older than N days")
    prune_parser.add_argument("--days", type=int, default=45)

    args = parser.parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    init_db(args.db)

    {"news": _cmd_news, "data": _cmd_data, "rank": _cmd_rank, "brief": _cmd_brief,
     "export": _cmd_export, "list": _cmd_list, "dash": _cmd_dash,
     "calendar": _cmd_calendar, "prune": _cmd_prune}[args.cmd](args)


# ------------------------------------------------------------------- fetch

def _cmd_news(args) -> None:
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    total = 0
    for fetcher in build_news_fetchers():
        if only and fetcher.name not in only:
            continue
        try:
            items = fetcher.fetch()
        except Exception as exc:
            # One dead feed must never cost the other twenty-eight sources.
            print(f"{fetcher.name}: FAILED ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
            continue
        upsert_items(args.db, items)
        total += len(items)
        print(f"{fetcher.name}: {len(items)} items")
        if not items and fetcher.name in FRAGILE_SOURCES:
            print(f"  warning: {fetcher.name} returned 0 items - it is "
                  "rate-limited or credential-gated, so check before assuming "
                  "it was a quiet day.", file=sys.stderr)
    print(f"fetched {total} items; {count_items(args.db)} in the database")


def _cmd_data(args) -> None:
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    if "fred" not in skip:
        fred = FredFetcher(fred_series_map(), years=args.years)
        observations = fred.fetch()
        upsert_observations(args.db, observations)
        print(f"fred: {len(observations)} observations across "
              f"{len(fred.series_map) - len(fred.failures)} series")
        for series_id, why in fred.failures:
            print(f"  fred {series_id}: FAILED ({why})", file=sys.stderr)

    if "quotes" not in skip:
        yahoo = YahooFetcher(quote_symbol_map())
        quotes = yahoo.fetch()
        upsert_observations(args.db, quotes)
        print(f"quotes: {len(quotes)} observations across "
              f"{len(yahoo.symbol_map) - len(yahoo.failures)} symbols")
        for symbol, why in yahoo.failures:
            print(f"  quote {symbol}: FAILED ({why})", file=sys.stderr)
        if getattr(yahoo, "rate_limited", False):
            print("  warning: the quote source rate-limited this run and the "
                  "rest were skipped. Headline market series fall back to FRED "
                  "(a day stale); the cross-asset snapshot keeps whatever "
                  "history is already stored.", file=sys.stderr)
        elif not quotes:
            print("  warning: every quote failed. Market series fall back to "
                  "FRED (a day stale) and the cross-asset snapshot will be "
                  "missing.", file=sys.stderr)

    if "calendar" not in skip:
        # Rules first, then the scrape: `upsert_events` refuses to let an
        # estimated date overwrite a confirmed one, so order does not actually
        # matter - but reading it in this order makes the precedence obvious.
        rules = generate_calendar(date.today(), months=args.months)
        upsert_events(args.db, rules)
        print(f"calendar: {len(rules)} rules-derived events (dates estimated)")
        try:
            confirmed = FomcFetcher().fetch()
            written = upsert_events(args.db, confirmed)
            print(f"calendar: {written} confirmed Fed dates from "
                  f"federalreserve.gov")
        except Exception as exc:
            print(f"  fomc: FAILED ({type(exc).__name__}: {exc}) - the Fed "
                  "calendar is the only confirmed source here, so check it",
                  file=sys.stderr)

    print(f"{count_observations(args.db)} observations, "
          f"{count_events(args.db)} events in the database")


# -------------------------------------------------------------------- rank

def _cmd_rank(args) -> None:
    rows = [row_to_dict(r) for r in query_items(args.db)]
    if not rows:
        print("nothing to rank - run `news` first")
        return

    # 1. Crowd popularity, normalized per source, then shared across clusters.
    #    A minor input here, but it is the only vote count that exists.
    scores = popularity_mod.popularity_scores(rows)
    scores = popularity_mod.propagate(rows, scores)
    set_popularity(args.db, scores)
    print(f"popularity: scored {len(scores)}/{len(rows)} items "
          f"({len(rows) - len(scores)} have no crowd signal)")

    # 2. Keyword categories and horizons, so filters work without a key.
    hints = feed_hints()
    cats = {r["id"]: categorizing.categorize(r, hints) for r in rows}
    print(f"categories: filed {set_categories(args.db, cats)} items "
          f"({len(rows) - len(cats)} already carry the model's)")

    # 3. Market impact, reading the popularity just written.
    rows = [row_to_dict(r) for r in query_items(args.db)]
    horizons = {r["id"]: r.get("horizon") or categorizing.horizon(r, r.get("category"))
                for r in rows}
    impacts = impact_scores(rows, horizons)
    set_impact(args.db, impacts)
    print(f"impact: scored {len(impacts)} items "
          f"(top {max((v[0] for v in impacts.values()), default=0):.0f})")

    # 4. Heuristic relevance, reading the impact and category just written.
    rows = [row_to_dict(r) for r in query_items(args.db)]
    heuristic = ranking.heuristic_scores(rows)
    written = set_heuristic_scores(args.db, heuristic)
    kept = len(heuristic) - written
    print(f"heuristic: scored {written} items"
          + (f" ({kept} keep their LLM score)" if kept else ""))

    if not args.llm:
        print("(pass --llm to also rank against profile.md)")
        return

    try:
        profile = ranking.load_profile(args.profile)
    except FileNotFoundError as exc:
        print(f"llm: SKIPPED ({exc})", file=sys.stderr)
        return

    model = args.model or ranking.PROVIDERS[args.provider][1]
    phash = ranking.profile_hash(profile, model)
    since = (datetime.now(timezone.utc) - timedelta(days=args.window_days)).isoformat()

    if args.rescore_all:
        todo = [row_to_dict(r) for r in query_items(args.db, since=since)]
    else:
        todo = [row_to_dict(r) for r in unscored_items(args.db, phash, since=since)]
    if args.limit:
        # unscored_items returns highest-impact first, so a cap spends the
        # budget on what actually moved markets.
        todo = todo[: args.limit]
    if not todo:
        print(f"llm: nothing to do - everything recent is scored for profile {phash}")
        return

    # The model is told what is already true, so it can tell a print that
    # confirms the consensus from one that breaks it.
    summaries, series = _load_metrics(args.db)
    context = ranking.market_context(summaries, regime_mod.assess(summaries, series))

    fallbacks = [p.strip() for p in args.fallback.split(",")
                 if p.strip() and p.strip() != args.provider]
    batch_no = 0

    def on_provider(name, used_model, pending, note):
        nonlocal batch_no
        batch_no = 0
        if used_model is None:
            print(f"llm: {name} {note}")
        elif note:
            print(f"llm: {name}/{used_model} {note}")
        else:
            print(f"llm: sending {pending} items to {name}/{used_model} "
                  f"in batches of {args.batch_size}")

    def progress(offset, size, note):
        nonlocal batch_no
        batch_no += 1
        print(f"  batch {batch_no} ({size} items): {note}")

    try:
        by_model = ranking.llm_scores_chain(
            todo, profile, [args.provider, *fallbacks], model=model,
            batch_size=args.batch_size, min_interval=args.min_interval,
            context=context, on_progress=progress, on_provider=on_provider,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"llm: SKIPPED ({exc})", file=sys.stderr)
        return

    # The hash is the primary model's even for fallback scores: it marks the
    # item as done for this profile, so tomorrow doesn't re-send it.
    # scored_by keeps the truth about which model gave the score.
    results = {}
    for scored_by, got in by_model.items():
        set_llm_results(args.db, got, scored_by, phash)
        results.update(got)
    if len(by_model) > 1:
        print("llm: by model: " + ", ".join(f"{k} {len(v)}" for k, v in by_model.items()))
    if results:
        # Horizons the model changed feed back into impact, whose decay curve
        # depends on them - otherwise an item the model reclassified as
        # structural would keep decaying like tape.
        rows = [row_to_dict(r) for r in query_items(args.db)]
        set_impact(args.db, impact_scores(rows, {r["id"]: r.get("horizon") for r in rows}))
    print(f"llm: scored {len(results)}/{len(todo)} items for profile {phash}")


# ------------------------------------------------------------------- brief

def _cmd_brief(args) -> None:
    summaries, series = _load_metrics(args.db)
    ratios = _ratios(args.db)
    reading = regime_mod.assess(summaries, series, ratios)
    since = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    items = [row_to_dict(r) for r in query_items(args.db, order_by="impact", since=since)]
    events = query_events(args.db, start=date.today().isoformat(), max_importance=2)

    if args.llm:
        # One prompt, so the chain is simply "next provider on failure". A
        # fallback without a key is skipped; --model only applies to the first.
        fallbacks = [p.strip() for p in args.fallback.split(",")
                 if p.strip() and p.strip() != args.provider]
        for n, name in enumerate([args.provider, *fallbacks]):
            env_var = ranking.PROVIDERS[name][0]
            if n and not os.environ.get(env_var, "").strip():
                print(f"brief: {name} skipped ({env_var} not set)")
                continue
            try:
                profile = ranking.load_profile(args.profile)
                written = briefing.llm_brief(
                    profile, reading, summaries, items, events,
                    provider=name, model=args.model if n == 0 else None,
                    timeout=ranking.PROVIDER_TIMEOUT.get(name, 120))
                set_state(args.db, "brief", written)
                print(f"brief: written by {written['by']} "
                      f"({len(written['points'])} points)")
                print(f"  {written['lede']}")
                return
            except Exception as exc:
                print(f"brief: {name} failed ({type(exc).__name__}: {exc})",
                      file=sys.stderr)
        print("brief: every LLM failed - falling back to the computed brief",
              file=sys.stderr)

    written = briefing.heuristic_brief(reading, items, events)
    set_state(args.db, "brief", written)
    print(f"brief: written by {written['by']} ({len(written['points'])} points)")
    print(f"  {written['lede']}")


# ------------------------------------------------------------------ metrics

def _load_metrics(db_path, today: date = None) -> tuple:
    """({series id: summary}, {series id: raw history}) for every tracked series.

    Both are returned because `regime` needs the raw history for the handful of
    calculations that are not a single latest value - the Sahm unemployment gap
    above all.
    """
    today = today or date.today()
    summaries, series = {}, {}
    for spec in indicators.SERIES:
        values = series_values(db_path, spec.id)
        if not values:
            continue
        series[spec.id] = values
        summary = metrics_mod.summarize(spec, values, today)
        if summary:
            summaries[spec.id] = summary
    return summaries, series


def _ratios(db_path, today: date = None) -> dict:
    """{"IWM/SPY": {"3m": pct}} for the leadership pairs.

    A ratio of two prices, not a difference of two returns: the ratio is a
    single series whose own percentage change answers "which one has been
    winning, over this window" without either leg's absolute move getting in
    the way.
    """
    today = today or date.today()
    out = {}
    for numerator, denominator, label, why in indicators.RATIOS:
        top = series_values(db_path, f"mkt:{numerator}")
        bottom = series_values(db_path, f"mkt:{denominator}")
        if not top or not bottom:
            continue
        by_date = dict(bottom)
        paired = [(on, value / by_date[on]) for on, value in top
                  if by_date.get(on)]
        if len(paired) < 30:
            continue
        snap = metrics_mod.snapshot(paired, today)
        out[f"{numerator}/{denominator}"] = {
            "label": label, "why": why, **snap.get("changes", {}),
            "as_of": snap.get("as_of", ""),
        }
    return out


def _snapshot(db_path, today: date = None) -> list:
    today = today or date.today()
    out = []
    for symbol, label, group in indicators.SNAPSHOT_SYMBOLS:
        values = series_values(db_path, f"mkt:{symbol}")
        if not values:
            continue
        snap = metrics_mod.snapshot(values, today)
        if snap:
            out.append({"symbol": symbol, "label": label, "group": group, **snap})
    return out


# ------------------------------------------------------------------ export

# What the page reads. Everything else (source_id, fetched_at, profile_hash,
# scored_at) is bookkeeping the browser never touches, and these files are
# fetched on every page load.
EXPORT_FIELDS = (
    "id", "source", "title", "url", "discussion_url", "author", "published_ts",
    "summary", "points", "comments", "metric", "tags", "tier", "popularity",
    "impact", "impact_reason", "horizon", "category", "assets", "score",
    "score_reason", "scored_by",
)
SUMMARY_LIMIT = 260

# Fields where zero is a measurement, not an absence. Everything else is dropped
# when empty to keep the payload small, but a story the model scored 0 must not
# be exported as unscored - the page renders those differently and "nothing for
# you" is a real answer.
KEEP_ZERO = {"score", "impact", "popularity"}


def _slim(row: dict) -> dict:
    out = {
        k: row[k] for k in EXPORT_FIELDS
        if k in row and (row[k] not in (None, "", [], 0)
                         or (k in KEEP_ZERO and row[k] == 0))
    }
    summary = out.get("summary") or ""
    if len(summary) > SUMMARY_LIMIT:
        out["summary"] = summary[:SUMMARY_LIMIT].rstrip() + "..."
    return out


def _pick_representative(group: list) -> dict:
    """Which copy of a story to actually show.

    Preference order: the primary source, then the highest-scoring, then one
    with a summary to read. Tier first is the finance-specific part - when the
    Fed's own statement and four write-ups of it collapse into one row, the row
    should link to the statement.
    """
    return max(
        group,
        key=lambda r: (
            -int(r.get("tier") or 3),
            r.get("score") or 0,
            bool(r.get("summary")),
            r.get("impact") or 0,
        ),
    )


def collapse(rows: list) -> list:
    """Merge every copy of the same story into one row carrying all its links."""
    groups = {}
    for row in rows:
        key = row.get("cluster_key") or f"id:{row['id']}"
        groups.setdefault(key, []).append(row)

    merged = []
    for group in groups.values():
        best = dict(_pick_representative(group))
        others = [r for r in group if r["id"] != best["id"]]
        # The best score, impact and popularity anywhere in the cluster win: one
        # source having been read properly is enough.
        for row in others:
            if (row.get("score") or 0) > (best.get("score") or 0):
                best["score"], best["score_reason"] = row["score"], row.get("score_reason")
            if (row.get("impact") or 0) > (best.get("impact") or 0):
                best["impact"] = row["impact"]
                best["impact_reason"] = row.get("impact_reason")
            if (row.get("popularity") or 0) > (best.get("popularity") or 0):
                best["popularity"] = row["popularity"]
            best["category"] = best.get("category") or row.get("category")
            best["horizon"] = best.get("horizon") or row.get("horizon")
            best["summary"] = best.get("summary") or row.get("summary")
            best["assets"] = best.get("assets") or row.get("assets")
        best["also"] = [
            {"source": r["source"],
             "url": r.get("discussion_url") or r.get("url") or "",
             "tier": r.get("tier") or 3}
            for r in sorted(others, key=lambda r: int(r.get("tier") or 3))
        ]
        merged.append(best)
    return merged


def _cmd_export(args) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # --- news
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    rows = [row_to_dict(r) for r in query_items(args.db, order_by=args.sort, since=since)]
    total = len(rows)
    if not args.no_collapse:
        rows = collapse(rows)
        # Collapsing reshuffles: a merged row may have inherited a better score
        # than the position it was sorted into.
        rows.sort(key=_sort_key(args.sort), reverse=True)
    news_payload = {
        "generated_at": generated,
        "window_days": args.days,
        "categories": categorizing.CATEGORIES,
        "horizons": categorizing.HORIZONS,
        "assets": ranking.ASSETS,
        "items": [dict(_slim(r), also=r.get("also") or []) for r in rows],
    }
    _write_json(out_dir / "items.json", news_payload, "items")
    print(f"exported {len(rows)} news rows (from {total} raw over {args.days} days)")

    # --- market: metrics, regime, calendar, snapshot, brief
    summaries, series = _load_metrics(args.db)
    ratios = _ratios(args.db)
    reading = regime_mod.assess(summaries, series, ratios)
    today = date.today()
    events = query_events(
        args.db, start=today.isoformat(),
        end=(today + timedelta(days=120)).isoformat())
    recent = query_events(
        args.db, start=(today - timedelta(days=7)).isoformat(),
        end=(today - timedelta(days=1)).isoformat(), max_importance=2)
    market_payload = {
        "generated_at": generated,
        "families": indicators.FAMILIES,
        "regime": reading,
        "metrics": [summaries[s.id] for s in indicators.SERIES if s.id in summaries],
        "ratios": ratios,
        "snapshot": _snapshot(args.db),
        "calendar": events,
        "recent_events": recent,
        "brief": get_state(args.db, "brief") or {},
    }
    _write_json(out_dir / "market.json", market_payload, "metrics")
    print(f"exported {len(market_payload['metrics'])} metrics, "
          f"{len(reading['reads'])} regime reads, {len(events)} upcoming events "
          f"to {out_dir}")


def _write_json(path: Path, payload: dict, list_key: str) -> None:
    """One compact record per line: valid JSON, far smaller than indent=2, and
    still readable as a diff - these files are committed on every daily run, and
    a single-line blob would make every change unreviewable."""
    records = payload.get(list_key) or []
    head = json.dumps({k: v for k, v in payload.items() if k != list_key},
                      separators=(",", ":"), default=str)
    if not records:
        path.write_text(head[:-1] + f',"{list_key}":[]}}\n')
        return
    lines = ",\n".join("  " + json.dumps(r, separators=(",", ":"), default=str)
                       for r in records)
    path.write_text(f'{head[:-1]},"{list_key}":[\n{lines}\n]}}\n')


def _sort_key(sort: str):
    if sort == "date":
        return lambda r: (r.get("published_ts") or "")
    field = "impact" if sort == "impact" else "score"
    return lambda r: (r.get(field) if r.get(field) is not None else -1)


# -------------------------------------------------------------- terminal UI

def _cmd_list(args) -> None:
    rows = collapse([row_to_dict(r) for r in query_items(args.db, order_by=args.sort)])
    rows.sort(key=_sort_key(args.sort), reverse=True)
    if args.category:
        rows = [r for r in rows if (r.get("category") or "") == args.category]
    if args.horizon:
        rows = [r for r in rows if (r.get("horizon") or "") == args.horizon]
    for row in rows[: args.limit or None]:
        score = f"{row['score']:5.1f}" if row.get("score") is not None else "    -"
        impact = f"{row['impact']:4.0f}" if row.get("impact") is not None else "   -"
        print(f"{score} imp{impact} {(row.get('horizon') or '?')[:6]:6} "
              f"{(row.get('category') or 'other')[:15]:15} "
              f"{row['source'][:14]:14} {(row['title'] or '')[:58]:58}"
              + (f" +{len(row.get('also') or [])}" if row.get("also") else ""))


def _cmd_dash(args) -> None:
    summaries, series = _load_metrics(args.db)
    if not summaries:
        print("no market data - run `data` first")
        return
    reading = regime_mod.assess(summaries, series, _ratios(args.db))
    print(f"REGIME: {reading['stance']} ({reading['score']:+d})")
    for read in reading["reads"]:
        print(f"  {read['label']:22} {read['score']:+d}  {read['state']}")
    print(f"\nTENSION: {reading['tension']}\n")

    for family, label in indicators.FAMILIES.items():
        picked = [s for s in indicators.SERIES
                  if s.family == family and s.id in summaries
                  and (args.all or s.tier <= 2)]
        if args.family and family != args.family:
            continue
        if not picked:
            continue
        print(label.upper())
        for spec in picked:
            entry = summaries[spec.id]
            changes = entry.get("changes") or {}
            window = "1m" if "1m" in changes else next(iter(changes), "")
            move = f"{changes[window]:+8.2f} {window}" if window else " " * 11
            rank = (f"  {entry['pct_rank']:3.0f}th pct"
                    if entry.get("pct_rank") is not None else "")
            print(f"  {spec.label:34} {entry['value']:>10.{spec.decimals}f}"
                  f" {spec.unit:7} {move}{rank}")
        print()
    print(regime_mod.DISCLAIMER)


def _cmd_calendar(args) -> None:
    today = date.today()
    events = query_events(
        args.db, start=today.isoformat(),
        end=(today + timedelta(days=args.days)).isoformat(),
        max_importance=args.importance)
    if not events:
        print("no calendar - run `data` first")
        return
    for event in events:
        mark = "~" if event.get("estimated") else " "
        stars = "*" * (4 - int(event["importance"]))
        print(f"{mark}{event['on_date']} {event.get('time_et') or '     ':>5} "
              f"{stars:3} {event['title']}")
    print("\n~ = date inferred from the publication rule, not confirmed.")


def _cmd_prune(args) -> None:
    removed = prune(args.db, args.days)
    print(f"pruned {removed} news items older than {args.days} days; "
          f"{count_items(args.db)} remain")


if __name__ == "__main__":
    main()
