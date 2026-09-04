"""add_patrimonio_snapshots

Revision ID: d5f6a7b8c9e0
Revises: c4e5f6a7b8d9
Create Date: 2026-09-04 00:00:00.000000

Una fotografia mensile del patrimonio: quanto c'era sui conti e quanto
valevano i titoli, alla fine di ogni mese.

Serve perché il patrimonio di ieri non è ricostruibile. I saldi dei conti sì
— basta togliere le transazioni successive — ma il valore di mercato dei
titoli no: lo storico degli investimenti tiene le operazioni, non i prezzi
giorno per giorno. Senza una foto scattata al momento, "sei cresciuto del 2,4%
rispetto ad agosto" non si può dire.

La tabella parte vuota e si riempie da qui in avanti: finché non c'è la foto
del mese scorso, l'interfaccia non mostra nessun confronto invece di
inventarne uno.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5f6a7b8c9e0"
down_revision: Union[str, Sequence[str], None] = "c4e5f6a7b8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patrimonio_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("anno", sa.Integer(), nullable=False),
        sa.Column("mese", sa.Integer(), nullable=False),
        sa.Column("conti", sa.Numeric(12, 2), nullable=False),
        sa.Column("titoli", sa.Numeric(12, 2), nullable=False),
        sa.Column("creationDate", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Una foto sola per utente e per mese: il job può girare più volte.
        sa.UniqueConstraint(
            "user_id", "anno", "mese", name="uq_patrimonio_utente_mese"
        ),
    )
    op.create_index(
        "ix_patrimonio_snapshots_user_id",
        "patrimonio_snapshots",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_patrimonio_snapshots_user_id", table_name="patrimonio_snapshots")
    op.drop_table("patrimonio_snapshots")
