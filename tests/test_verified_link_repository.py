from datetime import datetime, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.dbConfig import Base
from data.model.user import User
from data.model.verifiedLink import VerifiedLink
import data.repository.verifiedLinkRepository as verifiedLinkRepository


class VerifiedLinkRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.original_session_local = verifiedLinkRepository.SessionLocal
        verifiedLinkRepository.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(self.engine, tables=[User.__table__, VerifiedLink.__table__])

    def tearDown(self):
        verifiedLinkRepository.SessionLocal = self.original_session_local
        Base.metadata.drop_all(self.engine, tables=[VerifiedLink.__table__, User.__table__])

    def test_list_for_user_references_only_returns_owned_links(self):
        session = verifiedLinkRepository.SessionLocal()
        try:
            session.add_all(
                [
                    User(telegramId=1, userId="user-1"),
                    User(telegramId=2, userId="user-2"),
                    VerifiedLink(
                        reference="vl10776",
                        telegramId=1,
                        userId="user-1",
                        updatedAt=datetime.now(timezone.utc),
                    ),
                    VerifiedLink(
                        reference="vl99999",
                        telegramId=2,
                        userId="user-2",
                        updatedAt=datetime.now(timezone.utc),
                    ),
                ]
            )
            session.commit()
        finally:
            session.close()

        links = verifiedLinkRepository.list_for_user_references(1, ["VL10776", "VL99999"], "user-1")

        self.assertEqual([link.reference for link in links], ["vl10776"])


if __name__ == "__main__":
    unittest.main()
