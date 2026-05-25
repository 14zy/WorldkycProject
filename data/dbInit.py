from sqlalchemy import inspect, text

from config.dbConfig import engine


def ensure_user_token_columns():
    inspector = inspect(engine)
    try:
        columns = {column["name"] for column in inspector.get_columns("users")}
    except Exception:
        return

    statements = []
    if "accessTokenExpiresAt" not in columns:
        statements.append('ALTER TABLE users ADD COLUMN "accessTokenExpiresAt" TIMESTAMPTZ NULL')
    if "refreshTokenExpiresAt" not in columns:
        statements.append('ALTER TABLE users ADD COLUMN "refreshTokenExpiresAt" TIMESTAMPTZ NULL')
    if "lastTokenRefreshAt" not in columns:
        statements.append('ALTER TABLE users ADD COLUMN "lastTokenRefreshAt" TIMESTAMPTZ NULL')

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
