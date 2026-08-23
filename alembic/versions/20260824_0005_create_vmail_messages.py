"""Create vmail_messages table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260824_0005"
down_revision = "20250630_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "vmail_messages" in tables:
        return

    op.create_table(
        "vmail_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mailbox", sa.String(), nullable=False),
        sa.Column("imap_uid", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("recipient_alias", sa.String(), nullable=False),
        sa.Column("telegramId", sa.BigInteger(), nullable=True),
        sa.Column("userId", sa.String(), nullable=True),
        sa.Column("from_header", sa.String(), nullable=False),
        sa.Column("reply_to", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("snippet", sa.String(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("sender_trust", sa.String(), nullable=False, server_default="anonymous"),
        sa.Column("notary_status", sa.String(), nullable=True),
        sa.Column("identity_status", sa.String(), nullable=True),
        sa.Column("governance_status", sa.String(), nullable=True),
        sa.Column("delivery_status", sa.String(), nullable=False),
        sa.Column("receivedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processedAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.String(), nullable=True),
        sa.UniqueConstraint("mailbox", "imap_uid", "recipient_alias", name="uq_vmail_messages_mailbox_uid_alias"),
    )
    op.create_index("ix_vmail_messages_recipient_alias", "vmail_messages", ["recipient_alias"], unique=False)
    op.create_index("ix_vmail_messages_telegramId", "vmail_messages", ["telegramId"], unique=False)
    op.create_index("ix_vmail_messages_userId", "vmail_messages", ["userId"], unique=False)
    op.create_index("ix_vmail_messages_delivery_status", "vmail_messages", ["delivery_status"], unique=False)
    op.create_index("ix_vmail_messages_processedAt", "vmail_messages", ["processedAt"], unique=False)
    op.create_index("ix_vmail_messages_receivedAt", "vmail_messages", ["receivedAt"], unique=False)
    op.create_index("ix_vmail_messages_message_id", "vmail_messages", ["message_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "vmail_messages" not in tables:
        return

    op.drop_index("ix_vmail_messages_message_id", table_name="vmail_messages")
    op.drop_index("ix_vmail_messages_receivedAt", table_name="vmail_messages")
    op.drop_index("ix_vmail_messages_processedAt", table_name="vmail_messages")
    op.drop_index("ix_vmail_messages_delivery_status", table_name="vmail_messages")
    op.drop_index("ix_vmail_messages_userId", table_name="vmail_messages")
    op.drop_index("ix_vmail_messages_telegramId", table_name="vmail_messages")
    op.drop_index("ix_vmail_messages_recipient_alias", table_name="vmail_messages")
    op.drop_table("vmail_messages")
