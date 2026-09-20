import pytest

from finance.categorize import CATEGORIES, CATEGORY_ORDER, categorize, horizon


def item(title, summary="", tags=None, tier=3, category=""):
    return {"title": title, "summary": summary, "tags": tags or [],
            "tier": tier, "category": category}


def test_every_category_except_the_fallback_is_in_the_priority_order():
    assert set(CATEGORY_ORDER) | {"other"} == set(CATEGORIES)
    assert "other" not in CATEGORY_ORDER


@pytest.mark.parametrize("title,expected", [
    ("Fed holds rates steady, Powell signals patience", "monetary_policy"),
    ("CPI rises 0.3% in August as shelter costs stay firm", "inflation"),
    ("Initial jobless claims fall to 196,000", "labor"),
    ("White House announces 25% tariffs on imported semiconductors", "fiscal"),
    ("A primer on how to read the yield curve", "frameworks"),
    ("Nvidia guides above estimates as data center capex accelerates", "tech_capex"),
    ("Moody's downgrades regional bank on CRE loan losses", "credit"),
    ("Stocks close lower as yields climb after a weak 30-year auction", "rates"),
    ("Brent crude jumps after a vessel is struck in the Strait of Hormuz", "geopolitics"),
    ("Bitcoin slides below $80,000", "crypto"),
])
def test_headlines_land_in_the_expected_bucket(title, expected):
    assert categorize(item(title)) == expected


def test_clo_does_not_match_the_word_close():
    # "clo\\w*" used to file every market wrap under credit.
    assert categorize(item("Stocks close lower")) == "equities"
    assert categorize(item("CLO issuance hits a record")) == "credit"


def test_a_primary_source_hint_loses_to_a_more_specific_keyword_match():
    # A Fed feed item that is really about tariffs files under fiscal, because
    # fiscal outranks nothing here - monetary_policy is first, so this checks
    # the reverse: the hint cannot demote a higher-priority match.
    assert categorize(item("Tariff effects on prices"), {"x": "inflation"}) == "fiscal"


def test_source_hint_applies_when_nothing_matches():
    assert categorize(item("Quarterly update"), {"calculatedrisk": "housing"}) == "other"
    assert categorize({"source": "calculatedrisk", "title": "Quarterly update",
                       "summary": "", "tags": []}, {"calculatedrisk": "housing"}) == "housing"


def test_structural_language_beats_price_action_language():
    assert horizon(item("Stocks fell after the White House imposed tariffs")) == "months"


def test_price_action_is_day_unless_it_is_a_setup():
    assert horizon(item("Bitcoin slides below $80,000")) == "day"
    assert horizon(item("Stocks slip ahead of next week's CPI")) == "week"


def test_an_off_topic_item_is_never_filed_as_durable():
    # Several feeds carry a publication's whole front page, and the structural
    # vocabulary is not finance-specific.
    assert horizon(item("Wine has changed over five decades"), "other") == "week"
    assert horizon(item("A grove ravaged for decades"), category="other") == "week"


def test_a_primary_source_defaults_to_the_longest_horizon():
    assert horizon(item("Statement on longer-run goals", tier=1,
                        category="monetary_policy")) == "months"


def test_an_index_rebalance_is_a_flow_event_not_a_portfolio_explainer():
    assert categorize(item("Nasdaq 100 weight to jump in quarterly rebalance")) \
        == "equities"
    assert categorize(item("How to think about rebalancing your portfolio")) \
        == "frameworks"


def test_teaching_material_is_recognised_by_its_shape_not_its_subject():
    for title in ("A primer on the yield curve",
                  "What history says about rate-cutting cycles",
                  "Asset allocation for a 30-year horizon",
                  "Anatomy of a credit crunch"):
        assert categorize(item(title)) == "frameworks", title
