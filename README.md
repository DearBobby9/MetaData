# acm-meta-mvp (v0.2)

Metadata-first pipeline for ACM Digital Library PDFs. The project extracts spreadsheet-ready metadata (Title, Venue, Year, Authors, Abstract, DOI) so the teacher’s sheet can be filled with minimal manual work. Representative figures and video links remain placeholders for now.

## Version 0.2 – Release Notes

- Added mouse-driven resizing for metadata-table columns and rows so reviewers can adjust column widths or row heights directly in the UI.
- Converted the entire documentation to English and removed Chinese text from the repository.
- Continued polishing the persistent metadata table (drag-to-reorder, inline delete, CSV/JSON/Excel export, adjustable font size).

---

## 1. Requirements & Field Breakdown

### 1.1 Target Data Schema

Each paper occupies one spreadsheet row. Column definitions stay fixed:

| Column | Description | Constraint |
| --- | --- | --- |
| Title | Paper title | Use the original English title; avoid trailing punctuation |
| Venue | Conference or journal name | Prefer the full official name (e.g., `CHI Conference on Human Factors in Computing Systems`) |
| Publication year | Year of publication | Four-digit integer (e.g., `2022`) |
| Author list | Authors in `Given Family` format | Join with `, `; do not include `and` or periods |
| Abstract | Paper abstract | Plain English paragraph with the `ABSTRACT` label removed |
| Representative figure | Hero image placeholder | Currently always `N/A` in the MVP; later versions may insert a filename |
| DOI | Digital Object Identifier | e.g., `10.1145/3491102.3502071` |
| Video | Public video URL | Only YouTube/Vimeo accepted; fallback to `N/A` |

### 1.2 Core Metadata Fields

The MVP automates Title, Venue, Publication year, Author list, Abstract, and DOI. Representative figure and Video are manual placeholders that will be handled in later releases.

---

## 2. Roadmap & Priority

### 2.1 V0 / MVP (current scope)

- Batch or web uploads for ACM DL PDFs (assuming each PDF contains a DOI).
- Extract DOI from the first pages, query Crossref `/works/{doi}`, and normalize fields.
- Produce two outputs:
  - `output/metadata.json`: verbose record for downstream automation.
  - `output/metadata_for_spreadsheet.csv`: column order matches the teacher’s sheet with `N/A` placeholders.

### 2.2 V1 (next)

- CLI or UI helpers for manually attaching representative figures and video links.
- Scripts that export all images contained in a PDF.

### 2.3 V2+ (long-term)

- Automatically discover official video links or recommend candidates.
- Rank images to help select a teaser.
- Generate “making of” prompts, XR browsing experiences, and other exploratory features.

---

## 3. MVP Documentation

### 3.1 Overview

- **Project name:** `acm-meta-mvp`
- **Goal:** Given ACM DL PDFs, automatically output Title / Venue / Year / Authors / Abstract / DOI that can be pasted directly into the teacher’s spreadsheet.
- **Pipeline:** PDF → DOI extraction → Crossref metadata → normalization → JSON & CSV.

### 3.2 Tech Stack

- Python 3.10+
- FastAPI + Uvicorn: Web API (`/api/upload`)
- PyPDF/PyMuPDF: extract DOI/abstract snippets from PDFs
- Requests: call Crossref
- Pandas: build CSV/Excel exports
- python-dotenv: read Crossref email for the polite User-Agent

### 3.3 Directory Layout

```text
MetaData/
├─ README.md
├─ requirements.txt
├─ main.py
├─ config.example.env
├─ data/
│  └─ .gitkeep              # becomes records.json / records.csv after runs
├─ frontend/
│  └─ index.html
├─ static/
│  ├─ app.js
│  └─ styles.css
├─ pdfs/
└─ output/
```

`frontend/index.html` plus everything in `static/` power the web UI. Run `python main.py serve` and open `http://127.0.0.1:8000/` to batch-upload PDFs (max 20) and manage the persistent metadata table.

### 3.4 Dependencies & Configuration

`requirements.txt`

```txt
fastapi
uvicorn[standard]
pypdf
requests
pandas
python-dotenv
python-multipart
pymupdf
openpyxl
```

`config.example.env`

```env
CROSSREF_MAILTO=your_email@example.com
```

Copy to `.env` and replace the email with a real inbox for Crossref’s User-Agent guidelines.

### 3.5 Core Pipeline (`main.py`)

1. **DOI extraction:** Use `pypdf` to read the first two pages and apply `r"10\.\d{4,9}/[^\s\"<>]+"`.
2. **Crossref lookup:** `GET https://api.crossref.org/works/{doi}` with the configured email in the User-Agent.
3. **Field normalization:**
   - Title: `message.title[0]`.
   - Venue: `container-title[0]`.
   - Publication year: `issued.date-parts[0][0]`.
   - Author list: join `given family` names with `, `.
   - Abstract: prefer Crossref, otherwise extract from the PDF’s “Abstract” paragraph via PyMuPDF.
   - DOI: returned DOI or the PDF fallback.
4. **Outputs:**
   - `metadata_for_spreadsheet.csv`: eight columns with figure/video at `N/A`.
5. **API modes:** `/api/upload` handles a single file, `POST /api/upload/batch` processes multiple PDFs, and `python main.py batch` runs over everything inside `pdfs/`.

### 3.6 Persistence & Batch API

- `POST /api/upload/batch`: accepts up to 20 `files`, returns status per file, and saves successes to `data/records.json` and `data/records.csv`. Missing abstracts are auto extracted from the PDF.
- `GET /api/records`: returns all stored records (most recent first); the frontend uses this for the metadata table.
- `DELETE /api/records/{id}`: deletes a record (triggered by the table’s Delete button).
- `POST /api/records/reorder`: persists drag-and-drop ordering from the UI.
- `GET /api/export`: downloads `data/records.csv`.
- `GET /api/export/json`: downloads the JSON dataset.
- `GET /api/export/xlsx`: downloads an Excel workbook built with `openpyxl`.

### 3.7 Running the Project

1. **Environment setup**

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp config.example.env .env  # then edit CROSSREF_MAILTO
   mkdir -p pdfs output
   ```

2. **Batch extraction**

   ```bash
   python main.py batch
   ```

   Outputs land in `output/metadata.json` and `output/metadata_for_spreadsheet.csv` with the teacher’s column order, using `N/A` for figure/video.

3. **Web UI**

   ```bash
   python main.py serve
   ```

   Browse to `http://127.0.0.1:8000/` to access:

   - **Upload PDFs**: drag/drop ≤20 files and watch metadata cards appear instantly; the status list shows success/failure for each file.
   - **Metadata Table**: browse persistent records, delete rows, drag to reorder, resize columns/rows, tweak font size, and export CSV/JSON/Excel. All data persists under `data/`.
   - CLI users can also call the API directly (sample `curl` commands live in the code comments).

4. **All-in-one helper**

   ```bash
   ./run.sh
   ```

   Ensures virtualenv/requirements/env vars exist, then launches `python main.py serve`.

### 3.8 Status Snapshot

- ✅ Automatic metadata: DOI detection + Crossref + CSV/JSON/Excel export.
- ✅ Persistent metadata table with drag/drop, delete, column/row resize, font slider, and multi-format export.
- ✅ Documentation and UI strings fully in English.
- ⏳ Upcoming (V1): representative figure picker, video link helper, image export script.
- 🔭 Future (V2+): automated video discovery, teaser recommendations, AI-powered tooling.

---

Happy metadata harvesting! Contributions, bug reports, and feature ideas are welcome—file an issue or open a pull request.
