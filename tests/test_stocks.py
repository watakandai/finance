"""The three stock lists: what gets on each, and why."""
from datetime import date, timedelta

import pytest

from finance import stocks
from finance.stocks import (
    candidates, clean_reddit, dipping, headline_for, is_dipping, money, size_label,
    stock_facts, tech_favourites, trending,
)

TODAY = date(2026, 9, 26)


def row(symbol, cap=20e9, name=None, **kw):
    return {"symbol": symbol, "name": name or f"{symbol} Corp", "price": 100.0,
            "pct_today": 1.0, "volume": 1000, "market_cap": cap, "sector": "Technology",
            "industry": "Software", **kw}


def history(start_price, end_price, days=300, peak=None, peak_days_ago=None):
    """Daily closes rising or falling linearly, with an optional one-day peak."""
    out = []
    for i in range(days):
        on = TODAY - timedelta(days=days - 1 - i)
        value = start_price + (end_price - start_price) * i / (days - 1)
        if peak and peak_days_ago is not None and (TODAY - on).days == peak_days_ago:
            value = peak
        out.append((on, value))
    return out


def twit(symbol, rank, summary="People are talking."):
    return {"symbol": symbol, "rank": rank, "title": symbol, "score": 1.0,
            "summary": summary, "watchers": 0, "kind": "stock"}


def red(symbol, rank, mentions=50, before=20):
    return {"symbol": symbol, "name": symbol, "rank": rank, "rank_24h_ago": rank,
            "mentions": mentions, "mentions_24h_ago": before, "upvotes": 0}


# ------------------------------------------------------------------ facts

@pytest.mark.parametrize("cap,label", [(5e12, "giant"), (50e9, "large"), (5e9, "mid-size"),
                                       (5e8, "small"), (1e8, "tiny")])
def test_size_bands(cap, label):
    assert size_label(cap) == label


def test_money_reads_like_a_person_would_say_it():
    assert money(5.41e12) == "$5.4 trillion"
    assert money(1.28e11) == "$128 billion"
    assert money(8.4e8) == "$840 million"


def test_facts_measure_the_month_and_the_fall_from_the_high():
    facts = stock_facts(row("X"), history(100, 80, peak=150, peak_days_ago=100), TODAY)
    assert facts["off_high"] == pytest.approx(-46.7, abs=0.1)
    assert facts["high_on"] == (TODAY - timedelta(days=100)).isoformat()
    assert facts["chg_1m"] < 0 and facts["spark"]


def test_facts_without_history_still_carry_the_screener_data():
    facts = stock_facts(row("X", cap=2e11), [], TODAY)
    assert facts["size"] == "giant" and facts["cap_text"] == "$200 billion"
    assert "off_high" not in facts and "chg_1m" not in facts


# --------------------------------------------------------------- trending

def test_trending_keeps_stocktwits_order_and_drops_what_it_cannot_price():
    screener = {"MU": row("MU"), "META": row("META")}
    rows = trending(screener, {}, [twit("QQQ", 1), twit("MU", 2), twit("BTC.X", 3),
                                   twit("META", 4)], [], today=TODAY)
    assert [r["symbol"] for r in rows] == ["MU", "META"]   # ETF and crypto dropped
    assert rows[0]["why"] == "People are talking." and rows[0]["why_source"] == "Stocktwits"


def test_reddit_risers_join_when_mentions_at_least_double():
    screener = {"AAA": row("AAA"), "BBB": row("BBB"), "CCC": row("CCC")}
    reddit = [red("AAA", 1, mentions=90, before=30),   # tripled: in
              red("BBB", 2, mentions=90, before=80),   # steady: out
              red("CCC", 3, mentions=12, before=2)]    # doubled but tiny: out
    rows = trending(screener, {}, [], reddit, today=TODAY)
    assert [r["symbol"] for r in rows] == ["AAA"]
    assert "from 30 to 90" in rows[0]["why"]


def test_a_handful_of_reddit_posts_is_not_shown_as_attention():
    screener = {"MU": row("MU")}
    rows = trending(screener, {}, [twit("MU", 1)], [red("MU", 150, mentions=2, before=1)],
                    today=TODAY)
    assert not any("Reddit" in b for b in rows[0]["badges"])


# ---------------------------------------------------------------- dipping

def test_a_stock_recovering_from_an_old_peak_is_not_a_dip():
    # Peaked a year ago, down 60% from it - but up 20% this month.
    recovering = stock_facts(row("R"), history(40, 60, peak=150, peak_days_ago=280), TODAY)
    assert recovering["off_high"] < -50 and recovering["chg_1m"] > 0
    assert not is_dipping(recovering)


def test_a_sharp_month_or_a_still_falling_stock_off_its_high_is_a_dip():
    sharp = {"chg_1m": -12.0, "off_high": -5.0}
    sliding = {"chg_1m": -2.0, "off_high": -30.0}
    assert is_dipping(sharp) and is_dipping(sliding)
    assert not is_dipping({"chg_1m": None, "off_high": -40.0})


def test_dipping_needs_a_reason_to_be_well_known_and_sorts_by_the_recent_fall():
    screener = {"HOT": row("HOT"), "BIG": row("BIG", cap=5e11), "OBSCURE": row("OBSCURE")}
    hist = {"HOT": history(100, 80), "BIG": history(100, 60), "OBSCURE": history(100, 50)}
    rows = dipping(screener, hist, [twit("HOT", 3)], [], {}, today=TODAY)
    assert [r["symbol"] for r in rows] == ["BIG", "HOT"]    # OBSCURE has no reason
    assert "one of the largest companies" in rows[0]["badges"][0]
    assert rows[0]["why"].startswith("Now ")


# -------------------------------------------------------------- candidates

def test_one_symbol_per_company_so_alphabet_is_not_listed_twice():
    screener = {"GOOG": row("GOOG", cap=3e12, name="Alphabet", volume=10),
                "GOOGL": row("GOOGL", cap=3e12, name="Alphabet", volume=99)}
    assert candidates(screener, [], [], {}) == ["GOOGL"]


def test_forum_vocabulary_is_not_mistaken_for_a_ticker():
    reddit = [red("IP", 1), red("DTE", 2), red("ALL", 3), red("BYD", 4), red("MU", 5)]
    assert [r["symbol"] for r in clean_reddit(reddit)] == ["MU"]


# --------------------------------------------------------------- tech list

def test_the_tech_list_is_developer_companies_the_crowd_is_not_discussing():
    screener = {"NET": row("NET", cap=1.2e11), "HUGE": row("HUGE", cap=3e12),
                "APP": row("APP", cap=5e10), "HYPED": row("HYPED", cap=2e10),
                "QUIET": row("QUIET", cap=5e9)}
    hn = {s: {"stories": 20, "points": 500, "top_title": f"{s} launch", "top_url": "u"}
          for s in screener}
    hn["QUIET"] = {"stories": 1, "points": 5, "top_title": "", "top_url": ""}
    universe = {"APP": {"consumer": True}, "NET": {"what": "Network edge"}}
    rows = tech_favourites(screener, {}, hn, [red("HYPED", 5)], universe, today=TODAY)
    # HUGE is too famous, APP a household brand, HYPED a Reddit favourite,
    # QUIET below the attention floor.
    assert [r["symbol"] for r in rows] == ["NET"]
    assert rows[0]["what"] == "Network edge" and "NET launch" in rows[0]["why"]


def test_one_viral_post_does_not_outrank_a_month_of_steady_discussion():
    screener = {"VIRAL": row("VIRAL"), "STEADY": row("STEADY")}
    hn = {"VIRAL": {"stories": 3, "points": 3000},
          "STEADY": {"stories": 40, "points": 600}}
    rows = tech_favourites(screener, {}, hn, [], {}, today=TODAY)
    assert [r["symbol"] for r in rows] == ["STEADY", "VIRAL"]


# ------------------------------------------------------------------- news

def test_the_most_market_relevant_headline_about_a_company_is_attached():
    items = [{"title": "Cloudflare outage takes down sites", "impact": 20, "url": "a", "source": "x"},
             {"title": "Cloudflare beats estimates, raises guidance", "impact": 40, "url": "b", "source": "y"},
             {"title": "Unrelated story", "impact": 90, "url": "c", "source": "z"}]
    news = headline_for({"symbol": "NET", "name": "Cloudflare"}, items)
    assert news["url"] == "b"


def test_ambiguous_names_and_tickers_do_not_match_ordinary_words():
    items = [{"title": "American consumers are spending less", "impact": 50, "url": "x"},
             {"title": "Markets open higher", "impact": 50, "url": "y"}]
    assert headline_for({"symbol": "AAL", "name": "American Airlines"}, items) is None
    assert headline_for({"symbol": "OPEN", "name": "Opendoor Technologies"}, items) is None


def test_a_row_with_no_explanation_borrows_its_headline():
    rows = stocks.attach_news([{"symbol": "NET", "name": "Cloudflare", "why": ""}],
                              [{"title": "Cloudflare buys a startup", "impact": 30,
                                "url": "u", "source": "cnbc_finance"}])
    assert rows[0]["why"] == "In the news: Cloudflare buys a startup"
    assert rows[0]["why_url"] == "u"


def test_every_list_ships_with_a_plain_note_on_how_to_read_it():
    built = stocks.build({}, {}, [], [], {}, {})
    assert set(built["lists"]) == set(built["notes"]) == {"trending", "dipping", "tech"}
    for note in built["notes"].values():
        assert note["what"] and note["careful"]
