"""add attendee priority and seat zone

Revision ID: c3a7d8e2f195
Revises: b09e6c1a0f60
Create Date: 2026-03-20 23:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a7d8e2f195'
down_revision: Union[str, None] = 'b09e6c1a0f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Attendee: add priority column (int, default 0)
    op.add_column(
        'attendees',
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
    )

    # Attendee: widen role column from enum-length to 50 chars for free-text
    op.alter_column(
        'attendees',
        'role',
        existing_type=sa.String(20),
        type_=sa.String(50),
        server_default='参会者',
    )

    # Seat: add zone column (nullable string for venue zones)
    op.add_column(
        'seats',
        sa.Column('zone', sa.String(50), nullable=True),
    )

    # Seat: remove 'vip' from seat_type values (migrate existing rows)
    op.execute(
        "UPDATE seats SET seat_type = 'reserved', zone = '贵宾区' "
        "WHERE seat_type = 'vip'"
    )

    # Migrate old role enum values to new labels with priorities
    op.execute(
        "UPDATE attendees SET priority = 15, role = '甲方嘉宾' "
        "WHERE role = 'vip'"
    )
    op.execute(
        "UPDATE attendees SET priority = 10, role = '演讲嘉宾' "
        "WHERE role = 'speaker'"
    )
    op.execute(
        "UPDATE attendees SET priority = 5, role = '组织方' "
        "WHERE role = 'organizer'"
    )
    op.execute(
        "UPDATE attendees SET priority = 1, role = '工作人员' "
        "WHERE role = 'staff'"
    )
    op.execute(
        "UPDATE attendees SET priority = 0, role = '参会者' "
        "WHERE role = 'attendee'"
    )


def downgrade() -> None:
    # Reverse role migrations
    op.execute(
        "UPDATE attendees SET role = 'vip' "
        "WHERE role IN ('甲方嘉宾', '投资人') AND priority >= 10"
    )
    op.execute(
        "UPDATE attendees SET role = 'speaker' WHERE role = '演讲嘉宾'"
    )
    op.execute(
        "UPDATE attendees SET role = 'organizer' WHERE role = '组织方'"
    )
    op.execute(
        "UPDATE attendees SET role = 'staff' WHERE role = '工作人员'"
    )
    op.execute(
        "UPDATE attendees SET role = 'attendee' WHERE role = '参会者'"
    )

    # Reverse seat migration
    op.execute(
        "UPDATE seats SET seat_type = 'vip' "
        "WHERE seat_type = 'reserved' AND zone = '贵宾区'"
    )

    op.drop_column('seats', 'zone')

    op.alter_column(
        'attendees',
        'role',
        existing_type=sa.String(50),
        type_=sa.String(20),
    )

    op.drop_column('attendees', 'priority')
