"""Project knowledge: the repo's own docs, split by heading and searched with BM25. Small corpus, so no vector index.

shortcut: in-memory keyword search over a few dozen sections; move to Vector Search once docs number in the hundreds.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATHS = ("README.md", "ARCHITECTURE.md", "docs", "evals/REPORT.md")
_WORD = re.compile(r"[a-z0-9_]+")
_STOP = set("a an and are as at be by can do does for from how i in is it of on or our that the this to was we what when where which who why with you".split())


@dataclass(frozen=True)
class Passage:
    id: str
    file: str
    section: str
    text: str


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP]


def _sections(path: Path) -> list[Passage]:
    rel = path.relative_to(ROOT).as_posix()
    parts = re.split(r"(?m)^(#{1,3} .+)$", path.read_text(errors="ignore"))
    out, heading = [], path.stem
    for part in parts:
        if re.match(r"#{1,3} ", part):
            heading = part.lstrip("#").strip()
        elif part.strip():
            for n, start in enumerate(range(0, len(part), 1500)):  # long sections become ~1,500-character passages
                out.append(Passage(f"{rel}#{len(out) + 1}", rel, heading if not n else f"{heading} (cont.)", part[start:start + 1500].strip()))
    return out


@lru_cache(maxsize=1)
def corpus(paths: tuple[str, ...] = DEFAULT_PATHS) -> tuple[list[Passage], list[Counter], dict[str, int], float]:
    files = [f for p in paths for f in (sorted((ROOT / p).rglob("*.md")) if (ROOT / p).is_dir() else [ROOT / p]) if f.is_file()]
    passages = [s for f in files for s in _sections(f)]
    counts = [Counter(_tokens(f"{p.section} {p.text}")) for p in passages]
    df = Counter(t for c in counts for t in c)
    avg = sum(sum(c.values()) for c in counts) / max(len(counts), 1)
    return passages, counts, dict(df), avg


def search(query: str, k: int = 4, paths: tuple[str, ...] = DEFAULT_PATHS) -> list[Passage]:
    """BM25 top-k passages with a positive score."""
    passages, counts, df, avg = corpus(paths)
    terms = set(_tokens(query))
    scored = []
    for p, c in zip(passages, counts):
        length = sum(c.values())
        score = sum(math.log(1 + (len(passages) - df[t] + 0.5) / (df[t] + 0.5)) * c[t] * 2.2 / (c[t] + 1.2 * (0.25 + 0.75 * length / avg))
                    for t in terms if t in c)
        if score > 0:
            scored.append((score, p))
    return [p for _, p in sorted(scored, key=lambda x: -x[0])[:k]]
