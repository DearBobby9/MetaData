"""Domain-specific exceptions and error codes."""

from __future__ import annotations

from enum import Enum


class MetaErrorCode(str, Enum):
    DOI_NOT_FOUND = "DOI_NOT_FOUND"
    CROSSREF_NOT_FOUND = "CROSSREF_NOT_FOUND"
    CROSSREF_RATE_LIMIT = "CROSSREF_RATE_LIMIT"
    CROSSREF_SERVER_ERROR = "CROSSREF_SERVER_ERROR"
    CROSSREF_REQUEST_FAILED = "CROSSREF_REQUEST_FAILED"
    PDF_PARSE_FAILED = "PDF_PARSE_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class MetaError(Exception):
    """Exception raised for controlled pipeline failures."""

    def __init__(self, code: MetaErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
