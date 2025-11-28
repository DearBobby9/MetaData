"""PDF helpers: DOI extraction and abstract fallbacks."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

import fitz
from pypdf import PdfReader

try:  # pypdf < 3 does not expose PdfReadError centrally
    from pypdf.errors import PdfReadError  # type: ignore
except Exception:  # pragma: no cover - fallback for older versions
    class PdfReadError(Exception):
        """Raised when a PDF cannot be parsed."""

from .errors import MetaError, MetaErrorCode


DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+\b")
logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_doi_candidates(pdf_path: Path, max_pages: int = 2) -> List[str]:
    try:
        reader = PdfReader(str(pdf_path))
    except (PdfReadError, OSError, ValueError) as exc:
        raise MetaError(MetaErrorCode.PDF_PARSE_FAILED, f"Failed to read {pdf_path.name}: {exc}") from exc
    text = ""
    for page in reader.pages[:max_pages]:
        text += page.extract_text() or ""
    candidates = []
    for match in DOI_RE.findall(text):
        cleaned = match.strip().rstrip(".,;")
        lowered = cleaned.lower()
        if lowered not in candidates:
            candidates.append(lowered)
    return candidates


def extract_abstract_from_pdf(pdf_path: Path, max_pages: int = 2) -> str:
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:  # pragma: no cover - PyMuPDF internals
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
        return _normalize_text(match.group(1))

    # Fallback to block parsing if regex fails
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:  # pragma: no cover - PyMuPDF internals
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
                    return _normalize_text(" ".join(abstract_chunks))
                abstract_chunks.append(text)
    finally:
        doc.close()

    return _normalize_text(" ".join(abstract_chunks))
