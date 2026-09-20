"""The paragraph at the top of the page: what changed, and what to watch.

Two implementations of the same shape, and the deterministic one is not a
consolation prize:

- `heuristic_brief` composes the regime reads, the day's highest-impact stories
  and the next scheduled events into a brief with no model involved. It always
  works, it is free, and because it is assembled from computed states rather
  than generated, it cannot be wrong about a number.
- `llm_brief` asks one model call to write the same thing in prose, which reads
  better and can connect two facts the templates cannot. It costs one request
  per day.

The LLM version is given the computed regime rather than the raw series, on
purpose. Asking a model to both do the arithmetic and write the summary is how
you get a fluent paragraph containing a wrong number; asking it only to
synthesise states that were already computed means the numbers come from
`metrics` and only the joins come from the model.

Both are explicitly barred from telling anyone what to do with their money. The
useful output is "here is what changed and the mechanism by which it matters",
which is a thing a reader can combine with their own situation. The brief is
also stored in the database, so a run where the model is skipped or fails
serves yesterday's rather than an empty box.
"""
from __future__ import annotations
import json
import re
from datetime import date, datetime, timezone

from .rank import PROVIDERS, ProviderError, _call_with_retry
from .regime import DISCLAIMER

MAX_POINTS = 6

# A news item has to clear this to be worth a line in a six-line brief. Without
# a floor, the "one per category" rule pads the brief with whatever happened to
# be the least uninteresting thing in an otherwise quiet category.
MIN_BRIEF_IMPACT = 35

# Reasons that say nothing. They are the fallback strings from the scorers, and
# appending "- baseline coverage" to a headline is worse than appending nothing.
EMPTY_REASONS = {"baseline coverage", "routine coverage", ""}


def heuristic_brief(regime: dict, items: list, events: list,
                    now: datetime = None) -> dict:
    """A brief assembled from computed states. No model, no network, no cost."""
    now = now or datetime.now(timezone.utc)
    reads = regime.get("reads") or []
    points = []

    # The reads that are actually saying something. A neutral read is not worth
    # a line - "credit is normal" is the absence of news.
    for read in sorted(reads, key=lambda r: -abs(r["score"]))[:4]:
        if read["score"] == 0:
            continue
        # The label is rendered as its own chip, so repeating it in the text
        # ("Inflation  Inflation: sticky above target") reads as a stutter.
        points.append({
            "kind": "regime",
            "label": read["label"],
            "text": f"{read['state'].capitalize()}. {_first_sentence(read['means'])}",
        })

    for item in _top_items(items, 3):
        reason = item.get("score_reason") or item.get("impact_reason") or ""
        if reason.strip().lower() in EMPTY_REASONS:
            reason = ""
        points.append({
            "kind": "news",
            "label": item.get("source", ""),
            "text": item["title"] + (f" - {reason}" if reason else ""),
            "url": item.get("url") or item.get("discussion_url") or "",
        })

    lede = regime.get("summary", "")
    tension = regime.get("tension", "")
    return {
        "by": "heuristic",
        "generated_at": now.isoformat(timespec="seconds"),
        "lede": (f"Conditions look {regime.get('stance', 'balanced')}: {lede}"
                 if lede else "Not enough market data to read the regime yet."),
        "tension": tension,
        "points": points[:MAX_POINTS],
        "watch": watch_list(events),
        "disclaimer": DISCLAIMER,
    }


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return parts[0] if parts else ""


def _top_items(items: list, limit: int) -> list:
    """The day's biggest stories by market impact, one per story.

    Deduplicated by category as well as by cluster: three tariff headlines are
    one thing to tell somebody, and a brief that spends all three of its slots
    on the same subject has told the reader about one subject.
    """
    seen_categories, out = set(), []
    for item in sorted(items, key=lambda r: -(r.get("impact") or 0)):
        if (item.get("impact") or 0) < MIN_BRIEF_IMPACT:
            break  # sorted, so nothing after this clears the floor either
        category = item.get("category") or "other"
        # "other" means no finance vocabulary matched, so it has no place in a
        # summary of what moved markets.
        if category in seen_categories or category == "other":
            continue
        seen_categories.add(category)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def watch_list(events: list, limit: int = 5) -> list:
    """The next scheduled things that can change the picture.

    Deduplicated by title, keeping the nearest occurrence. Claims are weekly, so
    without this the same release takes two of five slots and says nothing the
    second time.
    """
    out, seen = [], set()
    for event in events:
        if int(event.get("importance", 3)) > 2:
            continue
        if event["title"] in seen:
            continue
        seen.add(event["title"])
        out.append({
            "on": event["on_date"],
            "title": event["title"],
            "time_et": event.get("time_et", ""),
            "estimated": bool(event.get("estimated", 1)),
            "why": _first_sentence(event.get("detail", "")),
        })
        if len(out) >= limit:
            break
    return out


PROMPT = """You are writing the morning macro note for one investor, whose \
profile is below. It is read once, before the market opens, by somebody \
managing their own long-term money.

INVESTOR PROFILE
{profile}

COMPUTED REGIME (already calculated from public data - do NOT recompute or \
contradict these numbers)
{regime}

KEY READINGS
{metrics}

TODAY'S HIGHEST-IMPACT NEWS
{news}

SCHEDULED NEXT
{events}

Write a brief with this exact JSON shape, no prose outside it, no code fence:
{{"lede": "<2 sentences: what state the market is in and what changed>",
  "points": [{{"label": "<2-4 word tag>", "text": "<1-2 sentences>"}}],
  "tension": "<1-2 sentences naming where the readings disagree with each \
other, or where the market looks priced for something the data does not \
support. If they agree, say so and say which upcoming release would break the \
agreement.>",
  "watch_note": "<1 sentence on which upcoming event matters most and why>"}}

Rules:
- Between 3 and 5 points. Each must connect a fact to a MECHANISM - how it \
reaches asset prices - not just restate the fact.
- Use the numbers given. Never invent a figure, a level or a date.
- Write for somebody who wants to understand the machine, not to be told an \
answer. Explain transmission; name what would change your read.
- Never recommend buying, selling, holding, allocating or timing anything, and \
never describe anything as cheap, expensive, a good entry or an opportunity. \
Describe consequences and let the reader decide.
- Plain language. No hedging filler, no "it is important to note", no bullet \
points inside a text field."""


def llm_brief(profile: str, regime: dict, summaries: dict, items: list,
              events: list, *, provider="gemini", model=None, timeout=120,
              api_key: str = "", sleep=None, now: datetime = None) -> dict:
    """One model call for the brief. Raises on failure; the caller falls back."""
    import os
    import time as _time
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    env_var, default_model, call = PROVIDERS[provider]
    key = api_key or os.environ.get(env_var, "").strip()
    if not key:
        raise RuntimeError(f"{env_var} is not set, so provider {provider!r} can't be used")
    model = model or default_model
    now = now or datetime.now(timezone.utc)

    prompt = PROMPT.format(
        profile=profile,
        regime=_regime_block(regime),
        metrics=_metrics_block(summaries),
        news=_news_block(items),
        events=_events_block(events),
    )
    reply = _call_with_retry(call, prompt, model, key, timeout, sleep or _time.sleep)
    parsed = parse_brief(reply)
    return {
        "by": f"{provider}:{model}",
        "generated_at": now.isoformat(timespec="seconds"),
        "lede": parsed["lede"],
        "tension": parsed.get("tension") or regime.get("tension", ""),
        "points": [{"kind": "llm", **p} for p in parsed["points"]][:MAX_POINTS],
        "watch": watch_list(events),
        "watch_note": parsed.get("watch_note", ""),
        "disclaimer": DISCLAIMER,
    }


def parse_brief(text: str) -> dict:
    """Pull the JSON object out of a model reply, tolerating fences and prose."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError(f"no JSON object in model reply: {(text or '')[:200]!r}")
    data = json.loads(match.group(0))
    lede = re.sub(r"\s+", " ", str(data.get("lede") or "")).strip()
    if not lede:
        raise ValueError("model returned a brief with no lede")
    points = []
    for entry in data.get("points") or []:
        if not isinstance(entry, dict):
            continue
        body = re.sub(r"\s+", " ", str(entry.get("text") or "")).strip()
        if not body:
            continue
        points.append({
            "label": re.sub(r"\s+", " ", str(entry.get("label") or "")).strip()[:40],
            "text": body[:400],
        })
    if not points:
        raise ValueError("model returned a brief with no points")
    return {
        "lede": lede[:500],
        "points": points,
        "tension": re.sub(r"\s+", " ", str(data.get("tension") or "")).strip()[:400],
        "watch_note": re.sub(r"\s+", " ", str(data.get("watch_note") or "")).strip()[:300],
    }


def _regime_block(regime: dict) -> str:
    lines = [f"Overall: {regime.get('stance', 'unknown')}"]
    for read in regime.get("reads") or []:
        lines.append(f"- {read['label']}: {read['state']} (score {read['score']:+d})")
    if regime.get("tension"):
        lines.append(f"Computed tension: {regime['tension']}")
    return "\n".join(lines)


def _metrics_block(summaries: dict, limit: int = 16) -> str:
    lines = []
    for entry in sorted((s for s in summaries.values() if s.get("tier", 3) <= 2),
                        key=lambda s: (s.get("tier", 3), s["family"]))[:limit]:
        changes = entry.get("changes") or {}
        window = "1m" if "1m" in changes else next(iter(changes), "")
        move = f", {changes[window]:+g} over {window}" if window else ""
        rank = (f", {entry['pct_rank']:.0f}th pct of {entry['lookback_years']:g}y"
                if entry.get("pct_rank") is not None else "")
        lines.append(f"- {entry['label']}: {entry['value']:g}{entry['unit']}"
                     f"{move}{rank} (as of {entry['as_of']})")
    return "\n".join(lines) or "(market data unavailable this run)"


def _news_block(items: list, limit: int = 14) -> str:
    lines = []
    for item in sorted(items, key=lambda r: -(r.get("impact") or 0))[:limit]:
        lines.append(f"- [{item.get('category', 'other')}/"
                     f"{item.get('horizon', 'week')}] {item['title']} "
                     f"({item.get('source', '')}, impact "
                     f"{int(item.get('impact') or 0)})")
    return "\n".join(lines) or "(no news fetched this run)"


def _events_block(events: list, limit: int = 8) -> str:
    lines = []
    for event in events[:limit]:
        mark = "~" if event.get("estimated", 1) else ""
        lines.append(f"- {mark}{event['on_date']} {event.get('time_et', '')} "
                     f"{event['title']} (importance {event.get('importance', 3)})")
    return "\n".join(lines) or "(no calendar generated)"
