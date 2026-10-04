from datetime import datetime, timedelta, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.dbConfig import Base
from data.model.vmailMessage import VMailMessage
import data.repository.vmailMessageRepository as vmailMessageRepository


class VMailMessageRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.original_session_local = vmailMessageRepository.SessionLocal
        vmailMessageRepository.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(self.engine, tables=[VMailMessage.__table__])

    def tearDown(self):
        vmailMessageRepository.SessionLocal = self.original_session_local
        Base.metadata.drop_all(self.engine, tables=[VMailMessage.__table__])

    def test_upsert_does_not_duplicate_same_mailbox_uid_alias(self):
        first = vmailMessageRepository.upsert_from_processed_message(
            mailbox="INBOX",
            imap_uid="123",
            message_id="<msg-1@example.com>",
            recipient_alias="VL10776",
            telegram_id=10776,
            user_id="user-1",
            from_header="Sender <sender@example.com>",
            reply_to="reply@example.com",
            subject="Original",
            body_text="First body",
            delivery_status="delivered",
        )
        second = vmailMessageRepository.upsert_from_processed_message(
            mailbox="INBOX",
            imap_uid="123",
            message_id="<msg-1@example.com>",
            recipient_alias="vl10776",
            telegram_id=10776,
            user_id="user-1",
            from_header="Sender <sender@example.com>",
            reply_to="reply@example.com",
            subject="Updated",
            body_text="Updated body",
            delivery_status="partial",
            error="smtp down",
        )

        self.assertEqual(first.id, second.id)
        messages = vmailMessageRepository.list_for_aliases(["vl10776"])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].recipient_alias, "vl10776")
        self.assertEqual(messages[0].subject, "Updated")
        self.assertEqual(messages[0].delivery_status, "partial")
        self.assertEqual(messages[0].error, "smtp down")

    def test_list_filters_unread_and_sorts_newest_first(self):
        older = datetime.now(timezone.utc) - timedelta(hours=2)
        newer = datetime.now(timezone.utc) - timedelta(minutes=5)
        vmailMessageRepository.upsert_from_processed_message(
            mailbox="INBOX",
            imap_uid="1",
            message_id=None,
            recipient_alias="vl1",
            telegram_id=1,
            user_id="user-1",
            from_header="a@example.com",
            reply_to=None,
            subject="Older",
            body_text="Older body",
            delivery_status="delivered",
            received_at=older,
        )
        newest = vmailMessageRepository.upsert_from_processed_message(
            mailbox="INBOX",
            imap_uid="2",
            message_id=None,
            recipient_alias="vl2",
            telegram_id=1,
            user_id="user-1",
            from_header="b@example.com",
            reply_to=None,
            subject="Newer",
            body_text="Newer body",
            delivery_status="delivered",
            received_at=newer,
        )
        vmailMessageRepository.mark_read(newest.id, telegram_id=1, user_id="user-1")

        all_messages = vmailMessageRepository.list_for_aliases(["VL1", "VL2"])
        self.assertEqual([message.subject for message in all_messages], ["Newer", "Older"])

        unread_messages = vmailMessageRepository.list_for_aliases(["vl1", "vl2"], unread_only=True)
        self.assertEqual([message.subject for message in unread_messages], ["Older"])

    def test_mark_read_requires_matching_owner_when_provided(self):
        message = vmailMessageRepository.upsert_from_processed_message(
            mailbox="INBOX",
            imap_uid="1",
            message_id=None,
            recipient_alias="vl1",
            telegram_id=1,
            user_id="user-1",
            from_header="a@example.com",
            reply_to=None,
            subject="Subject",
            body_text="Body",
            delivery_status="delivered",
        )

        self.assertIsNone(vmailMessageRepository.mark_read(message.id, telegram_id=2, user_id="user-2"))
        unread = vmailMessageRepository.list_for_aliases(["vl1"], unread_only=True)
        self.assertEqual(len(unread), 1)

        self.assertIsNotNone(vmailMessageRepository.mark_read(message.id, telegram_id=1, user_id="user-1"))
        unread = vmailMessageRepository.list_for_aliases(["vl1"], unread_only=True)
        self.assertEqual(unread, [])

    def test_list_for_user_cannot_read_another_accounts_alias_mail(self):
        for uid, user_id in (("1", "user-1"), ("2", "user-2")):
            vmailMessageRepository.upsert_from_processed_message(
                mailbox="INBOX",
                imap_uid=uid,
                message_id=None,
                recipient_alias="herve",
                mailbox_type="alias",
                telegram_id=None,
                user_id=user_id,
                from_header="sender@example.com",
                reply_to=None,
                subject=user_id,
                body_text="Body",
                delivery_status="delivered",
            )

        messages = vmailMessageRepository.list_for_user("user-1", mailboxes=["HERVE"])

        self.assertEqual([message.subject for message in messages], ["user-1"])
        self.assertEqual(messages[0].mailbox_type, "alias")


if __name__ == "__main__":
    unittest.main()
