"""URL Inspection models (spec 8.10, 8.11)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RichResults(BaseModel):
    verdict: str = "UNKNOWN"
    detected_types: list[str] = Field(default_factory=list)
    issues: list[dict[str, str | None]] = Field(default_factory=list)


class InspectionResult(BaseModel):
    """Spec 8.10 output for a single URL."""
    page_url: str
    site_url: str
    verdict: str = "UNKNOWN"
    coverage_state: str | None = None
    indexing_state: str | None = None
    last_crawl_time: str | None = None
    crawled_as: str | None = None
    robots_txt_state: str | None = None
    page_fetch_state: str | None = None
    user_canonical: str | None = None
    google_canonical: str | None = None
    referring_urls: list[str] = Field(default_factory=list)
    rich_results: RichResults | None = None
    inspection_result_link: str | None = None


class BatchInspectionItem(BaseModel):
    """One entry in a batch inspection result."""
    url: str
    ok: bool = True
    verdict: str | None = None
    coverage_state: str | None = None
    last_crawl_time: str | None = None
    rich_results: str | None = None
    error: str | None = None


class BatchInspectionSummary(BaseModel):
    succeeded: int = 0
    failed: int = 0
    indexed: int = 0
    not_indexed: int = 0


__all__ = [
    "InspectionResult", "RichResults", "BatchInspectionItem",
    "BatchInspectionSummary",
]
