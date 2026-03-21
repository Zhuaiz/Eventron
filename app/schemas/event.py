"""Pydantic schemas for Event API."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EventCreate(BaseModel):
    """Request body for creating an event."""

    name: str = Field(..., max_length=200)
    description: Optional[str] = None
    event_date: Optional[datetime] = None
    location: Optional[str] = Field(None, max_length=300)
    venue_rows: int = Field(0, ge=0, le=200)
    venue_cols: int = Field(0, ge=0, le=200)
    layout_type: str = Field("theater", pattern=r"^(grid|theater|classroom|roundtable|banquet|u_shape)$")
    config: dict = Field(default_factory=dict)


class EventUpdate(BaseModel):
    """Request body for partial event update."""

    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    event_date: Optional[datetime] = None
    location: Optional[str] = Field(None, max_length=300)
    venue_rows: Optional[int] = Field(None, ge=0, le=200)
    venue_cols: Optional[int] = Field(None, ge=0, le=200)
    layout_type: Optional[str] = Field(
        None, pattern=r"^(grid|theater|classroom|roundtable|banquet|u_shape)$"
    )
    status: Optional[str] = Field(None, pattern=r"^(draft|active|completed|cancelled)$")
    config: Optional[dict] = None


class EventResponse(BaseModel):
    """Response body for event data."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: Optional[str]
    event_date: Optional[datetime]
    location: Optional[str]
    venue_rows: int
    venue_cols: int
    layout_type: str
    status: str
    created_by: Optional[str]
    config: dict
    created_at: datetime
    updated_at: datetime
