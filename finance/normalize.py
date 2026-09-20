"""Deciding when two listings are the same story.

Financial news is the most duplicated news there is: one Fed sentence becomes
forty headlines inside a minute, and every wire rewrites the same paragraph.
Counting how many outlets carried something is only evidence once identical
stories stop looking like forty separate ones.

Two mechanisms, in order of trust:

- `canonical_url` - the same article syndicated to four sites is often the
  same URL wearing different tracking parameters. Exact, cheap, catches most.
- `title_key` - for the rest, because wires genuinely publish different URLs
  for the same sentence. Fuzzier, so it is only consulted when there is no
  URL to compare.
"""
from __future__ import annotations
import re
import urllib.parse

TRACKING_PREFIXES = ("utm_", "mc_", "pk_", "hsa_", "at_", "oly_")
TRACKING_EXACT = {
    "ref", "ref_src", "ref_url", "source", "cmpid", "cmp", "fbclid", "gclid",
    "igshid", "mkt_tok", "spm", "sh", "share_id", "guccounter", "smid",
    "__twitter_impression", "s", "t", "si", "feature", "guce_referrer",
    "mod", "reflink", "st", "yptr", "ns_campaign", "partner",
}
# Query parameters that genuinely select content and must be kept even though
# they look generic. Dropping `id` would collapse every CNBC story into one,
# and the Fed's own press releases are identified by path, not query.
MEANINGFUL = {"v", "id", "p", "story", "article", "page", "q", "symbol", "ticker"}

WWW_RE = re.compile(r"^(www|m|mobile|amp)\.", re.I)
AMP_SUFFIX_RE = re.compile(r"/amp(/|$)|\.amp(/|$)", re.I)

# Headline filler. The finance-specific additions matter more than they look:
# "stocks", "market", "shares", "says" and "amid" appear in a third of all
# headlines here and carry no identity at all, so leaving them in makes
# unrelated stories look similar.
STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "was", "were", "be", "with", "at", "by", "from", "as", "it", "its", "that",
    "this", "how", "why", "what", "new", "using", "via", "after", "amid",
    "says", "said", "say", "up", "down", "more", "than", "over", "into",
    "could", "would", "may", "will", "not", "but", "his", "her", "their",
}


def canonical_url(url: str) -> str:
    """A URL reduced to what identifies the document.

    Returns "" for anything unusable, which callers read as "no URL identity
    available, fall back to the title".
    """
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https", ""):
        return ""
    host = WWW_RE.sub("", parts.netloc.lower()).rstrip(".")
    if not host:
        return ""
    host = re.sub(r":(80|443)$", "", host)

    path = AMP_SUFFIX_RE.sub("/", parts.path or "/")
    path = re.sub(r"^/amp(?=/)", "", path)
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1:
        path = path.rstrip("/")

    kept = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=False)
        if _keep_param(k)
    ]
    query = urllib.parse.urlencode(sorted(kept))
    return urllib.parse.urlunsplit(("https", host, path, query, ""))


def _keep_param(key: str) -> bool:
    k = key.lower()
    if k in MEANINGFUL:
        return True
    if k in TRACKING_EXACT:
        return False
    return not any(k.startswith(p) for p in TRACKING_PREFIXES)


def title_tokens(title: str) -> list[str]:
    """Content words of a headline, lowercased, markup and boilerplate dropped.

    Numbers are kept: "CPI rises 0.3%" and "CPI rises 0.4%" are different
    stories, and in this domain the number is frequently the whole story.
    """
    text = (title or "").lower()
    text = re.sub(r"\[[^\]]{1,12}\]", " ", text)
    text = re.sub(r"\(\s*(19|20)\d{2}\s*\)", " ", text)
    # Wires prefix the venue: "UPDATE 2-", "EXCLUSIVE:", "BREAKING:".
    text = re.sub(r"^\s*(update \d+|exclusive|breaking|analysis|explainer)\s*[-:]", " ", text)
    return [w for w in re.findall(r"[a-z0-9][a-z0-9+#.%$-]*", text) if w not in STOPWORDS]


def title_key(title: str) -> str:
    """A headline reduced to its five most distinctive words, in order.

    Five rather than the whole thing: outlets rewrite the tail of a headline
    ("...", economists say / ...as traders weigh Fed path) far more than the
    head.
    """
    return " ".join(title_tokens(title)[:5])


def cluster_key(url: str, title: str) -> str:
    """The identity of a STORY, across sources.

    URL first because it is exact. The prefix keeps the two namespaces apart,
    so a title that happens to look like a URL can never collide with one.
    """
    canon = canonical_url(url)
    if canon:
        return "u:" + canon
    key = title_key(title)
    return "t:" + key if key else ""


def same_story(a: dict, b: dict) -> bool:
    """Whether two rows are one story, for the fuzzy pass over title-only rows.

    Containment rather than equality, with a floor of three content words, so
    that a shared prefix ("Stocks close lower as ...") is never enough on its
    own.
    """
    ta, tb = set(title_tokens(a.get("title") or "")), set(title_tokens(b.get("title") or ""))
    if len(ta) < 3 or len(tb) < 3:
        return False
    return ta <= tb or tb <= ta
