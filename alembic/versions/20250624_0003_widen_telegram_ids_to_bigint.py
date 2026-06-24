"""Widen Telegram ID columns to BIGINT."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20250624_0003"
down_revision = "20250622_0002"
branch_labels = None
depends_on = None


def _find_verified_links_fk_name(inspector) -> str | None:
    for fk in inspector.get_foreign_keys("verified_links"):
        constrained = fk.get("constrained_columns") or []
        if constrained == ["telegramId"] and fk.get("referred_table") == "users":
            return fk.get("name")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        return

    if "verified_links" in tables:
        fk_name = _find_verified_links_fk_name(inspector)
        if fk_name:
            op.drop_constraint(fk_name, "verified_links", type_="foreignkey")

        op.alter_column(
            "verified_links",
            "telegramId",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )

    op.alter_column(
        "users",
        "telegramId",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )

    if "verified_links" in tables:
        op.create_foreign_key(
            None,
            "verified_links",
            "users",
            ["telegramId"],
            ["telegramId"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        return

    if "verified_links" in tables:
        fk_name = _find_verified_links_fk_name(inspector)
        if fk_name:
            op.drop_constraint(fk_name, "verified_links", type_="foreignkey")

        op.alter_column(
            "verified_links",
            "telegramId",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )

    op.alter_column(
        "users",
        "telegramId",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )

    if "verified_links" in tables:
        op.create_foreign_key(
            None,
            "verified_links",
            "users",
            ["telegramId"],
            ["telegramId"],
        )
