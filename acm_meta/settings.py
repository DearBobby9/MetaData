"""Project-wide paths and constants."""

from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
PDF_DIR = BASE_DIR / "pdfs"
OUT_DIR = BASE_DIR / "output"
STATIC_DIR = BASE_DIR / "static"
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR = BASE_DIR / "data"

for directory in (PDF_DIR, OUT_DIR, STATIC_DIR, FRONTEND_DIR, DATA_DIR):
    directory.mkdir(parents=True, exist_ok=True)

INDEX_HTML = FRONTEND_DIR / "index.html"
RECORDS_JSON_PATH = DATA_DIR / "records.json"
RECORDS_CSV_PATH = DATA_DIR / "records.csv"
RECORDS_XLSX_PATH = DATA_DIR / "records.xlsx"
RECORDS_LOCK_PATH = DATA_DIR / "records.lock"

CSV_COLUMNS = [
    "Title",
    "Venue",
    "Publication year",
    "Author list",
    "Abstract",
    "DOI",
]

MAX_UPLOAD_BATCH = 20
MAX_UPLOAD_SIZE_MB = int(os.getenv("ACM_META_MAX_UPLOAD_MB", "25"))
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1MB chunks keep memory usage low during uploads
ALLOWED_UPLOAD_CONTENT_TYPES = {
    "application/pdf",
    "application/octet-stream",
}
