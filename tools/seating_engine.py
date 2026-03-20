"""Seat assignment algorithms — pure functions, no DB, no IO.

All functions take plain dicts (not ORM objects) and return assignment lists.
The calling agent is responsible for fetching data from services and passing it in.

Priority system: attendee.priority (0=normal, higher=more important).
Zone system: seat.zone (string label, None=general area).
"""

import random
from typing import Any


def assign_seats_random(
    attendees: list[dict[str, Any]],
    seats: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Random assignment using Fisher-Yates shuffle.

    Args:
        attendees: List of attendee dicts with at least 'id' key.
        seats: List of seat dicts with at least 'id' key.

    Returns:
        List of {attendee_id, seat_id} assignment dicts.

    Raises:
        ValueError: If more attendees than available seats.
    """
    if len(attendees) > len(seats):
        raise ValueError(
            f"Not enough seats: {len(attendees)} attendees, {len(seats)} seats"
        )
    if not attendees:
        return []

    shuffled_seats = seats.copy()
    random.shuffle(shuffled_seats)

    return [
        {"attendee_id": att["id"], "seat_id": shuffled_seats[i]["id"]}
        for i, att in enumerate(attendees)
    ]


def assign_seats_priority_first(
    attendees: list[dict[str, Any]],
    seats: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Priority-based assignment: high-priority attendees get best seats.

    Seats are scored: lower row_num → front (better), center col → better.
    Attendees sorted by priority descending — highest priority gets seat #1.

    Args:
        attendees: Dicts with 'id', 'priority' (int, higher=better).
        seats: Dicts with 'id', 'row_num', 'col_num'.

    Returns:
        List of {attendee_id, seat_id} assignment dicts.
    """
    if len(attendees) > len(seats):
        raise ValueError(
            f"Not enough seats: {len(attendees)} attendees, {len(seats)} seats"
        )
    if not attendees:
        return []

    max_col = max(s["col_num"] for s in seats) if seats else 1
    center = (max_col + 1) / 2

    # Best seats first: front row, center column
    sorted_seats = sorted(
        seats,
        key=lambda s: (s["row_num"], abs(s["col_num"] - center)),
    )

    # Highest priority first
    sorted_attendees = sorted(
        attendees,
        key=lambda a: a.get("priority", 0),
        reverse=True,
    )

    return [
        {"attendee_id": att["id"], "seat_id": sorted_seats[i]["id"]}
        for i, att in enumerate(sorted_attendees)
    ]


# Keep backward compat alias
def assign_seats_vip_first(
    attendees: list[dict[str, Any]],
    seats: list[dict[str, Any]],
    vip_roles: tuple[str, ...] = ("vip", "speaker"),
) -> list[dict[str, str]]:
    """Legacy VIP-first: converts role match to priority, then delegates.

    For backward compatibility. New code should use assign_seats_priority_first.
    """
    enhanced = []
    for att in attendees:
        a = dict(att)
        if a.get("priority", 0) == 0 and a.get("role") in vip_roles:
            a["priority"] = 10  # Treat old VIP roles as priority 10
        enhanced.append(a)
    return assign_seats_priority_first(enhanced, seats)


def assign_seats_by_department(
    attendees: list[dict[str, Any]],
    seats: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Group attendees by department, assign adjacent seats per group.

    Within each department, higher-priority members get earlier seats.
    Departments are ordered by max member priority (most important dept first).

    Args:
        attendees: Dicts with 'id', 'department', 'priority'.
        seats: Dicts with 'id', 'row_num', 'col_num'.

    Returns:
        List of {attendee_id, seat_id} assignment dicts.
    """
    if len(attendees) > len(seats):
        raise ValueError(
            f"Not enough seats: {len(attendees)} attendees, {len(seats)} seats"
        )
    if not attendees:
        return []

    sorted_seats = sorted(seats, key=lambda s: (s["row_num"], s["col_num"]))

    # Group by department
    dept_groups: dict[str, list[dict]] = {}
    for att in attendees:
        dept = att.get("department") or "未分组"
        dept_groups.setdefault(dept, []).append(att)

    # Sort departments by max priority (most important dept first)
    sorted_depts = sorted(
        dept_groups.items(),
        key=lambda kv: max(a.get("priority", 0) for a in kv[1]),
        reverse=True,
    )

    # Within each dept, sort by priority desc
    ordered = []
    for _dept, members in sorted_depts:
        members.sort(key=lambda a: a.get("priority", 0), reverse=True)
        ordered.extend(members)

    return [
        {"attendee_id": att["id"], "seat_id": sorted_seats[i]["id"]}
        for i, att in enumerate(ordered)
    ]


def assign_seats_by_zone(
    attendees: list[dict[str, Any]],
    seats: list[dict[str, Any]],
    zone_rules: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Zone-aware assignment: match attendee priority to seat zones.

    Zone rules define which priority ranges map to which zones.
    Attendees without a matching zone fall back to general (zone=None) seats.

    Args:
        attendees: Dicts with 'id', 'priority'.
        seats: Dicts with 'id', 'row_num', 'col_num', 'zone'.
        zone_rules: List of {zone: str, min_priority: int}.
            Example: [
                {"zone": "VIP区", "min_priority": 10},
                {"zone": "嘉宾区", "min_priority": 5},
            ]
            If None, falls back to priority_first for all seats.

    Returns:
        List of {attendee_id, seat_id} assignment dicts.
    """
    if len(attendees) > len(seats):
        raise ValueError(
            f"Not enough seats: {len(attendees)} attendees, {len(seats)} seats"
        )
    if not attendees:
        return []

    if not zone_rules:
        return assign_seats_priority_first(attendees, seats)

    # Sort rules by min_priority descending (highest zone first)
    sorted_rules = sorted(
        zone_rules, key=lambda r: r.get("min_priority", 0), reverse=True
    )

    # Group seats by zone
    zone_seats: dict[str | None, list[dict]] = {}
    for s in seats:
        z = s.get("zone")
        zone_seats.setdefault(z, []).append(s)

    # Sort each zone's seats (front-center first)
    for z, z_seats in zone_seats.items():
        if not z_seats:
            continue
        max_col = max(s["col_num"] for s in z_seats)
        center = (max_col + 1) / 2
        z_seats.sort(key=lambda s: (s["row_num"], abs(s["col_num"] - center)))

    # Sort attendees by priority desc
    sorted_att = sorted(
        attendees, key=lambda a: a.get("priority", 0), reverse=True
    )

    assignments = []
    used_seats: set[str] = set()

    for att in sorted_att:
        pri = att.get("priority", 0)
        assigned = False

        # Find matching zone
        for rule in sorted_rules:
            if pri >= rule.get("min_priority", 0):
                zone_name = rule["zone"]
                for s in zone_seats.get(zone_name, []):
                    if s["id"] not in used_seats:
                        assignments.append({
                            "attendee_id": att["id"],
                            "seat_id": s["id"],
                        })
                        used_seats.add(s["id"])
                        assigned = True
                        break
                if assigned:
                    break

        # Fallback to general seats (zone=None)
        if not assigned:
            for s in zone_seats.get(None, []):
                if s["id"] not in used_seats:
                    assignments.append({
                        "attendee_id": att["id"],
                        "seat_id": s["id"],
                    })
                    used_seats.add(s["id"])
                    assigned = True
                    break

        # Last resort: any available seat
        if not assigned:
            for z_seats_list in zone_seats.values():
                for s in z_seats_list:
                    if s["id"] not in used_seats:
                        assignments.append({
                            "attendee_id": att["id"],
                            "seat_id": s["id"],
                        })
                        used_seats.add(s["id"])
                        assigned = True
                        break
                if assigned:
                    break

    return assignments


def generate_seat_labels(
    rows: int, cols: int, style: str = "alpha"
) -> list[dict[str, Any]]:
    """Generate seat label metadata for a venue grid.

    Args:
        rows: Number of rows.
        cols: Number of columns.
        style: 'alpha' (A1, A2...) or 'numeric' (1-1, 1-2...).

    Returns:
        List of {row_num, col_num, label} dicts.
    """
    labels = []
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            if style == "alpha":
                label = f"{chr(64 + r)}{c}"
            else:
                label = f"{r}-{c}"
            labels.append({"row_num": r, "col_num": c, "label": label})
    return labels


def suggest_zones(
    rows: int,
    cols: int,
    attendees: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """AI-style zone suggestion based on attendee composition.

    Analyzes attendee priorities and suggests how to divide the venue
    into zones. Pure heuristic — no LLM needed.

    Args:
        rows: Total venue rows.
        cols: Total venue columns.
        attendees: Dicts with 'priority'.

    Returns:
        List of zone defs: {zone, min_priority, rows, color, description}.
    """
    if not attendees or rows == 0:
        return []

    priorities = [a.get("priority", 0) for a in attendees]
    max_pri = max(priorities)

    if max_pri == 0:
        # Everyone is equal — no zones needed
        return [{"zone": "普通区", "min_priority": 0,
                 "rows": list(range(1, rows + 1)),
                 "color": "#6b7280", "description": "所有座位"}]

    # Count tiers
    high = [p for p in priorities if p >= 10]
    mid = [p for p in priorities if 1 <= p < 10]

    zones = []
    row_cursor = 1

    if high:
        # Front rows for VIP-level
        vip_rows = max(1, min(rows // 3, (len(high) + cols - 1) // cols))
        zones.append({
            "zone": "贵宾区",
            "min_priority": 10,
            "rows": list(range(row_cursor, row_cursor + vip_rows)),
            "color": "#e2b93b",
            "description": f"前 {vip_rows} 排 · 高优先级嘉宾",
        })
        row_cursor += vip_rows

    if mid:
        mid_rows = max(1, min(
            (rows - row_cursor + 1) // 2,
            (len(mid) + cols - 1) // cols,
        ))
        zones.append({
            "zone": "嘉宾区",
            "min_priority": 1,
            "rows": list(range(row_cursor, row_cursor + mid_rows)),
            "color": "#4a90d9",
            "description": f"中间 {mid_rows} 排 · 重要嘉宾",
        })
        row_cursor += mid_rows

    remaining = rows - row_cursor + 1
    if remaining > 0:
        zones.append({
            "zone": "普通区",
            "min_priority": 0,
            "rows": list(range(row_cursor, rows + 1)),
            "color": "#6b7280",
            "description": f"后 {remaining} 排 · 普通参会者",
        })

    return zones
