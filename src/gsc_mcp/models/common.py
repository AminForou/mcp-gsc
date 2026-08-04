"""Common Pydantic models shared across tools (spec 7.1, 8.3)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..config import VALID_DIMENSIONS, VALID_FILTER_OPERATORS


class DateRange(BaseModel):
    start: str
    end: str
    timezone: str = "America/Los_Angeles"


class Pagination(BaseModel):
    start_row: int = 0
    page_size: int = 500
    returned_rows: int = 0
    has_more: bool = False
    next_start_row: int | None = None


class Filter(BaseModel):
    """A single dimension filter (spec 8.3)."""
    dimension: str = Field(..., description="query, page, country, device, date, hour, searchAppearance")
    operator: str = Field(..., description="contains, equals, notContains, notEquals, includingRegex, excludingRegex")
    expression: str

    @field_validator("dimension")
    @classmethod
    def _validate_dimension(cls, v: str) -> str:
        if v not in VALID_DIMENSIONS:
            raise ValueError(
                f"Invalid filter dimension {v!r}. Valid: {VALID_DIMENSIONS}."
            )
        return v

    @field_validator("operator")
    @classmethod
    def _validate_operator(cls, v: str) -> str:
        if v not in VALID_FILTER_OPERATORS:
            raise ValueError(
                f"Invalid filter operator {v!r}. Valid: {VALID_FILTER_OPERATORS}."
            )
        return v


class ToolMeta(BaseModel):
    """The `meta` block of the success envelope (spec 7.2)."""
    client_id: str | None = None
    client_name: str | None = None
    site_url: str
    date_range: DateRange
    search_type: str = "web"
    data_state: str = "final"
    data_may_be_incomplete: bool = False
    first_incomplete_date: str | None = None
    response_aggregation_type: str = "auto"
    rows_examined: int = 0
    warnings: list[str] = Field(default_factory=list)
    model_config = {"extra": "allow"}  # tools may add tool-specific meta fields


__all__ = ["DateRange", "Pagination", "Filter", "ToolMeta"]
