"""Seed script — create realistic demo data for Eventron.

Creates 3 events with attendees, seats (some assigned), and approval requests.
Uses ORM models directly so types are handled automatically.

Usage:
    python scripts/seed.py          # default: seed all
    python scripts/seed.py --reset  # drop existing seed data first

Or from docker:
    docker compose exec app alembic upgrade head
    docker compose exec app python scripts/seed.py
"""

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.approval import ApprovalRequest
from app.models.attendee import Attendee
from app.models.event import Event
from app.models.seat import Seat

# ── Fixed UUIDs for reproducibility ────────────────────────────
EVENT_1_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
EVENT_2_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
EVENT_3_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")

NOW = datetime.now(timezone.utc)

# ── Events ─────────────────────────────────────────────────────
EVENTS = [
    {
        "id": EVENT_1_ID,
        "name": "2026 年度战略发布会",
        "description": "公司年度战略规划发布，邀请投资人、媒体及合作伙伴参加。主题演讲 + 圆桌讨论 + 自助晚宴。",
        "event_date": NOW + timedelta(days=7),
        "location": "上海浦东香格里拉大酒店·宴会厅 A",
        "venue_rows": 8,
        "venue_cols": 10,
        "layout_type": "theater",
        "status": "active",
        "created_by": "admin",
        "config": {"allow_self_checkin": True, "require_approval_for_swap": True},
    },
    {
        "id": EVENT_2_ID,
        "name": "Q1 产品评审会",
        "description": "第一季度产品线评审，内部参会，各产品线负责人汇报进展与 Q2 规划。",
        "event_date": NOW + timedelta(days=3),
        "location": "北京朝阳 WeWork 706 会议室",
        "venue_rows": 4,
        "venue_cols": 5,
        "layout_type": "classroom",
        "status": "active",
        "created_by": "admin",
        "config": {"allow_self_checkin": False},
    },
    {
        "id": EVENT_3_ID,
        "name": "客户答谢晚宴",
        "description": "年度重要客户答谢晚宴，圆桌式，每桌 8 人。",
        "event_date": NOW + timedelta(days=30),
        "location": "深圳华侨城洲际酒店·国际厅",
        "venue_rows": 6,
        "venue_cols": 8,
        "layout_type": "banquet",
        "status": "draft",
        "created_by": "admin",
        "config": {"table_size": 8, "allow_self_checkin": True},
    },
]

# ── Attendees ──────────────────────────────────────────────────
# Priority system: 0=普通参会者, 1-9=嘉宾, 10+=贵宾/甲方
# Role is a free-text label (e.g. "投资人", "演讲嘉宾", "工作人员")
# Event 1: 大型发布会 — 25 人
EVENT_1_ATTENDEES = [
    # 投资人 (贵宾, priority 20)
    {"name": "张明远", "title": "董事长", "organization": "华创投资", "department": "", "role": "投资人", "priority": 20, "status": "confirmed", "phone": "13800001001", "email": "zhang@huachuang.cn", "attrs": {"dietary": "无"}},
    {"name": "李雪琴", "title": "合伙人", "organization": "红杉资本", "department": "投资部", "role": "投资人", "priority": 20, "status": "confirmed", "phone": "13800001002", "email": "lixq@sequoia.cn", "attrs": {"dietary": "素食"}},
    {"name": "陈建国", "title": "CEO", "organization": "Eventron", "department": "管理层", "role": "甲方嘉宾", "priority": 15, "status": "checked_in", "phone": "13800001003", "email": "ceo@eventron.ai", "attrs": {}},
    {"name": "王芳", "title": "COO", "organization": "Eventron", "department": "管理层", "role": "甲方嘉宾", "priority": 15, "status": "checked_in", "phone": "13800001004", "email": "coo@eventron.ai", "attrs": {}},
    # 演讲嘉宾 (priority 10)
    {"name": "赵伟", "title": "CTO", "organization": "Eventron", "department": "技术部", "role": "演讲嘉宾", "priority": 10, "status": "confirmed", "phone": "13800001005", "email": "cto@eventron.ai", "attrs": {"talk_title": "AI 驱动的智能排座引擎"}},
    {"name": "孙丽", "title": "产品 VP", "organization": "Eventron", "department": "产品部", "role": "演讲嘉宾", "priority": 10, "status": "confirmed", "phone": "13800001006", "email": "sunli@eventron.ai", "attrs": {"talk_title": "从需求到体验：Eventron 产品之路"}},
    {"name": "刘洋", "title": "AI 首席科学家", "organization": "清华大学", "department": "计算机系", "role": "演讲嘉宾", "priority": 10, "status": "confirmed", "phone": "13800001007", "email": "liuyang@tsinghua.edu.cn", "attrs": {"talk_title": "大模型在企业服务中的落地"}},
    # 媒体 (priority 3)
    {"name": "周海燕", "title": "资深记者", "organization": "36氪", "department": "企业服务组", "role": "媒体", "priority": 3, "status": "confirmed", "phone": "13800001008", "email": "zhouhy@36kr.com", "attrs": {"media_type": "科技媒体"}},
    {"name": "吴斌", "title": "编辑", "organization": "虎嗅", "department": "深度报道", "role": "媒体", "priority": 3, "status": "confirmed", "phone": "13800001009", "email": "wubin@huxiu.com", "attrs": {"media_type": "科技媒体"}},
    {"name": "郑琳", "title": "记者", "organization": "第一财经", "department": "科技版", "role": "媒体", "priority": 3, "status": "pending", "phone": "13800001010", "email": "zhenglin@yicai.com", "attrs": {"media_type": "财经媒体"}},
    # 合作伙伴 (priority 5-10)
    {"name": "钱进", "title": "BD 总监", "organization": "腾讯云", "department": "生态合作部", "role": "合作伙伴", "priority": 10, "status": "pending", "phone": "13800001011", "email": "qianjin@tencent.com", "attrs": {}},
    {"name": "杨光", "title": "产品经理", "organization": "企业微信", "department": "开放平台", "role": "合作伙伴", "priority": 5, "status": "pending", "phone": "13800001012", "email": "yangguang@wecom.work", "attrs": {}},
    {"name": "徐磊", "title": "技术总监", "organization": "飞书", "department": "ISV 生态", "role": "合作伙伴", "priority": 5, "status": "confirmed", "phone": "13800001013", "email": "xulei@feishu.cn", "attrs": {}},
    {"name": "朱峰", "title": "高级架构师", "organization": "阿里云", "department": "智能办公", "role": "合作伙伴", "priority": 5, "status": "confirmed", "phone": "13800001014", "email": "zhufeng@alibaba.com", "attrs": {}},
    # 内部团队 (工作人员, priority 1)
    {"name": "何晓东", "title": "前端负责人", "organization": "Eventron", "department": "技术部", "role": "工作人员", "priority": 1, "status": "checked_in", "phone": "13800001015", "email": "hexd@eventron.ai", "attrs": {}},
    {"name": "谢雨桐", "title": "后端工程师", "organization": "Eventron", "department": "技术部", "role": "工作人员", "priority": 1, "status": "checked_in", "phone": "13800001016", "email": "xieyt@eventron.ai", "attrs": {}},
    {"name": "马丽丽", "title": "UI 设计师", "organization": "Eventron", "department": "设计部", "role": "工作人员", "priority": 1, "status": "confirmed", "phone": "13800001017", "email": "mall@eventron.ai", "attrs": {}},
    {"name": "宋文博", "title": "市场经理", "organization": "Eventron", "department": "市场部", "role": "工作人员", "priority": 1, "status": "confirmed", "phone": "13800001018", "email": "songwb@eventron.ai", "attrs": {}},
    {"name": "唐颖", "title": "行政主管", "organization": "Eventron", "department": "行政部", "role": "组织方", "priority": 5, "status": "checked_in", "phone": "13800001019", "email": "tangy@eventron.ai", "attrs": {}},
    # 客户代表 (priority 0)
    {"name": "韩冰", "title": "会务总监", "organization": "万达集团", "department": "行政中心", "role": "参会者", "priority": 0, "status": "confirmed", "phone": "13800001020", "email": "hanbing@wanda.cn", "attrs": {}},
    {"name": "冯超", "title": "IT 经理", "organization": "美团", "department": "企业服务", "role": "参会者", "priority": 0, "status": "confirmed", "phone": "13800001021", "email": "fengchao@meituan.com", "attrs": {}},
    {"name": "曹雪", "title": "运营负责人", "organization": "得到 App", "department": "活动运营", "role": "参会者", "priority": 0, "status": "pending", "phone": "13800001022", "email": "caoxue@dedao.cn", "attrs": {}},
    {"name": "彭波", "title": "合伙人", "organization": "经纬创投", "department": "", "role": "投资人", "priority": 20, "status": "confirmed", "phone": "13800001023", "email": "pengbo@matrixpartners.cn", "attrs": {}},
    {"name": "蒋一帆", "title": "投资经理", "organization": "IDG 资本", "department": "TMT 组", "role": "参会者", "priority": 0, "status": "confirmed", "phone": "13800001024", "email": "jiangyf@idg.com", "attrs": {}},
    {"name": "沈思", "title": "策划总监", "organization": "奥美", "department": "活动策划", "role": "参会者", "priority": 0, "status": "cancelled", "phone": "13800001025", "email": "shensi@ogilvy.com", "attrs": {}},
]

# Event 2: 内部评审会 — 12 人
EVENT_2_ATTENDEES = [
    {"name": "陈建国", "title": "CEO", "organization": "Eventron", "department": "管理层", "role": "管理层", "priority": 15, "status": "confirmed", "phone": "13800001003", "email": "ceo@eventron.ai", "attrs": {}},
    {"name": "赵伟", "title": "CTO", "organization": "Eventron", "department": "技术部", "role": "管理层", "priority": 15, "status": "confirmed", "phone": "13800001005", "email": "cto@eventron.ai", "attrs": {}},
    {"name": "孙丽", "title": "产品 VP", "organization": "Eventron", "department": "产品部", "role": "汇报人", "priority": 10, "status": "confirmed", "phone": "13800001006", "email": "sunli@eventron.ai", "attrs": {}},
    {"name": "何晓东", "title": "前端负责人", "organization": "Eventron", "department": "技术部", "role": "汇报人", "priority": 10, "status": "confirmed", "phone": "13800001015", "email": "hexd@eventron.ai", "attrs": {}},
    {"name": "谢雨桐", "title": "后端工程师", "organization": "Eventron", "department": "技术部", "role": "参会者", "priority": 0, "status": "confirmed", "phone": "13800001016", "email": "xieyt@eventron.ai", "attrs": {}},
    {"name": "马丽丽", "title": "UI 设计师", "organization": "Eventron", "department": "设计部", "role": "参会者", "priority": 0, "status": "confirmed", "phone": "13800001017", "email": "mall@eventron.ai", "attrs": {}},
    {"name": "宋文博", "title": "市场经理", "organization": "Eventron", "department": "市场部", "role": "参会者", "priority": 0, "status": "pending", "phone": "13800001018", "email": "songwb@eventron.ai", "attrs": {}},
    {"name": "王芳", "title": "COO", "organization": "Eventron", "department": "管理层", "role": "管理层", "priority": 15, "status": "confirmed", "phone": "13800001004", "email": "coo@eventron.ai", "attrs": {}},
    {"name": "林志远", "title": "数据工程师", "organization": "Eventron", "department": "技术部", "role": "参会者", "priority": 0, "status": "confirmed", "phone": "13800001030", "email": "linzy@eventron.ai", "attrs": {}},
    {"name": "黄嘉琪", "title": "测试工程师", "organization": "Eventron", "department": "技术部", "role": "参会者", "priority": 0, "status": "confirmed", "phone": "13800001031", "email": "huangjq@eventron.ai", "attrs": {}},
    {"name": "罗鑫", "title": "DevOps", "organization": "Eventron", "department": "技术部", "role": "参会者", "priority": 0, "status": "absent", "phone": "13800001032", "email": "luoxin@eventron.ai", "attrs": {}},
    {"name": "邓紫琪", "title": "产品经理", "organization": "Eventron", "department": "产品部", "role": "参会者", "priority": 0, "status": "confirmed", "phone": "13800001033", "email": "dengzq@eventron.ai", "attrs": {}},
]

# Event 3: 客户晚宴 — 12 人
EVENT_3_ATTENDEES = [
    {"name": "陈建国", "title": "CEO", "organization": "Eventron", "department": "管理层", "role": "甲方嘉宾", "priority": 15, "status": "pending", "phone": "13800001003", "email": "ceo@eventron.ai", "attrs": {"dietary": "无"}},
    {"name": "王芳", "title": "COO", "organization": "Eventron", "department": "管理层", "role": "甲方嘉宾", "priority": 15, "status": "pending", "phone": "13800001004", "email": "coo@eventron.ai", "attrs": {"dietary": "无"}},
    {"name": "韩冰", "title": "会务总监", "organization": "万达集团", "department": "行政中心", "role": "客户代表", "priority": 10, "status": "pending", "phone": "13800001020", "email": "hanbing@wanda.cn", "attrs": {"dietary": "无"}},
    {"name": "冯超", "title": "IT 经理", "organization": "美团", "department": "企业服务", "role": "客户代表", "priority": 5, "status": "pending", "phone": "13800001021", "email": "fengchao@meituan.com", "attrs": {}},
    {"name": "曹雪", "title": "运营负责人", "organization": "得到 App", "department": "活动运营", "role": "参会者", "priority": 0, "status": "pending", "phone": "13800001022", "email": "caoxue@dedao.cn", "attrs": {}},
    {"name": "钱进", "title": "BD 总监", "organization": "腾讯云", "department": "生态合作部", "role": "客户代表", "priority": 10, "status": "pending", "phone": "13800001011", "email": "qianjin@tencent.com", "attrs": {}},
    {"name": "杨光", "title": "产品经理", "organization": "企业微信", "department": "开放平台", "role": "参会者", "priority": 0, "status": "pending", "phone": "13800001012", "email": "yangguang@wecom.work", "attrs": {}},
    {"name": "高明", "title": "CIO", "organization": "碧桂园", "department": "信息中心", "role": "客户代表", "priority": 10, "status": "pending", "phone": "13800001040", "email": "gaoming@bgy.cn", "attrs": {"dietary": "清真"}},
    {"name": "龙飞", "title": "副总裁", "organization": "字节跳动", "department": "企业服务", "role": "客户代表", "priority": 10, "status": "pending", "phone": "13800001041", "email": "longfei@bytedance.com", "attrs": {}},
    {"name": "范晓萱", "title": "大客户经理", "organization": "Eventron", "department": "销售部", "role": "组织方", "priority": 5, "status": "pending", "phone": "13800001042", "email": "fanxx@eventron.ai", "attrs": {}},
    {"name": "程浩", "title": "解决方案架构师", "organization": "华为云", "department": "企业智能", "role": "参会者", "priority": 0, "status": "pending", "phone": "13800001043", "email": "chenghao@huawei.com", "attrs": {}},
    {"name": "苏锐", "title": "商务总监", "organization": "京东", "department": "企业采购", "role": "参会者", "priority": 0, "status": "pending", "phone": "13800001044", "email": "surui@jd.com", "attrs": {}},
]


async def seed(reset: bool = False):
    """Seed the database with demo data using ORM models."""
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        if reset:
            # Delete in FK order
            await session.execute(text("DELETE FROM approval_requests"))
            await session.execute(text("DELETE FROM seats"))
            await session.execute(text("DELETE FROM attendees"))
            await session.execute(text("DELETE FROM events"))
            await session.commit()
            print("🗑️  已清空所有数据。")

        # Check if already seeded
        result = await session.execute(
            select(Event).where(Event.id == EVENT_1_ID)
        )
        if result.scalar_one_or_none() is not None:
            print("⚠️  演示数据已存在。用 --reset 重新导入。")
            await engine.dispose()
            return

        # ── Insert Events ──────────────────────────────────
        events_orm: dict[uuid.UUID, Event] = {}
        for evt_data in EVENTS:
            evt = Event(**evt_data)
            session.add(evt)
            events_orm[evt_data["id"]] = evt
        await session.flush()
        print(f"✅ 创建了 {len(EVENTS)} 个活动")

        # ── Insert Attendees ───────────────────────────────
        # Track by (event_id, name) for seat assignment and approvals
        att_orm: dict[tuple[uuid.UUID, str], Attendee] = {}

        for event_id, att_list in [
            (EVENT_1_ID, EVENT_1_ATTENDEES),
            (EVENT_2_ID, EVENT_2_ATTENDEES),
            (EVENT_3_ID, EVENT_3_ATTENDEES),
        ]:
            for att_data in att_list:
                att = Attendee(event_id=event_id, **att_data)
                session.add(att)
                att_orm[(event_id, att_data["name"])] = att

        await session.flush()  # generates IDs
        total_att = len(EVENT_1_ATTENDEES) + len(EVENT_2_ATTENDEES) + len(EVENT_3_ATTENDEES)
        print(f"✅ 创建了 {total_att} 位参会人")

        # ── Insert Seats ───────────────────────────────────
        seat_orm: dict[tuple[uuid.UUID, int, int], Seat] = {}
        total_seats = 0

        for evt_data in EVENTS:
            eid = evt_data["id"]
            rows, cols = evt_data["venue_rows"], evt_data["venue_cols"]
            layout = evt_data["layout_type"]

            for r in range(1, rows + 1):
                for c in range(1, cols + 1):
                    label = f"{chr(64 + r)}{c}"

                    # Determine seat type + zone
                    zone = None
                    if layout in ("theater", "classroom"):
                        if r == 1:
                            stype = "reserved"
                            zone = "贵宾区"
                        else:
                            stype = "normal"
                    elif layout == "banquet":
                        if r <= 2:
                            stype = "reserved"
                            zone = "贵宾区"
                        else:
                            stype = "normal"
                    else:
                        stype = "normal"

                    # Reserve a few seats in event 1
                    if eid == EVENT_1_ID and r == 8 and c >= 8:
                        stype = "reserved"

                    seat = Seat(
                        event_id=eid,
                        row_num=r,
                        col_num=c,
                        label=label,
                        seat_type=stype,
                        zone=zone,
                    )
                    session.add(seat)
                    seat_orm[(eid, r, c)] = seat
                    total_seats += 1

        await session.flush()
        print(f"✅ 创建了 {total_seats} 个座位")

        # ── Assign seats ───────────────────────────────────
        assignments = [
            # Event 1: VIP row 1
            (EVENT_1_ID, "陈建国", 1, 4),
            (EVENT_1_ID, "王芳", 1, 5),
            (EVENT_1_ID, "张明远", 1, 6),
            (EVENT_1_ID, "李雪琴", 1, 7),
            (EVENT_1_ID, "彭波", 1, 3),
            # Event 1: Speakers row 2
            (EVENT_1_ID, "赵伟", 2, 4),
            (EVENT_1_ID, "孙丽", 2, 5),
            (EVENT_1_ID, "刘洋", 2, 6),
            # Event 1: regular attendees
            (EVENT_1_ID, "周海燕", 3, 1),
            (EVENT_1_ID, "钱进", 3, 5),
            (EVENT_1_ID, "杨光", 3, 6),
            # Event 2: front row
            (EVENT_2_ID, "陈建国", 1, 2),
            (EVENT_2_ID, "赵伟", 1, 3),
            (EVENT_2_ID, "王芳", 1, 4),
        ]

        assigned_count = 0
        for eid, name, r, c in assignments:
            att = att_orm.get((eid, name))
            seat = seat_orm.get((eid, r, c))
            if att and seat:
                seat.attendee_id = att.id
                assigned_count += 1

        await session.flush()
        print(f"✅ 分配了 {assigned_count} 个座位")

        # ── Insert Approval Requests ───────────────────────
        approvals_data = [
            {
                "event_id": EVENT_1_ID,
                "requester_name": "周海燕",
                "change_type": "swap",
                "change_detail": {"from_seat": "C1", "to_seat": "C5", "reason": "想坐在合作伙伴旁边方便采访"},
                "status": "pending",
            },
            {
                "event_id": EVENT_1_ID,
                "requester_name": "冯超",
                "change_type": "swap",
                "change_detail": {"from_seat": "未分配", "to_seat": "D3", "reason": "希望靠近过道，方便提前离场"},
                "status": "approved",
                "reviewer_id": "唐颖",
                "review_note": "已协调，同意换座",
            },
            {
                "event_id": EVENT_1_ID,
                "requester_name": "宋文博",
                "change_type": "add_person",
                "change_detail": {"new_person": "黄磊", "title": "摄影师", "organization": "Eventron", "reason": "临时增加活动摄影师"},
                "status": "pending",
            },
            {
                "event_id": EVENT_1_ID,
                "requester_name": "唐颖",
                "change_type": "remove",
                "change_detail": {"target": "沈思", "reason": "已确认取消参会"},
                "status": "approved",
                "reviewer_id": "王芳",
                "review_note": "确认取消",
            },
            {
                "event_id": EVENT_2_ID,
                "requester_name": "何晓东",
                "change_type": "swap",
                "change_detail": {"from_seat": "B2", "to_seat": "A5", "reason": "需要接投影设备，坐前排方便"},
                "status": "rejected",
                "reviewer_id": "赵伟",
                "review_note": "前排已满，建议在 B 排端头就座",
            },
        ]

        approval_count = 0
        for appr in approvals_data:
            att = att_orm.get((appr["event_id"], appr["requester_name"]))
            if not att:
                continue
            ar = ApprovalRequest(
                event_id=appr["event_id"],
                requester_id=att.id,
                change_type=appr["change_type"],
                change_detail=appr["change_detail"],
                status=appr["status"],
                reviewer_id=appr.get("reviewer_id"),
                review_note=appr.get("review_note"),
            )
            session.add(ar)
            approval_count += 1

        print(f"✅ 创建了 {approval_count} 条审批记录")

        await session.commit()

    await engine.dispose()

    print("\n🎉 演示数据导入完成！")
    print("=" * 50)
    for evt_data in EVENTS:
        print(f"  {evt_data['name']}")
        print(f"    {evt_data['location']} | {evt_data['venue_rows']}×{evt_data['venue_cols']} 座")
    print("=" * 50)
    print("  API 文档: http://localhost:8000/docs")


if __name__ == "__main__":
    reset_flag = "--reset" in sys.argv
    asyncio.run(seed(reset=reset_flag))
