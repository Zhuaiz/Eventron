"""LangChain tools for the seating agent — wrapping service calls.

Each tool is a pure async function that the LLM can call via tool_calling.
Tools get service instances via closure from ``make_seating_tools()``.

Design principle: tools are *thin wrappers* around services. The LLM
decides WHEN and WHY to call them; the tools just execute and return
a text summary the LLM can reason about.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.tools import tool


def make_seating_tools(
    event_id: str,
    seat_svc: Any,
    event_svc: Any,
    attendee_svc: Any,
) -> list:
    """Build LangChain tools with services bound via closure.

    Args:
        event_id: UUID string of the current event.
        seat_svc: SeatingService instance.
        event_svc: EventService instance.
        attendee_svc: AttendeeService instance.

    Returns:
        List of LangChain tool objects ready for ``llm.bind_tools()``.
    """
    eid = uuid.UUID(event_id)

    @tool
    async def get_event_info() -> str:
        """获取当前活动的基本信息（名称、布局类型、行列数、状态）。"""
        ev = await event_svc.get_event(eid)
        return json.dumps({
            "name": ev.name,
            "layout_type": ev.layout_type,
            "venue_rows": ev.venue_rows,
            "venue_cols": ev.venue_cols,
            "status": ev.status,
            "location": ev.location,
        }, ensure_ascii=False)

    @tool
    async def view_seats() -> str:
        """查看当前座位状态：总数、已分配、空闲、各分区详情。每次操作后都应调用此工具验证结果。"""
        seats = await seat_svc.get_seats(eid)
        if not seats:
            return "当前没有座位。需要先创建布局。"
        occupied = sum(1 for s in seats if s.attendee_id)
        total = len(seats)
        zones: dict[str, int] = {}
        for s in seats:
            z = getattr(s, "zone", None) or "未分区"
            zones[z] = zones.get(z, 0) + 1
        zone_str = ", ".join(
            f"{z}({c})" for z, c in sorted(zones.items())
        )
        max_row = max(s.row_num for s in seats)
        max_col = max(s.col_num for s in seats)
        return (
            f"总计 {total} 座, 已分配 {occupied}, "
            f"空闲 {total - occupied}。"
            f"布局 {max_row}排×{max_col}列。"
            f"分区: {zone_str}"
        )

    @tool
    async def create_layout(
        layout_type: str,
        rows: int,
        cols: int,
        table_size: int = 8,
    ) -> str:
        """创建座位布局（替换已有座位）。

        Args:
            layout_type: 布局类型 grid|theater|roundtable|banquet|u_shape|classroom
            rows: 排数
            cols: 每排座位数
            table_size: 每桌人数（仅 roundtable/banquet 用）
        """
        seats = await seat_svc.create_venue_layout(
            eid,
            layout_type=layout_type,
            rows=rows,
            cols=cols,
            table_size=table_size,
            replace=True,
        )
        return (
            f"已创建 {layout_type} 布局: "
            f"{rows}排×{cols}列, 共 {len(seats)} 个座位"
        )

    @tool
    async def create_custom_layout(row_specs_json: str) -> str:
        """创建自定义布局（每排座位数可不同）。

        Args:
            row_specs_json: JSON 数组，例如:
                [{"count":8,"repeat":3,"zone":"贵宾区"},
                 {"count":20,"repeat":12}]
                count=每排座位数, repeat=连续相同的排数, zone=分区名(可选)
        """
        specs = json.loads(row_specs_json)
        seats = await seat_svc.create_custom_layout(
            eid, specs, replace=True,
        )
        total_rows = sum(s.get("repeat", 1) for s in specs)
        return (
            f"已创建自定义布局: {total_rows}排, "
            f"共 {len(seats)} 个座位"
        )

    @tool
    async def auto_assign(
        strategy: str = "priority_first",
    ) -> str:
        """自动排座：把参会者分配到空座位。

        Args:
            strategy: 排座策略 random|priority_first|by_department|by_zone
        """
        assignments = await seat_svc.auto_assign(
            eid, strategy=strategy,
        )
        if not assignments:
            return "没有需要分配的参会者（都已有座位，或没有参会者）"
        return f"已分配 {len(assignments)} 位参会者, 策略: {strategy}"

    @tool
    async def set_zone(
        row_start: int,
        row_end: int,
        zone_name: str,
    ) -> str:
        """给指定排的座位设置分区。

        Args:
            row_start: 起始排号（含），从 1 开始
            row_end: 结束排号（含）
            zone_name: 分区名，如 "贵宾区"、"嘉宾区"、"普通区"
        """
        seats = await seat_svc.get_seats(eid)
        target_ids = [
            s.id for s in seats
            if row_start <= s.row_num <= row_end
        ]
        if not target_ids:
            return f"第 {row_start}-{row_end} 排没有座位"
        count = await seat_svc.bulk_update_zone(target_ids, zone_name)
        return f"已将第 {row_start}-{row_end} 排共 {count} 个座位设为 {zone_name}"

    @tool
    async def set_zone_unzoned(zone_name: str) -> str:
        """把所有还没有分区的座位设为指定分区。

        Args:
            zone_name: 分区名
        """
        seats = await seat_svc.get_seats(eid)
        target_ids = [
            s.id for s in seats
            if getattr(s, "zone", None) is None
        ]
        if not target_ids:
            return "没有未分区的座位"
        count = await seat_svc.bulk_update_zone(target_ids, zone_name)
        return f"已将 {count} 个未分区座位设为 {zone_name}"

    @tool
    async def read_event_excel() -> str:
        """读取本活动最近上传的 Excel 文件内容（原始文本）。
        用于分析座位表、参会名单等。如果用户提到"文件"、"座位表"、"名单"，先调用此工具查看内容。"""
        from tools.event_files import find_latest_file_by_type
        from tools.excel_io import read_excel_sheets_as_text

        entry = find_latest_file_by_type(event_id, "excel")
        if not entry:
            return "本活动没有上传过 Excel 文件"
        text = read_excel_sheets_as_text(file_path=entry["path"])
        fname = entry.get("filename", "Excel")
        return f"文件: {fname}\n\n{text}"

    @tool
    async def list_attendees() -> str:
        """查看当前活动的参会者名单。"""
        attendees = await attendee_svc.list_attendees_for_event(eid)
        if not attendees:
            return "当前没有参会者"
        lines = [f"共 {len(attendees)} 位参会者:"]
        for a in attendees[:30]:
            zone = a.role or "参会者"
            lines.append(f"  - {a.name} ({zone})")
        if len(attendees) > 30:
            lines.append(f"  ... 及另外 {len(attendees) - 30} 位")
        return "\n".join(lines)

    @tool
    async def import_attendees(attendees_json: str) -> str:
        """批量导入参会者。已存在的同名参会者会更新角色等信息，不存在的会新增。

        Args:
            attendees_json: JSON 数组，例如:
                [{"name":"张三","role":"贵宾","organization":"XX公司"},
                 {"name":"李四"}]
                必须有 name 字段，其他字段可选:
                role, organization, title, department, priority
        """
        data = json.loads(attendees_json)
        existing = await attendee_svc.list_attendees_for_event(eid)
        existing_map: dict[str, Any] = {a.name: a for a in existing}

        created = 0
        updated = 0
        skipped = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name:
                skipped += 1
                continue

            # Collect updatable fields
            fields: dict[str, Any] = {}
            for f in ("role", "organization", "title", "department"):
                if item.get(f):
                    fields[f] = item[f]
            if "priority" in item:
                fields["priority"] = int(item["priority"])

            if name in existing_map:
                # Update existing attendee's role/org/etc.
                if fields:
                    try:
                        await attendee_svc.update_attendee(
                            existing_map[name].id, **fields,
                        )
                        updated += 1
                    except Exception:
                        skipped += 1
                else:
                    skipped += 1
            else:
                # Create new attendee
                try:
                    await attendee_svc.create_attendee(
                        eid, name=name, **fields,
                    )
                    created += 1
                except Exception:
                    skipped += 1

        parts = []
        if created:
            parts.append(f"新增 {created} 人")
        if updated:
            parts.append(f"更新 {updated} 人")
        if skipped:
            parts.append(f"跳过 {skipped} 人（无变更/无效）")
        return f"导入完成: {', '.join(parts)}" if parts else "没有需要导入的数据"

    @tool
    async def list_attendees_with_seats() -> str:
        """查看参会者及其座位分配详情。比 list_attendees 更详细，包含座位标签和分区。
        适用于需要了解谁坐在哪里的场景（换座、调整前先查看）。"""
        attendees = await attendee_svc.list_attendees_for_event(eid)
        seats = await seat_svc.get_seats(eid)
        if not attendees:
            return "当前没有参会者"

        # Build seat lookup: attendee_id -> seat
        seat_map: dict[str, Any] = {}
        for s in seats:
            if s.attendee_id:
                seat_map[str(s.attendee_id)] = s

        lines = [f"共 {len(attendees)} 位参会者:"]
        for a in attendees[:50]:
            role = a.role or "参会者"
            s = seat_map.get(str(a.id))
            if s:
                zone_str = f", 分区:{s.zone}" if s.zone else ""
                lines.append(
                    f"  - {a.name} ({role}) → 座位 {s.label}"
                    f" (第{s.row_num}排第{s.col_num}列{zone_str})"
                )
            else:
                lines.append(f"  - {a.name} ({role}) → 未分配座位")
        if len(attendees) > 50:
            lines.append(f"  ... 及另外 {len(attendees) - 50} 位")
        return "\n".join(lines)

    @tool
    async def swap_two_attendees(name_a: str, name_b: str) -> str:
        """交换两位参会者的座位。通过姓名查找参会者和他们的座位，然后互换。

        Args:
            name_a: 第一位参会者的姓名
            name_b: 第二位参会者的姓名
        """
        attendees = await attendee_svc.list_attendees_for_event(eid)
        att_a = next((a for a in attendees if a.name == name_a), None)
        att_b = next((a for a in attendees if a.name == name_b), None)

        if not att_a:
            return f"未找到参会者: {name_a}"
        if not att_b:
            return f"未找到参会者: {name_b}"

        seats = await seat_svc.get_seats(eid)
        seat_a = next(
            (s for s in seats if s.attendee_id == att_a.id), None,
        )
        seat_b = next(
            (s for s in seats if s.attendee_id == att_b.id), None,
        )

        if not seat_a:
            return f"{name_a} 目前没有分配座位，无法换座"
        if not seat_b:
            return f"{name_b} 目前没有分配座位，无法换座"

        await seat_svc.swap_seats(seat_a.id, seat_b.id)

        return (
            f"已交换座位: {name_a} ({seat_a.label}) ↔ "
            f"{name_b} ({seat_b.label})"
        )

    @tool
    async def reassign_attendee_seat(
        name: str, target_seat_label: str,
    ) -> str:
        """将指定参会者移动到目标座位。如果参会者已有座位，先取消原座位再分配新座位。

        Args:
            name: 参会者姓名
            target_seat_label: 目标座位标签，如 "A3"、"B5"
        """
        attendees = await attendee_svc.list_attendees_for_event(eid)
        att = next((a for a in attendees if a.name == name), None)
        if not att:
            return f"未找到参会者: {name}"

        seats = await seat_svc.get_seats(eid)
        target = next(
            (s for s in seats if s.label == target_seat_label), None,
        )
        if not target:
            return (
                f"未找到座位: {target_seat_label}。"
                f"可用座位标签示例: "
                + ", ".join(s.label for s in seats[:5])
            )

        if target.attendee_id and target.attendee_id != att.id:
            occupant = next(
                (a for a in attendees
                 if a.id == target.attendee_id), None,
            )
            occ_name = occupant.name if occupant else "未知"
            return (
                f"座位 {target_seat_label} 已被 {occ_name} 占用。"
                "请先换座或取消该座位分配。"
            )

        if target.seat_type in ("disabled", "aisle"):
            return f"座位 {target_seat_label} 类型为 {target.seat_type}，不可分配"

        # Unassign from current seat if any
        current = next(
            (s for s in seats if s.attendee_id == att.id), None,
        )
        if current:
            await seat_svc.unassign_seat(current.id)

        # Assign to new seat
        await seat_svc.assign_seat(target.id, att.id)
        old_label = current.label if current else "无"
        return (
            f"已将 {name} 从座位 {old_label} "
            f"移至座位 {target_seat_label}"
        )

    @tool
    async def unassign_attendee(name: str) -> str:
        """取消指定参会者的座位分配，使其变为未入座状态。

        Args:
            name: 参会者姓名
        """
        attendees = await attendee_svc.list_attendees_for_event(eid)
        att = next((a for a in attendees if a.name == name), None)
        if not att:
            return f"未找到参会者: {name}"

        seats = await seat_svc.get_seats(eid)
        current = next(
            (s for s in seats if s.attendee_id == att.id), None,
        )
        if not current:
            return f"{name} 目前没有分配座位"

        await seat_svc.unassign_seat(current.id)
        return f"已取消 {name} 的座位 {current.label}"

    return [
        get_event_info,
        view_seats,
        create_layout,
        create_custom_layout,
        auto_assign,
        set_zone,
        set_zone_unzoned,
        read_event_excel,
        list_attendees,
        import_attendees,
        list_attendees_with_seats,
        swap_two_attendees,
        reassign_attendee_seat,
        unassign_attendee,
    ]
