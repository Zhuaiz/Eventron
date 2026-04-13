"""Seat ORM model."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.attendee import Attendee
    from app.models.event import Event
    from app.models.venue_area import VenueArea


class Seat(Base, UUIDMixin):
    """A physical seat in an event venue.

    Supports both grid-based (row_num/col_num) and free-form (pos_x/pos_y)
    positioning.  Layout generators set pos_x/pos_y for non-rectangular
    arrangements (roundtable, U-shape, etc.).
    """

    __tablename__ = "seats"

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id"))
    row_num: Mapped[int] = mapped_column(Integer)
    col_num: Mapped[int] = mapped_column(Integer)
    label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    seat_type: Mapped[str] = mapped_column(String(20), default="normal")
    # normal | reserved | disabled | aisle
    zone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Venue zone (e.g. "贵宾区", "嘉宾区", "工作人员区", None=普通区)

    # Free-form position (virtual canvas units, 0-based).
    # For grid layouts, computed as col_num * spacing / row_num * spacing.
    pos_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pos_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Rotation in degrees (for angled seats around round tables, etc.)
    rotation: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=0.0
    )

    area_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("venue_areas.id"), nullable=True
    )
    attendee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("attendees.id"), nullable=True
    )

    # Relationships
    event: Mapped[Event] = relationship(back_populates="seats")
    area: Mapped[Optional[VenueArea]] = relationship(back_populates="seats")
    attendee: Mapped[Optional[Attendee]] = relationship(back_populates="seat")

    __table_args__ = (
        UniqueConstraint(
            "event_id", "area_id", "row_num", "col_num",
            name="uq_seat_position_area",
        ),
    )
