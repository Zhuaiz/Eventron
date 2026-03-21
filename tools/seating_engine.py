"""Seat assignment algorithms + layout generators — pure functions.

All functions take plain dicts (not ORM objects) and return assignment lists
or seat specifications.  No DB, no IO.

Priority system: attendee.priority (0=normal, higher=more important).
Zone system: seat.zone (string label, None=general area).
"""

import math
import random
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SPACING = 46.0  # virtual canvas units between seats (seat ⌀ ≈ 36)
TARGET_CANVAS = 960.0   # target canvas width to fit typical viewport at ~100%
MIN_SEAT_SPACING = 38.0  # min spacing (seat ⌀ ≈ 36, min gap ≈ 2)


def _adaptive_spacing(cols: int, spacing: float, factor: float = 1.0) -> float:
    """Shrink spacing for wide layouts to fit TARGET_CANVAS at ~100% zoom."""
    return min(spacing, max(MIN_SEAT_SPACING, TARGET_CANVAS / max(cols * factor, 1)))


# ===================================================================
# Layout generators — return list of seat spec dicts
# ===================================================================

def generate_layout(
    layout_type: str,
    rows: int,
    cols: int,
    *,
    spacing: float = DEFAULT_SPACING,
    table_size: int = 8,
    aisle_every: int = 0,
) -> list[dict[str, Any]]:
    """Dispatch to specific layout generator.

    Returns list of seat spec dicts:
      {row_num, col_num, pos_x, pos_y, rotation, label, seat_type}
    """
    generators = {
        "grid": _layout_grid,
        "theater": _layout_theater,
        "classroom": _layout_classroom,
        "roundtable": _layout_roundtable,
        "banquet": _layout_banquet,
        "u_shape": _layout_u_shape,
    }
    fn = generators.get(layout_type, _layout_grid)
    return fn(
        rows, cols,
        spacing=spacing,
        table_size=table_size,
        aisle_every=aisle_every,
    )


def generate_custom_layout(
    row_specs: list[dict[str, Any]],
    *,
    default_spacing: float = DEFAULT_SPACING,
) -> list[dict[str, Any]]:
    """Generate layout with variable seats per row — for real venue configs.

    Each entry in *row_specs* describes one or more rows:
        {
          "count": 8,           # seats in this row (required)
          "repeat": 3,          # how many identical rows (default 1)
          "spacing": 60,        # seat-to-seat spacing override (optional)
          "zone": "贵宾区",      # zone label for all seats in these rows
          "label_prefix": "V",  # row label prefix override (optional)
        }

    Rows are centered horizontally (widest row sets the canvas width).
    Returns list of seat spec dicts compatible with Seat model.
    """
    if not row_specs:
        return []

    # Expand repeats into a flat row list
    expanded: list[dict[str, Any]] = []
    for spec in row_specs:
        repeat = max(1, spec.get("repeat", 1))
        for _ in range(repeat):
            expanded.append(spec)

    # Find widest row to center everything
    max_width = 0.0
    for spec in expanded:
        count = spec["count"]
        sp = spec.get("spacing", default_spacing)
        row_width = (count - 1) * sp if count > 1 else 0
        max_width = max(max_width, row_width)

    seats: list[dict[str, Any]] = []
    y_cursor = 0.0
    row_num = 1

    for idx, spec in enumerate(expanded):
        count = spec["count"]
        sp = spec.get("spacing", default_spacing)
        zone = spec.get("zone")
        prefix = spec.get("label_prefix") or chr(65 + idx % 26)
        row_width = (count - 1) * sp if count > 1 else 0

        # Center this row relative to widest row
        x_offset = (max_width - row_width) / 2

        for c in range(count):
            seat: dict[str, Any] = {
                "row_num": row_num,
                "col_num": c + 1,
                "pos_x": round(x_offset + c * sp, 1),
                "pos_y": round(y_cursor, 1),
                "rotation": 0,
                "label": f"{prefix}{c + 1}",
                "seat_type": "normal",
            }
            if zone:
                seat["zone"] = zone
            seats.append(seat)

        # Vertical gap: use this row's spacing for row height
        y_cursor += sp
        row_num += 1

    return seats


def _layout_grid(
    rows: int, cols: int, *, spacing: float = DEFAULT_SPACING, **_kw: Any,
) -> list[dict[str, Any]]:
    """Simple rectangular grid (default).

    Spacing adapts to keep total width ≤ TARGET_CANVAS px (≈ one viewport),
    while never going below MIN_SEAT_SPACING to avoid overlap.
    """
    sp = _adaptive_spacing(cols, spacing)

    seats: list[dict[str, Any]] = []
    for r in range(rows):
        for c in range(cols):
            seats.append({
                "row_num": r + 1,
                "col_num": c + 1,
                "pos_x": round(c * sp, 1),
                "pos_y": round(r * sp, 1),
                "rotation": 0,
                "label": f"{chr(65 + r % 26)}{c + 1}",
                "seat_type": "normal",
            })
    return seats


def _layout_theater(
    rows: int, cols: int, *, spacing: float = DEFAULT_SPACING, **_kw: Any,
) -> list[dict[str, Any]]:
    """Theater: curved rows, wider toward the back.

    Front rows are slightly narrower and curve toward a focal point (stage).
    """
    sp = _adaptive_spacing(cols, spacing)

    seats: list[dict[str, Any]] = []
    # Virtual stage at (center_x, -100)
    center_x = (cols - 1) * sp / 2
    base_radius = cols * sp * 0.8

    for r in range(rows):
        radius = base_radius + r * sp * 1.1
        # Arc angle range — wider for back rows
        arc_range = min(math.pi * 0.55, 0.4 + r * 0.02)
        n_seats = cols + (r // 3)  # back rows can be slightly wider
        n_seats = min(n_seats, cols + rows // 2)  # cap it
        actual_cols = min(n_seats, cols + r // 3)

        for c in range(actual_cols):
            if actual_cols == 1:
                angle = 0
            else:
                angle = -arc_range / 2 + c * arc_range / (actual_cols - 1)

            px = center_x + radius * math.sin(angle)
            py = radius * (1 - math.cos(angle))

            seats.append({
                "row_num": r + 1,
                "col_num": c + 1,
                "pos_x": round(px, 1),
                "pos_y": round(py, 1),
                "rotation": round(math.degrees(angle), 1),
                "label": f"{chr(65 + r % 26)}{c + 1}",
                "seat_type": "normal",
            })
    return seats


def _layout_classroom(
    rows: int, cols: int, *, spacing: float = DEFAULT_SPACING, **_kw: Any,
) -> list[dict[str, Any]]:
    """Classroom: paired seats with desk-width gap between pairs.

    Pairs share a desk.  Extra vertical spacing between rows.
    """
    sp = _adaptive_spacing(cols, spacing, factor=1.15)  # account for desk gaps

    seats: list[dict[str, Any]] = []
    desk_gap = sp * 0.3  # gap between pairs
    row_gap = sp * 1.6  # extra vertical spacing (desk depth)

    col_idx = 0
    for r in range(rows):
        col_idx = 0
        px_offset = 0.0
        for c in range(cols):
            col_idx += 1
            seats.append({
                "row_num": r + 1,
                "col_num": col_idx,
                "pos_x": round(px_offset, 1),
                "pos_y": round(r * row_gap, 1),
                "rotation": 0,
                "label": f"{chr(65 + r % 26)}{col_idx}",
                "seat_type": "normal",
            })
            px_offset += sp
            # Add desk gap after every 2 seats
            if col_idx % 2 == 0:
                px_offset += desk_gap
    return seats


def _layout_roundtable(
    rows: int,
    cols: int,
    *,
    spacing: float = DEFAULT_SPACING,
    table_size: int = 8,
    **_kw: Any,
) -> list[dict[str, Any]]:
    """Roundtable: circular tables with seats around them.

    `rows * cols` is treated as total seat count.  Tables are auto-arranged
    in a roughly square grid.  Each table has `table_size` seats.
    """
    total_seats = rows * cols
    n_tables = max(1, math.ceil(total_seats / table_size))

    # Arrange tables in a grid
    table_cols = max(1, math.ceil(math.sqrt(n_tables)))
    table_rows = max(1, math.ceil(n_tables / table_cols))
    # Compact radius: circumference fits seats, minimal padding
    table_radius = spacing * table_size / (2 * math.pi) + spacing * 0.15
    # Tight gap between table edges (≈ 0.8 seat-widths)
    table_spacing = 2 * table_radius + spacing * 0.8

    seats: list[dict[str, Any]] = []
    seat_counter = 0
    global_row = 1

    for tr in range(table_rows):
        for tc in range(table_cols):
            table_idx = tr * table_cols + tc
            if table_idx >= n_tables:
                break
            # Table center
            tx = tc * table_spacing + table_spacing / 2
            ty = tr * table_spacing + table_spacing / 2

            # Place seats around the table
            remaining = total_seats - seat_counter
            seats_this_table = min(table_size, remaining)
            if seats_this_table <= 0:
                break

            for s in range(seats_this_table):
                angle = 2 * math.pi * s / seats_this_table
                px = tx + table_radius * math.cos(angle)
                py = ty + table_radius * math.sin(angle)
                seat_counter += 1
                # Use table number + seat position as label
                tbl_label = f"T{table_idx + 1}-{s + 1}"

                seats.append({
                    "row_num": global_row,
                    "col_num": s + 1,
                    "pos_x": round(px, 1),
                    "pos_y": round(py, 1),
                    "rotation": round(math.degrees(angle) + 90, 1),
                    "label": tbl_label,
                    "seat_type": "normal",
                })
            global_row += 1

    return seats


def _layout_banquet(
    rows: int,
    cols: int,
    *,
    spacing: float = DEFAULT_SPACING,
    table_size: int = 8,
    **_kw: Any,
) -> list[dict[str, Any]]:
    """Banquet: rectangular tables with seats on two long sides.

    Similar to roundtable but with rectangular tables.
    """
    total_seats = rows * cols
    seats_per_side = max(2, table_size // 2)
    n_tables = max(1, math.ceil(total_seats / table_size))

    table_cols = max(1, math.ceil(math.sqrt(n_tables)))
    table_rows = max(1, math.ceil(n_tables / table_cols))
    table_w = seats_per_side * spacing
    table_h = spacing * 2.5
    table_spacing_x = table_w + spacing * 1.2
    table_spacing_y = table_h + spacing * 2

    seats: list[dict[str, Any]] = []
    seat_counter = 0
    global_row = 1

    for tr in range(table_rows):
        for tc in range(table_cols):
            table_idx = tr * table_cols + tc
            if table_idx >= n_tables:
                break
            tx = tc * table_spacing_x
            ty = tr * table_spacing_y

            remaining = total_seats - seat_counter
            seats_this_table = min(table_size, remaining)
            if seats_this_table <= 0:
                break

            half = math.ceil(seats_this_table / 2)
            col_counter = 0

            # Top side
            for s in range(half):
                col_counter += 1
                px = tx + s * spacing + spacing * 0.5
                py = ty
                seat_counter += 1
                seats.append({
                    "row_num": global_row,
                    "col_num": col_counter,
                    "pos_x": round(px, 1),
                    "pos_y": round(py, 1),
                    "rotation": 0,
                    "label": f"T{table_idx + 1}-{col_counter}",
                    "seat_type": "normal",
                })

            # Bottom side
            bottom_count = seats_this_table - half
            for s in range(bottom_count):
                col_counter += 1
                px = tx + s * spacing + spacing * 0.5
                py = ty + table_h
                seat_counter += 1
                seats.append({
                    "row_num": global_row,
                    "col_num": col_counter,
                    "pos_x": round(px, 1),
                    "pos_y": round(py, 1),
                    "rotation": 180,
                    "label": f"T{table_idx + 1}-{col_counter}",
                    "seat_type": "normal",
                })
            global_row += 1

    return seats


def _layout_u_shape(
    rows: int, cols: int, *, spacing: float = DEFAULT_SPACING, **_kw: Any,
) -> list[dict[str, Any]]:
    """U-shape: seats along three sides (left, bottom, right).

    Open side faces the stage/front.  `rows` = depth, `cols` = width.
    """
    sp = _adaptive_spacing(cols, spacing)
    seats: list[dict[str, Any]] = []
    width = (cols - 1) * sp
    depth = (rows - 1) * sp
    seat_counter = 0
    row_counter = 1

    # Left side (top-to-bottom)
    left_seats = rows
    for i in range(left_seats):
        seat_counter += 1
        seats.append({
            "row_num": row_counter,
            "col_num": 1,
            "pos_x": 0.0,
            "pos_y": round(i * sp, 1),
            "rotation": 90,
            "label": f"L{i + 1}",
            "seat_type": "normal",
        })
        row_counter += 1

    # Bottom side (left-to-right, excluding corners already placed)
    bottom_seats = max(0, cols - 2)
    for i in range(bottom_seats):
        seat_counter += 1
        seats.append({
            "row_num": row_counter,
            "col_num": i + 2,
            "pos_x": round((i + 1) * sp, 1),
            "pos_y": round(depth, 1),
            "rotation": 0,
            "label": f"B{i + 1}",
            "seat_type": "normal",
        })
        row_counter += 1

    # Right side (bottom-to-top)
    right_seats = rows
    for i in range(right_seats):
        seat_counter += 1
        seats.append({
            "row_num": row_counter,
            "col_num": cols,
            "pos_x": round(width, 1),
            "pos_y": round(depth - i * sp, 1),
            "rotation": -90,
            "label": f"R{i + 1}",
            "seat_type": "normal",
        })
        row_counter += 1

    return seats


# ===================================================================
# Seat assignment algorithms
# ===================================================================

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
        # Auto-infer zone rules from existing seat zones.
        # Zones whose seats have lower average row_num (closer to stage)
        # get higher min_priority thresholds.
        zone_names = sorted(
            {s["zone"] for s in seats if s.get("zone")},
        )
        if not zone_names:
            # No zones painted — fall back to priority_first
            return assign_seats_priority_first(attendees, seats)

        # Rank zones by average row_num (front zones = high priority)
        zone_avg_row: dict[str, float] = {}
        for z in zone_names:
            rows = [s["row_num"] for s in seats if s.get("zone") == z]
            zone_avg_row[z] = sum(rows) / len(rows) if rows else 999

        ranked = sorted(zone_names, key=lambda z: zone_avg_row[z])
        step = 100 // (len(ranked) + 1)
        zone_rules = [
            {"zone": z, "min_priority": max(1, (len(ranked) - i) * step)}
            for i, z in enumerate(ranked)
        ]

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


"""Rotating color palette for auto-generated zone colors (matches frontend)."""
_ZONE_COLORS = [
    '#e2b93b', '#4a90d9', '#9b59b6', '#27ae60', '#6b7280',
    '#e94560', '#00b894', '#fd79a8', '#636e72', '#0984e3',
]


def suggest_zones(
    rows: int,
    cols: int,
    attendees: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Role-aware zone suggestion based on attendee composition.

    Groups attendees by role, allocates rows proportionally (higher-
    priority roles get front rows), and names zones "{role}区".

    Args:
        rows: Total venue rows.
        cols: Total venue columns.
        attendees: Dicts with 'role' (str) and 'priority' (int).

    Returns:
        List of zone defs: {zone, rows, color, description, count}.
    """
    if not attendees or rows == 0:
        return []

    # Group by role
    role_groups: dict[str, list[dict[str, Any]]] = {}
    for a in attendees:
        role = a.get("role") or "参会者"
        role_groups.setdefault(role, []).append(a)

    # Only one role (or everyone is "参会者") → single zone
    if len(role_groups) <= 1:
        role_name = next(iter(role_groups))
        zone_name = role_name if role_name.endswith("区") else f"{role_name}区"
        return [{"zone": zone_name, "rows": list(range(1, rows + 1)),
                 "color": "#6b7280",
                 "description": f"所有座位 · {len(attendees)} 人",
                 "count": len(attendees)}]

    # Sort roles by avg priority desc (high-priority roles get front rows)
    def _avg_pri(group: list[dict[str, Any]]) -> float:
        return sum(a.get("priority", 0) for a in group) / len(group)

    sorted_roles = sorted(
        role_groups.items(),
        key=lambda kv: _avg_pri(kv[1]),
        reverse=True,
    )

    # Split "参会者" (default role) out — always goes to the back
    main_roles = [(r, g) for r, g in sorted_roles if r != "参会者"]
    default_group = role_groups.get("参会者", [])

    # Allocate rows proportionally by headcount
    total_non_default = sum(len(g) for _, g in main_roles)
    total_all = total_non_default + len(default_group)
    # Reserve at least 1 row for default group if it exists
    available_rows = rows - (1 if default_group else 0)

    zones = []
    row_cursor = 1
    color_idx = 0

    for role_name, group in main_roles:
        # Proportional rows: by headcount, at least 1, at most enough to fit
        proportion = len(group) / total_all if total_all else 0
        needed_rows = max(1, round(rows * proportion))
        # Don't exceed what's left (reserve space for remaining roles)
        remaining_roles = len(main_roles) - len(zones) - 1 + (1 if default_group else 0)
        max_rows = available_rows - row_cursor + 1 - remaining_roles
        alloc_rows = max(1, min(needed_rows, max_rows))

        zone_name = role_name if role_name.endswith("区") else f"{role_name}区"
        color = _ZONE_COLORS[color_idx % len(_ZONE_COLORS)]
        color_idx += 1

        zones.append({
            "zone": zone_name,
            "rows": list(range(row_cursor, row_cursor + alloc_rows)),
            "color": color,
            "description": f"{alloc_rows} 排 · {role_name} {len(group)} 人",
            "count": len(group),
        })
        row_cursor += alloc_rows

    # Remaining rows → "参会者" / "普通区"
    remaining = rows - row_cursor + 1
    if remaining > 0:
        zones.append({
            "zone": "普通区",
            "rows": list(range(row_cursor, rows + 1)),
            "color": "#6b7280",
            "description": f"{remaining} 排 · 参会者 {len(default_group)} 人",
            "count": len(default_group),
        })

    return zones
