"""Typed models shared across the pipeline, API, and storage layers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional

try:  # Support both Pydantic v1 and v2
    from pydantic import BaseModel, Field, ConfigDict
except ImportError:  # pragma: no cover - fallback for old versions
    from pydantic import BaseModel, Field  # type: ignore[misc]
    ConfigDict = None  # type: ignore[assignment]

from .settings import CSV_COLUMNS


def generate_record_id(doi: str, file_name: str) -> str:
    doi_value = (doi or "").strip().lower()
    if doi_value:
        return f"doi:{doi_value}"
    return f"file:{(file_name or '').strip().lower()}"


class PaperRecord(BaseModel):
    id: str
    title: str = Field("", alias="Title")
    venue: str = Field("", alias="Venue")
    publication_year: Optional[int] = Field(None, alias="Publication year")
    author_list: str = Field("", alias="Author list")
    abstract: str = Field("", alias="Abstract")
    doi: str = Field("", alias="DOI")
    file_name: str
    source_url: str = ""
    saved_at: datetime

    if ConfigDict:
        model_config = ConfigDict(populate_by_name=True)
    else:  # pragma: no cover - Pydantic v1
        class Config:
            allow_population_by_field_name = True

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Map to the CSV/JSON schema expected by older clients."""

        legacy = {
            "Title": self.title,
            "Venue": self.venue,
            "Publication year": self.publication_year or "",
            "Author list": self.author_list,
            "Abstract": self.abstract,
            "DOI": self.doi,
            "file_name": self.file_name,
            "source_url": self.source_url,
            "saved_at": self.saved_at.replace(microsecond=0).isoformat() + "Z",
            "id": self.id,
        }
        return legacy

    @classmethod
    def from_legacy_dict(cls, data: Dict[str, Any]) -> "PaperRecord":
        publication_year = data.get("Publication year")
        if isinstance(publication_year, str) and publication_year.isdigit():
            publication_year = int(publication_year)
        elif isinstance(publication_year, int):
            publication_year = publication_year
        else:
            publication_year = None

        saved_at_raw = str(data.get("saved_at") or "")
        saved_at = datetime.utcnow()
        if saved_at_raw:
            try:
                saved_at = datetime.fromisoformat(saved_at_raw.rstrip("Z"))
            except ValueError:
                saved_at = datetime.utcnow()

        record_id = data.get("id") or generate_record_id(data.get("DOI", ""), data.get("file_name", ""))

        return cls(
            id=record_id,
            title=data.get("Title", ""),
            venue=data.get("Venue", ""),
            publication_year=publication_year,
            author_list=data.get("Author list", ""),
            abstract=data.get("Abstract", ""),
            doi=data.get("DOI", ""),
            file_name=data.get("file_name", data.get("Title", "")),
            source_url=data.get("source_url", ""),
            saved_at=saved_at,
        )


class UploadResponseItem(BaseModel):
    file_name: str
    status: Literal["ok", "error"]
    record: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    error_code: Optional[str] = None

    @classmethod
    def success(cls, record: PaperRecord) -> "UploadResponseItem":
        return cls(file_name=record.file_name, status="ok", record=record.to_legacy_dict())

    @classmethod
    def failure(cls, file_name: str, *, code: str, message: str) -> "UploadResponseItem":
        return cls(file_name=file_name, status="error", message=message, error_code=code)

    def to_payload(self) -> Dict[str, Any]:
        try:  # Pydantic v2
            return self.model_dump()
        except AttributeError:  # pragma: no cover - compatibility path for v1
            return self.dict()


def rows_from_records(records: list[PaperRecord]) -> list[Dict[str, Any]]:
    """Return sheet rows for CSV/JSON export."""

    return [{column: record.to_legacy_dict().get(column, "") for column in CSV_COLUMNS} for record in records]


EDITABLE_COLUMNS = [
    "Title",
    "Venue",
    "Publication year",
    "Author list",
    "Abstract",
    "DOI",
]
