"""Shared HTTP plumbing for every source.

Standard library only, on purpose: the whole pipeline runs on a bare
`actions/setup-python` with no `pip install` step, which is what keeps the
daily job fast and unbreakable by a dependency release.
"""
from __future__ import annotations
import gzip
import json
import urllib.error
import urllib.request
from typing import Protocol

USER_AGENT = "finance/0.1 (+https://github.com/watakandai/finance)"

# Yahoo's chart endpoint is the one host here that refuses the honest agent
# above, so it gets a browser string. Everything else - twenty-five feeds, the
# Fed, FRED, the SEC - was verified to serve the honest one, and asking for a
# real identity is the right default when calling other people's servers for
# free.
BROWSER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class Fetcher(Protocol):
    name: str

    def fetch(self) -> list:
        """Fetch and return the current set of records from this source."""
        ...


class _Redirect308(urllib.request.HTTPRedirectHandler):
    """Follow HTTP 308 as well as the classic redirects.

    urllib's built-in handler ignores 308 on older Pythons, and several
    publishers (Substack-hosted newsletters especially) moved their feeds
    behind exactly that status - the fetch fails with "308 Permanent Redirect"
    rather than following it.
    """

    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_301(req, fp, 301, msg, headers)

    https_error_308 = http_error_308


_opener = urllib.request.build_opener(_Redirect308)


def get_bytes(url: str, timeout: int = 20, headers: dict = None) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", **(headers or {})},
    )
    with _opener.open(req, timeout=timeout) as resp:
        raw = resp.read()
    # Feeds are the bulk of the traffic here and compress by ~80%; a few ignore
    # the header and send plain bytes anyway, so sniff rather than trust it.
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def get_text(url: str, timeout: int = 20, headers: dict = None) -> str:
    return get_bytes(url, timeout, headers).decode("utf-8", "replace")


def get_json(url: str, timeout: int = 20, headers: dict = None):
    return json.loads(get_bytes(
        url, timeout, {"Accept": "application/json", **(headers or {})}))


def post_form(url: str, data: dict, timeout: int = 20, headers: dict = None):
    """POST an urlencoded form and read JSON back. Used for OAuth token grants."""
    import urllib.parse
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})},
        method="POST",
    )
    with _opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())
