"""watchlist.json: validated adds, removes, and the CLI's forgiving input."""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from finance import watchlist

ROOT = Path(__file__).resolve().parent.parent


def fake_nasdaq(known):
    """A stand-in for Nasdaq's info endpoint: {(symbol, class): name}."""
    def fetch(url, timeout, headers):
        for (symbol, kind), name in known.items():
            if f"/quote/{symbol}/info?assetclass={kind}" in url:
                return {"data": {"companyName": name}}
        return {"data": None, "status": {"bCodeMessage": [{"errorMessage": "Symbol not exists."}]}}
    return fetch


def test_adds_are_checked_and_funds_are_recognised(tmp_path):
    path = tmp_path / "w.json"
    fetch = fake_nasdaq({("NET", "stocks"): "Cloudflare, Inc. Class A Common Stock",
                         ("VOO", "etf"): "Vanguard S&P 500 ETF"})
    report = dict(watchlist.add(["net", "$VOO", "ZZZZQ", "bad!!"], path, fetch=fetch,
                                today=date(2026, 9, 28)))
    assert report["NET"].startswith("added (Cloudflare, stock)")
    assert report["VOO"].startswith("added (Vanguard S&P 500 ETF, etf)")
    assert "does not know" in report["ZZZZQ"] and "format" in report["bad!!"]
    saved = json.loads(path.read_text())["tickers"]
    assert [(t["symbol"], t["kind"]) for t in saved] == [("NET", "stock"), ("VOO", "etf")]
    assert saved[0]["added"] == "2026-09-28"


def test_a_network_failure_adds_the_symbol_unchecked_rather_than_refusing(tmp_path):
    def down(url, timeout, headers):
        raise OSError("no route to host")
    report = dict(watchlist.add(["NET"], tmp_path / "w.json", fetch=down))
    assert "unchecked" in report["NET"]
    assert watchlist.symbols(tmp_path / "w.json") == ["NET"]


def test_duplicates_and_removals_report_what_happened(tmp_path):
    path = tmp_path / "w.json"
    watchlist.add(["NET"], path, check=False)
    assert "already" in dict(watchlist.add(["NET"], path, check=False))["NET"]
    report = dict(watchlist.remove(["net", "QQQ"], path))
    assert report == {"NET": "removed", "QQQ": "was not on the watchlist"}
    assert watchlist.symbols(path) == []


def test_editing_keeps_the_explanatory_comment(tmp_path):
    path = tmp_path / "w.json"
    path.write_text((ROOT / "watchlist.json").read_text())
    watchlist.add(["NET"], path, check=False)
    data = json.loads(path.read_text())
    assert data["_comment"] and data["tickers"][0]["symbol"] == "NET"


def test_share_class_formats_are_valid_and_junk_is_not():
    for good in ("NET", "BRK.B", "BRK/B", "A", "GOOGL"):
        assert watchlist.valid_format(good), good
    for bad in ("", "net$", "TOOLONGSYM", "1ABC", "A B"):
        assert not watchlist.valid_format(watchlist.normalise(bad)), bad


def test_the_cli_accepts_one_comma_separated_string_like_the_github_form(tmp_path):
    path = tmp_path / "w.json"
    out = subprocess.run(
        [sys.executable, "-m", "finance.cli", "--db", str(tmp_path / "x.db"), "watch", "add",
         "NET, VOO  AMD", "--no-check", "--file", str(path)],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert out.count("added") == 3
    assert watchlist.symbols(path) == ["NET", "VOO", "AMD"]


def test_the_shipped_watchlist_file_is_valid():
    data = watchlist.load(ROOT / "watchlist.json")
    assert isinstance(data["tickers"], list)
    for entry in data["tickers"]:
        assert watchlist.valid_format(entry["symbol"])
