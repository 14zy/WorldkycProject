"""Persist administrator-assigned VMail domains and inbound recipient domains."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261023_0009"
down_revision = "20261004_0008"
branch_labels = None
depends_on = None

DEFAULT_DOMAIN = "tonstealthid.com"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "verified_links" in tables:
        columns = {column["name"] for column in inspector.get_columns("verified_links")}
        indexes = {index["name"] for index in inspector.get_indexes("verified_links")}
        if "mailboxDomain" not in columns:
            op.add_column(
                "verified_links",
                sa.Column("mailboxDomain", sa.String(length=253), nullable=False, server_default=DEFAULT_DOMAIN),
            )
        if "ix_verified_links_mailbox_domain_user_id" not in indexes:
            op.create_index(
                "ix_verified_links_mailbox_domain_user_id",
                "verified_links",
                ["mailboxDomain", "userId"],
                unique=False,
            )
        if "ix_verified_links_mailbox_alias_domain_user_id" not in indexes:
            op.create_index(
                "ix_verified_links_mailbox_alias_domain_user_id",
                "verified_links",
                ["mailboxAlias", "mailboxDomain", "userId"],
                unique=False,
            )

    if "vmail_messages" in tables:
        columns = {column["name"] for column in inspector.get_columns("vmail_messages")}
        constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("vmail_messages")}
        indexes = {index["name"] for index in inspector.get_indexes("vmail_messages")}
        if "recipient_domain" not in columns:
            op.add_column(
                "vmail_messages",
                sa.Column("recipient_domain", sa.String(length=253), nullable=False, server_default=DEFAULT_DOMAIN),
            )
        if "ix_vmail_messages_recipient_domain" not in indexes:
            op.create_index(
                "ix_vmail_messages_recipient_domain",
                "vmail_messages",
                ["recipient_domain"],
                unique=False,
            )
        if "uq_vmail_messages_mailbox_uid_alias" in constraints:
            op.drop_constraint("uq_vmail_messages_mailbox_uid_alias", "vmail_messages", type_="unique")
        if "uq_vmail_messages_mailbox_uid_alias_domain" not in constraints:
            op.create_unique_constraint(
                "uq_vmail_messages_mailbox_uid_alias_domain",
                "vmail_messages",
                ["mailbox", "imap_uid", "recipient_alias", "recipient_domain"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "vmail_messages" in tables:
        constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("vmail_messages")}
        indexes = {index["name"] for index in inspector.get_indexes("vmail_messages")}
        columns = {column["name"] for column in inspector.get_columns("vmail_messages")}
        if "uq_vmail_messages_mailbox_uid_alias_domain" in constraints:
            op.drop_constraint("uq_vmail_messages_mailbox_uid_alias_domain", "vmail_messages", type_="unique")
        if "uq_vmail_messages_mailbox_uid_alias" not in constraints:
            op.create_unique_constraint(
                "uq_vmail_messages_mailbox_uid_alias",
                "vmail_messages",
                ["mailbox", "imap_uid", "recipient_alias"],
            )
        if "ix_vmail_messages_recipient_domain" in indexes:
            op.drop_index("ix_vmail_messages_recipient_domain", table_name="vmail_messages")
        if "recipient_domain" in columns:
            op.drop_column("vmail_messages", "recipient_domain")

    if "verified_links" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("verified_links")}
        columns = {column["name"] for column in inspector.get_columns("verified_links")}
        if "ix_verified_links_mailbox_domain_user_id" in indexes:
            op.drop_index("ix_verified_links_mailbox_domain_user_id", table_name="verified_links")
        if "ix_verified_links_mailbox_alias_domain_user_id" in indexes:
            op.drop_index("ix_verified_links_mailbox_alias_domain_user_id", table_name="verified_links")
        if "mailboxDomain" in columns:
            op.drop_column("verified_links", "mailboxDomain")
