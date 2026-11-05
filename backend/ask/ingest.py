"""Ingestion service: the only code path that writes data. Model-written SQL never runs here.

upload -> validate (size, type, encoding, sheets, columns) -> parse (malformed rows listed, never dropped silently)
-> infer column types in code (leading zeros stay text; ambiguous dates and mixed columns stay text, with a note)
-> stage raw + cleaned CSV in /Volumes/<catalog>/<schema>/<volume>/<user>/<conversation>/<upload>/
-> CREATE TABLE ... AS SELECT CAST(...) FROM read_files(cleaned CSV) -> verify row count -> profile -> register (TTL).
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import logging
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable

from databricks.sdk import WorkspaceClient

from backend.ask import profiling
from backend.ask.contracts import ColumnPlan, DatasetRecord, SheetInfo, UploadResult
from backend.ask.profiling import q, table_ref
from backend.ask.registry import Registry, now
from backend.ask.settings import AskSettings
from backend.ask.warehouse import Execution
from backend.schemas import ColumnNode

logger = logging.getLogger("ask.ingest")
EXTENSIONS = {".csv": "csv", ".tsv": "tsv", ".xlsx": "xlsx"}
MIME_OK = {"csv": {"text/csv", "text/plain", "application/vnd.ms-excel", "application/csv", "application/octet-stream", ""},
           "tsv": {"text/tab-separated-values", "text/plain", "application/octet-stream", ""},
           "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream", "application/zip", ""}}
NULL_TOKENS = {"na", "n/a", "null", "none", "nan", "#n/a", "-"}
_INT = re.compile(r"^[+-]?\d+$")
_DEC = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class UploadRejected(ValueError):
    pass


@dataclass
class Parsed:
    header: list[str]
    original: list[str]
    rows: list[list[str | None]]
    rejected: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def user_key(principal: str | None) -> str:
    return hashlib.sha256((principal or "local-user").lower().encode()).hexdigest()[:16]


def _id(value: str | None) -> str:
    if value and _SAFE_ID.match(value):
        return value.lower().replace("-", "_")
    return hashlib.sha256((value or "default").encode()).hexdigest()[:12]


# ---- validation and parsing --------------------------------------------------------------------------------------

def file_kind(name: str, content_type: str, data: bytes, cfg: AskSettings) -> str:
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    kind = EXTENSIONS.get(ext)
    if not kind:
        raise UploadRejected(f"Only CSV, TSV and XLSX files can become tables (got '{ext or 'no extension'}').")
    if (content_type or "").split(";")[0].strip().lower() not in MIME_OK[kind]:
        raise UploadRejected(f"The file type ({content_type}) doesn't match its .{kind} extension.")
    if len(data) > cfg.upload_max_mb * 1024 * 1024:
        raise UploadRejected(f"The file is larger than {cfg.upload_max_mb} MB.")
    if not data.strip():
        raise UploadRejected("The file is empty.")
    if kind == "xlsx" and not (data[:4] == b"PK\x03\x04" and zipfile.is_zipfile(io.BytesIO(data))):
        raise UploadRejected("This isn't a valid .xlsx workbook.")
    if kind != "xlsx" and b"\x00" in data[:65536]:
        raise UploadRejected("The file looks binary, not text CSV.")
    return kind


def sanitize_headers(raw: list[str]) -> tuple[list[str], list[str]]:
    """Safe, unique snake_case column names; untrusted header text never reaches SQL as-is."""
    names, notes = [], []
    for i, header in enumerate(raw):
        text = str(header or "").strip()
        name = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()[:64] or f"column_{i + 1}"
        if name[0].isdigit():
            name = f"c_{name}"
        base, n = name, 2
        while name in names:
            name, n = f"{base}_{n}", n + 1
        if name != text:
            notes.append(f"'{text[:40]}' → {name}")
        names.append(name)
    return names, notes


def _decode(data: bytes) -> tuple[str, list[str]]:
    try:
        return data.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), ["The file isn't UTF-8; it was read as Windows-1252. Check accented characters."]


def _finish(raw_header: list[str], body: list[list[str | None]], rejected: list[int], warnings: list[str], cfg: AskSettings) -> Parsed:
    if not raw_header or not any(str(h or "").strip() for h in raw_header):
        raise UploadRejected("The first row must be a header row.")
    if len(raw_header) > cfg.upload_max_columns:
        raise UploadRejected(f"The file has {len(raw_header)} columns; the limit is {cfg.upload_max_columns}.")
    if len(body) > cfg.upload_max_rows:
        raise UploadRejected(f"The file has more than {cfg.upload_max_rows:,} rows.")
    if not body:
        raise UploadRejected("The file has a header but no data rows.")
    header, renamed = sanitize_headers([str(h or "") for h in raw_header])
    if renamed:
        warnings.append("Column names were made SQL-safe: " + ", ".join(renamed[:8]) + (" …" if len(renamed) > 8 else ""))
    if rejected:
        warnings.append(f"{len(rejected):,} rows had the wrong number of fields and were not loaded (lines {', '.join(map(str, rejected[:10]))}"
                        + (" …" if len(rejected) > 10 else "") + ").")
    return Parsed(header, [str(h or "").strip() for h in raw_header], body, rejected, warnings)


def read_csv(data: bytes, kind: str, cfg: AskSettings) -> Parsed:
    text, warnings = _decode(data)
    delimiter = "\t" if kind == "tsv" else ","
    if kind == "csv":
        try:
            delimiter = csv.Sniffer().sniff(text[:65536], delimiters=",;|\t").delimiter
        except csv.Error:
            pass
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise UploadRejected("The file is empty.") from None
    body, rejected = [], []
    for row in reader:
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) != len(header):
            rejected.append(reader.line_num)
            continue
        body.append([cell for cell in row])
    return _finish(header, body, rejected, warnings, cfg)


def _openpyxl():
    import openpyxl

    return openpyxl


def xlsx_sheets(data: bytes, cfg: AskSettings) -> list[SheetInfo]:
    book = _openpyxl().load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        if len(book.sheetnames) > cfg.upload_max_sheets:
            raise UploadRejected(f"The workbook has {len(book.sheetnames)} sheets; the limit is {cfg.upload_max_sheets}.")
        return [SheetInfo(name=ws.title, rows=max(0, (ws.max_row or 1) - 1), columns=ws.max_column or 0) for ws in book.worksheets]
    finally:
        book.close()


def _cell(value: Any) -> tuple[str | None, bool]:
    """(text, is_error). Excel stores every number as a float; whole numbers are written without '.0'."""
    if value is None:
        return None, False
    if isinstance(value, bool):
        return ("true" if value else "false"), False
    if isinstance(value, float):
        return (str(int(value)) if value.is_integer() and abs(value) < 2 ** 53 else repr(value)), False
    if isinstance(value, int):
        return str(value), False
    if isinstance(value, dt.datetime):
        return (value.date().isoformat() if value.time() == dt.time() else value.isoformat()), False
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat(), False
    text = str(value)
    if text.startswith("#") and text.rstrip("!?0/").upper() in ("#DIV", "#N/A", "#VALUE", "#REF", "#NAME", "#NUM", "#NULL"):
        return None, True
    return text, False


def read_xlsx(data: bytes, sheet: str, cfg: AskSettings) -> Parsed:
    book = _openpyxl().load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        if sheet not in book.sheetnames:
            raise UploadRejected(f"There's no sheet named '{sheet}'.")
        rows = book[sheet].iter_rows(values_only=True)
        try:
            header = [(_cell(v)[0] or "") for v in next(rows)]
        except StopIteration:
            raise UploadRejected("The sheet is empty.") from None
        while header and not header[-1].strip():  # trailing empty header cells
            header.pop()
        body, errors = [], 0
        for raw in rows:
            cells = [_cell(v) for v in raw[: len(header)]] + [(None, False)] * max(0, len(header) - len(raw))
            errors += sum(1 for _, err in cells if err)
            values = [text for text, _ in cells]
            if any(v is not None and str(v).strip() for v in values):
                body.append(values)
        warnings = [f"{errors:,} formula error cells (#DIV/0!, #N/A, …) were loaded as NULL."] if errors else []
        return _finish(header, body, [], warnings, cfg)
    finally:
        book.close()


# ---- type inference ----------------------------------------------------------------------------------------------

def _slash_order(values: list[str]) -> str | None:
    """'MDY', 'DMY', or None when every value fits both (ambiguous)."""
    firsts, seconds = [int(_SLASH_DATE.match(v).group(1)) for v in values], [int(_SLASH_DATE.match(v).group(2)) for v in values]
    if any(f > 12 for f in firsts) and all(s <= 12 for s in seconds):
        return "DMY"
    if any(s > 12 for s in seconds) and all(f <= 12 for f in firsts):
        return "MDY"
    return None


def _valid_date(text: str) -> bool:
    try:
        dt.date.fromisoformat(text)
        return True
    except ValueError:
        return False


def infer(parsed: Parsed) -> tuple[list[ColumnPlan], list[list[str | None]]]:
    """Column types plus normalized rows (NULL tokens -> None, '1,234.5' -> '1234.5', 3/14/2017 -> 2017-03-14)."""
    plans: list[ColumnPlan] = []
    rows = [list(r) for r in parsed.rows]
    for i, name in enumerate(parsed.header):
        notes: list[str] = []
        nulls = 0
        for r in rows:
            v = r[i]
            if v is not None and (v.strip() == "" or v.strip().lower() in NULL_TOKENS):
                nulls += 1 if v.strip() else 0
                r[i] = None
        if nulls:
            notes.append(f"{nulls:,} values like 'N/A' or 'null' were treated as missing.")
        values = [r[i].strip() for r in rows if r[i] is not None]
        kind = "STRING"
        if values:
            ints = [v for v in values if _INT.match(v)]
            if len(ints) == len(values):
                if any(v.lstrip("+-").startswith("0") and len(v.lstrip("+-")) > 1 for v in ints):
                    notes.append("Has leading zeros, so it's kept as text.")
                elif all(-2 ** 63 <= int(v) < 2 ** 63 for v in ints):
                    kind = "BIGINT"
            elif all(_DEC.match(v) or _THOUSANDS.match(v) for v in values):
                kind = "DOUBLE"
                if any(_THOUSANDS.match(v) for v in values):
                    notes.append("Thousands separators were removed.")
                    for r in rows:
                        if r[i] is not None:
                            r[i] = r[i].strip().replace(",", "")
            elif all(v.lower() in ("true", "false") for v in values):
                kind = "BOOLEAN"
            elif all(_ISO_DATE.match(v) and _valid_date(v) for v in values):
                kind = "DATE"
            elif all(_ISO_TS.match(v) for v in values):
                kind = "TIMESTAMP"
            elif all(_SLASH_DATE.match(v) for v in values):
                order = _slash_order(values)
                if order is None:
                    notes.append("Dates like 03/04/2017 could be day/month or month/day; kept as text.")
                else:
                    converted = []
                    for v in values:
                        a, b, y = _SLASH_DATE.match(v).groups()
                        month, day = (a, b) if order == "MDY" else (b, a)
                        converted.append(f"{y}-{int(month):02d}-{int(day):02d}")
                    if all(_valid_date(c) for c in converted):
                        kind = "DATE"
                        notes.append(f"Dates parsed as {'month/day/year' if order == 'MDY' else 'day/month/year'}.")
                        it = iter(converted)
                        for r in rows:
                            if r[i] is not None:
                                r[i] = next(it)
            else:
                numeric = sum(1 for v in values if _DEC.match(v) or _THOUSANDS.match(v))
                if numeric and numeric >= 0.8 * len(values):
                    bad = next(v for v in values if not (_DEC.match(v) or _THOUSANDS.match(v)))
                    notes.append(f"{len(values) - numeric:,} of {len(values):,} values aren't numbers (e.g. '{bad[:20]}'); kept as text.")
        if kind != "STRING":
            for r in rows:
                if r[i] is not None:
                    r[i] = r[i].strip()
        plans.append(ColumnPlan(name=name, original=parsed.original[i], type=kind, notes=notes))
    return plans, rows


def to_csv(header: list[str], rows: list[list[str | None]]) -> bytes:
    """Cleaned CSV; NULL is an empty unquoted field, empty text is impossible after normalization."""
    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(header)
    for r in rows:
        writer.writerow(["" if v is None else v for v in r])
    return out.getvalue().encode("utf-8")


# ---- service -----------------------------------------------------------------------------------------------------

class IngestionService:
    def __init__(self, w: WorkspaceClient, cfg: AskSettings, registry: Registry, run: Callable[..., Execution]) -> None:
        self.w, self.cfg, self.registry, self.run = w, cfg, registry, run

    def upload(self, principal: str | None, conversation_id: str | None, file_name: str, content_type: str, data: bytes,
               sheet: str | None = None) -> UploadResult:
        kind = file_kind(file_name, content_type, data, self.cfg)
        safe_name = re.sub(r"[^\w .()-]", "_", file_name)[:120]
        if kind == "xlsx":
            sheets = xlsx_sheets(data, self.cfg)
            if not sheet:
                if len(sheets) != 1:
                    return UploadResult(status="NEEDS_SHEET", file_name=safe_name, sheets=sheets)
                sheet = sheets[0].name
            parsed = read_xlsx(data, sheet, self.cfg)
        else:
            parsed = read_csv(data, kind, self.cfg)
        plans, rows = infer(parsed)

        owner, conv, upload_id = user_key(principal), _id(conversation_id), uuid.uuid4().hex[:10]
        directory = f"/Volumes/{self.cfg.catalog}/{self.cfg.schema}/{self.cfg.upload_volume}/{owner}/{conv}/{upload_id}"
        table = f"{self.cfg.catalog}.{self.cfg.upload_schema}.u_{owner[:12]}_{upload_id}".lower()
        expires = (now() + dt.timedelta(hours=self.cfg.upload_ttl_hours)).isoformat(timespec="seconds")
        created = False
        try:
            self.w.files.upload(f"{directory}/original.{kind}", io.BytesIO(data), overwrite=False)
            self.w.files.upload(f"{directory}/data.csv", io.BytesIO(to_csv(parsed.header, rows)), overwrite=False)
            self.registry.ensure_table()
            casts = ", ".join(f"CAST({q(p.name)} AS {p.type}) AS {q(p.name)}" if p.type != "STRING" else q(p.name) for p in plans)
            comment = f"Uploaded file {safe_name}".replace("'", "")
            self.run(f"CREATE TABLE {table_ref(table)} COMMENT '{comment}' "
                     f"TBLPROPERTIES ('assistant.owner' = '{owner}', 'assistant.expires_at' = '{expires}') AS "
                     f"SELECT {casts} FROM read_files('{directory}/data.csv', format => 'csv', header => true, inferSchema => false, "
                     f"multiLine => true, escape => '\"', mode => 'FAILFAST')")
            created = True
            count = int(self.run(f"SELECT COUNT(*) AS n FROM {table_ref(table)}").result.rows[0]["n"])
            if count != len(rows):
                raise UploadRejected(f"Loaded {count:,} rows but the file has {len(rows):,}; the upload was rolled back.")
            if self.cfg.use_user_token and principal and _EMAIL.match(principal):
                # The app owns the table; the uploader gets read access so Unity Catalog allows their own queries.
                self.run(f"GRANT SELECT ON TABLE {table_ref(table)} TO {q(principal)}")
            columns = [ColumnNode(name=p.name, type=p.type.lower()) for p in plans]
            date_column = next((p.name for p in plans if p.type in ("DATE", "TIMESTAMP")), None)
            profile = profiling.profile(self.run, table, columns, [], date_column)
            notes = [f"{p.name}: {n}" for p in plans for n in p.notes]
            record = DatasetRecord(dataset=table, kind="upload", owner=owner, conversation_id=conv, source=f"{directory}/original.{kind}",
                                   description=f"Uploaded {safe_name}" + (f", sheet {sheet}" if sheet else ""),
                                   grain="one row per row of the uploaded file", original_names={p.name: p.original for p in plans},
                                   profile=profile, warnings=parsed.warnings + notes, created_at=now().isoformat(timespec="seconds"),
                                   refreshed_at=now().isoformat(timespec="seconds"), expires_at=expires, volume_dir=directory)
            self.registry.save(record)
        except Exception:
            self._remove(table if created else None, directory)
            raise
        return UploadResult(status="INGESTED", dataset=table, file_name=safe_name, sheet=sheet, columns=plans, row_count=len(rows),
                            rejected_rows=parsed.rejected[:100], rejected_row_count=len(parsed.rejected),
                            warnings=parsed.warnings + profile.warnings, profile=profile, expires_at=expires)

    def delete(self, principal: str | None, dataset: str) -> bool:
        record = self.registry.get(dataset)
        if not record or record.kind != "upload" or record.owner != user_key(principal):
            return False
        self._remove(record.dataset, record.volume_dir)
        self.registry.delete(record.dataset)
        return True

    def cleanup_expired(self) -> int:
        removed = 0
        for record in self.registry.expired():
            try:
                self._remove(record.dataset, record.volume_dir)
                self.registry.delete(record.dataset)
                removed += 1
            except Exception as exc:
                logger.warning("Couldn't remove expired upload %s: %s", record.dataset, exc)
        return removed

    def _remove(self, table: str | None, directory: str | None) -> None:
        if table:
            try:
                self.run(f"DROP TABLE IF EXISTS {table_ref(table)}")
            except Exception as exc:
                logger.warning("DROP TABLE %s failed: %s", table, exc)
        if directory:
            try:
                for entry in self.w.files.list_directory_contents(directory):
                    if entry.path and not entry.is_directory:
                        self.w.files.delete(entry.path)
                self.w.files.delete_directory(directory)
            except Exception as exc:
                logger.info("Cleanup of %s: %s", directory, exc)
            parent = directory
            for _ in range(2):  # the conversation and user folders, only once they're empty
                parent = parent.rsplit("/", 1)[0]
                try:
                    if any(True for _ in self.w.files.list_directory_contents(parent)):
                        break
                    self.w.files.delete_directory(parent)
                except Exception:
                    break


def register_volume_csv(cfg: AskSettings, run: Callable[..., Execution], path: str) -> tuple[str, int]:
    """DEFAULT_DATASET_SOURCE given as a Volume CSV: register it once as a typed Delta table. Rows that don't fit the
    inferred schema are kept, with the raw text in _rescued_data, and counted, never silently dropped."""
    if not re.match(r"^/Volumes/[\w-]+/[\w-]+/[\w-]+/[\w./ -]+\.csv$", path):
        raise ValueError("DEFAULT_DATASET_SOURCE must be a catalog.schema.table name or a /Volumes/.../file.csv path.")
    name = re.sub(r"[^0-9a-z]+", "_", path.rsplit("/", 1)[-1][:-4].lower()).strip("_") or "dataset"
    table = f"{cfg.catalog}.{cfg.schema}.{name}"
    run(f"CREATE TABLE IF NOT EXISTS {table_ref(table)} AS SELECT * FROM read_files('{path}', format => 'csv', header => true, "
        f"inferSchema => true, mode => 'PERMISSIVE', rescuedDataColumn => '_rescued_data')")
    rescued = int(run(f"SELECT COUNT_IF(_rescued_data IS NOT NULL) AS n FROM {table_ref(table)}").result.rows[0]["n"])
    return table, rescued
