"""The ranker's and brief's LLM paths, against a stub provider.

No network and no key: `PROVIDERS` is patched with a callable of the same
signature, which is the whole reason that table exists.
"""
import json

import pytest

from finance import brief as briefing
from finance import rank
from finance.rank import ProviderError, llm_scores, parse_results, profile_hash, \
    strip_comments, market_context


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def stub(replies, calls=None):
    """A provider that returns each reply in turn, recording the prompts."""
    sequence = list(replies)

    def call(prompt, model, api_key, timeout):
        if calls is not None:
            calls.append(prompt)
        reply = sequence.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    return call


def install(monkeypatch, call):
    monkeypatch.setitem(rank.PROVIDERS, "gemini", ("GEMINI_API_KEY", "stub-model", call))


def rows(n):
    return [{"id": i, "title": f"Item {i}", "source": "wsj", "tier": 2,
             "impact": 50, "summary": "", "url": "https://x/%d" % i, "tags": []}
            for i in range(1, n + 1)]


def reply_for(count, start=1, score=80):
    return json.dumps([
        {"i": i, "score": score, "category": "rates", "horizon": "months",
         "assets": ["duration"], "reason": "raises the discount rate"}
        for i in range(start, start + count)])


# ---------------------------------------------------------------- parsing

def test_a_fenced_reply_with_prose_around_it_still_parses():
    text = "Sure!\n```json\n" + reply_for(1) + "\n```\nHope that helps."
    assert parse_results(text, 1)[1]["score"] == 80.0


def test_invented_categories_assets_and_horizons_are_dropped_not_stored():
    text = json.dumps([{"i": 1, "score": 50, "category": "vibes",
                        "horizon": "forever", "assets": ["duration", "moon"],
                        "reason": "x"}])
    out = parse_results(text, 1)[1]
    assert out["category"] == "" and out["horizon"] == ""
    assert out["assets"] == ["duration"]


def test_out_of_range_indices_and_malformed_entries_are_skipped():
    text = json.dumps([{"i": 9, "score": 50}, {"i": 1}, {"i": 2, "score": 60}])
    assert set(parse_results(text, 3)) == {2}


def test_scores_are_clamped_to_the_advertised_range():
    text = json.dumps([{"i": 1, "score": 900}, {"i": 2, "score": -5}])
    parsed = parse_results(text, 2)
    assert parsed[1]["score"] == 100.0 and parsed[2]["score"] == 0.0


def test_a_reply_with_no_json_array_is_an_error_not_a_silent_empty():
    with pytest.raises(ValueError, match="no JSON array"):
        parse_results("I cannot help with that.", 1)


def test_asset_tags_are_capped_at_three():
    text = json.dumps([{"i": 1, "score": 50,
                        "assets": ["duration", "equities", "credit", "gold"]}])
    assert len(parse_results(text, 1)[1]["assets"]) == 3


# ------------------------------------------------------------------ prompt

def test_html_comments_never_reach_the_model():
    profile = "I hold equities.\n<!-- TODO: ask about bonds -->\nAnd cash."
    assert "TODO" not in strip_comments(profile)


def test_the_profile_hash_covers_the_model_and_every_taxonomy():
    base = profile_hash("p", "m")
    assert base != profile_hash("p2", "m")
    assert base != profile_hash("p", "m2")
    assert len(base) == 16


def test_market_context_gives_the_model_what_is_already_true():
    summaries = {"core_pce": {"label": "Core PCE", "value": 3.3, "unit": "% y/y",
                              "tier": 1, "changes": {"1m": -0.1}}}
    regime = {"reads": [{"label": "Inflation", "state": "sticky above target"}]}
    text = market_context(summaries, regime)
    assert "sticky above target" in text and "Core PCE: 3.3% y/y" in text


def test_the_prompt_carries_the_profile_the_context_and_the_rubric(monkeypatch, key):
    calls = []
    install(monkeypatch, stub([reply_for(2)], calls))
    llm_scores(rows(2), "I hold index funds", context="Inflation: sticky")
    prompt = calls[0]
    assert "I hold index funds" in prompt and "Inflation: sticky" in prompt
    assert "never tell them to buy, sell, hold" in prompt
    assert "Item 1" in prompt and "Item 2" in prompt


# ------------------------------------------------------------------ batching

def test_items_are_sent_in_batches_and_results_map_back_to_row_ids(monkeypatch, key):
    calls = []
    install(monkeypatch, stub([reply_for(2), reply_for(2)], calls))
    out = llm_scores(rows(4), "p", batch_size=2)
    assert len(calls) == 2
    assert set(out) == {1, 2, 3, 4}


def test_one_failed_batch_does_not_lose_the_others(monkeypatch, key):
    notes = []
    install(monkeypatch, stub([ValueError("bad json"), reply_for(2)]))
    out = llm_scores(rows(4), "p", batch_size=2,
                     on_progress=lambda o, n, note: notes.append(note))
    assert set(out) == {3, 4}
    assert any("FAILED" in n for n in notes)


def test_a_per_minute_rate_limit_is_waited_out_and_retried(monkeypatch, key):
    waits = []
    install(monkeypatch, stub([ProviderError("429", status=429, retry_after=7),
                               reply_for(2)]))
    out = llm_scores(rows(2), "p", batch_size=2, sleep=waits.append)
    assert set(out) == {1, 2}
    assert waits == [7]


def test_an_exhausted_daily_quota_stops_the_run_instead_of_burning_it(monkeypatch, key):
    notes = []
    install(monkeypatch, stub([ProviderError("quota", status=429, daily=True)]))
    out = llm_scores(rows(6), "p", batch_size=2, sleep=lambda s: None,
                     on_progress=lambda o, n, note: notes.append(note))
    assert out == {}
    assert sum("skipped (rate limited)" in n for n in notes) == 2


def test_batches_are_spaced_out_to_stay_under_a_per_minute_limit(monkeypatch, key):
    # A clock that advances one second per read: the first batch sets the
    # marker at 0, the second is asked for at 1, so it must wait the remaining 7
    # of an 8-second interval rather than the full 8.
    waits, ticks = [], iter(range(10))
    install(monkeypatch, stub([reply_for(1), reply_for(1)]))
    llm_scores(rows(2), "p", batch_size=1, min_interval=8,
               sleep=waits.append, clock=lambda: next(ticks))
    assert waits == [pytest.approx(7)]


def test_an_unknown_provider_or_a_missing_key_fails_loudly(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="unknown provider"):
        llm_scores(rows(1), "p", provider="nope")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm_scores(rows(1), "p", provider="gemini")


# ------------------------------------------------------------------- brief

def test_the_brief_parses_and_bounds_what_the_model_returned():
    text = json.dumps({"lede": "A. B.", "tension": "t", "watch_note": "w",
                       "points": [{"label": "Rates", "text": "x"},
                                  {"label": "", "text": ""}]})
    out = briefing.parse_brief(text)
    assert out["lede"] == "A. B." and len(out["points"]) == 1


def test_a_brief_with_no_lede_or_no_points_is_rejected():
    with pytest.raises(ValueError):
        briefing.parse_brief(json.dumps({"points": [{"text": "x"}]}))
    with pytest.raises(ValueError):
        briefing.parse_brief(json.dumps({"lede": "x", "points": []}))


def test_the_computed_brief_needs_no_model_and_never_leads_with_off_topic(monkeypatch):
    regime = {"stance": "balanced", "summary": "inflation sticky.",
              "tension": "t", "reads": [
                  {"id": "inflation", "label": "Inflation", "score": -2,
                   "state": "sticky", "means": "First sentence. Second."}]}
    items = [{"id": 1, "title": "Front page feature", "impact": 90, "category": "other"},
             {"id": 2, "title": "Core CPI cools", "impact": 70, "category": "inflation",
              "score_reason": "changes the Fed path", "url": "http://x"},
             {"id": 3, "title": "Quiet day", "impact": 5, "category": "equities"}]
    out = briefing.heuristic_brief(regime, items, [])
    texts = " | ".join(p["text"] for p in out["points"])
    assert "Front page feature" not in texts   # matched no market subject
    assert "Quiet day" not in texts            # below the impact floor
    assert "Core CPI cools" in texts
    assert out["by"] == "heuristic"


def test_the_computed_brief_drops_a_reason_that_says_nothing():
    regime = {"stance": "balanced", "summary": "s", "tension": "t", "reads": []}
    items = [{"id": 1, "title": "Core CPI cools", "impact": 70, "category": "inflation",
              "score_reason": "baseline coverage"}]
    out = briefing.heuristic_brief(regime, items, [])
    assert out["points"][0]["text"] == "Core CPI cools"


def test_the_watch_list_keeps_only_what_can_move_a_market():
    events = [{"on_date": "2026-10-13", "title": "CPI", "importance": 1,
               "time_et": "08:30", "estimated": 1, "detail": "First. Second."},
              {"on_date": "2026-10-14", "title": "Minor", "importance": 3,
               "estimated": 0, "detail": ""}]
    watch = briefing.watch_list(events)
    assert [w["title"] for w in watch] == ["CPI"]
    assert watch[0]["why"] == "First." and watch[0]["estimated"] is True
