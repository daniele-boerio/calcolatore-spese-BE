"""idempotenza_saldo_base_ricorrenze

Revision ID: f7b8c9d0e1a2
Revises: e6a7b8c9d0f1
Create Date: 2026-10-04 00:00:00.000000

Tre cose che rendono più solidi i movimenti:

- `transazioni.idempotency_key` + indice unico (user_id, idempotency_key): una
  POST ripetuta (rete caduta dopo il commit, coda offline) non duplica più. Le
  righe esistenti restano a NULL, e NULL non collide nell'indice unico.
- `conti.saldo_base`: saldo meno l'effetto dei movimenti attivi. Nasce NULL e la
  fotografa il primo controllo notturno, che da lì in poi segnala i saldi
  andati fuori sincrono.
- Ricorrenze: `data_fine`, `rate_rimanenti`, `importo_variabile` (NOT NULL,
  default false per le righe esistenti) e `debito_id` per le rate di un debito.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7b8c9d0e1a2'
down_revision: Union[str, Sequence[str], None] = 'e6a7b8c9d0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'transazioni',
        sa.Column('idempotency_key', sa.String(length=64), nullable=True),
    )
    op.create_index(
        'ux_transazioni_user_idempotency',
        'transazioni',
        ['user_id', 'idempotency_key'],
        unique=True,
    )

    op.add_column(
        'conti',
        sa.Column('saldo_base', sa.Numeric(10, 2), nullable=True),
    )

    op.add_column('ricorrenze', sa.Column('data_fine', sa.Date(), nullable=True))
    op.add_column(
        'ricorrenze', sa.Column('rate_rimanenti', sa.Integer(), nullable=True)
    )
    op.add_column(
        'ricorrenze',
        sa.Column(
            'importo_variabile',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        'ricorrenze', sa.Column('debito_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_ricorrenze_debito_id',
        'ricorrenze',
        'debiti',
        ['debito_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_ricorrenze_debito_id', 'ricorrenze', type_='foreignkey')
    op.drop_column('ricorrenze', 'debito_id')
    op.drop_column('ricorrenze', 'importo_variabile')
    op.drop_column('ricorrenze', 'rate_rimanenti')
    op.drop_column('ricorrenze', 'data_fine')

    op.drop_column('conti', 'saldo_base')

    op.drop_index('ux_transazioni_user_idempotency', table_name='transazioni')
    op.drop_column('transazioni', 'idempotency_key')
