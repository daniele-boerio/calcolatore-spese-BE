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
    op.add_column(
        "conti", sa.Column("bank_connector_provider", sa.String(), nullable=True)
    )
    op.add_column(
        "conti", sa.Column("bank_connector_account_id", sa.String(), nullable=True)
    )
    op.add_column(
        "conti", sa.Column("bank_connector_institution_id", sa.String(), nullable=True)
    )
    op.add_column(
        "conti", sa.Column("bank_connector_client_id", sa.String(), nullable=True)
    )
    op.add_column(
        "conti", sa.Column("bank_connector_secret", sa.String(), nullable=True)
    )
    op.add_column(
        "conti", sa.Column("bank_connector_access_token", sa.String(), nullable=True)
    )
    op.add_column(
        "conti", sa.Column("bank_connector_refresh_token", sa.String(), nullable=True)
    )
    op.add_column(
        "conti", sa.Column("bank_connector_last_sync", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "conti", sa.Column("bank_connector_last_error", sa.String(), nullable=True)
    )

    op.create_table(
        "bank_transaction_proposals",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")
        ),
        sa.Column(
            "conto_id", sa.Integer(), sa.ForeignKey("conti.id", ondelete="CASCADE")
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True, index=True),
        sa.Column("tipo", sa.String(), nullable=False),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("importo", sa.Numeric(10, 2), nullable=False),
        sa.Column("descrizione", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, default="PENDING"),
        sa.Column(
            "imported_transaction_id",
            sa.Integer(),
            sa.ForeignKey("transazioni.id"),
            nullable=True,
        ),
        sa.Column("creationDate", sa.DateTime(), nullable=True),
        sa.Column("lastUpdate", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("bank_transaction_proposals")
    op.drop_column("conti", "bank_connector_last_error")
    op.drop_column("conti", "bank_connector_last_sync")
    op.drop_column("conti", "bank_connector_refresh_token")
    op.drop_column("conti", "bank_connector_access_token")
    op.drop_column("conti", "bank_connector_secret")
    op.drop_column("conti", "bank_connector_client_id")
    op.drop_column("conti", "bank_connector_institution_id")
    op.drop_column("conti", "bank_connector_account_id")
    op.drop_column("conti", "bank_connector_provider")
    op.drop_column("transazioni", "split_group_id")
