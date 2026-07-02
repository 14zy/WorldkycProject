"""Add emailAddress column to users."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20250630_0004"
down_revision = "20250624_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "users" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "emailAddress" not in columns:
        op.add_column("users", sa.Column("emailAddress", sa.String(), nullable=True))
        op.create_index("ix_users_emailAddress", "users", ["emailAddress"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "users" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "emailAddress" in columns:
        op.drop_index("ix_users_emailAddress", table_name="users")
        op.drop_column("users", "emailAddress")
