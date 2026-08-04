"""Sitemap models (spec 4.7, 8.12, 8.13)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SitemapContent(BaseModel):
    """Distinct `submitted` and `indexed` counts (spec 4.7)."""
    type: str = "web"
    submitted_urls: int = 0
    indexed_urls: int | None = None


class Sitemap(BaseModel):
    """One sitemap entry (spec 8.12)."""
    path: str
    last_submitted: str | None = None
    last_downloaded: str | None = None
    is_pending: bool = False
    is_sitemap_index: bool = False
    errors: int = 0
    warnings: int = 0
    contents: list[SitemapContent] = Field(default_factory=list)


class SitemapDetails(BaseModel):
    """Spec 8.13 output."""
    sitemap_url: str
    site_url: str
    type: str = "Sitemap"
    status: str = "processed"
    last_submitted: str | None = None
    last_downloaded: str | None = None
    errors: int = 0
    warnings: int = 0
    contents: list[SitemapContent] = Field(default_factory=list)
    is_index: bool = False


__all__ = ["Sitemap", "SitemapDetails", "SitemapContent"]
