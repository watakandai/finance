from datetime import date, datetime, timezone

import pytest

from finance import db
from finance.models import CalEvent, Item, Observation


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


def item(**kw):
    base = dict(source="wsj", source_id="a", title="Fed holds rates steady",
                url="https://wsj.com/a")
    return Item(**{**base, **kw})


def test_init_is_idempotent_and_migrates_an_older_database(store):
    db.init_db(store)  # running twice must not raise
    with db.connect(store) as conn:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(items)")}
    assert {"impact", "horizon", "assets", "tier"} <= columns


def test_crowd_counts_merge_with_max_so_a_peak_is_never_erased(store):
    db.upsert_items(store, [item(points=500, comments=90)])
    db.upsert_items(store, [item(points=10, comments=2)])
    row = db.row_to_dict(db.query_items(store)[0])
    assert (row["points"], row["comments"]) == (500, 90)


def test_upsert_stores_the_canonical_url_and_cluster_key(store):
    db.upsert_items(store, [item(url="https://www.wsj.com/a?utm_source=x")])
    row = db.row_to_dict(db.query_items(store)[0])
    assert row["canonical"] == "https://wsj.com/a"
    assert row["cluster_key"] == "u:https://wsj.com/a"


def test_json_columns_come_back_as_lists_even_when_never_written(store):
    db.upsert_items(store, [item(tags=["a", "b"])])
    row = db.row_to_dict(db.query_items(store)[0])
    assert row["tags"] == ["a", "b"] and row["assets"] == []


def test_observations_overwrite_because_agencies_revise(store):
    db.upsert_observations(store, [Observation("payrolls", date(2026, 8, 1), 22.0)])
    db.upsert_observations(store, [Observation("payrolls", date(2026, 8, 1), 79.0)])
    assert db.series_values(store, "payrolls") == [(date(2026, 8, 1), 79.0)]


def test_series_values_come_back_oldest_first(store):
    db.upsert_observations(store, [
        Observation("x", date(2026, 3, 1), 2.0), Observation("x", date(2026, 1, 1), 1.0)])
    assert [v for _, v in db.series_values(store, "x")] == [1.0, 2.0]


def event(**kw):
    base = dict(event_id="cpi-2026-10-13", on=date(2026, 10, 13), title="CPI",
                kind="release", importance=1)
    return CalEvent(**{**base, **kw})


def test_a_confirmed_date_wins_and_an_estimated_one_never_overwrites_it(store):
    db.upsert_events(store, [event(estimated=True)])
    db.upsert_events(store, [event(on=date(2026, 10, 14), title="CPI confirmed",
                                   estimated=False)])
    db.upsert_events(store, [event(estimated=True)])  # the daily rules run again
    stored = db.query_events(store)
    assert len(stored) == 1
    assert stored[0]["on_date"] == "2026-10-14" and stored[0]["estimated"] == 0


def test_events_are_filtered_by_window_and_importance(store):
    db.upsert_events(store, [
        event(event_id="a", on=date(2026, 10, 1), importance=1),
        event(event_id="b", on=date(2026, 11, 1), importance=3)])
    assert len(db.query_events(store, start="2026-10-15")) == 1
    assert len(db.query_events(store, max_importance=2)) == 1


def test_a_heuristic_score_never_overwrites_the_models(store):
    db.upsert_items(store, [item()])
    row_id = db.query_items(store)[0]["id"]
    db.set_llm_results(store, {row_id: {"score": 90.0, "reason": "r", "category": "rates",
                                        "horizon": "months", "assets": ["duration"]}},
                       "gemini:m", "hash1")
    assert db.set_heuristic_scores(store, {row_id: (10.0, "cheap")}) == 0
    row = db.row_to_dict(db.query_items(store)[0])
    assert row["score"] == 90.0 and row["assets"] == ["duration"]


def test_a_keyword_category_never_overwrites_the_models(store):
    db.upsert_items(store, [item()])
    row_id = db.query_items(store)[0]["id"]
    db.set_llm_results(store, {row_id: {"score": 90.0, "reason": "r",
                                        "category": "rates", "horizon": "", "assets": []}},
                       "gemini:m", "hash1")
    assert db.set_categories(store, {row_id: "equities"}) == 0


def test_re_filing_a_keyword_category_is_a_no_op_until_the_taxonomy_changes(store):
    db.upsert_items(store, [item()])
    row_id = db.query_items(store)[0]["id"]
    assert db.set_categories(store, {row_id: "rates"}) == 1
    assert db.set_categories(store, {row_id: "rates"}) == 0
    assert db.set_categories(store, {row_id: "credit"}) == 1


def test_unscored_items_skips_what_this_profile_already_paid_for(store):
    db.upsert_items(store, [item(source_id="a"), item(source_id="b")])
    first = db.query_items(store)[0]["id"]
    db.set_llm_results(store, {first: {"score": 1.0, "reason": "", "category": "",
                                       "horizon": "", "assets": []}}, "m", "hash1")
    assert len(db.unscored_items(store, "hash1")) == 1
    # Editing profile.md changes the hash, which re-scores the backlog once.
    assert len(db.unscored_items(store, "hash2")) == 2


def test_prune_drops_old_news_but_never_the_series_history(store):
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.upsert_items(store, [item(published=old)])
    db.upsert_observations(store, [Observation("x", date(2020, 1, 1), 1.0)])
    assert db.prune(store, days=45) == 1
    assert db.count_items(store) == 0
    assert db.count_observations(store) == 1


def test_state_round_trips_and_falls_back_cleanly(store):
    db.set_state(store, "brief", {"lede": "x"})
    assert db.get_state(store, "brief") == {"lede": "x"}
    assert db.get_state(store, "missing", default={}) == {}
