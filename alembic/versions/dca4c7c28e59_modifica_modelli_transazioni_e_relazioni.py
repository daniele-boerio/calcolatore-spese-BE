"""modifica modelli transazioni e relazioni

Revision ID: dca4c7c28e59
Revises: d6836968bc6f
Create Date: 2026-01-23 15:40:35.380579

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

# revision identifiers, used by Alembic.
revision: str = 'dca4c7c28e59'
down_revision: Union[str, Sequence[str], None] = 'd6836968bc6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    
    # 1. Investimenti: Cambio da 'nome' a 'isin/nome_titolo'
    with op.batch_alter_table('investimenti', schema=None) as batch_op:
        batch_op.add_column(sa.Column('isin', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('nome_titolo', sa.String(), nullable=True))
        batch_op.create_index(op.f('ix_investimenti_isin'), ['isin'], unique=False)
        batch_op.drop_column('nome')

    # 2. Sottocategorie: Aggiunta user_id per sicurezza diretta
    with op.batch_alter_table('sottocategorie', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_sottocategorie_user', 'users', ['user_id'], ['id'], ondelete='CASCADE')

    # 3. Transazioni: Aggiunta user_id e Foreign Key rimborsi
    with op.batch_alter_table('transazioni', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_transazioni_user', 'users', ['user_id'], ['id'], ondelete='CASCADE')
        # Se la colonna parent_transaction_id esiste già, creiamo solo il vincolo
        batch_op.create_foreign_key('fk_transazioni_parent', 'transazioni', ['parent_transaction_id'], ['id'], ondelete='CASCADE')

    # 4. Storico Investimenti: Nuovi campi tecnici
    with op.batch_alter_table('storico_investimenti', schema=None) as batch_op:
        batch_op.add_column(sa.Column('quantita', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('prezzo_unitario', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('valore_attuale', sa.Float(), nullable=True))
        batch_op.drop_column('valore')

    # 5. Aggiunta colonne temporali a tutte le tabelle
    # Usiamo server_default con sa.func.now() così il DB popola i record esistenti
    tables_to_timestamp = [
        'users', 'categorie', 'conti', 'investimenti', 
        'ricorrenze', 'sottocategorie', 'storico_investimenti', 
        'tags', 'transazioni'
    ]

    for table in tables_to_timestamp:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('creationDate', sa.DateTime(), server_default=sa.func.now(), nullable=True))
            batch_op.add_column(sa.Column('lastUpdate', sa.DateTime(), server_default=sa.func.now(), nullable=True))

def downgrade() -> None:
    """Downgrade schema."""
    
    # Tabelle a cui rimuovere le colonne temporali
    tables_to_timestamp = [
        'users', 'categorie', 'conti', 'investimenti', 
        'ricorrenze', 'sottocategorie', 'storico_investimenti', 
        'tags', 'transazioni'
    ]

    # 1. Rimuoviamo le colonne temporali da tutte le tabelle
    for table in tables_to_timestamp:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('lastUpdate')
            batch_op.drop_column('creationDate')

    # 2. Ripristiniamo la tabella transazioni
    with op.batch_alter_table('transazioni', schema=None) as batch_op:
        batch_op.drop_constraint('fk_transazioni_user', type_='foreignkey')
        batch_op.drop_constraint('fk_transazioni_parent', type_='foreignkey')
        batch_op.drop_column('user_id')

    # 3. Ripristiniamo la tabella sottocategorie
    with op.batch_alter_table('sottocategorie', schema=None) as batch_op:
        batch_op.drop_constraint('fk_sottocategorie_user', type_='foreignkey')
        batch_op.drop_column('user_id')

    # 4. Ripristiniamo la tabella storico_investimenti
    with op.batch_alter_table('storico_investimenti', schema=None) as batch_op:
        # Ripristiniamo la vecchia colonna 'valore'
        batch_op.add_column(sa.Column('valore', sa.Float(), nullable=True))
        batch_op.drop_column('valore_attuale')
        batch_op.drop_column('prezzo_unitario')
        batch_op.drop_column('quantita')

    # 5. Ripristiniamo la tabella investimenti
    with op.batch_alter_table('investimenti', schema=None) as batch_op:
        # Ripristiniamo la vecchia colonna 'nome'
        batch_op.add_column(sa.Column('nome', sa.String(), nullable=True))
        batch_op.drop_index(op.f('ix_investimenti_isin'))
        batch_op.drop_column('nome_titolo')
        batch_op.drop_column('isin')