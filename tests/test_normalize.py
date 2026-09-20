from finance.normalize import canonical_url, cluster_key, same_story, title_key


def test_tracking_parameters_are_dropped_but_content_ones_are_kept():
    assert canonical_url("https://www.cnbc.com/2026/09/19/cpi.html?utm_source=x&id=7") \
        == "https://cnbc.com/2026/09/19/cpi.html?id=7"


def test_amp_and_mobile_variants_collapse_onto_the_canonical_article():
    plain = canonical_url("https://www.reuters.com/markets/cpi-report")
    assert canonical_url("https://m.reuters.com/markets/cpi-report/amp/") == plain
    assert canonical_url("http://reuters.com/markets/cpi-report#section-2") == plain


def test_unusable_urls_return_empty_so_callers_fall_back_to_the_title():
    assert canonical_url("") == ""
    assert canonical_url("javascript:void(0)") == ""
    assert canonical_url("mailto:x@y.com") == ""


def test_wire_prefixes_do_not_change_a_headlines_identity():
    assert title_key("UPDATE 2-Fed holds rates steady as inflation cools") \
        == title_key("Fed holds rates steady as inflation cools")


def test_numbers_are_kept_because_the_number_is_often_the_story():
    assert title_key("CPI rises 0.3% in August") != title_key("CPI rises 0.4% in August")


def test_cluster_key_prefers_the_url_and_namespaces_the_two_kinds():
    assert cluster_key("https://ft.com/a", "Whatever").startswith("u:")
    assert cluster_key("", "Fed holds rates steady").startswith("t:")


def test_same_story_needs_containment_and_three_content_words():
    a = {"title": "Fed holds rates steady as inflation cools"}
    b = {"title": "Fed holds rates steady as inflation cools, Powell says"}
    assert same_story(a, b)
    assert not same_story({"title": "Stocks fell"}, {"title": "Stocks fell today"})
