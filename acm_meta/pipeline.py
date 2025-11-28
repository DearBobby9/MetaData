"""High-level orchestration of the metadata extraction pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from fastapi import UploadFile

from .crossref_client import CrossrefClient
from .errors import MetaError, MetaErrorCode
from .models import PaperRecord
from .normalize import normalize_metadata
from .pdf_io import extract_doi_candidates
from .settings import (
    ALLOWED_UPLOAD_CONTENT_TYPES,
    CSV_COLUMNS,
    MAX_UPLOAD_SIZE_BYTES,
    MAX_UPLOAD_SIZE_MB,
    OUT_DIR,
    PDF_DIR,
    UPLOAD_CHUNK_SIZE,
)
from .storage import RecordStore


logger = logging.getLogger(__name__)

_FILENAME_SANITIZER = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_display_name(filename: Optional[str]) -> str:
    candidate = (filename or "upload.pdf").strip()
    candidate = Path(candidate).name or "upload.pdf"
    sanitized = _FILENAME_SANITIZER.sub("_", candidate)
    if not sanitized:
        sanitized = "upload.pdf"
    suffix = Path(sanitized).suffix.lower()
    if suffix != ".pdf":
        stem = Path(sanitized).stem or "upload"
        sanitized = f"{stem}.pdf"
    return sanitized[:120]


def _allocate_storage_path(base_name: str) -> Path:
    target = PDF_DIR / base_name
    if not target.exists():
        return target
    stem = Path(base_name).stem or "upload"
    suffix = Path(base_name).suffix or ".pdf"
    for _ in range(32):
        candidate = PDF_DIR / f"{stem}_{uuid4().hex[:8]}{suffix}"
        if not candidate.exists():
            return candidate
    raise MetaError(MetaErrorCode.UNKNOWN_ERROR, "Unable to allocate storage for upload")


def _validate_upload(upload: UploadFile, display_name: str) -> None:
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type and content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
        raise MetaError(MetaErrorCode.INVALID_FILE_TYPE, "Only PDF uploads are supported")
    if not display_name.lower().endswith(".pdf"):
        raise MetaError(MetaErrorCode.INVALID_FILE_TYPE, "Only PDF uploads are supported")


async def _write_upload_to_disk(upload: UploadFile, destination: Path) -> None:
    total_bytes = 0
    try:
        with destination.open("wb") as buffer:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_SIZE_BYTES:
                    with suppress(FileNotFoundError):
                        destination.unlink()
                    raise MetaError(
                        MetaErrorCode.FILE_TOO_LARGE,
                        f"PDF exceeds the {MAX_UPLOAD_SIZE_MB}MB upload limit",
                    )
                buffer.write(chunk)
        if total_bytes == 0:
            with suppress(FileNotFoundError):
                destination.unlink()
            raise MetaError(MetaErrorCode.INVALID_FILE_TYPE, "Uploaded file was empty")
    finally:
        await upload.close()


class MetadataPipeline:
    def __init__(self, store: RecordStore, client: CrossrefClient) -> None:
        self.store = store
        self.client = client

    def _process_pdf(self, pdf_path: Path, *, display_name: Optional[str] = None) -> Tuple[PaperRecord, Dict[str, Any]]:
        candidates = extract_doi_candidates(pdf_path)
        if not candidates:
            raise MetaError(MetaErrorCode.DOI_NOT_FOUND, f"DOI not found in {pdf_path.name}")

        last_error: MetaError | None = None
        for doi in candidates:
            try:
                message = self.client.fetch_metadata(doi)
                record, full = normalize_metadata(
                    message,
                    file_name=display_name or pdf_path.name,
                    doi_fallback=doi,
                    pdf_path=pdf_path,
                )
                return record, full
            except MetaError as exc:
                last_error = exc
                if exc.code not in {MetaErrorCode.CROSSREF_NOT_FOUND}:
                    raise
                logger.info("Candidate DOI %s failed: %s", doi, exc)
                continue

        raise last_error or MetaError(MetaErrorCode.DOI_NOT_FOUND, f"DOI not found in {pdf_path.name}")

    def process_local_pdf(self, pdf_path: Path, *, display_name: Optional[str] = None) -> Tuple[PaperRecord, Dict[str, Any]]:
        record, full = self._process_pdf(pdf_path, display_name=display_name)
        existing = self.store.find_by_doi(record.doi)
        if existing:
            record.id = existing.id
        self.store.upsert(record)
        logger.info("Persisted record %s", record.id)
        return record, full

    async def process_upload(self, upload: UploadFile) -> Tuple[PaperRecord, Dict[str, Any]]:
        display_name = _sanitize_display_name(upload.filename)
        _validate_upload(upload, display_name)
        storage_path = _allocate_storage_path(display_name)

        try:
            await _write_upload_to_disk(upload, storage_path)
            return await asyncio.to_thread(
                self.process_local_pdf,
                storage_path,
                display_name=display_name,
            )
        except Exception:
            with suppress(FileNotFoundError):
                storage_path.unlink()
            raise

    def batch_process(self, pdf_dir: Path = PDF_DIR) -> List[Tuple[PaperRecord, Dict[str, Any]]]:
        results: List[Tuple[PaperRecord, Dict[str, Any]]] = []
        for pdf in sorted(pdf_dir.glob("*.pdf")):
            logger.info("Processing %s", pdf.name)
            try:
                results.append(self.process_local_pdf(pdf, display_name=pdf.name))
            except MetaError as exc:
                logger.error("Failed to process %s: %s", pdf.name, exc)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Unexpected failure while processing %s", pdf.name)
        return results


def save_outputs(results: Sequence[Tuple[PaperRecord, Dict[str, Any]]]) -> None:
    json_data = [full for _, full in results]
    json_path = OUT_DIR / "metadata.json"
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")

    sheet_rows = [record.to_legacy_dict() for record, _ in results]
    df_path = OUT_DIR / "metadata_for_spreadsheet.csv"
    import pandas as pd

    df = pd.DataFrame(sheet_rows or [], columns=CSV_COLUMNS)
    df.to_csv(df_path, index=False, encoding="utf-8-sig")
    logger.info("Batch outputs written to %s and %s", json_path, df_path)
