"""add_performance_indexes

Aggiunge indici di performance sulle colonne filtrate in (quasi) ogni query:

- `user_id` su tutte le tabelle user-scoped: senza indice il DB fa un full scan
  che cresce con TUTTI i dati di TUTTI gli utenti.
- `transazioni(user_id, data)`: indice composito che copre il filtro utente +
  il range/ordinamento per data della lista paginata (la query più calda).
- `transazioni(conto_id)` e `sottocategorie(categoria_id)`: filtri/join frequenti.

Solo `CREATE INDEX` (nessuna modifica dati, non distruttivo). Su tabelle molto
grandi valutare `CREATE INDEX CONCURRENTLY` per evitare il lock in scrittura.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(op.f('ix_conti_user_id'), 'conti', ['user_id'], unique=False)
    op.create_index(
        op.f('ix_categorie_user_id'), 'categorie', ['user_id'], unique=False
    )
    op.create_index(
        op.f('ix_sottocategorie_user_id'), 'sottocategorie', ['user_id'], unique=False
    )
    op.create_index(
        op.f('ix_sottocategorie_categoria_id'),
        'sottocategorie',
        ['categoria_id'],
        unique=False,
    )
    op.create_index(op.f('ix_tags_user_id'), 'tags', ['user_id'], unique=False)
    op.create_index(op.f('ix_debiti_user_id'), 'debiti', ['user_id'], unique=False)
    op.create_index(
        op.f('ix_investimenti_user_id'), 'investimenti', ['user_id'], unique=False
    )
    op.create_index(
        op.f('ix_ricorrenze_user_id'), 'ricorrenze', ['user_id'], unique=False
    )
    op.create_index(
        op.f('ix_bank_proposals_user_id'),
        'bank_transaction_proposals',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_transazioni_user_id_data'),
        'transazioni',
        ['user_id', 'data'],
        unique=False,
    )
    op.create_index(
        op.f('ix_transazioni_conto_id'), 'transazioni', ['conto_id'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_transazioni_conto_id'), table_name='transazioni')
    op.drop_index(op.f('ix_transazioni_user_id_data'), table_name='transazioni')
    op.drop_index(
        op.f('ix_bank_proposals_user_id'), table_name='bank_transaction_proposals'
    )
    op.drop_index(op.f('ix_ricorrenze_user_id'), table_name='ricorrenze')
    op.drop_index(op.f('ix_investimenti_user_id'), table_name='investimenti')
    op.drop_index(op.f('ix_debiti_user_id'), table_name='debiti')
    op.drop_index(op.f('ix_tags_user_id'), table_name='tags')
    op.drop_index(op.f('ix_sottocategorie_categoria_id'), table_name='sottocategorie')
    op.drop_index(op.f('ix_sottocategorie_user_id'), table_name='sottocategorie')
    op.drop_index(op.f('ix_categorie_user_id'), table_name='categorie')
    op.drop_index(op.f('ix_conti_user_id'), table_name='conti')
