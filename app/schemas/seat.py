"""Pydantic schemas for Seat API."""

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class SeatCreate(BaseModel):
    """Request body for creating a seat."""

    row_num: int = Field(..., ge=1)
    col_num: int = Field(..., ge=1)
    label: Optional[str] = Field(None, max_length=20)
    seat_type: str = Field("normal", pattern=r"^(normal|reserved|disabled|aisle)$")
    zone: Optional[str] = Field(None, max_length=50)


class SeatUpdate(BaseModel):
    """Request body for updating a seat."""

    label: Optional[str] = Field(None, max_length=20)
    seat_type: Optional[str] = Field(
        None, pattern=r"^(normal|reserved|disabled|aisle)$"
    )
    zone: Optional[str] = Field(None, max_length=50)
    attendee_id: Optional[uuid.UUID] = None


class SeatResponse(BaseModel):
    """Response body for seat data."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    event_id: uuid.UUID
    row_num: int
    col_num: int
    label: Optional[str]
    seat_type: str
    zone: Optional[str]
    attendee_id: Optional[uuid.UUID]


class AutoAssignRequest(BaseModel):
    """Request body for auto-assigning seats."""

    strategy: str = Field(
        "random",
        pattern=r"^(random|priority_first|by_department|by_zone)$",
    )
    # priority_first: high-priority attendees get front/center seats
    # by_zone: match attendee priority to seat zones
