"""Persistent storage for PaperRecord entries."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, List, Optional, Sequence

try:
    import fcntl  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

import pandas as pd

from .models import EDITABLE_COLUMNS, PaperRecord, rows_from_records
from .settings import (
    CSV_COLUMNS,
    RECORDS_CSV_PATH,
    RECORDS_JSON_PATH,
    RECORDS_LOCK_PATH,
    RECORDS_XLSX_PATH,
)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(path)


class _FileLock:
    """Minimal cross-platform lock that prefers fcntl when available."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._thread_lock = threading.Lock()
        self._handle = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()

    def acquire(self) -> None:
        self._thread_lock.acquire()
        if fcntl:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle = self._path.open("a+")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            self._handle = handle

    def release(self) -> None:
        if fcntl and self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None
        self._thread_lock.release()


class RecordStore:
    def __init__(self) -> None:
        self._records: List[PaperRecord] = []
        self._lock = threading.Lock()
        self._file_lock = _FileLock(RECORDS_LOCK_PATH)
        self._load()

    def _normalize_doi(self, doi: str) -> str:
        return (doi or "").strip().lower()

    def _load(self) -> None:
        if RECORDS_JSON_PATH.exists():
            try:
                raw_data = json.loads(RECORDS_JSON_PATH.read_text(encoding="utf-8"))
                if not isinstance(raw_data, list):
                    raw_data = []
            except json.JSONDecodeError:
                raw_data = []
        else:
            raw_data = []

        records: List[PaperRecord] = []
        for item in raw_data:
            if isinstance(item, dict):
                records.append(PaperRecord.from_legacy_dict(item))

        self._records = records
        self._persist_files()

    def _persist_files(self) -> None:
        rows = [record.to_legacy_dict() for record in self._records]
        with self._file_lock:
            _atomic_write_bytes(
                RECORDS_JSON_PATH,
                json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            export_rows = rows_from_records(self._records)
            df = pd.DataFrame(export_rows, columns=CSV_COLUMNS)
            tmp_csv = RECORDS_CSV_PATH.with_suffix(".csv.tmp")
            df.to_csv(tmp_csv, index=False, encoding="utf-8-sig")
            tmp_csv.replace(RECORDS_CSV_PATH)

    def snapshot(self) -> List[Dict]:
        with self._lock:
            return [record.to_legacy_dict() for record in self._records]

    def reversed_snapshot(self) -> List[Dict]:
        with self._lock:
            return [record.to_legacy_dict() for record in reversed(self._records)]

    def upsert(self, record: PaperRecord) -> PaperRecord:
        with self._lock:
            for idx, existing in enumerate(self._records):
                if existing.id == record.id:
                    self._records[idx] = record
                    break
            else:
                self._records.append(record)
            self._persist_files()
            return record

    def get_by_id(self, record_id: str) -> Optional[PaperRecord]:
        with self._lock:
            for record in self._records:
                if record.id == record_id:
                    return record
        return None

    def find_by_doi(self, doi: str) -> Optional[PaperRecord]:
        normalized = self._normalize_doi(doi)
        if not normalized:
            return None
        with self._lock:
            for record in self._records:
                if self._normalize_doi(record.doi) == normalized:
                    return record
        return None

    def delete(self, record_id: str) -> bool:
        with self._lock:
            for idx, record in enumerate(self._records):
                if record.id == record_id:
                    del self._records[idx]
                    self._persist_files()
                    return True
            return False

    def reorder(self, order: Sequence[str]) -> None:
        with self._lock:
            id_to_record = {record.id: record for record in self._records}
            new_list: List[PaperRecord] = []
            seen = set()
            for record_id in order:
                record = id_to_record.get(record_id)
                if record and record_id not in seen:
                    new_list.append(record)
                    seen.add(record_id)
            for record in self._records:
                if record.id not in seen:
                    new_list.append(record)
            self._records = new_list
            self._persist_files()

    def export_xlsx(self) -> Path:
        with self._lock:
            export_rows = rows_from_records(self._records)
        df = pd.DataFrame(export_rows, columns=CSV_COLUMNS)
        tmp_path = RECORDS_XLSX_PATH.with_suffix(".xlsx.tmp")
        df.to_excel(tmp_path, index=False)
        tmp_path.replace(RECORDS_XLSX_PATH)
        return RECORDS_XLSX_PATH

    def flush(self) -> None:
        with self._lock:
            self._persist_files()

    def update_fields(self, record_id: str, updates: Dict[str, object]) -> Dict:
        if not updates:
            raise ValueError("No updates provided")
        for field in updates:
            if field not in EDITABLE_COLUMNS:
                raise ValueError(f"Field {field} not editable")
        with self._lock:
            for idx, record in enumerate(self._records):
                if record.id == record_id:
                    legacy = record.to_legacy_dict()
                    legacy.update(updates)
                    updated = PaperRecord.from_legacy_dict(legacy)
                    self._records[idx] = updated
                    self._persist_files()
                    return updated.to_legacy_dict()
        raise KeyError(f"Record {record_id} not found")
