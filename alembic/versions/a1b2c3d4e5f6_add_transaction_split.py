"""add transaction split

Revision ID: a1b2c3d4e5f6
Revises: 8c711d33ea7b
Create Date: 2026-06-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "8c711d33ea7b"
branch_labels = None
depend_on = None


def upgrade() -> None:
    op.add_column(
        "transazioni", sa.Column("split_group_id", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("transazioni", "split_group_id")
