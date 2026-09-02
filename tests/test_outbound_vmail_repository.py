from datetime import datetime, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.dbConfig import Base
from data.model.outboundVmailMessage import OutboundVmailMessage, ResendWebhookEvent
from data.model.vmailMessage import VMailMessage
from data.model.worldKycAccount import WorldKycAccount
import data.repository.outboundVmailMessageRepository as repository


class OutboundVmailRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.original_session_local = repository.SessionLocal
        repository.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(
            self.engine,
            tables=[
                WorldKycAccount.__table__,
                VMailMessage.__table__,
                OutboundVmailMessage.__table__,
                ResendWebhookEvent.__table__,
            ],
        )

    def tearDown(self):
        repository.SessionLocal = self.original_session_local
        Base.metadata.drop_all(self.engine)

    def _values(self):
        return {
            "userId": "user-1",
            "reference": "vl1",
            "original_message_id": None,
            "client_request_id": "a" * 32,
            "payload_hash": "b" * 64,
            "from_address": "vl1@tonstealthid.com",
            "to_address": "recipient@example.com",
            "subject": "Subject",
            "body_text": "Body",
            "in_reply_to": None,
            "references": None,
            "correlation_id": "correlation",
        }

    def test_unique_account_request_and_idempotent_webhook_status(self):
        first, created = repository.create_submission(**self._values())
        duplicate, duplicate_created = repository.create_submission(**self._values())
        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate.id, first.id)

        repository.mark_queued(first.id, "resend-1")
        self.assertTrue(repository.apply_webhook_event("event-1", "email.delivered", "resend-1"))
        self.assertFalse(repository.apply_webhook_event("event-1", "email.delivered", "resend-1"))
        stored = repository.find_by_request("user-1", "a" * 32)
        self.assertEqual(stored.status, "delivered")

    def test_failed_submission_retry_is_claimed_once(self):
        record, _created = repository.create_submission(**self._values())
        repository.mark_failed(record.id, "transport")

        claimed_record, claimed = repository.retry_failed(record.id, "retry-correlation")
        raced_record, raced_claim = repository.retry_failed(record.id, "other-correlation")

        self.assertTrue(claimed)
        self.assertEqual(claimed_record.status, "submitting")
        self.assertFalse(raced_claim)
        self.assertEqual(raced_record.status, "submitting")


if __name__ == "__main__":
    unittest.main()
