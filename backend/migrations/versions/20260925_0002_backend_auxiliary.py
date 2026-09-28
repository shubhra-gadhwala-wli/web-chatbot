"""backend auxiliary tables for two contract gaps (see backend/CONTRACT_GAPS.md)

Additive only: it does not alter any table, column or constraint published in
the DataAPI revision 20260925_0001.

1. `accounts` has no email column, but openapi.yaml's Register/Login requests
   authenticate by email. `account_emails` stores the lookup key out of band.
2. `create_upload(..., idempotency_key)` needs durable per-account idempotency
   storage; `documents` has no such column. `upload_idempotency` provides it.

Revision ID: 20260925_0002
Revises: 20260925_0001
"""
from alembic import op
import sqlalchemy as sa

revision = "20260925_0002"
down_revision = "20260925_0001"
branch_labels = None
depends_on = None


def _exists(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _exists("account_emails"):
        op.create_table(
            "account_emails",
            sa.Column("account_id", sa.String(64), primary_key=True),
            sa.Column("email_normalized", sa.String(320), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        )
    if not _exists("upload_idempotency"):
        op.create_table(
            "upload_idempotency",
            sa.Column("account_id", sa.String(64), nullable=False),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column("request_hash", sa.String(64), nullable=False),
            sa.Column("document_id", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("account_id", "idempotency_key",
                                    name="pk_upload_idempotency"),
            sa.ForeignKeyConstraint(["account_id", "document_id"],
                                    ["documents.account_id", "documents.id"],
                                    ondelete="CASCADE"),
        )


def downgrade() -> None:
    for table in ("upload_idempotency", "account_emails"):
        if _exists(table):
            op.drop_table(table)
