"""Check-in processing — business logic for attendee check-in."""

import re
import time
import uuid

from pypinyin import lazy_pinyin, Style

from app.repositories.attendee_repo import AttendeeRepository
from app.repositories.seat_repo import SeatRepository
from app.services.exceptions import (
    AttendeeNotFoundError,
    InvalidStateTransitionError,
)

# ── Simple TTL cache for stats (avoids DB hit on every 15s poll) ──
_stats_cache: dict[str, tuple[float, dict]] = {}  # event_id → (ts, data)
_STATS_TTL = 10.0  # seconds


def _is_ascii(s: str) -> bool:
    """Check if string contains only ASCII letters."""
    return bool(re.fullmatch(r"[a-zA-Z]+", s))


def _pinyin_initials(name: str) -> str:
    """Get pinyin initials. e.g. '王小明' → 'wxm'."""
    return "".join(lazy_pinyin(name, style=Style.FIRST_LETTER)).lower()


def _pinyin_full(name: str) -> str:
    """Get full pinyin. e.g. '王小明' → 'wangxiaoming'."""
    return "".join(lazy_pinyin(name)).lower()


def _pinyin_match(query: str, name: str) -> bool:
    """Check if query matches name via pinyin (initials or full).

    Supports: 'wxm' matches '王小明', 'wangxm' partial, 'wang' partial.
    """
    q = query.lower()
    initials = _pinyin_initials(name)
    full = _pinyin_full(name)
    # Exact initials match
    if q == initials:
        return True
    # Initials prefix
    if initials.startswith(q):
        return True
    # Full pinyin prefix
    if full.startswith(q):
        return True
    # Full pinyin contains
    if q in full:
        return True
    return False


class CheckinService:
    """Business logic for attendee check-in operations."""

    def __init__(
        self,
        attendee_repo: AttendeeRepository,
        seat_repo: SeatRepository,
    ):
        self._attendee_repo = attendee_repo
        self._seat_repo = seat_repo

    async def checkin(self, attendee_id: uuid.UUID) -> dict:
        """Process check-in for an attendee.

        Returns a dict with check-in result including seat info.

        Raises:
            AttendeeNotFoundError: If attendee doesn't exist.
            InvalidStateTransitionError: If attendee can't check in (cancelled, etc).
        """
        attendee = await self._attendee_repo.get_by_id(attendee_id)
        if attendee is None:
            raise AttendeeNotFoundError(f"Attendee {attendee_id} not found")

        if attendee.status == "cancelled":
            raise InvalidStateTransitionError(
                f"Cancelled attendee {attendee.name} cannot check in"
            )
        if attendee.status == "checked_in":
            # Idempotent — already checked in, return current info
            seat = await self._seat_repo.get_by_attendee(attendee_id)
            return {
                "attendee_id": str(attendee.id),
                "name": attendee.name,
                "already_checked_in": True,
                "seat_label": seat.label if seat else None,
                "seat_row": seat.row_num if seat else None,
                "seat_col": seat.col_num if seat else None,
            }

        # Update status to checked_in
        await self._attendee_repo.update(attendee.id, status="checked_in")

        # Bust stats cache so next poll reflects the change
        # (we need event_id; get it from the attendee)
        self._invalidate_stats_cache(attendee.event_id)

        # Find assigned seat
        seat = await self._seat_repo.get_by_attendee(attendee_id)

        return {
            "attendee_id": str(attendee.id),
            "name": attendee.name,
            "already_checked_in": False,
            "seat_label": seat.label if seat else None,
            "seat_row": seat.row_num if seat else None,
            "seat_col": seat.col_num if seat else None,
        }

    async def checkin_by_name(
        self, event_id: uuid.UUID, name: str
    ) -> dict | list[dict]:
        """Check in by name within an event.

        Supports Chinese name substring, pinyin initials (wxm → 王小明),
        and full pinyin (wangxiaoming).

        Returns check-in result if unique match, or list of candidates
        if ambiguous.
        """
        # 1) Try direct DB ILIKE match (Chinese substring)
        matches = await self._attendee_repo.fuzzy_match_by_name(
            event_id, name,
        )

        # 2) If no DB hit and query looks like ASCII → try pinyin
        if not matches and _is_ascii(name):
            all_attendees = await self._attendee_repo.get_by_event(
                event_id,
            )
            matches = [
                a for a in all_attendees
                if a.status not in ("cancelled",)
                and _pinyin_match(name, a.name)
            ]

        if not matches:
            raise AttendeeNotFoundError(
                f"No attendee matching '{name}' found in this event"
            )

        if len(matches) == 1:
            return await self.checkin(matches[0].id)

        # Ambiguous — return candidates for clarification
        return [
            {
                "attendee_id": str(a.id),
                "name": a.name,
                "title": a.title,
                "organization": a.organization,
            }
            for a in matches
        ]

    async def lookup_by_name(
        self, event_id: uuid.UUID, name: str,
    ) -> dict:
        """Look up an attendee by name **without** checking in.

        Drives the 2-step UX: lookup returns the match (badge / seat / status),
        the page shows it for review, then the user clicks 簽到 → ``/confirm``
        endpoint actually marks them checked-in via ``checkin``.

        The internal check-in business logic (state machine, DB writes) is
        intentionally untouched — this method is read-only and just shapes the
        same fuzzy/pinyin match as ``checkin_by_name`` into a review payload.

        Returns one of:
            ``{"status": "found", "attendee_id": ..., "attendee_name": ...,
              "seat_label": ..., "seat_zone": ..., "title": ...,
              "organization": ..., "attrs": {...}}``
            ``{"status": "already", "attendee_id": ..., "attendee_name": ...,
              "seat_label": ...}``
            ``{"status": "ambiguous", "candidates": [...]}``
            ``{"status": "not_found", "message": "..."}``
        """
        matches = await self._attendee_repo.fuzzy_match_by_name(
            event_id, name,
        )
        if not matches and _is_ascii(name):
            all_attendees = await self._attendee_repo.get_by_event(event_id)
            matches = [
                a for a in all_attendees
                if a.status not in ("cancelled",)
                and _pinyin_match(name, a.name)
            ]

        if not matches:
            return {
                "status": "not_found",
                "message": f"未找到「{name}」，请确认姓名后重试",
            }

        if len(matches) > 1:
            return {
                "status": "ambiguous",
                "candidates": [
                    {
                        "attendee_id": str(a.id),
                        "name": a.name,
                        "title": a.title,
                        "organization": a.organization,
                    }
                    for a in matches
                ],
            }

        # Unique match — read-only review payload.
        attendee = matches[0]
        seat = await self._seat_repo.get_by_attendee(attendee.id)

        base = {
            "attendee_id": str(attendee.id),
            "attendee_name": attendee.name,
            "title": attendee.title,
            "organization": attendee.organization,
            "seat_label": seat.label if seat else None,
            "seat_zone": seat.zone if seat else None,
            "attrs": attendee.attrs or {},
        }
        if attendee.status == "cancelled":
            return {**base, "status": "cancelled",
                    "message": f"{attendee.name} 已取消报名"}
        if attendee.status == "checked_in":
            return {**base, "status": "already"}
        return {**base, "status": "found"}

    async def suggest_by_name(
        self, event_id: uuid.UUID, name: str, limit: int = 8,
    ) -> list[dict]:
        """Search attendees by name/pinyin without checking in.

        Used for live autocomplete on the check-in page.
        """
        # 1) DB ILIKE match
        matches = await self._attendee_repo.fuzzy_match_by_name(
            event_id, name,
        )

        # 2) Pinyin fallback
        if not matches and _is_ascii(name):
            all_attendees = await self._attendee_repo.get_by_event(
                event_id,
            )
            matches = [
                a for a in all_attendees
                if a.status not in ("cancelled",)
                and _pinyin_match(name, a.name)
            ]

        return [
            {
                "attendee_id": str(a.id),
                "name": a.name,
                "title": a.title,
                "organization": a.organization,
            }
            for a in matches[:limit]
        ]

    async def get_checkin_stats(
        self, event_id: uuid.UUID, *, bust_cache: bool = False,
    ) -> dict:
        """Get check-in statistics for an event.

        Results are cached for ``_STATS_TTL`` seconds to reduce DB load
        when many attendees poll the stats endpoint simultaneously.
        """
        key = str(event_id)
        now = time.monotonic()

        if not bust_cache and key in _stats_cache:
            ts, cached = _stats_cache[key]
            if now - ts < _STATS_TTL:
                return cached

        attendees = await self._attendee_repo.get_by_event(event_id)
        total = len(attendees)
        checked_in = sum(
            1 for a in attendees if a.status == "checked_in"
        )
        result = {
            "total": total,
            "checked_in": checked_in,
            "remaining": total - checked_in,
            "rate": round(
                checked_in / total * 100, 1,
            ) if total > 0 else 0,
        }
        _stats_cache[key] = (now, result)
        return result

    def _invalidate_stats_cache(self, event_id: uuid.UUID) -> None:
        """Bust the stats cache after a check-in mutation."""
        _stats_cache.pop(str(event_id), None)
