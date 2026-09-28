"""The beginner layer: plain labels, real numbers, and no jargon leaks."""
import pytest

from finance import plain, regime
from finance.calendar_rules import RULES
from finance.plain import READS, event_plain


def m(series_id, value, **kw):
    return {series_id: {"id": series_id, "label": series_id, "value": value, "unit": "",
                        "decimals": 2, "as_of": "2026-09-26", "changes": kw.pop("changes", {}),
                        "family": "x", "tier": 1, **kw}}


def summaries():
    out = {}
    for d in (m("core_pce", 3.3), m("core_pce_3m", 3.2), m("fed_funds", 3.88),
              m("ust_2y", 4.6), m("ust_10y", 5.18, changes={"1m": 0.54}, pct_rank=97),
              m("mortgage_30y", 7.03), m("hy_spread", 2.8, pct_rank=12),
              m("unemployment", 4.1), m("payrolls", 162), m("claims", 202),
              m("vix", 14.2), m("spx", 7600, vs_ma200=5.2)):
        out.update(d)
    return out


@pytest.fixture
def assessed():
    return regime.assess(summaries(), {}, {})


def test_every_read_gets_a_plain_label_stance_and_explanation(assessed):
    for read in assessed["reads"]:
        p = read["plain"]
        assert p["label"] and p["what"] and p["why_you"] and p["now"]
        assert p["stance"] in plain.STANCE.values()


def test_numbers_are_anchored_to_something_a_beginner_can_hold(assessed):
    by_id = {r["id"]: r["plain"]["now"] for r in assessed["reads"]}
    assert "3.3% a year, against the Fed's goal of 2%" in by_id["inflation"]
    assert "up from about 4.64% a month ago" in by_id["rates"]
    assert "near the highest of the last five years" in by_id["rates"]
    assert "162,000 jobs" in by_id["growth"]


def test_the_expert_vocabulary_does_not_leak_into_the_plain_text(assessed):
    text = " ".join(r["plain"]["now"] + r["plain"]["what"] for r in assessed["reads"])
    for jargon in ("real policy rate", "OAS", "pp", "bear steepening", "restrictive",
                   "Sahm gap", "tailwind", "headwind"):
        assert jargon not in text, jargon


def test_the_summary_keeps_proper_nouns_capitalised(assessed):
    lede = assessed["plain"]["lede"]
    assert "the Fed" in lede and "the fed" not in lede


def test_every_tension_has_a_plain_translation():
    assert set(plain.TENSIONS) == set(regime.TENSIONS)
    for key in regime.TENSIONS:
        out = regime.assess({}, {}, {})
        out["tension_key"] = key
        assert plain.annotate(out, {})["plain"]["tension"] == plain.TENSIONS[key]


def test_every_calendar_rule_has_a_plain_title_and_explanation():
    for rule in RULES:
        info = event_plain(f"{rule['id']}-2026-10-13")
        assert info.get("title") and info.get("what"), rule["id"]


def test_fed_event_prefixes_resolve_to_the_right_description():
    assert event_plain("fomc-2026-10-28")["title"] == "Fed interest-rate decision"
    assert event_plain("fomc-minutes-2026-11-18")["title"] == "Fed meeting notes"
    assert event_plain("fomc-beige-2026-10-14")["title"].startswith("Fed's economy survey")
    assert event_plain("nonsense-2026-01-01") == {}


def test_missing_data_says_so_rather_than_printing_none():
    out = regime.assess({}, {}, {})
    for read in out["reads"]:
        assert "None" not in read["plain"]["now"]
