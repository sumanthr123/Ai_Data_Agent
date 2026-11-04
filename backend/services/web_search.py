"""Live web search through Gemini with Google Search grounding (REST, key from the Databricks secret).

Returns an evidence summary with numbered [n] markers tied to the pages that support each claim, and the sources
resolved to their real pages (title, publisher, publication date) instead of Google's grounding redirect links.
Everything fetched from the web is untrusted data: it is quoted to the models, never followed as instructions.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MODEL = os.getenv("WEB_SEARCH_MODEL", "gemini-flash-latest")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_UA = "Mozilla/5.0 (compatible; DatabricksDataAgent/1.0)"

SEARCH_PROMPT = """Current date and time: {now} ({tz}). Interpret "today", "now", "latest" and "this year" relative to it.
Using Google Search, answer factually: {query}

Rules:
- Prefer primary and official sources (government, election authorities, the organization itself, regulators) over aggregators.
- State the date or reporting time of every figure you give (e.g. "as of 9:40 PM ET, Nov 3").
- For elections: keep projections/calls, reported vote counts (with % reporting) and certified official results clearly separate;
  never present a projection as certified. Don't mix different election years or reporting times without saying so.
- If sources conflict or current information is not available yet, say so plainly instead of guessing.
- Never invent figures, quotes, seat counts, dates or sources."""


def available() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def local_now(timezone: str) -> tuple[str, str]:
    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz, timezone = ZoneInfo("UTC"), "UTC"
    return dt.datetime.now(tz).strftime("%A, %B %d, %Y %I:%M %p %Z"), timezone


def search(query: str, timezone: str = "UTC", timeout: float = 45.0) -> dict[str, Any]:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Web search isn't configured (GEMINI_API_KEY is missing).")
    now, tz = local_now(timezone)
    body = {"contents": [{"role": "user", "parts": [{"text": SEARCH_PROMPT.format(now=now, tz=tz, query=query)}]}],
            "tools": [{"google_search": {}}]}
    request = urllib.request.Request(URL.format(model=MODEL), data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="ignore")[:200]
        raise RuntimeError(f"Web search failed ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Web search couldn't be reached: {exc}") from exc
    candidate = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (candidate.get("content") or {}).get("parts", [])).strip()
    meta = candidate.get("groundingMetadata") or {}
    retrieved = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary, sources = cite(text, meta.get("groundingChunks") or [], meta.get("groundingSupports") or [], retrieved)
    if not text:
        raise RuntimeError("Web search returned no results.")
    return {"query": query, "searched_at": f"{now} ({tz})", "retrieved_at": retrieved, "summary": summary, "sources": sources}


def cite(text: str, chunks: list[dict[str, Any]], supports: list[dict[str, Any]], retrieved: str) -> tuple[str, list[dict[str, Any]]]:
    """Insert [n] after each supported claim and resolve the cited chunks to real pages, numbered in citation order."""
    used: list[int] = []
    for s in supports:
        for idx in s.get("groundingChunkIndices") or []:
            if idx not in used and idx < len(chunks):
                used.append(idx)
    pages = _resolve_all([(chunks[i].get("web") or {}) for i in used])
    number: dict[int, int] = {}
    sources: list[dict[str, Any]] = []
    by_url: dict[str, int] = {}
    for idx, page in zip(used, pages):
        if page is None:  # a search-results page or unreachable link is not a supporting source
            continue
        if page["url"] in by_url:  # two grounding chunks for the same page share one number
            number[idx] = by_url[page["url"]]
            continue
        number[idx] = by_url[page["url"]] = len(sources) + 1
        sources.append({"n": number[idx], **page, "retrieved_at": retrieved})
    # Insert markers after each supported segment, last first so earlier offsets stay valid.
    marked = text
    spans = []
    for s in supports:
        seg = (s.get("segment") or {}).get("text") or ""
        nums = sorted({number[i] for i in s.get("groundingChunkIndices") or [] if i in number})
        pos = marked.find(seg) if seg else -1
        if nums and pos >= 0:
            spans.append((pos + len(seg), "".join(f"[{n}]" for n in nums)))
    for end, marker in sorted(spans, reverse=True):
        marked = marked[:end] + marker + marked[end:]
    return marked, sources


def _resolve_all(webs: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(_resolve, webs))


def _resolve(web: dict[str, Any]) -> dict[str, Any] | None:
    """Follow Google's grounding redirect to the real page and read its title, publisher and publish date."""
    uri, fallback = web.get("uri") or "", (web.get("title") or "").strip()
    if not uri:
        return None
    final, head = uri, ""
    try:
        req = urllib.request.Request(uri, headers={"User-Agent": _UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=6) as response:
            final = response.geturl()
            head = response.read(300_000).decode("utf-8", errors="ignore")
    except Exception:
        pass
    host = urllib.parse.urlparse(final).netloc.lower().removeprefix("www.")
    if _is_search_page(final):
        return None
    if "vertexaisearch.cloud.google.com" in host:  # couldn't follow the redirect: keep it, labelled by the domain
        return {"title": fallback or "Source", "publisher": fallback, "url": uri, "published": ""}
    title = _meta(head, "og:title") or _tag(head, "title") or fallback or host
    publisher = _meta(head, "og:site_name") or fallback or host
    published = (_meta(head, "article:published_time") or _meta(head, "datePublished") or _jsonld_date(head)
                 or _attr(head, r"<time[^>]+datetime=\"([^\"]+)\""))
    return {"title": _clean(title)[:200], "publisher": _clean(publisher)[:80], "url": final, "published": _date(published)}


def _is_search_page(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    return ("google." in p.netloc or "bing.com" in p.netloc or "duckduckgo.com" in p.netloc) and p.path.startswith("/search")


def _meta(page: str, name: str) -> str:
    return _attr(page, rf"<meta[^>]+(?:property|name|itemprop)=[\"']{re.escape(name)}[\"'][^>]+content=[\"']([^\"']+)") or \
        _attr(page, rf"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+(?:property|name|itemprop)=[\"']{re.escape(name)}[\"']")


def _tag(page: str, tag: str) -> str:
    return _attr(page, rf"<{tag}[^>]*>([^<]+)</{tag}>")


def _jsonld_date(page: str) -> str:
    return _attr(page, r"\"datePublished\"\s*:\s*\"([^\"]+)\"")


def _attr(page: str, pattern: str) -> str:
    m = re.search(pattern, page, re.I | re.S)
    return m.group(1).strip() if m else ""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _date(value: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", value or "")
    return m.group(1) if m else ""
