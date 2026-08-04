"""Search Analytics models (spec 8.3, 8.5, 8.4)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SearchAnalyticsRow(BaseModel):
    """One row of search analytics data, with keys mapped to dimension names."""
    keys: dict[str, str] = Field(default_factory=dict)
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0.0
    position: float = 0.0


class Metrics(BaseModel):
    """A point-in-time metric snapshot for period comparison (spec 8.5)."""
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0.0
    position: float = 0.0


class Change(BaseModel):
    """Delta block for compare_periods (spec 4.6).

    `delta` and `*_percent` follow: positive = improvement for clicks/impressions;
    `position_improvement` is positive when position got better (lower number).
    """
    clicks: int = 0
    clicks_percent: float | None = None
    impressions: int = 0
    impressions_percent: float | None = None
    ctr_points: float = 0.0
    position_improvement: float | None = None
    status: str = "changed"


class ComparisonRow(BaseModel):
    """Spec 8.5 output row."""
    keys: dict[str, str]
    current: Metrics
    previous: Metrics
    change: Change


class PerformanceTotals(BaseModel):
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0.0
    position: float = 0.0


class PerformancePrevious(BaseModel):
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0.0
    position: float = 0.0


class DailyTrend(BaseModel):
    date: str
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0.0
    position: float = 0.0


class BreakdownEntry(BaseModel):
    key: str
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0.0
    position: float = 0.0


__all__ = [
    "SearchAnalyticsRow", "Metrics", "Change", "ComparisonRow",
    "PerformanceTotals", "PerformancePrevious", "DailyTrend", "BreakdownEntry",
]
