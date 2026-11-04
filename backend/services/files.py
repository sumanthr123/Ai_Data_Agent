"""Turn an uploaded file into something the council can use.

Data files (CSV, TSV, Excel, JSON, Parquet) are stored in a Unity Catalog Volume so the models can query them with
read_files(); documents and code become text; images are described by Gemini (the same key as web search).
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import PurePosixPath
from typing import Any

from databricks.sdk import WorkspaceClient

from backend.config import settings
from backend.services import web_search

MAX_BYTES = 25 * 1024 * 1024
MAX_TEXT = 40_000  # characters of extracted text kept per file
UPLOAD_ROOT = os.getenv("UPLOAD_VOLUME", f"/Volumes/{settings.catalog}/orders/uploads")

DATA_FORMATS = {".csv": "csv", ".tsv": "csv", ".json": "json", ".jsonl": "json", ".parquet": "parquet", ".xlsx": "csv", ".xlsm": "csv"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
               ".heic": "image/heic", ".bmp": "image/bmp"}


class UnsupportedFile(ValueError):
    pass


def process(w: WorkspaceClient, name: str, data: bytes, content_type: str = "") -> dict[str, Any]:
    if len(data) > MAX_BYTES:
        raise UnsupportedFile(f"{name} is {len(data) / 1e6:.1f} MB; the limit is {MAX_BYTES // 2**20} MB.")
    ext = PurePosixPath(name.lower()).suffix
    file_id = uuid.uuid4().hex[:12]
    base = {"id": file_id, "name": name, "size": len(data)}

    if ext in DATA_FORMATS:
        return {**base, **_data_file(w, file_id, name, ext, data)}
    if ext in IMAGE_TYPES or content_type.startswith("image/"):
        return {**base, "kind": "image", "text": _describe_image(data, IMAGE_TYPES.get(ext, content_type or "image/png"))}
    if ext == ".pdf":
        return {**base, "kind": "document", "text": _clip(_pdf_text(data))}
    if ext in (".docx", ".pptx"):
        return {**base, "kind": "document", "text": _clip(_office_text(data, ext))}
    text = _as_text(data)
    if text is None:
        raise UnsupportedFile(f"{name} looks like a binary file I can't read. Try PDF, Office, text, code, CSV, Excel, JSON, Parquet or an image.")
    return {**base, "kind": "code" if ext not in (".txt", ".md", ".log", "") else "text", "text": _clip(text)}


def _clip(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + f"\n\n[… truncated, {len(text) - MAX_TEXT:,} more characters]"


def _as_text(data: bytes) -> str | None:
    if b"\x00" in data[:4096]:
        return None
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _data_file(w: WorkspaceClient, file_id: str, name: str, ext: str, data: bytes) -> dict[str, Any]:
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", PurePosixPath(name).stem)[:60] or "file"
    if ext in (".xlsx", ".xlsm"):
        data = _excel_to_csv(data)
    fmt = DATA_FORMATS[ext]
    path = f"{UPLOAD_ROOT}/{file_id}/{stem}.{'csv' if fmt == 'csv' else ext.lstrip('.')}"
    w.files.upload(path, io.BytesIO(data), overwrite=True)
    options = {"csv": f"format => 'csv', header => true, inferSchema => true{', sep => ' + repr(chr(9)) if ext == '.tsv' else ''}",
               "json": "format => 'json'" + (", multiLine => true" if ext == ".json" else ""),
               "parquet": "format => 'parquet'"}[fmt]
    source = f"read_files('{path}', {options})"
    preview = _preview(data, ext) if fmt == "csv" or fmt == "json" else "(binary Parquet; query it to see rows)"
    return {"kind": "data", "table": source, "text": preview}


def _preview(data: bytes, ext: str, rows: int = 8) -> str:
    text = _as_text(data) or ""
    if ext in (".json", ".jsonl"):
        return text[:3000]
    reader = csv.reader(io.StringIO(text), delimiter="\t" if ext == ".tsv" else ",")
    lines = [r for _, r in zip(range(rows + 1), reader)]
    total = text.count("\n")
    return f"Columns: {', '.join(lines[0]) if lines else '(none)'}\nAbout {max(total - 1, 0):,} rows. First rows:\n" + \
        "\n".join(", ".join(r) for r in lines[1:])


def _excel_to_csv(data: bytes) -> bytes:
    from openpyxl import load_workbook

    sheet = load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
    out = io.StringIO()
    writer = csv.writer(out)
    for row in sheet.iter_rows(values_only=True):
        writer.writerow(["" if v is None else v for v in row])
    return out.getvalue().encode()


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    pages = PdfReader(io.BytesIO(data)).pages
    text = "\n\n".join(f"[Page {i + 1}]\n{p.extract_text() or ''}" for i, p in enumerate(pages[:200]))
    if not re.search(r"\w{3,}", text):
        raise UnsupportedFile("This PDF has no readable text (it may be scanned). Upload page images instead.")
    return text


def _office_text(data: bytes, ext: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = ["word/document.xml"] if ext == ".docx" else sorted(
            (n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
        parts = []
        for i, n in enumerate(names):
            xml = z.read(n).decode("utf-8", errors="ignore")
            xml = re.sub(r"</w:p>|</a:p>", "\n", xml)
            body = re.sub(r"<[^>]+>", "", xml)
            parts.append(body if ext == ".docx" else f"[Slide {i + 1}]\n{body}")
    return "\n".join(parts)


def _describe_image(data: bytes, mime: str) -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise UnsupportedFile("Images need the Gemini key (GEMINI_API_KEY) to be read.")
    body = {"contents": [{"role": "user", "parts": [
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}},
        {"text": "Describe this image in detail for someone who can't see it. Transcribe all visible text, numbers, "
                 "tables (as markdown) and chart values exactly."}]}]}
    request = urllib.request.Request(web_search.URL.format(model=web_search.MODEL), data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            out = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise UnsupportedFile(f"Couldn't read the image ({exc.code}).") from exc
    parts = ((out.get("candidates") or [{}])[0].get("content") or {}).get("parts", [])
    return _clip("".join(p.get("text", "") for p in parts)) or "(no description returned)"
