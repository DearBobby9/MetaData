"""Project-wide paths and constants."""

from __future__ import annotations

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
