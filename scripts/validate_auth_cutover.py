from __future__ import annotations

import json
import sys

from sqlalchemy import inspect, text

from config.dbConfig import engine


REQUIRED_TABLES = {
    "users",
    "world_kyc_accounts",
    "telegram_links",
    "verified_links",
    "vmail_messages",
}


def _scalar(connection, statement: str) -> int:
    return int(connection.execute(text(statement)).scalar_one())


def validate() -> tuple[dict[str, int | list[str]], bool]:
    tables = set(inspect(engine).get_table_names())
    missing_tables = sorted(REQUIRED_TABLES - tables)
    if missing_tables:
        return {"missingTables": missing_tables}, False

    with engine.connect() as connection:
        results: dict[str, int | list[str]] = {
            "legacyUsersWithUserId": _scalar(
                connection,
                'SELECT COUNT(*) FROM users WHERE "userId" IS NOT NULL AND TRIM("userId") <> \'\'',
            ),
            "worldKycAccounts": _scalar(connection, "SELECT COUNT(*) FROM world_kyc_accounts"),
            "activeTelegramLinks": _scalar(
                connection,
                'SELECT COUNT(*) FROM telegram_links WHERE "revokedAt" IS NULL',
            ),
            "legacyUsersMissingAccount": _scalar(
                connection,
                'SELECT COUNT(*) FROM users u LEFT JOIN world_kyc_accounts a '
                'ON a."userId" = u."userId" WHERE u."userId" IS NOT NULL '
                'AND TRIM(u."userId") <> \'\' AND a."userId" IS NULL',
            ),
            "legacyUsersMissingTelegramLink": _scalar(
                connection,
                'SELECT COUNT(*) FROM users u LEFT JOIN telegram_links t '
                'ON t."telegramId" = u."telegramId" AND t."userId" = u."userId" '
                'AND t."revokedAt" IS NULL WHERE u."userId" IS NOT NULL '
                'AND TRIM(u."userId") <> \'\' AND t."telegramId" IS NULL',
            ),
            "verifiedLinksMissingAccount": _scalar(
                connection,
                'SELECT COUNT(*) FROM verified_links v LEFT JOIN world_kyc_accounts a '
                'ON a."userId" = v."userId" WHERE a."userId" IS NULL',
            ),
            "vmailMessagesMissingOwner": _scalar(
                connection,
                'SELECT COUNT(*) FROM vmail_messages WHERE "userId" IS NULL '
                'OR TRIM("userId") = \'\'',
            ),
            "vmailMessagesWithUnknownOwner": _scalar(
                connection,
                'SELECT COUNT(*) FROM vmail_messages m LEFT JOIN world_kyc_accounts a '
                'ON a."userId" = m."userId" WHERE m."userId" IS NOT NULL '
                'AND TRIM(m."userId") <> \'\' AND a."userId" IS NULL',
            ),
        }

    failure_keys = (
        "legacyUsersMissingAccount",
        "legacyUsersMissingTelegramLink",
        "verifiedLinksMissingAccount",
        "vmailMessagesMissingOwner",
        "vmailMessagesWithUnknownOwner",
    )
    return results, not any(results[key] for key in failure_keys)


def main() -> int:
    results, valid = validate()
    print(json.dumps({"valid": valid, **results}, indent=2, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
