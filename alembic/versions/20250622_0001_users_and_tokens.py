"""Create or align users table with token metadata columns."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20250622_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("telegramId", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("userId", sa.String(), nullable=True),
            sa.Column("accessToken", sa.String(), nullable=True),
            sa.Column("refreshToken", sa.String(), nullable=True),
            sa.Column("accessTokenExpiresAt", sa.DateTime(timezone=True), nullable=True),
            sa.Column("refreshTokenExpiresAt", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lastTokenRefreshAt", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_users_telegramId", "users", ["telegramId"], unique=False)
        op.create_index("ix_users_userId", "users", ["userId"], unique=False)
        op.create_index("ix_users_accessToken", "users", ["accessToken"], unique=False)
        op.create_index("ix_users_refreshToken", "users", ["refreshToken"], unique=False)
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "accessTokenExpiresAt" not in columns:
        op.add_column("users", sa.Column("accessTokenExpiresAt", sa.DateTime(timezone=True), nullable=True))
    if "refreshTokenExpiresAt" not in columns:
        op.add_column("users", sa.Column("refreshTokenExpiresAt", sa.DateTime(timezone=True), nullable=True))
    if "lastTokenRefreshAt" not in columns:
        op.add_column("users", sa.Column("lastTokenRefreshAt", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "users" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "lastTokenRefreshAt" in columns:
        op.drop_column("users", "lastTokenRefreshAt")
    if "refreshTokenExpiresAt" in columns:
        op.drop_column("users", "refreshTokenExpiresAt")
    if "accessTokenExpiresAt" in columns:
        op.drop_column("users", "accessTokenExpiresAt")
