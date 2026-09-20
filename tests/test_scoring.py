"""Impact, popularity and the heuristic relevance ranker."""
from datetime import datetime, timezone

import pytest

from finance.impact import freshness, impact_scores, score_row
from finance.popularity import percentile_ranks, popularity_scores, propagate
from finance.rank import CATEGORY_WEIGHT, heuristic_scores

NOW = datetime(2026, 9, 19, 18, tzinfo=timezone.utc)


def row(**kw):
    base = dict(id=1, source="wsj_markets", title="Markets update", summary="",
                tier=3, category="equities", published_ts="2026-09-19T17:00:00+00:00",
                cluster_key="u:a")
    return {**base, **kw}


def impact_of(**kw):
    r = row(**kw)
    return score_row(r, {r["source"]}, kw.get("horizon", "week"), NOW,
                     r.get("category", ""))[0]


# --------------------------------------------------------------------- impact

def test_a_primary_source_outranks_commentary_about_it():
    statement = impact_of(source="fed_press", tier=1,
                          title="Federal Reserve issues FOMC statement",
                          category="monetary_policy")
    writeup = impact_of(source="marketwatch", tier=3,
                        title="What the Fed statement means for your mortgage",
                        category="monetary_policy")
    assert statement > writeup


def test_a_decision_with_a_price_attached_beats_a_topic_mention():
    decision = impact_of(title="Fed cuts rates by 25 basis points",
                         category="monetary_policy")
    topic = impact_of(title="A look at the Fed's thinking on rates",
                      category="monetary_policy")
    assert decision > topic + 15


def test_routine_institutional_notices_do_not_ride_the_primary_source_bonus():
    # The same feed publishes the FOMC statement and a supervisory notice about
    # one small bank; nothing but the wording can tell them apart.
    notice = impact_of(source="fed_press", tier=1, category="monetary_policy",
                       title="Federal Reserve Board issues enforcement actions "
                             "with former bank employees")
    statement = impact_of(source="fed_press", tier=1, category="monetary_policy",
                          title="Federal Reserve issues FOMC statement")
    assert notice < statement - 25


@pytest.mark.parametrize("title", [
    "Federal Reserve Board announces termination of enforcement action with X",
    "Agencies seek comment on proposed third-party risk management guidance",
    "Federal Reserve Board requests comment on a proposal to modify Regulation D",
    "Joint Readout of Principals' Meeting",
])
def test_the_admin_filter_catches_the_shapes_these_feeds_actually_publish(title):
    assert impact_of(source="fed_press", tier=1, title=title,
                     category="monetary_policy") < 35


def test_an_off_topic_front_page_story_is_penalised_whatever_outlet_ran_it():
    # Several feeds carry a publication's entire front page.
    finance = impact_of(tier=2, category="inflation", title="Core CPI cools to 2.4%")
    citrus = impact_of(tier=2, category="other",
                       title="The race to save Florida's orange industry")
    assert citrus < finance - 25


def test_low_information_formats_are_pushed_off_the_page():
    assert impact_of(title="10 best stocks to buy now") == 0.0
    assert impact_of(source="reddit", tier=4, title="Rate my portfolio - 24yo") == 0.0


def test_agreement_across_outlets_raises_impact_but_is_capped():
    rows = [row(id=i, source=f"outlet{i}", cluster_key="u:same",
                title="White House imposes tariffs on imported chips")
            for i in range(1, 7)]
    scored = impact_scores(rows, {i: "months" for i in range(1, 7)}, NOW)
    alone = impact_of(title="White House imposes tariffs on imported chips",
                      horizon="months")
    together = scored[1][0]
    assert together > alone
    assert together - alone <= 18


def test_decay_is_slow_for_structural_items_and_fast_for_tape():
    assert freshness(24, "day") < freshness(24, "week") < freshness(24, "months")
    # A tariff regime from last month still explains why a sector is repricing.
    assert freshness(720, "months") >= 0.45
    assert freshness(72, "day") < 0.05


def test_impact_scores_returns_the_horizon_it_scored_with():
    rows = [row(id=1)]
    assert impact_scores(rows, {1: "months"}, NOW)[1][2] == "months"


# ----------------------------------------------------------------- popularity

def test_percentile_ranks_give_ties_the_midpoint_of_their_span():
    assert percentile_ranks([5, 5, 5, 5]) == [0.5, 0.5, 0.5, 0.5]
    assert percentile_ranks([1, 2, 3]) == [0.0, 0.5, 1.0]


def test_popularity_is_relative_to_a_sources_own_distribution():
    rows = [{"id": i, "source": "reddit", "metric": "upvotes", "points": p,
             "comments": 0, "cluster_key": f"u:{i}"}
            for i, p in enumerate([10, 50, 200, 1200, 3000], 1)]
    scores = popularity_scores(rows)
    assert scores[1][0] < scores[3][0] < scores[5][0]


def test_a_source_with_no_vote_count_gets_no_number_rather_than_a_zero():
    rows = [{"id": 1, "source": "wsj", "metric": "", "points": 0, "comments": 0,
             "cluster_key": "u:a"}]
    assert popularity_scores(rows) == {}


def test_attention_propagates_to_the_publishers_own_copy():
    rows = [{"id": 1, "source": "reddit", "metric": "upvotes", "points": 900,
             "comments": 0, "cluster_key": "u:same"},
            {"id": 2, "source": "wsj", "metric": "", "points": 0, "comments": 0,
             "cluster_key": "u:same"}]
    scores = propagate(rows, popularity_scores(rows))
    assert scores[2][0] == scores[1][0]
    assert "via reddit" in scores[2][1]


# ------------------------------------------------------- heuristic relevance

def test_every_category_carries_a_weight():
    from finance.categorize import CATEGORIES
    assert set(CATEGORIES) <= set(CATEGORY_WEIGHT)


def test_relevance_prefers_the_durable_item_over_the_bigger_headline():
    structural = row(id=1, impact=55, category="fiscal", horizon="months",
                     title="Tariffs imposed on imported chips")
    tape = row(id=2, impact=55, category="equities", horizon="day",
               title="Stocks close lower")
    scores = heuristic_scores([structural, tape], NOW)
    assert scores[1][0] > scores[2][0] + 10


def test_an_unscored_item_starts_from_a_neutral_prior_not_from_zero():
    scores = heuristic_scores([row(id=1, impact=None, category="rates")], NOW)
    assert 15 < scores[1][0] < 60


def test_an_off_topic_item_can_never_reach_the_top_of_the_list():
    off = heuristic_scores([row(id=1, impact=60, category="other")], NOW)[1][0]
    on = heuristic_scores([row(id=1, impact=60, category="inflation")], NOW)[1][0]
    assert off < on - 25


def test_scores_stay_inside_the_advertised_range():
    extremes = [row(id=1, impact=100, category="monetary_policy", horizon="months"),
                row(id=2, impact=0, category="other", horizon="day",
                    title="10 best stocks to buy now")]
    for score, _ in heuristic_scores(extremes, NOW).values():
        assert 0.0 <= score <= 100.0
