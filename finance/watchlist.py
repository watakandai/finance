"""The reader's own list of tickers to follow, kept in watchlist.json.

A file in the repository rather than anything in the browser, because the page
is static: the only way a ticker gets a price history, a headline and an
attention check every day is for the daily job to know about it. The page can
still show a ticker instantly from the day's full listing (see `listing` in
cli.py), and offers the one-click route to make it permanent.

Every symbol is checked against Nasdaq before it is written, which is also how
a stock and an ETF are told apart - VOO is not in the stock screener, and a
beginner is at least as likely to add an index fund as a company.
"""
from __future__ import annotations
import json
import re
from datetime import date
from pathlib import Path

from .fetchers.base import get_json
from .fetchers.nasdaq import HEADERS, clean_name

DEFAULT_PATH = Path(__file__).parent.parent / "watchlist.json"
INFO_URL = "https://api.nasdaq.com/api/quote/{sym}/info?assetclass={cls}"
# Letters, digits, and the share-class separators exchanges use (BRK.B, BRK/B).
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[./-][A-Z0-9]{1,2})?$")


def normalise(symbol: str) -> str:
    return (symbol or "").strip().upper().lstrip("$")


def valid_format(symbol: str) -> bool:
    return bool(SYMBOL_RE.match(symbol))


def load(path=DEFAULT_PATH) -> dict:
    path = Path(path)
    if not path.is_file():
        return {"tickers": []}
    data = json.loads(path.read_text())
    data.setdefault("tickers", [])
    return data


def save(data: dict, path=DEFAULT_PATH) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def symbols(path=DEFAULT_PATH) -> list:
    return [t["symbol"] for t in load(path).get("tickers", []) if t.get("symbol")]


def lookup(symbol: str, timeout: int = 20, fetch=get_json):
    """{symbol, name, kind} from Nasdaq, trying stock then ETF; None if unknown.

    Raises on a network failure, which is different from "unknown": the caller
    can then decide to accept the symbol unchecked rather than refuse it.
    """
    for kind in ("stocks", "etf"):
        data = fetch(INFO_URL.format(sym=symbol.replace("/", "."), cls=kind), timeout, HEADERS)
        info = (data or {}).get("data")
        if info:
            return {"symbol": symbol, "name": clean_name(info.get("companyName") or symbol),
                    "kind": "etf" if kind == "etf" else "stock"}
    return None


def add(new: list, path=DEFAULT_PATH, check=True, fetch=get_json, today: date = None) -> list:
    """Add symbols; returns [(symbol, outcome)] for the caller to report."""
    data = load(path)
    have = {t["symbol"] for t in data["tickers"]}
    report = []
    for raw in new:
        symbol = normalise(raw)
        if not valid_format(symbol):
            report.append((raw, "not a valid ticker format - skipped"))
            continue
        if symbol in have:
            report.append((symbol, "already on the watchlist"))
            continue
        entry = {"symbol": symbol, "added": (today or date.today()).isoformat()}
        if check:
            try:
                info = lookup(symbol, fetch=fetch)
            except Exception as exc:
                info = None
                report.append((symbol, f"added unchecked (Nasdaq unreachable: "
                                       f"{type(exc).__name__})"))
            else:
                if info is None:
                    report.append((symbol, "Nasdaq does not know this symbol - skipped"))
                    continue
                entry.update(name=info["name"], kind=info["kind"])
                report.append((symbol, f"added ({info['name']}, {info['kind']})"))
        else:
            report.append((symbol, "added unchecked"))
        data["tickers"].append(entry)
        have.add(symbol)
    save(data, path)
    return report


def remove(old: list, path=DEFAULT_PATH) -> list:
    data = load(path)
    wanted = {normalise(s) for s in old}
    before = {t["symbol"] for t in data["tickers"]}
    data["tickers"] = [t for t in data["tickers"] if t["symbol"] not in wanted]
    save(data, path)
    return [(s, "removed" if s in before else "was not on the watchlist") for s in sorted(wanted)]
