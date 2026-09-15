"""add_budget_mensile_alle_categorie

Revision ID: e6a7b8c9d0f1
Revises: d5f6a7b8c9e0
Create Date: 2026-09-15 00:00:00.000000

Quanto si vorrebbe spendere in un mese su una categoria. È il fratello per
categoria di `users.monthly_spending_budget`, che è il tetto complessivo.

Nullable senza default: le categorie esistenti restano senza budget deciso, e
l'Analisi non mostra la barra finché non ce n'è uno. Zero non andrebbe bene
come "non impostato" — zero è un budget vero, e vuol dire "non spenderci
niente".

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6a7b8c9d0f1'
down_revision: Union[str, Sequence[str], None] = 'd5f6a7b8c9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'categorie',
        sa.Column('budget_mensile', sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('categorie', 'budget_mensile')
