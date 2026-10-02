"""One model call that reasons forward from today: scenarios, chains, ripples.

The computed layer (`scenarios`, `drops`) knows the patterns that recur and
can measure which one the data fits. What it cannot do is read today's
specific news and say "this tariff on Chinese EVs is the kind of thing that
reaches Mexican auto-parts makers in a year". That join is what a model is
good at, so it gets exactly that job and nothing else:

- for each of the four scenarios, how it would unfold FROM TODAY, and the one
  event that would tip things toward it;
- second-order chains for the three news stories with the longest reach -
  first effect, second, the long-run end state, which industries gain or
  lose and how, what could go right and wrong - each ending in a CHECK: a
  metric this project tracks, a direction and a horizon, so the claim is
  scored later instead of forgotten;
- for stocks that fell, one sentence on the ripple: who else the cause
  reaches (suppliers, competitors, customers).

As with the brief, the model is handed computed numbers and told not to
produce new ones, and it is barred from buy/sell language. Everything it
returns is validated: unknown scenario ids, metric ids and directions are
dropped rather than trusted.
"""
from __future__ import annotations
import json
import re

from .scenarios import CHAINS, SCENARIO_IDS

MAX_CHAINS = 3
MAX_RIPPLES = 8
CHECK_DAYS = (30, 180)

PROMPT = """You are helping one long-term investor, who is NEW TO FINANCE, \
reason about what could happen next. You do not predict one outcome. You lay \
out cause and effect clearly enough that the reader can judge it, and you make \
claims that can be checked later.

INVESTOR PROFILE
{profile}

TODAY'S COMPUTED READINGS (already calculated - never recompute or contradict)
{regime}

KEY NUMBERS
{metrics}

THE FOUR SCENARIOS AND HOW TODAY'S DATA FITS EACH
{scenarios}

KNOCK-ON CHAINS THE DATA HAS SWITCHED ON
{chains}

TODAY'S HIGHEST-IMPACT NEWS
{news}

STOCKS THAT FELL, WITH THE COMPUTED EXPLANATION
{drops}

Return ONLY this JSON, no prose outside it, no code fence:
{{"outlook": "<2-3 sentences: which scenario the data leans toward, the \
strongest reason, and the single thing that would most change the picture>",
  "scenarios": {{"<scenario id>": {{"from_here": "<2 sentences: how this \
scenario would unfold starting from today's actual news>", "tipping_point": \
"<1 sentence: the specific event or reading that would push things this \
way>"}}}},
  "chains": [{{"event": "<the news story, 3-10 words>",
    "first": "<the immediate effect, 1 sentence>",
    "second": "<the knock-on effect on other industries, 1-2 sentences>",
    "long_run": "<where it ends up in 1-3 years, 1-2 sentences>",
    "industries": [{{"name": "<industry>", "dir": "+ or -", "how": "<the \
mechanism, max 15 words>"}}],
    "goes_right": "<1 sentence: the version where this turns out well>",
    "goes_wrong": "<1 sentence: the version where this turns out badly>",
    "check": {{"metric": "<one id from METRIC IDS>", "direction": "up or down", \
"days": <30-180>, "claim": "<the prediction in plain words, max 14 words>"}}}}],
  "ripples": {{"<TICKER>": "<1 sentence: who else the cause of this fall \
reaches - competitors, suppliers, customers - and why>"}}}}

METRIC IDS you may use in a check: {metric_ids}

Rules:
- One entry in "scenarios" for each of: {scenario_ids}.
- Exactly {max_chains} chains, for the stories with the longest reach into \
other industries - not the most dramatic headlines. 3-5 industries each.
- A ripple only for the listed stocks, and only where the cause plausibly \
reaches beyond the company; omit the rest.
- Use the numbers given; never invent a figure, level or date.
- Never recommend buying, selling, holding or timing anything, and never call \
anything cheap, expensive, an opportunity or a good entry. Describe mechanisms \
and consequences only.
- Plain words for a beginner; explain any unavoidable term in the same \
sentence."""


def _scenarios_block(evaluated: list) -> str:
    lines = []
    for s in evaluated:
        signs = "; ".join(
            f"{c['text']}: {'yes' if c['met'] else 'no' if c['met'] is not None else 'n/a'}"
            for c in s["signposts"])
        lines.append(f"- {s['id']} ({s['title']}: {s['tagline']}) - {s['met']}/"
                     f"{s['known']} signs met. {signs}")
    return "\n".join(lines)


def _chains_block(active: list) -> str:
    if not active:
        return "(none switched on today)"
    return "\n".join(f"- {a['title']}: {' '.join(a.get('why_now') or [])}" for a in active)


def _drops_block(drops: dict) -> str:
    if not drops:
        return "(none)"
    lines = []
    for symbol, d in list(drops.items())[:MAX_RIPPLES]:
        heads = "; ".join(e["title"] for e in (d.get("evidence") or [])[:2])
        lines.append(f"- {symbol} ({d.get('name', symbol)}, {d.get('industry', '')}): "
                     f"{d.get('summary', '')} Headlines: {heads}")
    return "\n".join(lines)


def build_prompt(profile, regime_block, metrics_block, news_block, evaluated, active,
                 drops, metric_ids) -> str:
    return PROMPT.format(
        profile=profile, regime=regime_block, metrics=metrics_block,
        scenarios=_scenarios_block(evaluated), chains=_chains_block(active),
        news=news_block, drops=_drops_block(drops),
        metric_ids=", ".join(sorted(metric_ids)),
        scenario_ids=", ".join(SCENARIO_IDS), max_chains=MAX_CHAINS)


def _clean(text, limit=400) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


ADVICE_RE = re.compile(
    r"\b(?:buy(?:ing)? (?:the|more|now)|sell(?:ing)? (?:the|now)|good entry|"
    r"undervalued|overvalued|opportunity|bargain|you should (?:buy|sell|hold))\b", re.I)


def parse_analysis(text: str, metric_ids: set, symbols: set) -> dict:
    """Validate the model's JSON. Anything malformed is dropped, not repaired."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError(f"no JSON object in model reply: {(text or '')[:200]!r}")
    data = json.loads(match.group(0))
    outlook = _clean(data.get("outlook"), 600)
    if not outlook:
        raise ValueError("model returned no outlook")

    scenarios = {}
    for sid, body in (data.get("scenarios") or {}).items():
        if sid in SCENARIO_IDS and isinstance(body, dict) and body.get("from_here"):
            scenarios[sid] = {"from_here": _clean(body.get("from_here")),
                              "tipping_point": _clean(body.get("tipping_point"), 250)}

    chains = []
    for raw in data.get("chains") or []:
        if not isinstance(raw, dict) or not raw.get("event") or not raw.get("first"):
            continue
        industries = []
        for ind in raw.get("industries") or []:
            if not isinstance(ind, dict) or not ind.get("name"):
                continue
            direction = str(ind.get("dir") or "").strip()[:1]
            if direction not in "+-~" or not direction:
                continue
            industries.append({"name": _clean(ind["name"], 60), "dir": direction,
                               "how": _clean(ind.get("how"), 160)})
        check = raw.get("check") if isinstance(raw.get("check"), dict) else {}
        valid_check = None
        if (check.get("metric") in metric_ids and check.get("direction") in ("up", "down")):
            try:
                days = int(check.get("days") or 90)
            except (TypeError, ValueError):
                days = 90
            valid_check = {"metric": check["metric"], "direction": check["direction"],
                           "days": min(max(days, CHECK_DAYS[0]), CHECK_DAYS[1]),
                           "claim": _clean(check.get("claim"), 140)}
        chain = {
            "event": _clean(raw["event"], 120),
            "first": _clean(raw.get("first")),
            "second": _clean(raw.get("second")),
            "long_run": _clean(raw.get("long_run")),
            "industries": industries[:6],
            "goes_right": _clean(raw.get("goes_right"), 300),
            "goes_wrong": _clean(raw.get("goes_wrong"), 300),
            "check": valid_check,
        }
        # A chain that slipped into advice is dropped whole: it is easier to
        # lose one chain than to edit a model's sentence into compliance.
        if ADVICE_RE.search(" ".join(str(v) for v in chain.values())):
            continue
        chains.append(chain)
        if len(chains) >= MAX_CHAINS:
            break

    ripples = {}
    for symbol, sentence in (data.get("ripples") or {}).items():
        symbol = str(symbol).upper().strip()
        sentence = _clean(sentence, 300)
        if symbol in symbols and sentence and not ADVICE_RE.search(sentence):
            ripples[symbol] = sentence

    if ADVICE_RE.search(outlook):
        outlook = ""
    return {"outlook": outlook, "scenarios": scenarios, "chains": chains,
            "ripples": ripples}


def library_ids() -> list:
    return [c["id"] for c in CHAINS]
