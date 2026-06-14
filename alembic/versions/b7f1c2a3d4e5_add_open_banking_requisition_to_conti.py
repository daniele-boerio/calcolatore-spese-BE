"""add_open_banking_link_fields_to_conti

Revision ID: b7f1c2a3d4e5
Revises: 4a9299ada80f
Create Date: 2026-06-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f1c2a3d4e5'
down_revision: Union[str, Sequence[str], None] = '4a9299ada80f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('conti', sa.Column('bank_connector_session_id', sa.String(), nullable=True))
    op.add_column('conti', sa.Column('bank_connector_auth_state', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conti', 'bank_connector_auth_state')
    op.drop_column('conti', 'bank_connector_session_id')
