"""High-level orchestration of the metadata extraction pipeline."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from fastapi import UploadFile

from .crossref_client import CrossrefClient
from .errors import MetaError, MetaErrorCode
from .models import PaperRecord
from .normalize import normalize_metadata
from .pdf_io import extract_doi_candidates
from .settings import CSV_COLUMNS, OUT_DIR, PDF_DIR
from .storage import RecordStore


logger = logging.getLogger(__name__)


class MetadataPipeline:
    def __init__(self, store: RecordStore, client: CrossrefClient) -> None:
        self.store = store
        self.client = client

    def _process_pdf(self, pdf_path: Path) -> Tuple[PaperRecord, Dict[str, Any]]:
        candidates = extract_doi_candidates(pdf_path)
        if not candidates:
            raise MetaError(MetaErrorCode.DOI_NOT_FOUND, f"DOI not found in {pdf_path.name}")

        last_error: MetaError | None = None
        for doi in candidates:
            try:
                message = self.client.fetch_metadata(doi)
                record, full = normalize_metadata(
                    message,
                    file_name=pdf_path.name,
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

    def process_local_pdf(self, pdf_path: Path) -> Tuple[PaperRecord, Dict[str, Any]]:
        record, full = self._process_pdf(pdf_path)
        self.store.upsert(record)
        logger.info("Persisted record %s", record.id)
        return record, full

    async def process_upload(self, upload: UploadFile) -> Tuple[PaperRecord, Dict[str, Any]]:
        pdf_path = PDF_DIR / upload.filename
        contents = await upload.read()
        pdf_path.write_bytes(contents)
        return self.process_local_pdf(pdf_path)

    def batch_process(self, pdf_dir: Path = PDF_DIR) -> List[Tuple[PaperRecord, Dict[str, Any]]]:
        results: List[Tuple[PaperRecord, Dict[str, Any]]] = []
        for pdf in sorted(pdf_dir.glob("*.pdf")):
            logger.info("Processing %s", pdf.name)
            try:
                results.append(self.process_local_pdf(pdf))
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
    if not sheet_rows:
        return
    df_path = OUT_DIR / "metadata_for_spreadsheet.csv"
    import pandas as pd

    df = pd.DataFrame(sheet_rows, columns=CSV_COLUMNS)
    df.to_csv(df_path, index=False, encoding="utf-8-sig")
    logger.info("Batch outputs written to %s and %s", json_path, df_path)
