"""Keyless live lookups that need exact fields a search summary can't promise: stock quotes (Yahoo Finance chart data)
and dated headlines (Google News RSS, used when the grounded search is off or fails). Answers are built from the fetched
fields, never by a model, so a price or a date can't be invented. Fetched text is untrusted data: markup is stripped.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from typing import Any

_UA = "Mozilla/5.0 (compatible; DatabricksDataAgent/1.0)"
TIMEOUT = float(os.getenv("LIVE_TIMEOUT_S", "8"))
QUOTE_TTL_OPEN, QUOTE_TTL_CLOSED, NEWS_TTL = 30, 900, 600
# In use: Yahoo, Google News, Gemini. The rest are probed so an admin can see which optional providers are reachable.
HOSTS = ("query1.finance.yahoo.com", "news.google.com", "generativelanguage.googleapis.com",
         "finnhub.io", "api.twelvedata.com", "api.tavily.com", "api.gdeltproject.org")
DISCLAIMER = "*For informational purposes only; this is not investment advice.*"

_QUOTE_Q = re.compile(r"\b(stock|share) (price|quote)s?\b|\bstock quote\b|\bshares? (of \w+ )?trading at\b|\bprice of \w+ (stock|shares)\b", re.I)
_NEWS_Q = re.compile(r"\b(news|headlines?)\b", re.I)
_TICKER = re.compile(r"\(([A-Z][A-Z.\-]{0,9})\)|\$([A-Z][A-Z.\-]{0,9})\b|\b([A-Z]{2,5})\b")
_NOT_TICKERS = {"US", "USA", "UK", "EU", "CEO", "IPO", "ETF", "NYSE", "AI", "API", "GDP", "UTC", "PM", "AM", "TODAY", "WHAT", "THE", "IS"}
_FILLER = re.compile(r"\b(what('s| is| are)?|whats|the|current|latest|today'?s?|now|right now|live|stock|share|shares|price|prices|quote|"
                     r"of|for|on|about|is|are|trading|at|please|tell me|me|show|give|news|headlines?|in|a|an)\b|[?!.,$()]", re.I)
_TAGS = re.compile(r"<[^>]+>")

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def is_quote_question(question: str) -> bool:
    return bool(_QUOTE_Q.search(question))


def is_news_question(question: str) -> bool:
    return bool(_NEWS_Q.search(question))


def _get(url: str) -> bytes:
    """GET with one retry on 429/5xx that honours Retry-After (capped at 5 s)."""
    for attempt in (0, 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": _UA}), timeout=TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if attempt or exc.code not in (429, 500, 502, 503, 504):
                raise
            wait = exc.headers.get("Retry-After", "1") if exc.headers else "1"
            time.sleep(min(float(wait) if wait.replace(".", "", 1).isdigit() else 1.0, 5.0))
    raise RuntimeError("unreachable")


def _cached(key: str, ttl_for: Any, fetch: Any) -> dict[str, Any]:
    now = time.time()
    with _lock:
        hit = _cache.get(key)
    if hit and now < hit[0]:
        return {**hit[1], "cache_age_s": round(now - hit[1]["_fetched"], 1)}
    value = fetch()
    value["_fetched"] = now
    with _lock:
        _cache[key] = (now + ttl_for(value), value)
    return {**value, "cache_age_s": 0.0}


def clean(text: str, limit: int = 300) -> str:
    """Untrusted text as plain words: tags, markdown link syntax and citation brackets removed."""
    text = _TAGS.sub(" ", html.unescape(text or ""))
    text = re.sub(r"[\[\]<>`*_|]", "", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def resolve_symbol(question: str) -> tuple[str, str]:
    """(symbol, company) from an explicit ticker, else Yahoo's search on the remaining words."""
    for m in _TICKER.finditer(question):
        sym = next(g for g in m.groups() if g)
        if sym not in _NOT_TICKERS:
            return sym, ""
    words = re.sub(r"\s+", " ", _FILLER.sub(" ", question)).strip()
    if not words:
        raise LookupError("I couldn't tell which company or ticker you mean. Try a ticker, e.g. HOOD.")
    q = urllib.parse.quote(words)
    found = json.loads(_get(f"https://query1.finance.yahoo.com/v1/finance/search?q={q}&quotesCount=3&newsCount=0"))
    for item in found.get("quotes") or []:
        if item.get("symbol") and item.get("quoteType") in ("EQUITY", "ETF", "INDEX", "MUTUALFUND", "CRYPTOCURRENCY"):
            return item["symbol"], clean(item.get("longname") or item.get("shortname") or "", 80)
    raise LookupError(f"I couldn't find a listed company or ticker matching “{clean(words, 60)}”.")


def quote(symbol: str) -> dict[str, Any]:
    def fetch() -> dict[str, Any]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=1d"
        result = (json.loads(_get(url)).get("chart") or {}).get("result") or []
        meta = result[0].get("meta", {}) if result else {}
        price, at = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
        if price is None or not at:
            raise LookupError(f"No quote is available for {symbol}.")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
        now = time.time()
        state = "open" if regular.get("start", 0) <= now < regular.get("end", 0) else "closed"
        tz = meta.get("exchangeTimezoneName") or "UTC"
        change = round(price - prev, 4) if prev else None
        return {"symbol": meta.get("symbol", symbol), "name": clean(meta.get("longName") or meta.get("shortName") or "", 80),
                "price": price, "currency": meta.get("currency") or "", "previous_close": prev, "change": change,
                "percent_change": round(change / prev * 100, 2) if prev and change is not None else None,
                "as_of_utc": dt.datetime.fromtimestamp(at, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "", "exchange_tz": tz,
                "market_state": state, "data_delay": "may be delayed up to 15 minutes; free data source",
                "provider": "Yahoo Finance", "source_url": f"https://finance.yahoo.com/quote/{urllib.parse.quote(meta.get('symbol', symbol))}",
                "fetched_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    return _cached(f"q:{symbol.upper()}", lambda v: QUOTE_TTL_OPEN if v["market_state"] == "open" else QUOTE_TTL_CLOSED, fetch)


def quote_answer(q: dict[str, Any], company: str = "") -> str:
    move = f" (**{q['change']:+,.2f} / {q['percent_change']:+.2f}%**)" if q["change"] is not None else ""
    prev = f"{q['previous_close']:,.2f} {q['currency']}".strip() if q["previous_close"] else "not available"
    return (f"**{q['symbol']}** is trading at **{q['price']:,.2f} {q['currency']}**{move} as of {q['as_of_utc']} ({q['market_state']}).\n\n"
            "| Field | Value |\n| --- | --- |\n"
            f"| Previous Close | {prev} |\n"
            f"| Market State | {q['market_state'].capitalize()}{'' if q['market_state'] == 'open' else '; last regular-session price'} |\n"
            f"| Data Delay | {q['data_delay'].capitalize()} |\n"
            f"| Data Provider | [{q['provider']}]({q['source_url']}) |\n\n"
            f"{DISCLAIMER}")


def news(query: str) -> dict[str, Any]:
    words = re.sub(r"\s+", " ", _FILLER.sub(" ", query)).strip() or query

    def fetch() -> dict[str, Any]:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(words)}&hl=en-US&gl=US&ceid=US:en"
        items, seen = [], {}
        for it in ET.fromstring(_get(url)).iter("item"):
            src = it.find("source")
            publisher = clean(src.text if src is not None else "", 60)
            title = clean(it.findtext("title") or "", 200)
            if publisher and title.endswith(f" - {publisher}"):
                title = title[: -len(publisher) - 3]
            items.append({"title": title, "publisher": publisher, "url": (it.findtext("link") or "").strip(),
                          "published": _utc(it.findtext("pubDate") or "")})
        picked: list[dict[str, Any]] = []
        for item in items:  # one per outlet first, then fill up to 8
            if item["url"] and item["publisher"] not in seen:
                seen[item["publisher"]] = True
                picked.append(item)
        picked += [i for i in items if i["url"] and i not in picked][: max(0, 8 - len(picked))]
        return {"query": words, "items": picked[:8], "provider": "Google News",
                "retrieved_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    return _cached(f"n:{words.lower()}", lambda _: NEWS_TTL, fetch)


def _utc(stamp: str) -> str:
    """RSS pubDate as 'YYYY-MM-DD HH:MM UTC'; the cleaned original text when it isn't a date."""
    try:
        return parsedate_to_datetime(stamp).astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return clean(stamp, 40)


def news_answer(found: dict[str, Any]) -> str:
    """Headlines only (no model wrote a summary): each one linked to its outlet and time, then the retrieval line."""
    def link(i: dict[str, Any]) -> str:
        url = i["url"].replace("(", "%28").replace(")", "%29").replace(" ", "%20")
        return f"[{i['publisher'] or 'Source'}, {i['published'] or 'undated'}]({url})"
    lines = [f"{n}. {i['title']} {link(i)}" for n, i in enumerate(found["items"], 1)]
    outlets = len({i["publisher"] for i in found["items"]})
    thin = "" if outlets >= 3 else f"\n\nCoverage is thin: only {outlets} outlet(s) returned results."
    return (f"These are the latest headlines for “{found['query']}”, as reported by each outlet; no summary was written, "
            "so open the links for the full reports.\n\n### Sources\n\n" + "\n".join(lines) + thin
            + f"\n\n*Retrieved via {found['provider']} at {found['retrieved_at']}.*")


def reachability() -> dict[str, str]:
    """Each provider host: reachable (any HTTP answer) or blocked (no connection). No keys are sent."""
    def probe(host: str) -> tuple[str, str]:
        try:
            urllib.request.urlopen(urllib.request.Request(f"https://{host}/", headers={"User-Agent": _UA}), timeout=4).close()
            return host, "reachable"
        except urllib.error.HTTPError:
            return host, "reachable"
        except Exception as exc:
            return host, f"blocked ({type(exc).__name__})"
    with ThreadPoolExecutor(len(HOSTS)) as pool:
        return dict(pool.map(probe, HOSTS))
