"""Pydantic schemas for Attendee API."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AttendeeCreate(BaseModel):
    """Request body for adding an attendee."""

    name: str = Field(..., max_length=100)
    title: Optional[str] = Field(None, max_length=200)
    organization: Optional[str] = Field(None, max_length=200)
    department: Optional[str] = Field(None, max_length=100)
    role: str = Field("参会者", max_length=50)
    # Free-text label: "甲方嘉宾", "参展商", "工作人员", etc.
    priority: int = Field(0, ge=0, le=100)
    # Higher = more important. 0=普通, 10=important, 20+=VIP-level
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=200)
    attrs: dict = Field(default_factory=dict)


class AttendeeUpdate(BaseModel):
    """Request body for partial attendee update."""

    name: Optional[str] = Field(None, max_length=100)
    title: Optional[str] = Field(None, max_length=200)
    organization: Optional[str] = Field(None, max_length=200)
    department: Optional[str] = Field(None, max_length=100)
    role: Optional[str] = Field(None, max_length=50)
    priority: Optional[int] = Field(None, ge=0, le=100)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=200)
    status: Optional[str] = Field(
        None, pattern=r"^(pending|confirmed|checked_in|absent|cancelled)$"
    )
    attrs: Optional[dict] = None


class AttendeeResponse(BaseModel):
    """Response body for attendee data."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    title: Optional[str]
    organization: Optional[str]
    department: Optional[str]
    role: str
    priority: int
    phone: Optional[str]
    email: Optional[str]
    attrs: dict
    status: str
    wecom_user_id: Optional[str]
    lark_user_id: Optional[str]
    created_at: datetime
    updated_at: datetime
