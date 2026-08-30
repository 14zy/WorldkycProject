from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.dbConfig import Base
from data.model.telegramConnectionCode import TelegramConnectionCode
from data.model.telegramLink import TelegramLink
from data.model.worldKycAccount import WorldKycAccount
import data.repository.telegramConnectionCodeRepository as connectionCodeRepository
import data.repository.telegramLinkRepository as telegramLinkRepository
import data.repository.worldKycAccountRepository as accountRepository


class AccountIdentityRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.session_factory = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.original_sessions = (
            connectionCodeRepository.SessionLocal,
            telegramLinkRepository.SessionLocal,
            accountRepository.SessionLocal,
        )
        connectionCodeRepository.SessionLocal = self.session_factory
        telegramLinkRepository.SessionLocal = self.session_factory
        accountRepository.SessionLocal = self.session_factory
        Base.metadata.create_all(
            self.engine,
            tables=[WorldKycAccount.__table__, TelegramLink.__table__, TelegramConnectionCode.__table__],
        )

    def tearDown(self):
        (
            connectionCodeRepository.SessionLocal,
            telegramLinkRepository.SessionLocal,
            accountRepository.SessionLocal,
        ) = self.original_sessions
        Base.metadata.drop_all(
            self.engine,
            tables=[TelegramConnectionCode.__table__, TelegramLink.__table__, WorldKycAccount.__table__],
        )
        self.engine.dispose()

    def test_connection_code_creates_account_and_active_link_once(self):
        code, _record = connectionCodeRepository.create(12345)
        link = connectionCodeRepository.redeem_and_link(code, "wk-user", "user@example.com")

        self.assertEqual(link.telegramId, 12345)
        self.assertEqual(link.userId, "wk-user")
        self.assertEqual(accountRepository.find_by_user_id("wk-user").emailAddress, "user@example.com")
        self.assertEqual(telegramLinkRepository.find_active_by_telegram_id(12345).userId, "wk-user")

        with self.assertRaisesRegex(connectionCodeRepository.ConnectionCodeError, "already used"):
            connectionCodeRepository.redeem_and_link(code, "wk-user")

    def test_connection_code_cannot_replace_an_active_different_account(self):
        accountRepository.upsert("first-user")
        telegramLinkRepository.link(12345, "first-user")
        code, _record = connectionCodeRepository.create(12345)

        with self.assertRaisesRegex(connectionCodeRepository.ConnectionCodeError, "another"):
            connectionCodeRepository.redeem_and_link(code, "second-user")


if __name__ == "__main__":
    unittest.main()
