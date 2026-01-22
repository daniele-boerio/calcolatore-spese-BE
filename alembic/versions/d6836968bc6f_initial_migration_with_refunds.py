"""initial_migration_with_refunds

Revision ID: d6836968bc6f
Revises: 
Create Date: 2026-01-22 10:59:18.327140

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd6836968bc6f'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. Tabella USERS
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('total_budget', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)

    # 2. Tabella CATEGORIE
    op.create_table('categorie',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('tipo', sa.String(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_categorie_id'), 'categorie', ['id'], unique=False)

    # 3. Tabella SOTTOCATEGORIE
    op.create_table('sottocategorie',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('categoria_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['categoria_id'], ['categorie.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sottocategorie_id'), 'sottocategorie', ['id'], unique=False)

    # 4. Tabella TAGS
    op.create_table('tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tags_id'), 'tags', ['id'], unique=False)

    # 5. Tabella CONTI
    op.create_table('conti',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('saldo', sa.Float(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conti_id'), 'conti', ['id'], unique=False)

    # 6. Tabella TRANSAZIONI (Include parent_transaction_id)
    op.create_table('transazioni',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('importo', sa.Float(), nullable=False),
        sa.Column('tipo', sa.String(), nullable=False),
        sa.Column('data', sa.DateTime(), nullable=False),
        sa.Column('descrizione', sa.String(), nullable=True),
        sa.Column('conto_id', sa.Integer(), nullable=True),
        sa.Column('categoria_id', sa.Integer(), nullable=True),
        sa.Column('sottocategoria_id', sa.Integer(), nullable=True),
        sa.Column('tag_id', sa.Integer(), nullable=True),
        sa.Column('parent_transaction_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['categoria_id'], ['categorie.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['conto_id'], ['conti.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_transaction_id'], ['transazioni.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sottocategoria_id'], ['sottocategorie.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transazioni_id'), 'transazioni', ['id'], unique=False)

    # 7. Tabella INVESTIMENTI
    op.create_table('investimenti',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('tipo', sa.String(), nullable=False),
        sa.Column('ticker', sa.String(), nullable=True),
        sa.Column('quantita', sa.Float(), nullable=False),
        sa.Column('prezzo_medio_carico', sa.Float(), nullable=False),
        sa.Column('prezzo_attuale', sa.Float(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_investimenti_id'), 'investimenti', ['id'], unique=False)
    op.create_index(op.f('ix_investimenti_ticker'), 'investimenti', ['ticker'], unique=False)

def downgrade() -> None:
    op.drop_table('investimenti')
    op.drop_table('transazioni')
    op.drop_table('conti')
    op.drop_table('tags')
    op.drop_table('sottocategorie')
    op.drop_table('categorie')
    op.drop_table('users')