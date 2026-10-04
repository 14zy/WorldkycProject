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

    def test_sync_normalizes_alias_and_resolves_multiple_active_links(self):
        references, warnings = verifiedLinkRepository.sync_links_for_user(
            "user-1",
            [
                {
                    "verifiedLinkReference": " VL10776 ",
                    "verifiedLinkStatusTypeName": "Active",
                    "mailboxAlias": " Herve ",
                },
                {
                    "verifiedLinkReference": "VL10999",
                    "verifiedLinkStatusTypeName": "ACTIVE",
                    "SelectedAccountAlias": "HERVE",
                },
            ],
        )

        self.assertEqual(references, {"vl10776", "vl10999"})
        self.assertEqual(warnings, [])
        links = verifiedLinkRepository.list_active_by_mailbox_alias(" HERVE ")
        self.assertEqual([link.reference for link in links], ["vl10776", "vl10999"])
        self.assertEqual({link.mailboxAlias for link in links}, {"herve"})

    def test_inactive_links_do_not_make_alias_routable(self):
        verifiedLinkRepository.sync_links_for_user(
            "user-1",
            [{
                "verifiedLinkReference": "vl1",
                "verifiedLinkStatusTypeName": "Inactive",
                "mailboxAlias": "herve",
            }],
        )

        self.assertEqual(verifiedLinkRepository.list_active_by_mailbox_alias("herve"), [])

    def test_invalid_reserved_and_reference_collision_aliases_are_cleared(self):
        _references, warnings = verifiedLinkRepository.sync_links_for_user(
            "user-1",
            [
                {"verifiedLinkReference": "vl1", "verifiedLinkStatusTypeName": "Active", "mailboxAlias": "admin"},
                {"verifiedLinkReference": "vl2", "verifiedLinkStatusTypeName": "Active", "mailboxAlias": "bad alias"},
                {"verifiedLinkReference": "herve", "verifiedLinkStatusTypeName": "Active"},
                {"verifiedLinkReference": "vl3", "verifiedLinkStatusTypeName": "Active", "mailboxAlias": "herve"},
            ],
        )

        self.assertEqual({warning["reason"] for warning in warnings}, {"invalid_or_reserved", "vlink_reference_collision"})
        self.assertTrue(all(link.mailboxAlias is None for link in verifiedLinkRepository.list_for_account("user-1")))

    def test_cross_account_alias_collision_does_not_create_second_route(self):
        verifiedLinkRepository.sync_links_for_user(
            "user-1",
            [{"verifiedLinkReference": "vl1", "verifiedLinkStatusTypeName": "Active", "mailboxAlias": "herve"}],
        )
        _references, warnings = verifiedLinkRepository.sync_links_for_user(
            "user-2",
            [{"verifiedLinkReference": "vl2", "verifiedLinkStatusTypeName": "Active", "mailboxAlias": "herve"}],
        )

        self.assertEqual(warnings[0]["reason"], "cross_account_collision")
        self.assertEqual([link.userId for link in verifiedLinkRepository.list_active_by_mailbox_alias("herve")], ["user-1"])
        self.assertIsNone(verifiedLinkRepository.list_for_account("user-2")[0].mailboxAlias)

    def test_removed_reference_can_become_alias_in_same_atomic_sync(self):
        verifiedLinkRepository.sync_links_for_user(
            "user-1",
            [{"verifiedLinkReference": "herve", "verifiedLinkStatusTypeName": "Active"}],
        )

        _references, warnings = verifiedLinkRepository.sync_links_for_user(
            "user-1",
            [{"verifiedLinkReference": "vl1", "verifiedLinkStatusTypeName": "Active", "mailboxAlias": "herve"}],
        )

        self.assertEqual(warnings, [])
        self.assertEqual([link.reference for link in verifiedLinkRepository.list_active_by_mailbox_alias("herve")], ["vl1"])


if __name__ == "__main__":
    unittest.main()
