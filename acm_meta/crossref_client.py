"""HTTP client for Crossref with retry semantics."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict

import requests

from .errors import MetaError, MetaErrorCode


logger = logging.getLogger(__name__)


class CrossrefClient:
    def __init__(
        self,
        *,
        mailto: str | None = None,
        timeout: float = 15,
        max_retries: int = 2,
        backoff: float = 1.5,
    ) -> None:
        self.base_url = "https://api.crossref.org/works"
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        contact = mailto or os.getenv("CROSSREF_MAILTO", "nobody@example.com")
        self.headers = {"User-Agent": f"acm-meta-mvp/0.2.1 (mailto:{contact})"}
        self.session = requests.Session()

    def fetch_metadata(self, doi: str) -> Dict[str, Any]:
        url = f"{self.base_url}/{doi}"
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.get(url, headers=self.headers, timeout=self.timeout)
            except requests.RequestException as exc:
                logger.warning("Crossref request failed (%s/%s): %s", attempt + 1, self.max_retries + 1, exc)
                if attempt == self.max_retries:
                    raise MetaError(
                        MetaErrorCode.CROSSREF_REQUEST_FAILED,
                        f"Crossref request failed for DOI {doi}: {exc}",
                    ) from exc
                time.sleep(self.backoff ** attempt)
                continue

            if resp.status_code == 404:
                raise MetaError(MetaErrorCode.CROSSREF_NOT_FOUND, f"Crossref could not find DOI {doi}")
            if resp.status_code == 429:
                logger.warning("Crossref rate limit encountered for %s (%s/%s)", doi, attempt + 1, self.max_retries + 1)
                if attempt == self.max_retries:
                    raise MetaError(
                        MetaErrorCode.CROSSREF_RATE_LIMIT,
                        "Crossref rate limit reached. Try again shortly.",
                    )
                time.sleep(self.backoff ** (attempt + 1))
                continue
            if 500 <= resp.status_code < 600:
                logger.warning(
                    "Crossref server error %s for %s (%s/%s)",
                    resp.status_code,
                    doi,
                    attempt + 1,
                    self.max_retries + 1,
                )
                if attempt == self.max_retries:
                    raise MetaError(
                        MetaErrorCode.CROSSREF_SERVER_ERROR,
                        f"Crossref temporary error ({resp.status_code}) for DOI {doi}",
                    )
                time.sleep(self.backoff ** (attempt + 1))
                continue

            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:  # pragma: no cover - requests internals
                raise MetaError(
                    MetaErrorCode.CROSSREF_REQUEST_FAILED,
                    f"Crossref request error ({resp.status_code}) for DOI {doi}",
                ) from exc

            payload = resp.json()
            return payload.get("message", {})

        raise MetaError(
            MetaErrorCode.CROSSREF_REQUEST_FAILED,
            f"Crossref request failed for DOI {doi}",
        )
