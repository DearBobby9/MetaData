import argparse
import json
import logging
import os
import re
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader
import fitz
from pydantic import BaseModel


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger("acm_meta")


class MetaErrorCode(str, Enum):
    DOI_NOT_FOUND = "DOI_NOT_FOUND"
    CROSSREF_NOT_FOUND = "CROSSREF_NOT_FOUND"
    CROSSREF_RATE_LIMIT = "CROSSREF_RATE_LIMIT"
    CROSSREF_SERVER_ERROR = "CROSSREF_SERVER_ERROR"
    CROSSREF_REQUEST_FAILED = "CROSSREF_REQUEST_FAILED"
    PDF_PARSE_FAILED = "PDF_PARSE_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class MetaError(Exception):
    def __init__(self, code: MetaErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "pdfs"
OUT_DIR = BASE_DIR / "output"
STATIC_DIR = BASE_DIR / "static"
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR = BASE_DIR / "data"
PDF_DIR.mkdir(exist_ok=True, parents=True)
OUT_DIR.mkdir(exist_ok=True, parents=True)
STATIC_DIR.mkdir(exist_ok=True, parents=True)
FRONTEND_DIR.mkdir(exist_ok=True, parents=True)
DATA_DIR.mkdir(exist_ok=True, parents=True)

INDEX_HTML = FRONTEND_DIR / "index.html"
RECORDS_JSON_PATH = DATA_DIR / "records.json"
RECORDS_CSV_PATH = DATA_DIR / "records.csv"
RECORDS_XLSX_PATH = DATA_DIR / "records.xlsx"
CSV_COLUMNS = [
    "Title",
    "Venue",
    "Publication year",
    "Author list",
    "Abstract",
    "Representative figure",
    "DOI",
    "Video",
]
MAX_UPLOAD_BATCH = 20

PERSISTED_RECORDS: List[Dict] = []
RECORDS_LOCK = Lock()


class ReorderPayload(BaseModel):
    order: List[str]

DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+\b")
CROSSREF_API_BASE = "https://api.crossref.org/works"


def _record_identifier(row: Dict, file_name: str) -> str:
    doi = (row.get("DOI") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    return f"file:{file_name.strip().lower()}"


def _write_records_to_disk() -> None:
    records_copy = list(PERSISTED_RECORDS)
    RECORDS_JSON_PATH.write_text(
        json.dumps(records_copy, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rows_for_csv = [
        {col: record.get(col, "") for col in CSV_COLUMNS}
        for record in records_copy
    ]
    df = pd.DataFrame(rows_for_csv, columns=CSV_COLUMNS)
    df.to_csv(RECORDS_CSV_PATH, index=False, encoding="utf-8-sig")


def _generate_excel_file() -> Path:
    rows_for_excel = [
        {col: record.get(col, "") for col in CSV_COLUMNS}
        for record in PERSISTED_RECORDS
    ]
    df = pd.DataFrame(rows_for_excel, columns=CSV_COLUMNS)
    df.to_excel(RECORDS_XLSX_PATH, index=False)
    return RECORDS_XLSX_PATH


def _load_records_from_disk() -> None:
    if RECORDS_JSON_PATH.exists():
        try:
            data = json.loads(RECORDS_JSON_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                PERSISTED_RECORDS.clear()
                PERSISTED_RECORDS.extend(data)
        except json.JSONDecodeError:
            PERSISTED_RECORDS.clear()
    else:
        PERSISTED_RECORDS.clear()
    _write_records_to_disk()


def persist_sheet_row(row: Dict, file_name: str, source_url: str = "") -> Dict:
    entry = dict(row)
    entry["file_name"] = file_name
    entry["source_url"] = source_url
    entry["saved_at"] = datetime.utcnow().isoformat() + "Z"
    entry["id"] = _record_identifier(row, file_name)

    with RECORDS_LOCK:
        existing_idx = next(
            (idx for idx, record in enumerate(PERSISTED_RECORDS) if record.get("id") == entry["id"]),
            None,
        )
        if existing_idx is not None:
            PERSISTED_RECORDS[existing_idx] = entry
        else:
            PERSISTED_RECORDS.append(entry)
        _write_records_to_disk()
    return entry


def get_records_snapshot() -> List[Dict]:
    with RECORDS_LOCK:
        return list(PERSISTED_RECORDS)


_load_records_from_disk()


def delete_record_by_id(record_id: str) -> bool:
    with RECORDS_LOCK:
        for idx, record in enumerate(PERSISTED_RECORDS):
            if record.get("id") == record_id:
                del PERSISTED_RECORDS[idx]
                _write_records_to_disk()
                return True
    return False


def reorder_records(order: List[str]) -> None:
    with RECORDS_LOCK:
        id_to_record = {record.get("id"): record for record in PERSISTED_RECORDS}
        new_list: List[Dict] = []
        seen = set()
        for record_id in order:
            record = id_to_record.get(record_id)
            if record and record_id not in seen:
                new_list.append(record)
                seen.add(record_id)
        for record in PERSISTED_RECORDS:
            record_id = record.get("id")
            if record_id not in seen:
                new_list.append(record)
        PERSISTED_RECORDS.clear()
        PERSISTED_RECORDS.extend(new_list)
        _write_records_to_disk()


def extract_doi_from_pdf(pdf_path: Path, max_pages: int = 2) -> Optional[str]:
    """Extract DOI from the first few pages of the PDF."""

    reader = PdfReader(str(pdf_path))
    text = ""
    for page in reader.pages[:max_pages]:
        text += page.extract_text() or ""
    match = DOI_RE.search(text)
    return match.group(0) if match else None


def fetch_crossref_metadata(doi: str, retries: int = 2, backoff: float = 1.5) -> Dict:
    """Fetch metadata payload from Crossref REST API with retry semantics."""

    url = f"{CROSSREF_API_BASE}/{doi}"
    headers = {
        "User-Agent": f"acm-meta-mvp/1.1 (mailto:{os.getenv('CROSSREF_MAILTO', 'nobody@example.com')})"
    }
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
        except requests.RequestException as exc:  # network errors
            logger.warning("Crossref request failed (attempt %s/%s): %s", attempt + 1, retries + 1, exc)
            if attempt == retries:
                raise MetaError(
                    MetaErrorCode.CROSSREF_REQUEST_FAILED,
                    f"Crossref request failed for DOI {doi}: {exc}",
                ) from exc
            time.sleep(backoff ** attempt)
            continue

        if resp.status_code == 404:
            raise MetaError(
                MetaErrorCode.CROSSREF_NOT_FOUND,
                f"Crossref could not find DOI {doi}",
            )
        if resp.status_code == 429:
            logger.warning("Crossref rate limit encountered for DOI %s (attempt %s)", doi, attempt + 1)
            if attempt == retries:
                raise MetaError(
                    MetaErrorCode.CROSSREF_RATE_LIMIT,
                    "Crossref rate limit reached. Try again shortly.",
                )
            time.sleep(backoff ** (attempt + 1))
            continue
        if 500 <= resp.status_code < 600:
            logger.warning(
                "Crossref server error %s for DOI %s (attempt %s)",
                resp.status_code,
                doi,
                attempt + 1,
            )
            if attempt == retries:
                raise MetaError(
                    MetaErrorCode.CROSSREF_SERVER_ERROR,
                    f"Crossref temporary error ({resp.status_code}) for DOI {doi}",
                )
            time.sleep(backoff ** (attempt + 1))
            continue

        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise MetaError(
                MetaErrorCode.CROSSREF_REQUEST_FAILED,
                f"Crossref request error ({resp.status_code}) for DOI {doi}",
            ) from exc

        return resp.json().get("message", {})

    raise MetaError(
        MetaErrorCode.CROSSREF_REQUEST_FAILED,
        f"Crossref request failed for DOI {doi}",
    )


def strip_tags(text: str) -> str:
    """Remove HTML-like tags from Crossref abstract field."""

    return re.sub(r"<[^>]+>", "", text).strip()


def normalize_metadata(
    message: Dict,
    file_name: str,
    doi_fallback: Optional[str],
    pdf_path: Optional[Path] = None,
) -> Dict:
    """Map Crossref message to sheet row + full payload."""

    title_list = message.get("title") or []
    title = title_list[0] if title_list else ""

    authors: List[str] = []
    for author in message.get("author", []):
        given = author.get("given") or ""
        family = author.get("family") or ""
        full = " ".join(part for part in [given, family] if part)
        if full:
            authors.append(full)
    author_list_str = ", ".join(authors)

    issued = message.get("issued", {}).get("date-parts", [[None]])
    year = issued[0][0] if issued and issued[0] else ""

    venue_list = message.get("container-title") or []
    venue = venue_list[0] if venue_list else ""

    doi = message.get("DOI") or doi_fallback or ""

    abstract_raw = message.get("abstract")
    abstract = strip_tags(abstract_raw) if isinstance(abstract_raw, str) else ""
    if not abstract and pdf_path is not None and pdf_path.exists():
        abstract = extract_abstract_from_pdf(pdf_path)

    sheet_row = {
        "Title": title,
        "Venue": venue,
        "Publication year": year,
        "Author list": author_list_str,
        "Abstract": abstract,
        "Representative figure": "N/A",
        "DOI": doi,
        "Video": "N/A",
    }

    full = {
        "file_name": file_name,
        "title": title,
        "venue": venue,
        "year": year,
        "authors": authors,
        "abstract": abstract,
        "doi": doi,
        "source_url": message.get("URL", ""),
        "raw_crossref": message,
    }

    return {"sheet_row": sheet_row, "full": full}


def persist_result_bundle(result: Dict) -> Dict:
    full = result["full"]
    row = result["sheet_row"]
    return persist_sheet_row(row, full.get("file_name", ""), full.get("source_url", ""))


def extract_abstract_from_pdf(pdf_path: Path, max_pages: int = 2) -> str:
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        logger.warning("Failed to open PDF %s for abstract extraction: %s", pdf_path.name, exc)
        return ""

    try:
        text_buffer: List[str] = []
        for page_index in range(min(max_pages, len(doc))):
            page = doc.load_page(page_index)
            text_buffer.append(page.get_text("text"))
        raw_text = "\n".join(text_buffer)
    finally:
        doc.close()

    normalized = raw_text.replace("\r", "\n")
    pattern = re.compile(
        r"(?is)abstract[:\s-]*\n?(.*?)(?:\n\s*(keywords|index terms|ccs concepts|author keywords|introduction|1\.|i\.)|\Z)"
    )
    match = pattern.search(normalized)
    if match:
        abstract_text = match.group(1).strip()
        return re.sub(r"\s+", " ", abstract_text)

    # Fallback to block-based approach if pattern fails
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        logger.warning("Failed to reopen PDF %s for block parsing: %s", pdf_path.name, exc)
        return ""

    abstract_chunks: List[str] = []
    target_found = False
    try:
        for page_index in range(min(max_pages, len(doc))):
            page = doc.load_page(page_index)
            blocks = page.get_text("blocks")
            blocks.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))
            for block in blocks:
                text = (block[4] or "").strip()
                if not text:
                    continue
                lowered = text.lower()
                if not target_found:
                    if lowered.startswith("abstract"):
                        cleaned = re.sub(r"^abstract[:\s-]*", "", text, flags=re.IGNORECASE).strip()
                        if cleaned:
                            abstract_chunks.append(cleaned)
                        target_found = True
                    continue
                if re.match(r"^(keywords|index terms|ccs concepts|author keywords|introduction|1\.\s)", lowered):
                    return " ".join(abstract_chunks).strip()
                abstract_chunks.append(text)
    finally:
        doc.close()
    return " ".join(abstract_chunks).strip()


def process_single_pdf(pdf_path: Path) -> Dict:
    """Run DOI extraction + Crossref fetch for one PDF."""

    doi = extract_doi_from_pdf(pdf_path)
    if not doi:
        raise MetaError(
            MetaErrorCode.DOI_NOT_FOUND,
            f"DOI not found in {pdf_path.name}",
        )

    metadata = fetch_crossref_metadata(doi)
    return normalize_metadata(metadata, pdf_path.name, doi, pdf_path=pdf_path)


def batch_process(pdf_dir: Path = PDF_DIR) -> List[Dict]:
    """Process every PDF inside pdf_dir."""

    results: List[Dict] = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        logger.info("Processing %s", pdf.name)
        try:
            info = process_single_pdf(pdf)
            persist_result_bundle(info)
            results.append(info)
            logger.info("Successfully processed DOI=%s", info["sheet_row"].get("DOI", ""))
        except MetaError as exc:
            logger.error("Failed to process %s: %s", pdf.name, exc)
        except Exception as exc:  # pragma: no cover - unexpected failures
            logger.exception("Unexpected failure while processing %s", pdf.name)
    return results


def save_outputs(results: List[Dict]):
    """Persist JSON + CSV outputs for downstream use."""

    json_data = [item["full"] for item in results]
    json_path = OUT_DIR / "metadata.json"
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("JSON written to %s", json_path)

    sheet_rows = [item["sheet_row"] for item in results]
    df = pd.DataFrame(sheet_rows, columns=[
        "Title",
        "Venue",
        "Publication year",
        "Author list",
        "Abstract",
        "Representative figure",
        "DOI",
        "Video",
    ])
    csv_path = OUT_DIR / "metadata_for_spreadsheet.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    logger.info("CSV written to %s", csv_path)


async def handle_uploaded_pdf(upload: UploadFile) -> Dict:
    pdf_path = PDF_DIR / upload.filename
    with pdf_path.open("wb") as dest:
        dest.write(await upload.read())

    try:
        result = process_single_pdf(pdf_path)
        stored = persist_result_bundle(result)
        logger.info("Persisted record %s", stored.get("id"))
        return {
            "status": "ok",
            "file_name": upload.filename,
            "data": stored,
            "debug": {
                "file_name": stored.get("file_name", upload.filename),
                "source_url": stored.get("source_url", result["full"].get("source_url", "")),
            },
        }
    except MetaError as exc:
        logger.warning("Business error while processing %s: %s", upload.filename, exc)
        return {
            "status": "error",
            "file_name": upload.filename,
            "code": exc.code,
            "message": exc.message,
        }
    except Exception as exc:
        logger.exception("Unexpected error while processing %s", upload.filename)
        return {
            "status": "error",
            "file_name": upload.filename,
            "code": MetaErrorCode.UNKNOWN_ERROR,
            "message": str(exc),
        }


app = FastAPI(title="ACM Meta MVP")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=FileResponse)
def read_index():
    """Serve the front-end shell."""

    return FileResponse(INDEX_HTML)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    """Upload single PDF and return metadata row."""

    result = await handle_uploaded_pdf(file)
    status_code = 200 if result.get("status") == "ok" else 400
    return JSONResponse(result, status_code=status_code)


@app.post("/api/upload/batch")
async def upload_batch(files: List[UploadFile] = File(...)):
    """Upload multiple PDFs (up to MAX_UPLOAD_BATCH) and persist their metadata."""

    if not files:
        return JSONResponse({"status": "error", "error": "No files provided"}, status_code=400)
    if len(files) > MAX_UPLOAD_BATCH:
        return JSONResponse(
            {"status": "error", "error": f"Maximum {MAX_UPLOAD_BATCH} files per upload"},
            status_code=400,
        )

    responses: List[Dict] = []
    for upload_file in files:
        responses.append(await handle_uploaded_pdf(upload_file))

    success = any(item.get("status") == "ok" for item in responses)
    overall_status = "ok" if success else "error"
    body: Dict[str, object] = {"status": overall_status, "items": responses}
    if not success:
        first_error = next(
            (item for item in responses if item.get("status") == "error"),
            None,
        )
        if first_error:
            body["error"] = first_error.get("message")
            body["code"] = first_error.get("code")
    return JSONResponse(body)


@app.get("/api/records")
def list_records():
    """Return persisted metadata entries (newest first)."""

    records = list(reversed(get_records_snapshot()))
    return {"records": records}


@app.delete("/api/records/{record_id}")
def delete_record(record_id: str):
    if delete_record_by_id(record_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Record not found")


@app.post("/api/records/reorder")
def reorder_records_endpoint(payload: ReorderPayload):
    if not payload.order:
        raise HTTPException(status_code=400, detail="Order list required")
    reorder_records(payload.order)
    return {"status": "ok"}


@app.get("/api/export")
def export_records():
    """Download the persisted metadata CSV."""

    if not RECORDS_CSV_PATH.exists():
        _write_records_to_disk()
    return FileResponse(RECORDS_CSV_PATH, filename="metadata_records.csv")


@app.get("/api/export/json")
def export_records_json():
    if not RECORDS_JSON_PATH.exists():
        _write_records_to_disk()
    return FileResponse(RECORDS_JSON_PATH, filename="metadata_records.json")


@app.get("/api/export/xlsx")
def export_records_xlsx():
    with RECORDS_LOCK:
        if not PERSISTED_RECORDS:
            _write_records_to_disk()
        path = _generate_excel_file()
    return FileResponse(path, filename="metadata_records.xlsx")


def main():
    parser = argparse.ArgumentParser(description="ACM Meta MVP")
    parser.add_argument(
        "mode",
        nargs="?",
        default="batch",
        choices=["batch", "serve"],
        help="batch: process pdfs/ directory; serve: launch API",
    )
    args = parser.parse_args()

    if args.mode == "batch":
        results = batch_process(PDF_DIR)
        save_outputs(results)
    elif args.mode == "serve":
        import uvicorn

        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()

