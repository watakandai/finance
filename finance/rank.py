"""Scoring, so a day of four hundred headlines becomes a list worth reading.

Two rankers, layered, the same split as the sibling projects:

- `heuristic_scores` is deterministic, offline and free. It answers "would a
  reasonable investor want this?" from signals that need no model: market
  impact, the category's general usefulness, freshness by horizon, and a
  penalty for the formats that carry no facts. It runs every time and is the
  floor when there is no key, no network, or a spent quota.

- `llm_scores` answers the question that actually matters - "would THIS person,
  with THIS portfolio and THIS time horizon, act differently after reading
  it?" - by reading profile.md. It also assigns the category, the horizon and
  the affected asset classes in the same call, because the model has already
  read the item and a second request would double the cost for nothing.

One design point specific to this project: the prompt asks the model for
*mechanism*, not for a recommendation. "Raises the discount rate on long-
duration equities" is a fact about transmission that the reader can act on with
their own judgement; "sell growth stocks" is advice this project has no
business giving and no ability to tailor. The scoring rubric is built so that a
model trying to be helpful in the second way scores worse, not better.

Which model does the rating is a swappable provider - Gemini, Claude, Groq,
or a local Ollama model - see PROVIDERS. `llm_scores_chain` adds fallbacks:
whatever the first provider leaves unscored (a 503, a spent quota) goes to
the next.

Scores are cached by a hash of (profile, model, taxonomy), so a daily run only
pays for items it has never seen. Editing profile.md changes the hash and
re-scores everything once, which is the intended way to retune the feed.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .categorize import CATEGORIES, HORIZONS
from .impact import FILLER_RE, freshness, hours_old

DEFAULT_PROFILE = Path(__file__).parent.parent / "profile.md"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = "gemini-3.6-flash"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-5"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"
# Small enough (~3GB at Q4) to run on a GitHub Actions runner's CPU. The env
# var lets the workflow pull and use the same model from one setting.
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL") or "qwen3.5:4b"

# The asset-class tags the model may use. Closed, like the categories, because
# the page filters on them - and short, because the useful question is "which
# of my exposures does this touch", and a reader has five or six exposures.
ASSETS = {
    "equities": "Equities",
    "duration": "Long bonds / duration",
    "credit": "Corporate credit",
    "cash": "Cash & short rates",
    "dollar": "The dollar",
    "commodities": "Commodities",
    "gold": "Gold",
    "crypto": "Crypto",
    "real_estate": "Real estate",
    "intl": "International / EM",
}

# How generally useful a category is to someone managing their own money,
# before the profile has any say. This is the only editorial constant in the
# heuristic ranker: it encodes that policy and inflation decide the discount
# rate on everything a person owns, while a single day's index move decides
# nothing. `frameworks` scores well on purpose - the material that teaches how
# to read the rest is the highest-leverage thing on the page for a reader who
# is still building their own model, and it is exactly what a
# recency-and-popularity feed buries.
CATEGORY_WEIGHT = {
    "monetary_policy": 12,
    "inflation": 11,
    "frameworks": 10,
    "fiscal": 9,
    "rates": 8,
    "credit": 8,
    "labor": 7,
    "tech_capex": 6,
    "geopolitics": 5,
    "growth": 5,
    "earnings": 4,
    "global_macro": 4,
    "energy": 3,
    "regulation": 3,
    "commodities": 2,
    "fx": 2,
    "housing": 2,
    "positioning": 1,
    "crypto": -2,
    "equities": -3,   # "stocks rose" is the most common and least useful item
    # Not a topic but the absence of one: several feeds carry a publication's
    # whole front page, so "other" means the item matched no finance vocabulary
    # at all. It stays in the export and on its own filter chip - it is just
    # never allowed near the top of the list.
    "other": -25,
}


def heuristic_scores(rows: list, now: datetime = None) -> dict:
    """Score every row 0-100 on general usefulness. Pure function of the input."""
    out = {}
    for row in rows:
        why = []
        impact = row.get("impact")
        if impact is None:
            score = 30.0
        else:
            # Impact is the backbone: without a profile, "does this move
            # markets" is the best available proxy for "should you know it".
            score = 0.75 * float(impact)
            if impact >= 60:
                why.append("market-moving")

        category = row.get("category") or "other"
        weight = CATEGORY_WEIGHT.get(category, 0)
        score += weight
        if weight >= 9:
            why.append(f"{category.replace('_', ' ')} drives everything downstream")

        horizon = row.get("horizon") or "week"
        if horizon == "months":
            # A durable item is worth more to a reader who checks once a day
            # than a tape item that was already priced before they opened the
            # page.
            score += 6
            why.append("still matters in months")
        elif horizon == "day":
            score -= 4

        age = hours_old(row, now)
        score *= 0.7 + 0.3 * freshness(age, horizon)
        if row.get("summary"):
            score += 3  # something for the reader and the ranker to go on
        if FILLER_RE.search(row.get("title") or ""):
            score -= 20
            why.append("low-information format")

        out[row["id"]] = (
            round(max(0.0, min(100.0, score)), 1),
            ", ".join(why[:3]) or "baseline coverage",
        )
    return out


# --------------------------------------------------------------------------
# LLM ranker
# --------------------------------------------------------------------------

def load_profile(path=DEFAULT_PROFILE) -> str:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(
            f"no profile at {p}. Copy profile.example.md to profile.md and edit it - "
            "the LLM ranker needs to know who it is ranking for."
        )
    return strip_comments(p.read_text())


def strip_comments(text: str) -> str:
    """Drop HTML comments so editing notes never reach the model.

    profile.md is a prompt, not documentation: every word in it is sent.
    Instructions written for the human reader would otherwise be read as facts
    about the person - and in this project those "facts" would be facts about
    someone's money.
    """
    without = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return re.sub(r"\n{3,}", "\n\n", without).strip()


CATEGORY_LIST = ", ".join(f"{k} ({v})" for k, v in CATEGORIES.items())
HORIZON_LIST = ", ".join(f"{k} ({v})" for k, v in HORIZONS.items())
ASSET_LIST = ", ".join(f"{k} ({v})" for k, v in ASSETS.items())


def profile_hash(profile: str, model: str) -> str:
    """Identifies a (profile, model, taxonomy) triple, so an edit to any of them
    forces a re-rank.

    The taxonomies are in here because the cached row holds a category, a
    horizon and asset tags as well as a score. Leave them out and splitting a
    category would leave every item already scored sitting in a bucket that no
    longer means what it did.
    """
    key = f"{model}\x00{profile}\x00{CATEGORY_LIST}\x00{HORIZON_LIST}\x00{ASSET_LIST}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _item_line(i: int, row: dict) -> str:
    bits = [f"{i}. {row['title']}", f"src={row['source']}"]
    if row.get("tier"):
        bits.append(f"tier={row['tier']}")
    if row.get("impact") is not None:
        bits.append(f"impact={int(row['impact'])}")
    host = ""
    try:
        host = urllib.parse.urlsplit(row.get("url") or "").netloc.replace("www.", "")
    except ValueError:
        pass
    if host:
        bits.append(f"site={host}")
    tags = row.get("tags")
    if tags:
        bits.append("tags=" + ",".join((tags if isinstance(tags, list) else [tags])[:5]))
    summary = re.sub(r"\s+", " ", (row.get("summary") or ""))[:220]
    if summary:
        bits.append(f"note={summary}")
    return " | ".join(bits)


PROMPT = """You are triaging a day of financial news for one specific investor, \
whose profile is below. Score each item on whether it would change how THEY \
think or act - not on how dramatic the headline is.

INVESTOR PROFILE
{profile}

MARKET CONTEXT (today's readings, so you can judge what is already known)
{context}

SCORING
90-100 = changes their thinking or their plan; they should read it today
70-89  = squarely relevant to their holdings, horizon or open questions
40-69  = useful context, depends on the day
10-39  = weak match, or already priced and widely known
0-9    = noise for this person

Rules that matter more than the numbers:
- Judge DURABILITY. An item that still matters in six months outranks a bigger \
headline that is fully priced by tomorrow, because this person reads once a day \
and holds for years.
- Reward MECHANISM over event. A piece explaining why a variable transmits to \
asset prices is worth more than the nth report that the variable moved.
- A famous story outside their interests scores low; a quiet piece squarely \
inside them scores high. `impact=` is how much the item moves markets \
generally - use it to break ties, never as the score itself.
- Penalise heavily: stock tips, price targets, "best stocks to buy", personality \
coverage, listicles, recycled commentary, anything whose content is a \
prediction with no reasoning attached.
- If the profile is silent on something, score it in the middle rather than \
guessing.

CATEGORY - exactly one id from: {categories}
HORIZON - exactly one id from: {horizons}
  Horizon means how long the item stays RELEVANT, not when it first moves a \
price. A rate decision is `months` even though it moves the tape instantly.
ASSETS - zero to three ids from: {assets}
  Only what the item actually bears on.
REASON - at most 14 words. Say what it means or what it changes, in plain \
language. Describe the mechanism or the consequence; never tell them to buy, \
sell, hold or allocate anything.

Return ONLY a JSON array, no prose, no code fence:
[{{"i": <item number>, "score": <integer 0-100>, "category": "<id>", \
"horizon": "<id>", "assets": ["<id>"], "reason": "<max 14 words>"}}]

ITEMS
{items}"""


class ProviderError(ValueError):
    """An API call failed and the provider said why.

    Subclasses ValueError so llm_scores' per-batch handling catches it: one bad
    batch is reported and skipped, not fatal.
    """

    def __init__(self, message, status=None, retry_after=None, daily=False):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        # A per-day quota will not clear by waiting a minute, so retrying only
        # burns tomorrow's allowance.
        self.daily = daily


def _redact(text: str) -> str:
    """Never let an API key reach a log. Gemini puts its key in the URL."""
    return re.sub(r"(key=)[^&\s\"']+", r"\1***", text)


USER_AGENT = "finance/0.1 (+https://github.com/watakandai/finance)"


def _post_json(url: str, headers: dict, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        # Groq sits behind Cloudflare, which rejects urllib's default
        # "Python-urllib/3.x" agent with a bare 403 (error code 1010).
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        # The status alone ("400 Bad Request") does not say whether the key, the
        # model or the payload is wrong - the body does.
        try:
            body = exc.read().decode("utf-8", "replace").strip()
        except Exception:  # pragma: no cover - body already consumed
            body = ""
        detail = _redact(body)[:400] or exc.reason
        quota = re.search(r'"quotaId"\s*:\s*"([^"]+)"', body)
        if quota:
            detail = f"quota {quota.group(1)} exhausted"
        # Groq names the limit in prose: "... on tokens per day (TPD)".
        daily = (bool(quota) and "PerDay" in quota.group(1)) or (
            exc.code == 429 and re.search(r"per day", body, re.I) is not None
        )
        raise ProviderError(
            f"HTTP {exc.code}: {detail}",
            status=exc.code,
            retry_after=_retry_after(exc.headers, body),
            daily=daily,
        ) from None


def _retry_after(headers, body: str):
    """How long the provider asked us to wait, if it said.

    Anthropic sends a retry-after header; Gemini puts "retryDelay": "37s" in
    the error body instead.
    """
    value = headers.get("retry-after") if headers else None
    if value:
        try:
            return float(value)
        except ValueError:
            pass
    match = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body or "")
    return float(match.group(1)) if match else None


def call_gemini(prompt: str, model: str, api_key: str, timeout: int) -> str:
    # Gemini takes the key as a query parameter rather than a header.
    data = _post_json(
        GEMINI_URL.format(model=model) + f"?key={urllib.parse.quote(api_key)}",
        {},
        {
            "contents": [{"parts": [{"text": prompt}]}],
            # No temperature override: Google warns that going below the default
            # on Gemini 3 models can cause looping. Thinking stays low - triage
            # against a profile is not a reasoning problem, and thinking tokens
            # are billed as output.
            "generationConfig": {"thinkingConfig": {"thinkingLevel": "low"}},
        },
        timeout,
    )
    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError(f"gemini returned no candidates: {str(data)[:200]}")
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts)


def call_anthropic(prompt: str, model: str, api_key: str, timeout: int) -> str:
    data = _post_json(
        ANTHROPIC_URL,
        {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        {"model": model, "max_tokens": 8192,
         "messages": [{"role": "user", "content": prompt}]},
        timeout,
    )
    return "".join(
        block.get("text", "") for block in data.get("content", [])
        if block.get("type") == "text"
    )


def _chat_completions(url: str, prompt: str, model: str, api_key: str,
                      timeout: int, **extra) -> str:
    """The OpenAI-style request most other providers (Groq included) accept."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    data = _post_json(
        url,
        headers,
        {"model": model, "messages": [{"role": "user", "content": prompt}], **extra},
        timeout,
    )
    choices = data.get("choices") or []
    if not choices:
        raise ValueError(f"no choices in reply: {str(data)[:200]}")
    return choices[0].get("message", {}).get("content") or ""


def call_groq(prompt: str, model: str, api_key: str, timeout: int) -> str:
    # gpt-oss is a reasoning model. Low effort keeps the hidden reasoning -
    # which counts against Groq's tokens-per-minute cap - short, and
    # include_reasoning=False keeps it out of the reply we parse.
    return _chat_completions(
        GROQ_URL, prompt, model, api_key, timeout,
        reasoning_effort="low", include_reasoning=False,
        max_completion_tokens=4096,
    )


def call_ollama(prompt: str, model: str, host: str, timeout: int) -> str:
    """A model on a local (or self-hosted) Ollama server - no key, no quota.

    `host` comes from OLLAMA_HOST, which doubles as the "key": set means a
    server is up. Ollama's own CLI accepts it without a scheme, so this does
    too. The native /api/chat endpoint is used rather than Ollama's
    OpenAI-style one because only it can raise the context window, and
    Ollama's small default would silently cut a batch off mid-list.
    """
    base = host.strip().rstrip("/")
    if "://" not in base:
        base = f"http://{base}"
    data = _post_json(
        f"{base}/api/chat",
        {},
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            # Qwen 3.5 thinks by default; on a CPU that costs minutes a batch
            # and triage doesn't need it.
            "think": False,
            "options": {"num_ctx": 8192},
        },
        timeout,
    )
    return data.get("message", {}).get("content") or ""


# (env var holding the key, default model, call function). The signature is
# (prompt, model, key, timeout) -> reply text, so adding a provider is one
# function plus one line - nothing else in this module, the CLI or the workflow
# needs to know which one is in use.
PROVIDERS = {
    "gemini": ("GEMINI_API_KEY", GEMINI_MODEL, call_gemini),
    "anthropic": ("ANTHROPIC_API_KEY", ANTHROPIC_MODEL, call_anthropic),
    "groq": ("GROQ_API_KEY", GROQ_MODEL, call_groq),
    "ollama": ("OLLAMA_HOST", OLLAMA_MODEL, call_ollama),
}

# (items per request, seconds between requests) for a provider when it runs
# as a fallback, where the CLI's --batch-size/--min-interval (tuned for the
# primary) don't apply. Groq's free tier caps tokens per minute (8K on
# gpt-oss-120b), not requests per day: the market context and the category,
# horizon and asset lists make even a 10-item request ~3K tokens, so one
# every 30 seconds stays under the cap.
FALLBACK_PACING = {
    "groq": (10, 30.0),
    # No rate limit to respect, but a 4B model on a CPU slows down as the
    # prompt grows - small batches keep each request to a minute or so.
    "ollama": (8, 0.0),
}

# Per-request timeouts for providers slower than the default. A CPU-only
# Ollama can take minutes on one batch.
PROVIDER_TIMEOUT = {
    "ollama": 600,
}


def parse_results(text: str, batch_size: int) -> dict:
    """Pull the JSON array out of a model reply, tolerating fences and prose."""
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        raise ValueError(f"no JSON array in model reply: {text[:200]!r}")
    parsed = json.loads(match.group(0))
    out = {}
    for entry in parsed:
        try:
            idx = int(entry["i"])
            score = float(entry["score"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 1 <= idx <= batch_size:
            continue
        category = str(entry.get("category") or "").strip().lower()
        horizon = str(entry.get("horizon") or "").strip().lower()
        raw_assets = entry.get("assets")
        if isinstance(raw_assets, str):
            raw_assets = [raw_assets]
        assets = [str(a).strip().lower() for a in (raw_assets or [])]
        out[idx] = {
            "score": max(0.0, min(100.0, score)),
            # Anything off-list is dropped rather than stored: an invented
            # category or asset tag would quietly break the filter UI, and the
            # keyword pass's answer is a better fallback than a wrong one.
            "category": category if category in CATEGORIES else "",
            "horizon": horizon if horizon in HORIZONS else "",
            "assets": [a for a in assets if a in ASSETS][:3],
            "reason": re.sub(r"\s+", " ", str(entry.get("reason", ""))).strip()[:140],
        }
    return out


# Waits between retries of a rate-limited batch, when the provider does not say
# how long. Free-tier limits are per minute, so the last wait covers a full
# window.
RETRY_WAITS = (15, 30, 65)


def _call_with_retry(call, prompt, model, key, timeout, sleep):
    for wait in RETRY_WAITS + (None,):
        try:
            return call(prompt, model, key, timeout)
        except ProviderError as exc:
            if exc.status not in (429, 500, 503) or exc.daily or wait is None:
                raise
            sleep(min(exc.retry_after or wait, 120))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            # A reset connection or a timeout is as transient as a 503.
            if wait is None:
                raise
            sleep(wait)


def market_context(summaries: dict, regime: dict = None, limit: int = 12) -> str:
    """A compact "here is what is already true" block for the prompt.

    Without it the model scores a CPI headline in a vacuum. With it, the model
    knows inflation is already at 3% and falling, so it can tell the difference
    between a print that confirms the consensus and one that breaks it - which
    is the entire difference between a 40 and a 90.
    """
    lines = []
    if regime and regime.get("reads"):
        lines.append("Regime: " + "; ".join(
            f"{r['label']} {r['state'].split(' (')[0]}" for r in regime["reads"]))
    picked = [s for s in summaries.values() if s.get("tier") == 1][:limit]
    for s in picked:
        change = (s.get("changes") or {}).get("1m")
        arrow = "" if change is None else f", {change:+g} over 1m"
        lines.append(f"{s['label']}: {s['value']:g}{s['unit']}{arrow}")
    return "\n".join(lines) or "(market data unavailable this run)"


def llm_scores(rows, profile, *, provider="gemini", model=None, batch_size=40,
               timeout=120, min_interval=0, context="", on_progress=None,
               sleep=time.sleep, clock=time.monotonic) -> dict:
    """Score and classify rows against the profile. {row id: result dict}.

    Batches are independent: one failing batch is reported and skipped rather
    than losing the whole run, so a rate limit halfway through still leaves the
    batches that succeeded. A 429 is waited out and retried first.
    `min_interval` spaces batches out, so a run stays under a per-minute limit
    instead of hitting it and waiting.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; expected one of {sorted(PROVIDERS)}")
    env_var, default_model, call = PROVIDERS[provider]
    key = os.environ.get(env_var, "").strip()
    if not key:
        raise RuntimeError(f"{env_var} is not set, so provider {provider!r} can't be used")
    model = model or default_model

    out = {}
    rate_limited = False
    last_call = None
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        if rate_limited:
            # Once retries could not clear a 429, this is a daily quota rather
            # than a per-minute one - every later batch would fail the same
            # way. They stay unscored and tomorrow's run picks them up.
            if on_progress:
                on_progress(start, len(batch), "skipped (rate limited)")
            continue
        prompt = PROMPT.format(
            profile=profile,
            context=context or "(market data unavailable this run)",
            categories=CATEGORY_LIST,
            horizons=HORIZON_LIST,
            assets=ASSET_LIST,
            items="\n".join(_item_line(i, r) for i, r in enumerate(batch, 1)),
        )
        if min_interval and last_call is not None:
            wait = min_interval - (clock() - last_call)
            if wait > 0:
                sleep(wait)
        last_call = clock()
        try:
            reply = _call_with_retry(call, prompt, model, key, timeout, sleep)
            scored = parse_results(reply, len(batch))
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, KeyError) as exc:
            if getattr(exc, "status", None) == 429:
                rate_limited = True
            if on_progress:
                on_progress(start, len(batch), f"FAILED ({type(exc).__name__}: {exc})")
            continue
        for idx, result in scored.items():
            out[batch[idx - 1]["id"]] = result
        if on_progress:
            on_progress(start, len(batch), f"{len(scored)} scored")
    return out


def llm_scores_chain(rows, profile, providers, *, model=None, batch_size=40,
                     min_interval=0, on_progress=None, on_provider=None,
                     **kwargs) -> dict:
    """Score rows with providers[0], then hand what it missed to the next.

    Returns {"provider:model": {row id: result dict}}, so each score keeps a
    record of which model actually gave it. `model`, `batch_size` and
    `min_interval` apply to the first provider; fallbacks use their own
    default model and FALLBACK_PACING. A fallback with no key configured is
    skipped (reported through on_provider) rather than failing the run -
    only an unusable first provider is an error.
    """
    for name in providers:
        if name not in PROVIDERS:
            raise ValueError(f"unknown provider {name!r}; expected one of {sorted(PROVIDERS)}")

    results = {}
    pending = rows
    for n, name in enumerate(providers):
        if not pending:
            break
        env_var, default_model, _ = PROVIDERS[name]
        if n and not os.environ.get(env_var, "").strip():
            if on_provider:
                on_provider(name, None, len(pending), f"skipped ({env_var} not set)")
            continue
        use_model = model if n == 0 and model else default_model
        size, interval = (
            (batch_size, min_interval) if n == 0
            else FALLBACK_PACING.get(name, (batch_size, min_interval))
        )
        if on_provider:
            note = "" if n == 0 else f"falling back for {len(pending)} unscored items"
            on_provider(name, use_model, len(pending), note)
        if name in PROVIDER_TIMEOUT:
            kwargs = {**kwargs, "timeout": PROVIDER_TIMEOUT[name]}
        got = llm_scores(
            pending, profile, provider=name, model=use_model,
            batch_size=size, min_interval=interval, on_progress=on_progress, **kwargs,
        )
        if got:
            results[f"{name}:{use_model}"] = got
        pending = [r for r in pending if r["id"] not in got]
    return results
