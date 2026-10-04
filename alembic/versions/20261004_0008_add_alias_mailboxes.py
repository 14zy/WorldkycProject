"""Add synchronized VLink aliases and VMail namespace type."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261004_0008"
down_revision = "20260902_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "verified_links" in tables:
        columns = {column["name"] for column in inspector.get_columns("verified_links")}
        indexes = {index["name"] for index in inspector.get_indexes("verified_links")}
        if "mailboxAlias" not in columns:
            op.add_column("verified_links", sa.Column("mailboxAlias", sa.String(length=64), nullable=True))
        if "ix_verified_links_mailboxAlias" not in indexes:
            op.create_index("ix_verified_links_mailboxAlias", "verified_links", ["mailboxAlias"], unique=False)
        if "ix_verified_links_mailbox_alias_user_id" not in indexes:
            op.create_index(
                "ix_verified_links_mailbox_alias_user_id",
                "verified_links",
                ["mailboxAlias", "userId"],
                unique=False,
            )

    if "vmail_messages" in tables:
        columns = {column["name"] for column in inspect(bind).get_columns("vmail_messages")}
        if "mailbox_type" not in columns:
            op.add_column(
                "vmail_messages",
                sa.Column("mailbox_type", sa.String(length=16), nullable=False, server_default="vlink"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "vmail_messages" in tables:
        columns = {column["name"] for column in inspector.get_columns("vmail_messages")}
        if "mailbox_type" in columns:
            op.drop_column("vmail_messages", "mailbox_type")

    if "verified_links" in tables:
        columns = {column["name"] for column in inspector.get_columns("verified_links")}
        indexes = {index["name"] for index in inspector.get_indexes("verified_links")}
        if "ix_verified_links_mailbox_alias_user_id" in indexes:
            op.drop_index("ix_verified_links_mailbox_alias_user_id", table_name="verified_links")
        if "ix_verified_links_mailboxAlias" in indexes:
            op.drop_index("ix_verified_links_mailboxAlias", table_name="verified_links")
        if "mailboxAlias" in columns:
            op.drop_column("verified_links", "mailboxAlias")
