"""Add durable outbound VMail and inbound thread references."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260902_0007"
down_revision = "20260831_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "vmail_messages" in tables:
        columns = {column["name"] for column in inspector.get_columns("vmail_messages")}
        if "references" not in columns:
            op.add_column("vmail_messages", sa.Column("references", sa.Text(), nullable=True))

    if "outbound_vmail_messages" not in tables:
        op.create_table(
            "outbound_vmail_messages",
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column(
                "userId",
                sa.String(),
                sa.ForeignKey("world_kyc_accounts.userId", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("reference", sa.String(), nullable=False),
            sa.Column("original_message_id", sa.Integer(), nullable=True),
            sa.Column("client_request_id", sa.String(length=32), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("from_address", sa.String(length=320), nullable=False),
            sa.Column("to_address", sa.String(length=320), nullable=False),
            sa.Column("subject", sa.String(length=200), nullable=False),
            sa.Column("body_text", sa.Text(), nullable=False),
            sa.Column("in_reply_to", sa.String(), nullable=True),
            sa.Column("references", sa.Text(), nullable=True),
            sa.Column("resend_email_id", sa.String(), nullable=True),
            sa.Column("rfc_message_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("createdAt", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updatedAt", sa.DateTime(timezone=True), nullable=False),
            sa.Column("failure_category", sa.String(length=64), nullable=True),
            sa.Column("correlation_id", sa.String(length=64), nullable=False),
            sa.UniqueConstraint("userId", "client_request_id", name="uq_outbound_vmail_user_request"),
            sa.UniqueConstraint("resend_email_id", name="uq_outbound_vmail_resend_email_id"),
        )
        op.create_index("ix_outbound_vmail_messages_userId", "outbound_vmail_messages", ["userId"])
        op.create_index("ix_outbound_vmail_messages_reference", "outbound_vmail_messages", ["reference"])
        op.create_index("ix_outbound_vmail_messages_original_message_id", "outbound_vmail_messages", ["original_message_id"])
        op.create_index("ix_outbound_vmail_messages_resend_email_id", "outbound_vmail_messages", ["resend_email_id"])
        op.create_index("ix_outbound_vmail_messages_status", "outbound_vmail_messages", ["status"])
        op.create_index("ix_outbound_vmail_messages_createdAt", "outbound_vmail_messages", ["createdAt"])

    if "resend_webhook_events" not in tables:
        op.create_table(
            "resend_webhook_events",
            sa.Column("event_id", sa.String(), primary_key=True),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("receivedAt", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "resend_webhook_events" in tables:
        op.drop_table("resend_webhook_events")
    if "outbound_vmail_messages" in tables:
        op.drop_index("ix_outbound_vmail_messages_createdAt", table_name="outbound_vmail_messages")
        op.drop_index("ix_outbound_vmail_messages_status", table_name="outbound_vmail_messages")
        op.drop_index("ix_outbound_vmail_messages_resend_email_id", table_name="outbound_vmail_messages")
        op.drop_index("ix_outbound_vmail_messages_original_message_id", table_name="outbound_vmail_messages")
        op.drop_index("ix_outbound_vmail_messages_reference", table_name="outbound_vmail_messages")
        op.drop_index("ix_outbound_vmail_messages_userId", table_name="outbound_vmail_messages")
        op.drop_table("outbound_vmail_messages")
    if "vmail_messages" in tables:
        columns = {column["name"] for column in inspect(bind).get_columns("vmail_messages")}
        if "references" in columns:
            op.drop_column("vmail_messages", "references")
