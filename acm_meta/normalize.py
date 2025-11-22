"""Translate Crossref payloads into PaperRecord instances."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import PaperRecord, generate_record_id
from .pdf_io import extract_abstract_from_pdf


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _normalize_author(author: Dict[str, Any]) -> str:
    given = author.get("given") or ""
    family = author.get("family") or ""
    full = " ".join(part for part in [given, family] if part)
    return full.strip()


def _coerce_year(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_metadata(
    message: Dict[str, Any],
    *,
    file_name: str,
    doi_fallback: Optional[str],
    pdf_path: Optional[Path] = None,
) -> Tuple[PaperRecord, Dict[str, Any]]:
    title_list = message.get("title") or []
    title = title_list[0] if title_list else ""

    authors: List[str] = []
    for author in message.get("author", []):
        full = _normalize_author(author)
        if full:
            authors.append(full)
    author_list_str = ", ".join(authors)

    issued = message.get("issued", {}).get("date-parts", [[None]])
    year = issued[0][0] if issued and issued[0] else None
    publication_year = _coerce_year(year)

    venue_list = message.get("container-title") or []
    venue = venue_list[0] if venue_list else ""

    doi = (message.get("DOI") or doi_fallback or "").strip()

    abstract_raw = message.get("abstract")
    abstract = strip_tags(abstract_raw) if isinstance(abstract_raw, str) else ""
    if not abstract and pdf_path is not None and pdf_path.exists():
        abstract = extract_abstract_from_pdf(pdf_path)

    saved_at = datetime.utcnow()
    record = PaperRecord(
        id=generate_record_id(doi, file_name),
        title=title,
        venue=venue,
        publication_year=publication_year,
        author_list=author_list_str,
        abstract=abstract,
        doi=doi,
        file_name=file_name,
        source_url=message.get("URL", ""),
        saved_at=saved_at,
    )

    full = {
        "file_name": file_name,
        "title": title,
        "venue": venue,
        "year": publication_year,
        "authors": authors,
        "abstract": abstract,
        "doi": doi,
        "source_url": message.get("URL", ""),
        "raw_crossref": message,
        "record_id": record.id,
        "saved_at": saved_at.isoformat() + "Z",
    }

    return record, full
