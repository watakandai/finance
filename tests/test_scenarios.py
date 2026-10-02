"""Scenarios, knock-on chains, and the prediction log."""
from datetime import date, timedelta

from finance import scenarios as sc

TODAY = date(2026, 10, 1)


def summaries(**values):
    """{id: summary} from keyword args: value, or (value, {changes}), or (value, changes, as_of)."""
    out = {}
    for key, v in values.items():
        if isinstance(v, tuple):
            value, changes = v[0], v[1]
            as_of = v[2] if len(v) > 2 else "2026-09-01"
        else:
            value, changes, as_of = v, {}, "2026-09-01"
        out[key] = {"id": key, "label": key, "value": value, "changes": changes,
                    "unit": "%", "as_of": as_of, "change_kind": "abs"}
    return out


GOLDILOCKS = summaries(core_pce_3m=2.1, payrolls=160, claims=210, gdp_now=2.2, hy_spread=3.0,
                       breakeven_10y=2.3, wti=(70, {"3m": -5}), unemployment=(4.0, {"3m": 0.0}),
                       sentiment=70)


def test_signposts_compare_against_today_and_show_the_value():
    check = sc.check_signpost(GOLDILOCKS, ("core_pce_3m", "value", "<", 2.6, "x"))
    assert check["met"] is True and check["value"] == 2.1
    missing = sc.check_signpost({}, ("core_pce_3m", "value", "<", 2.6, "x"))
    assert missing["met"] is None


def test_goldilocks_data_leans_soft_landing():
    evaluated = sc.evaluate(GOLDILOCKS)
    assert evaluated[0]["id"] == "soft_landing"
    assert evaluated[0]["met"] == evaluated[0]["known"] == 5
    assert "Soft landing" in sc.lean_sentence(evaluated)


def test_stagflation_data_leans_stagflation():
    data = summaries(core_pce_3m=3.6, gdp_now=0.4, unemployment=(4.6, {"3m": 0.4}),
                     wti=(110, {"3m": 30}), sentiment=50, payrolls=40, claims=240,
                     hy_spread=4.0, breakeven_10y=2.4)
    assert sc.evaluate(data)[0]["id"] == "stagflation"


def test_a_tie_is_called_a_tie():
    evaluated = [{"id": "soft_landing", "title": "Soft landing", "met": 4, "known": 5, "share": 0.8},
                 {"id": "running_hot", "title": "Running hot", "met": 4, "known": 5, "share": 0.8}]
    text = sc.lean_sentence(evaluated)
    assert "equally" in text and "inflation readings decide" in text


def test_chains_switch_on_from_data():
    data = summaries(wti=(96, {"3m": 29}), ust_10y=5.2)
    regime = {"reads": [{"id": "policy", "score": -1}, {"id": "rates", "score": -2}]}
    active = {a["id"]: a for a in sc.active_chains(data, regime, [])}
    assert "oil_shock" in active and "rates_high" in active
    assert "29%" in active["oil_shock"]["why_now"][0]


def test_chains_switch_on_from_news_only_with_several_stories():
    items = [{"title": f"New tariffs hit imports {i}", "impact": 30} for i in range(3)]
    assert any(a["id"] == "tariffs" for a in sc.active_chains({}, {}, items))
    assert not any(a["id"] == "tariffs" for a in sc.active_chains({}, {}, items[:2]))
    weak = [{"title": f"tariff note {i}", "impact": 5} for i in range(5)]
    assert not any(a["id"] == "tariffs" for a in sc.active_chains({}, {}, weak))


def test_every_chain_has_a_testable_claim_on_a_tracked_series():
    from finance.indicators import BY_ID
    for chain in sc.CHAINS:
        metric, field, direction, days, claim = chain["test"]
        assert metric in BY_ID, chain["id"]
        assert direction in ("up", "down") and 30 <= days <= 180 and claim


def test_a_prediction_is_scored_only_on_newer_data():
    data = summaries(ppi=(2.0, {}, "2026-09-01"))
    h = sc.make_hypothesis("PPI higher", "ppi", "value", "up", 30, data, "rule", TODAY, "tariffs")
    assert h["due_on"] == (TODAY + timedelta(days=30)).isoformat()
    due = TODAY + timedelta(days=31)
    # Due, but the series has not printed since: still open.
    same = sc.resolve([h], data, due)[0]
    assert same["status"] == "open"
    # A newer, higher reading: it came true.
    newer = summaries(ppi=(2.4, {}, "2026-10-15"))
    assert sc.resolve([h], newer, due)[0]["status"] == "right"
    lower = summaries(ppi=(1.8, {}, "2026-10-15"))
    assert sc.resolve([h], lower, due)[0]["status"] == "wrong"
    # Never any new data, long after the due date: unscored, not "wrong".
    late = due + timedelta(days=60)
    assert sc.resolve([h], data, late)[0]["status"] == "unscored"


def test_open_predictions_show_progress():
    data = summaries(ppi=(2.0, {}, "2026-09-01"))
    h = sc.make_hypothesis("PPI higher", "ppi", "value", "up", 90, data, "rule", TODAY)
    progress = sc.resolve([h], summaries(ppi=(2.2, {}, "2026-10-15")), TODAY + timedelta(days=20))[0]
    assert progress["status"] == "open" and progress["so_far"] == "on track"


def test_a_chain_does_not_repeat_its_prediction_while_one_is_recent():
    data = summaries(wti=(96, {"3m": 29}), headline_cpi=3.3)
    active = [{"id": "oil_shock"}]
    first = sc.chain_hypotheses(active, data, [], TODAY)
    assert len(first) == 1
    again = sc.chain_hypotheses(active, data, first, TODAY + timedelta(days=5))
    assert again == []
    later = sc.chain_hypotheses(active, data, first, TODAY + timedelta(days=40))
    assert len(later) == 1


def test_scorecard_and_lean_history():
    hyps = [{"status": "right", "source": "rule"}, {"status": "wrong", "source": "model"},
            {"status": "open", "source": "rule"}]
    card = sc.scorecard(hyps)
    assert card == {"scored": 2, "right": 1, "open": 1,
                    "by_source": {"rule": {"right": 1, "wrong": 0}, "model": {"right": 0, "wrong": 1}}}
    evaluated = sc.evaluate(GOLDILOCKS)
    history = sc.record_lean([], evaluated, TODAY)
    history = sc.record_lean(history, evaluated, TODAY)   # same day replaces
    assert len(history) == 1 and history[0]["shares"]["soft_landing"] == 1.0


def test_build_carries_state_forward():
    data = summaries(wti=(96, {"3m": 29}), headline_cpi=3.3, **{
        k: v for k, v in GOLDILOCKS.items() if k != "wti"})
    out = sc.build(data, {"reads": []}, [], {}, TODAY)
    assert out["scenarios"] and out["active"]
    assert out["hypotheses"][0]["origin"] == "oil_shock"
    assert {c["id"] for c in out["library"]}.isdisjoint({a["id"] for a in out["active"]})
