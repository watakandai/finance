"""SQLite for all three planes: news, time series and the calendar.

One file rather than three because they are queried together - the export
writes a single view of "what is true today" - and because the whole database
is a disposable cache that GitHub Actions restores between runs. Losing it
costs one re-fetch and one re-score, nothing else.

Two rules earn their keep here and are easy to get wrong:

- **Crowd counts merge with MAX, never overwrite.** A story peaks and slides
  off the front page; a later run that re-reads it lower must not erase the
  peak, because peak attention is what `popularity` measures.
- **Observations are keyed by (series, date) and overwrite.** The opposite
  rule, for the opposite reason: statistical agencies revise. Last month's
  payroll number genuinely changes, and the revision is the truth. Keeping the
  first value seen would quietly preserve a number nobody trades on.
"""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .normalize import canonical_url, cluster_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    canonical TEXT,
    cluster_key TEXT,
    discussion_url TEXT,
    author TEXT,
    published_ts TEXT,
    summary TEXT,
    points INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    metric TEXT,
    rank INTEGER NOT NULL DEFAULT 0,
    tags TEXT,
    image TEXT,
    tier INTEGER NOT NULL DEFAULT 3,
    first_seen TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    popularity REAL,
    popularity_reason TEXT,
    impact REAL,
    impact_reason TEXT,
    horizon TEXT,
    category TEXT,
    assets TEXT,
    score REAL,
    score_reason TEXT,
    scored_by TEXT,
    scored_at TEXT,
    profile_hash TEXT,
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS observations (
    series_id TEXT NOT NULL,
    on_date TEXT NOT NULL,
    value REAL NOT NULL,
    source TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (series_id, on_date)
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    on_date TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 2,
    time_et TEXT,
    indicator TEXT,
    detail TEXT,
    url TEXT,
    estimated INTEGER NOT NULL DEFAULT 1,
    source TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# Applied after migrations, because an index cannot be created over a column
# an older database has not grown yet.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_ts);
CREATE INDEX IF NOT EXISTS idx_items_score ON items(score);
CREATE INDEX IF NOT EXISTS idx_items_impact ON items(impact);
CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_key);
CREATE INDEX IF NOT EXISTS idx_obs_series ON observations(series_id, on_date);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(on_date);
"""

MIGRATIONS = {
    "items": {
        "canonical": "TEXT", "cluster_key": "TEXT", "image": "TEXT",
        "tier": "INTEGER NOT NULL DEFAULT 3",
        "popularity": "REAL", "popularity_reason": "TEXT",
        "impact": "REAL", "impact_reason": "TEXT",
        "horizon": "TEXT", "category": "TEXT", "assets": "TEXT",
        "score": "REAL", "score_reason": "TEXT", "scored_by": "TEXT",
        "scored_at": "TEXT", "profile_hash": "TEXT",
    },
}


@contextmanager
def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        for table, columns in MIGRATIONS.items():
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for column, decl in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        conn.executescript(INDEXES)


# --------------------------------------------------------------------- news

def upsert_items(db_path, items: list) -> int:
    """Insert or refresh news items. Returns how many rows were written."""
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    with connect(db_path) as conn:
        for it in items:
            conn.execute(
                """INSERT INTO items
                     (source, source_id, title, url, canonical, cluster_key,
                      discussion_url, author, published_ts, summary, points,
                      comments, metric, rank, tags, image, tier, first_seen,
                      fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source, source_id) DO UPDATE SET
                     title=excluded.title,
                     url=excluded.url,
                     canonical=excluded.canonical,
                     cluster_key=excluded.cluster_key,
                     discussion_url=excluded.discussion_url,
                     author=excluded.author,
                     published_ts=COALESCE(excluded.published_ts, items.published_ts),
                     summary=excluded.summary,
                     points=MAX(excluded.points, items.points),
                     comments=MAX(excluded.comments, items.comments),
                     metric=excluded.metric,
                     rank=excluded.rank,
                     tags=excluded.tags,
                     image=COALESCE(NULLIF(excluded.image, ''), items.image),
                     tier=excluded.tier,
                     fetched_at=excluded.fetched_at
                """,
                (
                    it.source, it.source_id, it.title, it.url, canonical_url(it.url),
                    cluster_key(it.url, it.title), it.discussion_url, it.author,
                    it.published.isoformat() if it.published else None,
                    it.summary, int(it.points or 0), int(it.comments or 0),
                    it.metric, int(it.rank or 0), json.dumps(it.tags or []),
                    it.image, int(it.tier or 3), now, now,
                ),
            )
            written += 1
    return written


ORDERS = {
    # NULLs last in every ordering: an unscored row is unknown, not worst.
    "score": "score IS NULL, score DESC, impact DESC",
    "impact": "impact IS NULL, impact DESC, published_ts DESC",
    "popularity": "popularity IS NULL, popularity DESC, published_ts DESC",
    "date": "published_ts IS NULL, published_ts DESC",
}


def query_items(db_path, order_by: str = "date", since: str = "", source: str = ""):
    order = ORDERS.get(order_by, ORDERS["date"])
    where, params = [], []
    if since:
        # first_seen is the fallback because some sources publish no date, and
        # those rows must not silently vanish from a windowed query.
        where.append("COALESCE(published_ts, first_seen) >= ?")
        params.append(since)
    if source:
        where.append("source = ?")
        params.append(source)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with connect(db_path) as conn:
        return list(conn.execute(f"SELECT * FROM items{clause} ORDER BY {order}", params))


def row_to_dict(row) -> dict:
    d = dict(row)
    for field in ("tags", "assets"):
        try:
            d[field] = json.loads(d.get(field) or "[]")
        except (TypeError, ValueError):
            d[field] = []
    return d


def count_items(db_path) -> int:
    with connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]


def set_popularity(db_path, values: dict) -> int:
    with connect(db_path) as conn:
        for item_id, (pop, reason) in values.items():
            conn.execute(
                "UPDATE items SET popularity=?, popularity_reason=? WHERE id=?",
                (pop, reason, item_id),
            )
    return len(values)


def set_impact(db_path, values: dict) -> int:
    """Write market-impact scores. Always overwritten: `impact` is a pure
    function of the row and the day's other rows, so recomputing it is
    deterministic and a stale value would just be yesterday's arithmetic."""
    with connect(db_path) as conn:
        for item_id, (impact, reason, horizon) in values.items():
            conn.execute(
                """UPDATE items SET impact=?, impact_reason=?,
                       horizon=COALESCE(NULLIF(horizon,''), ?) WHERE id=?""",
                (impact, reason, horizon, item_id),
            )
    return len(values)


def set_heuristic_scores(db_path, scores: dict) -> int:
    """Write heuristic relevance scores, but never over an LLM score.

    The cheap ranker is the floor, not an overwrite. An item the model has
    already read against the profile keeps that judgement until the profile
    changes.
    """
    written = 0
    with connect(db_path) as conn:
        for item_id, (score, reason) in scores.items():
            cur = conn.execute(
                """UPDATE items SET score=?, score_reason=?, scored_by='heuristic'
                   WHERE id=? AND (scored_by IS NULL OR scored_by='heuristic')""",
                (score, reason, item_id),
            )
            written += cur.rowcount
    return written


def set_llm_results(db_path, results: dict, scored_by: str, profile_hash: str) -> int:
    """Write the model's score, reason, category, horizon and asset tags."""
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as conn:
        for item_id, r in results.items():
            conn.execute(
                """UPDATE items SET score=?, score_reason=?, category=?,
                       horizon=COALESCE(NULLIF(?,''), horizon),
                       assets=?, scored_by=?, scored_at=?, profile_hash=?
                   WHERE id=?""",
                (r["score"], r["reason"], r.get("category") or None,
                 r.get("horizon") or "", json.dumps(r.get("assets") or []),
                 scored_by, now, profile_hash, item_id),
            )
    return len(results)


def unscored_items(db_path, profile_hash: str, since: str = ""):
    """Items never scored against this exact (profile, model) pair.

    This is what makes a daily LLM run cost pennies: yesterday's items are
    already scored, so only today's arrivals are sent. Ordered by market
    impact, so a capped run spends the budget on what actually moved markets.
    """
    params = [profile_hash]
    clause = ""
    if since:
        clause = " AND COALESCE(published_ts, first_seen) >= ?"
        params.append(since)
    with connect(db_path) as conn:
        return list(conn.execute(
            f"""SELECT * FROM items
                WHERE (profile_hash IS NULL OR profile_hash != ?){clause}
                ORDER BY impact IS NULL, impact DESC""",
            params,
        ))


def set_categories(db_path, values: dict) -> int:
    """Write keyword categories over each other, but never over the model's.

    The guard protects the LLM's judgement, which is the only category here
    that cost anything. It deliberately does not make a keyword category
    sticky: the pass is free and deterministic, so re-filing is a no-op until
    the taxonomy changes - and on the run after it changes, this is what makes
    the new buckets reach items already in the database.
    """
    written = 0
    with connect(db_path) as conn:
        for item_id, cat in values.items():
            cur = conn.execute(
                """UPDATE items SET category=?
                    WHERE id=? AND (scored_by IS NULL OR scored_by='heuristic')
                      AND COALESCE(category, '') != ?""",
                (cat, item_id, cat),
            )
            written += cur.rowcount
    return written


def prune(db_path, days: int) -> int:
    """Drop news older than `days`. Observations and events are never pruned:
    a z-score needs years of history and the whole series is a few hundred KB,
    while news has a shelf life measured in days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM items WHERE COALESCE(published_ts, first_seen) < ?", (cutoff,)
        )
        return cur.rowcount


# -------------------------------------------------------------- observations

def upsert_observations(db_path, observations: list) -> int:
    """Insert or replace series values. Revisions win - see the module docstring."""
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as conn:
        conn.executemany(
            """INSERT INTO observations (series_id, on_date, value, source, fetched_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(series_id, on_date) DO UPDATE SET
                 value=excluded.value, source=excluded.source,
                 fetched_at=excluded.fetched_at""",
            [(o.series_id, o.on.isoformat(), float(o.value), o.source, now)
             for o in observations],
        )
    return len(observations)


def series_values(db_path, series_id: str, since: str = "") -> list:
    """[(date, value)] for one series, oldest first - the shape every
    calculation in `metrics` expects."""
    params = [series_id]
    clause = ""
    if since:
        clause = " AND on_date >= ?"
        params.append(since)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT on_date, value FROM observations
                WHERE series_id = ?{clause} ORDER BY on_date""",
            params,
        )
        return [(date.fromisoformat(r["on_date"]), r["value"]) for r in rows]


def series_ids(db_path) -> list:
    with connect(db_path) as conn:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT series_id FROM observations ORDER BY series_id")]


def count_observations(db_path) -> int:
    with connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]


# ----------------------------------------------------------------- calendar

def upsert_events(db_path, events: list) -> int:
    """Insert or replace calendar events.

    A confirmed event never loses to an estimated one. Rules-derived dates are
    regenerated every run and would otherwise overwrite a date scraped from the
    Fed's own calendar with this project's guess at it.
    """
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    with connect(db_path) as conn:
        for e in events:
            cur = conn.execute(
                """INSERT INTO events (event_id, on_date, title, kind, importance,
                       time_et, indicator, detail, url, estimated, source, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(event_id) DO UPDATE SET
                     on_date=excluded.on_date, title=excluded.title,
                     kind=excluded.kind, importance=excluded.importance,
                     time_et=excluded.time_et, indicator=excluded.indicator,
                     detail=excluded.detail, url=excluded.url,
                     estimated=excluded.estimated, source=excluded.source,
                     fetched_at=excluded.fetched_at
                   WHERE excluded.estimated = 0 OR events.estimated = 1""",
                (e.event_id, e.on.isoformat(), e.title, e.kind, int(e.importance),
                 e.time_et, e.indicator, e.detail, e.url, int(bool(e.estimated)),
                 e.source, now),
            )
            written += cur.rowcount
    return written


def query_events(db_path, start: str = "", end: str = "", max_importance: int = 3):
    where, params = ["importance <= ?"], [max_importance]
    if start:
        where.append("on_date >= ?")
        params.append(start)
    if end:
        where.append("on_date <= ?")
        params.append(end)
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute(
            f"""SELECT * FROM events WHERE {' AND '.join(where)}
                ORDER BY on_date, importance, title""", params)]


def count_events(db_path) -> int:
    with connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


# -------------------------------------------------------------------- state

def set_state(db_path, key: str, value) -> None:
    """Store a JSON blob under a key - used for the daily brief, so an export
    can reuse yesterday's when today's LLM call is skipped or fails."""
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO state (key, value, updated_at) VALUES (?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                              updated_at=excluded.updated_at""",
            (key, json.dumps(value, default=str), datetime.now(timezone.utc).isoformat()),
        )


def get_state(db_path, key: str, default=None):
    with connect(db_path) as conn:
        row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return default
