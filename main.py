import argparse
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "pdfs"
OUT_DIR = BASE_DIR / "output"
STATIC_DIR = BASE_DIR / "static"
FRONTEND_DIR = BASE_DIR / "frontend"
PDF_DIR.mkdir(exist_ok=True, parents=True)
OUT_DIR.mkdir(exist_ok=True, parents=True)
STATIC_DIR.mkdir(exist_ok=True, parents=True)
FRONTEND_DIR.mkdir(exist_ok=True, parents=True)

INDEX_HTML = FRONTEND_DIR / "index.html"

DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+\b")
CROSSREF_API_BASE = "https://api.crossref.org/works"


def extract_doi_from_pdf(pdf_path: Path, max_pages: int = 2) -> Optional[str]:
    """Extract DOI from the first few pages of the PDF."""

    reader = PdfReader(str(pdf_path))
    text = ""
    for page in reader.pages[:max_pages]:
        text += page.extract_text() or ""
    match = DOI_RE.search(text)
    return match.group(0) if match else None


def fetch_crossref_metadata(doi: str) -> Dict:
    """Fetch metadata payload from Crossref REST API."""

    url = f"{CROSSREF_API_BASE}/{doi}"
    headers = {
        "User-Agent": f"acm-meta-mvp/1.0 (mailto:{os.getenv('CROSSREF_MAILTO', 'nobody@example.com')})"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json().get("message", {})


def strip_tags(text: str) -> str:
    """Remove HTML-like tags from Crossref abstract field."""

    return re.sub(r"<[^>]+>", "", text).strip()


def normalize_metadata(message: Dict, file_name: str, doi_fallback: Optional[str]) -> Dict:
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


def process_single_pdf(pdf_path: Path) -> Dict:
    """Run DOI extraction + Crossref fetch for one PDF."""

    doi = extract_doi_from_pdf(pdf_path)
    if not doi:
        raise ValueError(f"DOI not found in {pdf_path.name}")

    metadata = fetch_crossref_metadata(doi)
    return normalize_metadata(metadata, pdf_path.name, doi)


def batch_process(pdf_dir: Path = PDF_DIR) -> List[Dict]:
    """Process every PDF inside pdf_dir."""

    results: List[Dict] = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        print(f"[INFO] Processing: {pdf.name}")
        try:
            info = process_single_pdf(pdf)
            results.append(info)
            print(f"       ✔ DOI={info['sheet_row']['DOI']}")
        except Exception as exc:
            print(f"       ✖ Failed: {exc}")
    return results


def save_outputs(results: List[Dict]):
    """Persist JSON + CSV outputs for downstream use."""

    json_data = [item["full"] for item in results]
    json_path = OUT_DIR / "metadata.json"
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] JSON written to {json_path}")

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
    print(f"[INFO] CSV written to {csv_path}")


app = FastAPI(title="ACM Meta MVP")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=FileResponse)
def read_index():
    """Serve the front-end shell."""

    return FileResponse(INDEX_HTML)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    """Upload single PDF and return metadata row."""

    pdf_path = PDF_DIR / file.filename
    with pdf_path.open("wb") as dest:
        dest.write(await file.read())

    try:
        result = process_single_pdf(pdf_path)
        return JSONResponse({
            "status": "ok",
            "data": result["sheet_row"],
            "debug": {
                "file_name": result["full"]["file_name"],
                "source_url": result["full"].get("source_url", ""),
            },
        })
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)


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
