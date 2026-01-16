"""finitura_database_v1

Revision ID: 0b35beccd144
Revises: 
Create Date: 2026-01-16 15:05:23.882180

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0b35beccd144'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 1. Tabella USERS (fondamentale per tutte le chiavi esterne)
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('total_budget', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)

    # 2. Tabella CATEGORIE
    op.create_table('categorie',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
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

    # 4. Tabella CONTI (con nuovi campi ricarica)
    op.create_table('conti',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('saldo', sa.Float(), nullable=False, server_default='0'),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('ricarica_automatica', sa.Boolean(), nullable=True),
        sa.Column('budget_obiettivo', sa.Float(), nullable=True),
        sa.Column('soglia_minima', sa.Float(), nullable=True),
        sa.Column('conto_sorgente_id', sa.Integer(), nullable=True),
        sa.Column('frequenza_controllo', sa.String(), nullable=True),
        sa.Column('prossimo_controllo', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conto_sorgente_id'], ['conti.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conti_id'), 'conti', ['id'], unique=False)

    # 5. Tabella TAGS
    op.create_table('tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tags_id'), 'tags', ['id'], unique=False)

    # 6. Tabella TRANSAZIONI
    op.create_table('transazioni',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('importo', sa.Float(), nullable=False),
        sa.Column('tipo', sa.String(), nullable=False),
        sa.Column('descrizione', sa.String(), nullable=True),
        sa.Column('data', sa.DateTime(), nullable=True),
        sa.Column('conto_id', sa.Integer(), nullable=True),
        sa.Column('categoria_id', sa.Integer(), nullable=True),
        sa.Column('sottocategoria_id', sa.Integer(), nullable=True),
        sa.Column('tag_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['categoria_id'], ['categorie.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['conto_id'], ['conti.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sottocategoria_id'], ['sottocategorie.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transazioni_id'), 'transazioni', ['id'], unique=False)

    # 7. Tabella RICORRENZE
    op.create_table('ricorrenze',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('importo', sa.Float(), nullable=False),
        sa.Column('tipo', sa.String(), nullable=False),
        sa.Column('frequenza', sa.String(), nullable=False),
        sa.Column('prossima_esecuzione', sa.Date(), nullable=False),
        sa.Column('attiva', sa.Boolean(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('conto_id', sa.Integer(), nullable=True),
        sa.Column('categoria_id', sa.Integer(), nullable=True),
        sa.Column('tag_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['categoria_id'], ['categorie.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['conto_id'], ['conti.id'], ),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ricorrenze_id'), 'ricorrenze', ['id'], unique=False)

    # 8. Tabella INVESTIMENTI
    op.create_table('investimenti',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('ticker', sa.String(), nullable=True),
        sa.Column('prezzo_attuale', sa.Float(), nullable=True),
        sa.Column('data_ultimo_aggiornamento', sa.Date(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_investimenti_id'), 'investimenti', ['id'], unique=False)
    op.create_index(op.f('ix_investimenti_ticker'), 'investimenti', ['ticker'], unique=False)

    # 9. Tabella STORICO_INVESTIMENTI
    op.create_table('storico_investimenti',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('data', sa.Date(), nullable=False),
        sa.Column('valore', sa.Float(), nullable=False),
        sa.Column('investimento_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['investimento_id'], ['investimenti.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_storico_investimenti_id'), 'storico_investimenti', ['id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'total_budget')
    op.drop_column('users', 'username')
    op.drop_constraint(None, 'transazioni', type_='foreignkey')
    op.drop_constraint(None, 'transazioni', type_='foreignkey')
    op.drop_constraint(None, 'transazioni', type_='foreignkey')
    op.drop_constraint(None, 'transazioni', type_='foreignkey')
    op.create_foreign_key(op.f('transazioni_conto_id_fkey'), 'transazioni', 'conti', ['conto_id'], ['id'])
    op.create_foreign_key(op.f('transazioni_categoria_id_fkey'), 'transazioni', 'categorie', ['categoria_id'], ['id'])
    op.drop_column('transazioni', 'tag_id')
    op.drop_column('transazioni', 'sottocategoria_id')
    op.drop_constraint(None, 'storico_investimenti', type_='foreignkey')
    op.create_foreign_key(op.f('storico_investimenti_investimento_id_fkey'), 'storico_investimenti', 'investimenti', ['investimento_id'], ['id'])
    op.drop_index(op.f('ix_investimenti_ticker'), table_name='investimenti')
    op.drop_column('investimenti', 'data_ultimo_aggiornamento')
    op.drop_column('investimenti', 'prezzo_attuale')
    op.drop_column('investimenti', 'ticker')
    op.add_column('conti', sa.Column('tipo', sa.VARCHAR(), autoincrement=False, nullable=True))
    op.drop_constraint(None, 'conti', type_='foreignkey')
    op.drop_column('conti', 'prossimo_controllo')
    op.drop_column('conti', 'frequenza_controllo')
    op.drop_column('conti', 'conto_sorgente_id')
    op.drop_column('conti', 'soglia_minima')
    op.drop_column('conti', 'budget_obiettivo')
    op.drop_column('conti', 'ricarica_automatica')
    op.drop_column('conti', 'saldo')
    op.add_column('categorie', sa.Column('parent_id', sa.INTEGER(), autoincrement=False, nullable=True))
    op.create_foreign_key(op.f('categorie_parent_id_fkey'), 'categorie', 'categorie', ['parent_id'], ['id'])
    op.drop_index(op.f('ix_sottocategorie_id'), table_name='sottocategorie')
    op.drop_table('sottocategorie')
    op.drop_index(op.f('ix_ricorrenze_id'), table_name='ricorrenze')
    op.drop_table('ricorrenze')
    op.drop_index(op.f('ix_tags_id'), table_name='tags')
    op.drop_table('tags')
    # ### end Alembic commands ###
