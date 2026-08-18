"""add_last_tag_id_to_users

Revision ID: f1a2b3c4d5e6
Revises: c3f81a9d2e07
Create Date: 2026-08-19 00:00:00.000000

Il tag usato nell'ultima transazione creata, per precompilare il form della
successiva. Nullable senza default: gli utenti esistenti partono senza
precompilazione, esattamente come oggi.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'c3f81a9d2e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('last_tag_id', sa.Integer(), nullable=True))
    # SET NULL e non CASCADE: cancellare un tag deve spegnere la precompilazione,
    # non toccare l'utente.
    op.create_foreign_key(
        'fk_users_last_tag_id',
        'users',
        'tags',
        ['last_tag_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_users_last_tag_id', 'users', type_='foreignkey')
    op.drop_column('users', 'last_tag_id')
