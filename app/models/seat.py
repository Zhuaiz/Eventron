"""Seat ORM model."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.attendee import Attendee
    from app.models.event import Event


class Seat(Base, UUIDMixin):
    """A physical seat in an event venue."""

    __tablename__ = "seats"

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id"))
    row_num: Mapped[int] = mapped_column(Integer)
    col_num: Mapped[int] = mapped_column(Integer)
    label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    seat_type: Mapped[str] = mapped_column(String(20), default="normal")
    # normal | reserved | disabled | aisle
    zone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Venue zone (e.g. "VIP区", "嘉宾区", "工作人员区", None=普通区)
    attendee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("attendees.id"), nullable=True
    )

    # Relationships
    event: Mapped[Event] = relationship(back_populates="seats")
    attendee: Mapped[Optional[Attendee]] = relationship(back_populates="seat")

    __table_args__ = (
        UniqueConstraint("event_id", "row_num", "col_num", name="uq_seat_position"),
    )
