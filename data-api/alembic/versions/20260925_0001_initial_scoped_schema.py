"""initial account-scoped first-slice schema

Revision ID: 20260925_0001
Revises:
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa

revision = "20260925_0001"
down_revision = None
branch_labels = None
depends_on = None


def _exists(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    # Guard makes a repeated `alembic upgrade head` safe after interrupted
    # orchestration; Alembic itself records successful revisions normally.
    if _exists("accounts"):
        return
    op.create_table("accounts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("disabled_at", sa.DateTime()),
    )
    op.create_table("sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sessions_account_active", "sessions", ["account_id", "expires_at"])
    op.create_table("documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(128), nullable=False, unique=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
        sa.CheckConstraint("byte_size >= 0 AND byte_size <= 26214400", name="ck_documents_size"),
        sa.CheckConstraint("status IN ('uploaded','processing','ready','failed','deleting')", name="ck_documents_status"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("account_id", "id", name="uq_documents_account_id"),
    )
    op.create_index("ix_documents_account_status_created", "documents", ["account_id", "status", "created_at"])
    op.create_table("chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("location_kind", sa.String(8), nullable=False),
        sa.Column("location_start", sa.Integer(), nullable=False),
        sa.Column("location_end", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["account_id", "document_id"], ["documents.account_id", "documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("account_id", "id", name="uq_chunks_account_id"),
        sa.UniqueConstraint("document_id", "generation", "ordinal", name="uq_chunks_document_generation_ordinal"),
        sa.CheckConstraint("ordinal >= 0 AND location_start >= 0 AND location_end >= location_start", name="ck_chunks_location"),
    )
    op.create_index("ix_chunks_account_document", "chunks", ["account_id", "document_id", "generation"])
    op.create_table("conversations",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("account_id", "id", name="uq_conversations_account_id"),
    )
    op.create_index("ix_conversations_account_updated", "conversations", ["account_id", "updated_at"])
    op.create_table("messages",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("account_id", sa.String(64), nullable=False), sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("role", sa.String(12), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("client_request_id", sa.String(128)), sa.Column("request_hash", sa.String(64)), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id", "conversation_id"], ["conversations.account_id", "conversations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("account_id", "id", name="uq_messages_account_id"),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_messages_conversation_sequence"), sa.UniqueConstraint("account_id", "client_request_id", name="uq_messages_account_request"),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_messages_role"),
    )
    op.create_index("ix_messages_account_conversation", "messages", ["account_id", "conversation_id", "sequence"])
    op.create_table("citations",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("account_id", sa.String(64), nullable=False), sa.Column("message_id", sa.String(64), nullable=False), sa.Column("chunk_id", sa.String(64), nullable=False), sa.Column("document_id", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["account_id", "message_id"], ["messages.account_id", "messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id", "chunk_id"], ["chunks.account_id", "chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id", "document_id"], ["documents.account_id", "documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("message_id", "chunk_id", name="uq_citations_message_chunk"),
    )
    op.create_index("ix_citations_account_message", "citations", ["account_id", "message_id"])


def downgrade() -> None:
    # Reverse dependency order; safe if a failed/partial upgrade never created tables.
    for table in ("citations", "messages", "conversations", "chunks", "documents", "sessions", "accounts"):
        if _exists(table):
            op.drop_table(table)
