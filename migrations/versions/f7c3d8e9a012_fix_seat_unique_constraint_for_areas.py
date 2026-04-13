"""Fix seat unique constraint to include area_id for multi-area support.

Revision ID: f7c3d8e9a012
Revises: e5a2b3c4d507
Create Date: 2026-03-22
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "f7c3d8e9a012"
down_revision = "e5a2b3c4d507"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old constraint that only covers (event_id, row_num, col_num)
    op.drop_constraint("uq_seat_position", "seats", type_="unique")
    # Create new constraint that includes area_id so different areas
    # can have seats with the same row_num/col_num
    op.create_unique_constraint(
        "uq_seat_position_area",
        "seats",
        ["event_id", "area_id", "row_num", "col_num"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_seat_position_area", "seats", type_="unique")
    op.create_unique_constraint(
        "uq_seat_position",
        "seats",
        ["event_id", "row_num", "col_num"],
    )
