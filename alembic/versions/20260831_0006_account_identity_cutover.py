"""Add account-centered identity and backfill Telegram links.

The legacy users table and Telegram ownership columns are intentionally retained
for rollback during the maintenance-window cutover.
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260831_0006"
down_revision = "20260824_0005"
branch_labels = None
depends_on = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _non_empty(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _create_identity_tables(inspector) -> None:
    tables = set(inspector.get_table_names())
    if "world_kyc_accounts" not in tables:
        op.create_table(
            "world_kyc_accounts",
            sa.Column("userId", sa.String(), primary_key=True, nullable=False),
            sa.Column("emailAddress", sa.String(), nullable=True),
            sa.Column("createdAt", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updatedAt", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_world_kyc_accounts_emailAddress",
            "world_kyc_accounts",
            ["emailAddress"],
            unique=False,
        )

    if "telegram_links" not in tables:
        op.create_table(
            "telegram_links",
            sa.Column("telegramId", sa.BigInteger(), primary_key=True, nullable=False),
            sa.Column(
                "userId",
                sa.String(),
                sa.ForeignKey("world_kyc_accounts.userId", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("linkedAt", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revokedAt", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_telegram_links_userId", "telegram_links", ["userId"], unique=False)
        op.create_index("ix_telegram_links_revokedAt", "telegram_links", ["revokedAt"], unique=False)

    if "telegram_connection_codes" not in tables:
        op.create_table(
            "telegram_connection_codes",
            sa.Column("codeHash", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("telegramId", sa.BigInteger(), nullable=False),
            sa.Column("createdAt", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=False),
            sa.Column("usedAt", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_telegram_connection_codes_telegramId",
            "telegram_connection_codes",
            ["telegramId"],
            unique=False,
        )
        op.create_index(
            "ix_telegram_connection_codes_expiresAt",
            "telegram_connection_codes",
            ["expiresAt"],
            unique=False,
        )
        op.create_index(
            "ix_telegram_connection_codes_usedAt",
            "telegram_connection_codes",
            ["usedAt"],
            unique=False,
        )


def _collect_accounts(bind, tables: set[str]) -> dict[str, str | None]:
    accounts: dict[str, str | None] = {}
    if "users" in tables:
        for row in bind.execute(sa.text('SELECT "userId", "emailAddress" FROM users')):
            user_id = _non_empty(row[0])
            if user_id:
                email = _non_empty(row[1])
                if user_id not in accounts or (accounts[user_id] is None and email is not None):
                    accounts[user_id] = email

    return accounts


def _backfill_accounts_and_links(bind, tables: set[str]) -> None:
    now = _utcnow()
    accounts = _collect_accounts(bind, tables)
    account_table = sa.table(
        "world_kyc_accounts",
        sa.column("userId", sa.String()),
        sa.column("emailAddress", sa.String()),
        sa.column("createdAt", sa.DateTime(timezone=True)),
        sa.column("updatedAt", sa.DateTime(timezone=True)),
    )
    if accounts:
        op.bulk_insert(
            account_table,
            [
                {
                    "userId": user_id,
                    "emailAddress": email,
                    "createdAt": now,
                    "updatedAt": now,
                }
                for user_id, email in accounts.items()
            ],
        )

    if "users" not in tables:
        return
    telegram_link_table = sa.table(
        "telegram_links",
        sa.column("telegramId", sa.BigInteger()),
        sa.column("userId", sa.String()),
        sa.column("linkedAt", sa.DateTime(timezone=True)),
        sa.column("revokedAt", sa.DateTime(timezone=True)),
    )
    links = []
    for row in bind.execute(sa.text('SELECT "telegramId", "userId" FROM users')):
        user_id = _non_empty(row[1])
        if row[0] is None or user_id is None:
            continue
        links.append(
            {
                "telegramId": int(row[0]),
                "userId": user_id,
                "linkedAt": now,
                "revokedAt": None,
            }
        )
    if links:
        op.bulk_insert(telegram_link_table, links)


def _backfill_message_owners(bind, tables: set[str]) -> None:
    if "vmail_messages" not in tables or "verified_links" not in tables:
        return
    bind.execute(
        sa.text(
            'UPDATE vmail_messages SET "userId" = ('
            'SELECT verified_links."userId" FROM verified_links '
            'WHERE verified_links.reference = vmail_messages.recipient_alias'
            ') WHERE ("userId" IS NULL OR TRIM("userId") = \'\') '
            'AND EXISTS (SELECT 1 FROM verified_links '
            'WHERE verified_links.reference = vmail_messages.recipient_alias)'
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    _create_identity_tables(inspector)
    _backfill_accounts_and_links(bind, tables)
    _backfill_message_owners(bind, tables)

    inspector = inspect(bind)
    if "verified_links" in tables:
        foreign_keys = {fk.get("name") for fk in inspector.get_foreign_keys("verified_links")}
        with op.batch_alter_table("verified_links") as batch_op:
            batch_op.alter_column("telegramId", existing_type=sa.BigInteger(), nullable=True)
            if "fk_verified_links_user_id_account" not in foreign_keys:
                batch_op.create_foreign_key(
                    "fk_verified_links_user_id_account",
                    "world_kyc_accounts",
                    ["userId"],
                    ["userId"],
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "verified_links" in tables:
        null_count = bind.execute(
            sa.text('SELECT COUNT(*) FROM verified_links WHERE "telegramId" IS NULL')
        ).scalar_one()
        if null_count:
            raise RuntimeError(
                "Cannot downgrade while non-Telegram verified links exist; restore the pre-cutover backup."
            )
        foreign_keys = {fk.get("name") for fk in inspector.get_foreign_keys("verified_links")}
        with op.batch_alter_table("verified_links") as batch_op:
            if "fk_verified_links_user_id_account" in foreign_keys:
                batch_op.drop_constraint("fk_verified_links_user_id_account", type_="foreignkey")
            batch_op.alter_column("telegramId", existing_type=sa.BigInteger(), nullable=False)

    if "telegram_connection_codes" in tables:
        op.drop_index("ix_telegram_connection_codes_usedAt", table_name="telegram_connection_codes")
        op.drop_index("ix_telegram_connection_codes_expiresAt", table_name="telegram_connection_codes")
        op.drop_index("ix_telegram_connection_codes_telegramId", table_name="telegram_connection_codes")
        op.drop_table("telegram_connection_codes")
    if "telegram_links" in tables:
        op.drop_index("ix_telegram_links_revokedAt", table_name="telegram_links")
        op.drop_index("ix_telegram_links_userId", table_name="telegram_links")
        op.drop_table("telegram_links")
    if "world_kyc_accounts" in tables:
        op.drop_index("ix_world_kyc_accounts_emailAddress", table_name="world_kyc_accounts")
        op.drop_table("world_kyc_accounts")
