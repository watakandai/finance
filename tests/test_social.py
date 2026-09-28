"""Stocktwits, ApeWisdom (Reddit) and Hacker News mention counting."""
import json
from pathlib import Path

from finance.fetchers.social import count_mentions, parse_apewisdom, parse_stocktwits

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_stocktwits_keeps_trending_order_and_the_why_summary():
    rows = parse_stocktwits(load("stocktwits_trending.json"))
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    assert rows[0]["symbol"] and rows[0]["summary"]
    # ETFs trend too; the list builder is what drops them, not the parser.
    assert {"stock", "etf"} & {r["kind"] for r in rows}


def test_apewisdom_unescapes_names_and_keeps_the_24h_comparison():
    rows = {r["symbol"]: r for r in parse_apewisdom(load("apewisdom.json"))}
    assert "&amp;" not in rows["SPY"]["name"] and "&" in rows["SPY"]["name"]
    assert rows["MU"]["mentions_24h_ago"] is not None


def test_hacker_news_counts_titles_that_actually_name_the_company():
    counts = count_mentions(load("hn_cloudflare.json")["hits"], "Cloudflare")
    assert counts["stories"] >= 1 and counts["points"] > 0
    assert counts["top_url"].startswith("https://news.ycombinator.com/item?id=")
    assert "Cloudflare" in counts["top_title"]


def test_the_word_check_is_case_sensitive_and_whole_word():
    hits = [{"title": "Zoom in on the details", "points": 50, "objectID": "1"},
            {"title": "Unity of purpose in teams", "points": 40, "objectID": "2"},
            {"title": "Datalog compiled to SQL", "points": 30, "objectID": "3"},
            {"title": "Unity 7 released", "points": 20, "objectID": "4"}]
    assert count_mentions(hits, "Zoom")["stories"] == 1        # capital Z matched
    assert count_mentions(hits, "zoom")["stories"] == 0
    assert count_mentions(hits, "Unity")["stories"] == 2        # both capitalised...
    assert count_mentions(hits, "Unity 7")["stories"] == 1      # ...so ambiguous names use a stricter match
    assert count_mentions(hits, "Datadog")["stories"] == 0      # no fuzzy "Datalog"


def test_no_mentions_is_zero_not_an_error():
    counts = count_mentions([], "Cloudflare")
    assert counts["stories"] == counts["points"] == counts["standalone"] == 0
    assert counts["top_url"] == ""


def hit(title, points=10, oid="1"):
    return {"title": title, "points": points, "objectID": oid}


def test_a_name_inside_a_longer_proper_noun_does_not_stand_alone():
    hits = [hit("Paul Graham on LLMs thinking"), hit("IBM Quantum ships a new chip")]
    assert count_mentions(hits, "Graham")["standalone"] == 0
    assert count_mentions(hits, "Quantum")["standalone"] == 0


def test_a_following_surname_is_a_known_gap_left_to_the_thresholds():
    # Only the word BEFORE the name is checked: checking the word after would
    # also reject Title Case headlines like "Nokia Design Archive". So "by
    # Graham Farmelo" counts - and accept_discovered's points and story floors
    # are what keep it out (in live data it had 7 points against a floor of 30).
    counts = count_mentions([hit("Hawking by Graham Farmelo review", points=7)], "Graham")
    assert counts["standalone"] == 1 and counts["standalone_points"] == 7


def test_a_name_at_the_start_or_after_a_lowercase_word_stands_alone():
    hits = [hit("Nokia design archive"), hit("Flipper Zero runs on Garmin watches"),
            hit("Marvell pushes GlobalFoundries to expand")]
    assert count_mentions(hits, "Nokia")["standalone"] == 1
    assert count_mentions(hits, "Garmin")["standalone"] == 1
    assert count_mentions(hits, "GlobalFoundries")["standalone"] == 1


def test_lower_case_uses_reveal_a_name_that_is_mostly_a_word():
    hits = [hit("A course on quantum computing"), hit("quantum error correction, explained"),
            hit("Quantum announces results")]
    counts = count_mentions(hits, "Quantum")
    assert counts["lower"] == 2 and counts["standalone"] == 1
