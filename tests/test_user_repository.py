from datetime import datetime, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import data.repository.userRepository as userRepository
from config.dbConfig import Base


class UserRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.original_session_local = userRepository.SessionLocal
        userRepository.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def tearDown(self):
        userRepository.SessionLocal = self.original_session_local
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_save_user_persists_email_address(self):
        now = datetime.now(timezone.utc)
        userRepository.saveUser(
            101,
            "wk-101",
            "access-token",
            "refresh-token",
            "user@example.com",
            now,
            now,
            now,
        )

        user = userRepository.findUserByTelegramId(101)
        self.assertEqual(user.emailAddress, "user@example.com")

    def test_update_user_tokens_with_missing_email_does_not_clear_existing_value(self):
        now = datetime.now(timezone.utc)
        userRepository.saveUser(
            102,
            "wk-102",
            "access-token",
            "refresh-token",
            "persisted@example.com",
            now,
            now,
            now,
        )

        userRepository.updateUserTokens(
            102,
            "new-access-token",
            "new-refresh-token",
            None,
            now,
            now,
            now,
        )

        user = userRepository.findUserByTelegramId(102)
        self.assertEqual(user.emailAddress, "persisted@example.com")


if __name__ == "__main__":
    unittest.main()
