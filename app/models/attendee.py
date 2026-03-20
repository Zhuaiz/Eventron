"""Attendee ORM model — core entity with title and extensible attrs."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.seat import Seat


class Attendee(Base, UUIDMixin, TimestampMixin):
    """A person attending an event."""

    __tablename__ = "attendees"

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id"))
    name: Mapped[str] = mapped_column(String(100))
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    organization: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="参会者")
    # Free-text label (e.g. "甲方嘉宾", "参展商", "工作人员")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    # Higher = more important. Used for seating (front-row, VIP zones).
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Flexible extra attributes — JSONB for future extensibility
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)

    # IM platform binding
    wecom_user_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )
    lark_user_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )

    # Status
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | confirmed | checked_in | absent | cancelled

    # Relationships
    event: Mapped[Event] = relationship(back_populates="attendees")
    seat: Mapped[Optional[Seat]] = relationship(
        back_populates="attendee", uselist=False
    )
