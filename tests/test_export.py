"""Collapsing, the export payloads, and a full offline pipeline run."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from finance import cli, db
from finance.calendar_rules import generate
from finance.models import CalEvent, Item, Observation


def row(**kw):
    base = dict(id=1, source="wsj", title="Fed cuts rates", cluster_key="u:a",
                tier=2, score=50.0, impact=60.0, summary="", category="rates",
                horizon="months", assets=[], url="https://wsj.com/a")
    return {**base, **kw}


# ------------------------------------------------------------------ collapse

def test_copies_of_one_story_become_one_row_carrying_every_link():
    rows = [row(id=1, source="wsj", tier=2),
            row(id=2, source="cnbc", tier=3),
            row(id=3, source="reddit", tier=4, discussion_url="https://r/x")]
    merged = cli.collapse(rows)
    assert len(merged) == 1
    assert {a["source"] for a in merged[0]["also"]} == {"cnbc", "reddit"}


def test_the_primary_source_is_the_copy_shown():
    # When the Fed's own statement and four write-ups collapse, the row should
    # link to the statement.
    rows = [row(id=1, source="cnbc", tier=3, score=90.0),
            row(id=2, source="fed_press", tier=1, score=40.0)]
    assert cli.collapse(rows)[0]["source"] == "fed_press"


def test_the_best_score_and_impact_anywhere_in_a_cluster_win():
    rows = [row(id=1, source="fed_press", tier=1, score=40.0, impact=20.0),
            row(id=2, source="cnbc", tier=3, score=90.0, impact=85.0,
                score_reason="why")]
    merged = cli.collapse(rows)[0]
    assert merged["score"] == 90.0 and merged["impact"] == 85.0
    assert merged["score_reason"] == "why"


def test_rows_with_no_cluster_key_stay_separate():
    rows = [row(id=1, cluster_key=""), row(id=2, cluster_key="")]
    assert len(cli.collapse(rows)) == 2


# -------------------------------------------------------------------- slim

def test_the_export_drops_empty_fields_but_keeps_a_measured_zero():
    slim = cli._slim(row(score=0.0, impact=0.0, author="", points=0))
    assert slim["score"] == 0.0 and slim["impact"] == 0.0
    assert "author" not in slim and "points" not in slim


def test_long_summaries_are_truncated_with_an_ellipsis():
    slim = cli._slim(row(summary="x" * 400))
    assert len(slim["summary"]) <= cli.SUMMARY_LIMIT + 3
    assert slim["summary"].endswith("...")


def test_bookkeeping_columns_never_reach_the_browser():
    slim = cli._slim(row(profile_hash="abc", scored_at="now", first_seen="then",
                         source_id="x", cluster_key="u:a"))
    assert not {"profile_hash", "scored_at", "first_seen", "source_id"} & set(slim)


def test_each_record_is_written_on_its_own_line_so_the_daily_diff_is_readable(tmp_path):
    out = tmp_path / "items.json"
    cli._write_json(out, {"generated_at": "x", "items": [{"a": 1}, {"a": 2}]}, "items")
    text = out.read_text()
    assert json.loads(text)["items"] == [{"a": 1}, {"a": 2}]
    assert text.count("\n") >= 3


def test_an_empty_export_is_still_valid_json(tmp_path):
    out = tmp_path / "items.json"
    cli._write_json(out, {"generated_at": "x", "items": []}, "items")
    assert json.loads(out.read_text())["items"] == []


# --------------------------------------------------------------- pipeline

@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "pipeline.db"
    db.init_db(path)
    now = datetime.now(timezone.utc)
    db.upsert_items(path, [
        Item(source="fed_press", source_id="1", tier=1, published=now,
             title="Federal Reserve issues FOMC statement",
             url="https://federalreserve.gov/a"),
        Item(source="cnbc_economy", source_id="2", tier=2, published=now,
             title="Fed cuts rates by 25 basis points",
             url="https://federalreserve.gov/a"),      # same story, same URL
        Item(source="marketwatch", source_id="3", tier=3, published=now,
             title="10 best stocks to buy now", url="https://mw.com/x"),
        Item(source="ft", source_id="4", tier=2, published=now,
             title="The race to save Florida's orange industry",
             url="https://ft.com/oranges"),
    ])
    # Two years of a daily series, so the metric maths has something to chew on.
    start = date(2024, 9, 1)
    db.upsert_observations(path, [
        Observation("ust_10y", date.fromordinal(start.toordinal() + i),
                    4.0 + (i % 50) / 100.0)
        for i in range(700)])
    db.upsert_events(path, generate(date.today(), months=2))
    return path


def args(**kw):
    base = dict(db=None, llm=False, sort="score", days=10, no_collapse=False,
                provider="gemini", model=None, profile="missing.md", limit=0,
                batch_size=40, min_interval=0, window_days=7, rescore_all=False)
    return SimpleNamespace(**{**base, **kw})


def test_rank_then_export_produces_both_payloads_with_no_network(store, tmp_path, capsys):
    cli._cmd_rank(args(db=str(store)))
    cli._cmd_brief(args(db=str(store)))
    out_dir = tmp_path / "out"
    cli._cmd_export(args(db=str(store), out_dir=str(out_dir)))

    items = json.loads((out_dir / "items.json").read_text())
    market = json.loads((out_dir / "market.json").read_text())

    # The duplicate collapsed, and the primary source is the one shown.
    titles = [i["title"] for i in items["items"]]
    assert len(titles) == 3
    statement = next(i for i in items["items"] if i["source"] == "fed_press")
    assert statement["also"][0]["source"] == "cnbc_economy"

    # The stock-tip listicle and the off-topic feature rank below the statement.
    by_title = {i["title"]: i for i in items["items"]}
    assert by_title["10 best stocks to buy now"]["score"] < statement["score"]
    assert by_title["The race to save Florida's orange industry"]["score"] \
        < statement["score"]

    # Every taxonomy the page needs to render its filters ships with the data.
    assert items["categories"] and items["horizons"] and items["assets"]
    assert market["regime"]["reads"] and market["families"]
    assert any(m["id"] == "ust_10y" for m in market["metrics"])
    assert market["calendar"] and market["brief"]["lede"]


def test_the_export_carries_the_why_text_the_page_renders(store, tmp_path):
    cli._cmd_rank(args(db=str(store)))
    out_dir = tmp_path / "out"
    cli._cmd_export(args(db=str(store), out_dir=str(out_dir)))
    market = json.loads((out_dir / "market.json").read_text())
    metric = next(m for m in market["metrics"] if m["id"] == "ust_10y")
    assert metric["why"] and metric["up_means"] and metric["down_means"]
    assert metric["watch"] and metric["spark"]
    for read in market["regime"]["reads"]:
        assert read["why"] and read["means"]


def test_a_calendar_entry_says_whether_its_date_is_confirmed(store, tmp_path):
    db.upsert_events(store, [CalEvent(
        event_id="fomc-x", on=date.today() + timedelta(days=5), title="FOMC decision",
        kind="decision", importance=1, estimated=False, source="federalreserve.gov")])
    out_dir = tmp_path / "out"
    cli._cmd_rank(args(db=str(store)))
    cli._cmd_export(args(db=str(store), out_dir=str(out_dir)))
    market = json.loads((out_dir / "market.json").read_text())
    fomc = next(e for e in market["calendar"] if e["title"] == "FOMC decision")
    assert fomc["estimated"] == 0
    assert any(e["estimated"] == 1 for e in market["calendar"])


def test_every_feed_declares_a_tier_and_a_known_category_hint():
    from finance.categorize import CATEGORIES
    feeds = cli.load_feeds()
    assert len(feeds) > 20
    assert all(f.get("tier") in (1, 2, 3) for f in feeds)
    assert all(f["hint"] in CATEGORIES for f in feeds if f.get("hint"))
    assert len({f["name"] for f in feeds}) == len(feeds)


def test_one_fred_request_per_series_even_when_two_indicators_share_it():
    mapping = cli.fred_series_map()
    assert mapping["PCEPILFE"] == ["core_pce", "core_pce_3m"]
    assert len(mapping) < sum(len(v) for v in mapping.values())
