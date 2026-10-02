"""The model's forward reasoning is validated, never trusted."""
import json

import pytest

from finance import analysis, scenarios

METRICS = {"ppi", "core_cpi", "ust_10y"}


def reply(**overrides):
    body = {
        "outlook": "The data leans toward a soft landing; a hot inflation print would change that.",
        "scenarios": {
            "soft_landing": {"from_here": "Inflation keeps cooling.", "tipping_point": "A soft CPI."},
            "made_up": {"from_here": "x"},
        },
        "chains": [{
            "event": "New tariffs on imported parts",
            "first": "Parts cost more.",
            "second": "Automakers' margins shrink.",
            "long_run": "Supply chains move to Mexico.",
            "industries": [{"name": "Automakers", "dir": "-", "how": "Parts cross borders"},
                           {"name": "Bad", "dir": "?", "how": "x"}],
            "goes_right": "Deals are struck.",
            "goes_wrong": "Retaliation spreads.",
            "check": {"metric": "ppi", "direction": "up", "days": 400, "claim": "PPI higher"},
        }],
        "ripples": {"MDB": "Other database vendors face the same AI worry.", "ZZZ": "not listed"},
    }
    body.update(overrides)
    return "Here you go:\n```json\n" + json.dumps(body) + "\n```"


def test_valid_reply_is_parsed_and_cleaned():
    out = analysis.parse_analysis(reply(), METRICS, {"MDB"})
    assert set(out["scenarios"]) == {"soft_landing"}           # unknown id dropped
    chain = out["chains"][0]
    assert [i["name"] for i in chain["industries"]] == ["Automakers"]   # bad direction dropped
    assert chain["check"]["days"] == analysis.CHECK_DAYS[1]    # clamped to 180
    assert set(out["ripples"]) == {"MDB"}                      # only listed stocks


def test_a_check_on_an_untracked_metric_is_removed():
    bad = reply(chains=[{"event": "e", "first": "f", "check": {"metric": "made_up",
                                                               "direction": "up", "days": 60}}])
    assert analysis.parse_analysis(bad, METRICS, set())["chains"][0]["check"] is None


def test_a_chain_that_gives_advice_is_dropped_whole():
    advice = reply(chains=[{"event": "e", "first": "This is a great opportunity for investors.",
                            "second": "s", "long_run": "l"}])
    assert analysis.parse_analysis(advice, METRICS, set())["chains"] == []


def test_no_outlook_is_an_error():
    with pytest.raises(ValueError):
        analysis.parse_analysis(reply(outlook=""), METRICS, set())
    with pytest.raises(ValueError):
        analysis.parse_analysis("no json here", METRICS, set())


def test_prompt_lists_scenarios_signposts_and_allowed_metrics():
    evaluated = scenarios.evaluate({})
    prompt = analysis.build_prompt("profile", "regime", "metrics", "news", evaluated, [], {},
                                   METRICS)
    for sid in scenarios.SCENARIO_IDS:
        assert sid in prompt
    assert "core_cpi, ppi, ust_10y" in prompt
    assert "Never recommend buying" in prompt
