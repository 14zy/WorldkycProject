"""Create verified_links and processed_emails tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20250622_0002"
down_revision = "20250622_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "verified_links" not in tables:
        op.create_table(
            "verified_links",
            sa.Column("reference", sa.String(), primary_key=True, nullable=False),
            sa.Column("telegramId", sa.Integer(), sa.ForeignKey("users.telegramId"), nullable=False),
            sa.Column("userId", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("updatedAt", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_verified_links_reference", "verified_links", ["reference"], unique=False)
        op.create_index("ix_verified_links_telegramId", "verified_links", ["telegramId"], unique=False)
        op.create_index("ix_verified_links_userId", "verified_links", ["userId"], unique=False)
        op.create_index("ix_verified_links_updatedAt", "verified_links", ["updatedAt"], unique=False)

    if "processed_emails" not in tables:
        op.create_table(
            "processed_emails",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("mailbox", sa.String(), nullable=False),
            sa.Column("imap_uid", sa.String(), nullable=False),
            sa.Column("message_id", sa.String(), nullable=True),
            sa.Column("recipient_alias", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("processedAt", sa.DateTime(timezone=True), nullable=False),
            sa.Column("error", sa.String(), nullable=True),
            sa.UniqueConstraint("mailbox", "imap_uid", name="uq_processed_emails_mailbox_uid"),
        )
        op.create_index("ix_processed_emails_mailbox", "processed_emails", ["mailbox"], unique=False)
        op.create_index("ix_processed_emails_message_id", "processed_emails", ["message_id"], unique=False)
        op.create_index("ix_processed_emails_recipient_alias", "processed_emails", ["recipient_alias"], unique=False)
        op.create_index("ix_processed_emails_status", "processed_emails", ["status"], unique=False)
        op.create_index("ix_processed_emails_processedAt", "processed_emails", ["processedAt"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "processed_emails" in tables:
        op.drop_index("ix_processed_emails_processedAt", table_name="processed_emails")
        op.drop_index("ix_processed_emails_status", table_name="processed_emails")
        op.drop_index("ix_processed_emails_recipient_alias", table_name="processed_emails")
        op.drop_index("ix_processed_emails_message_id", table_name="processed_emails")
        op.drop_index("ix_processed_emails_mailbox", table_name="processed_emails")
        op.drop_table("processed_emails")

    if "verified_links" in tables:
        op.drop_index("ix_verified_links_updatedAt", table_name="verified_links")
        op.drop_index("ix_verified_links_userId", table_name="verified_links")
        op.drop_index("ix_verified_links_telegramId", table_name="verified_links")
        op.drop_index("ix_verified_links_reference", table_name="verified_links")
        op.drop_table("verified_links")
