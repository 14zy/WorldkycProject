from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from config.dbConfig import Base
from data.model.worldKycAccount import WorldKycAccount  # noqa: F401 - registers FK metadata


class OutboundVmailMessage(Base):
    __tablename__ = "outbound_vmail_messages"
    __table_args__ = (
        UniqueConstraint("userId", "client_request_id", name="uq_outbound_vmail_user_request"),
        UniqueConstraint("resend_email_id", name="uq_outbound_vmail_resend_email_id"),
    )

    id = Column(String(32), primary_key=True)
    userId = Column(
        String,
        ForeignKey("world_kyc_accounts.userId", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reference = Column(String, nullable=False, index=True)
    original_message_id = Column(Integer, nullable=True, index=True)
    client_request_id = Column(String(32), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    from_address = Column(String(320), nullable=False)
    to_address = Column(String(320), nullable=False)
    subject = Column(String(200), nullable=False)
    body_text = Column(Text, nullable=False)
    in_reply_to = Column(String, nullable=True)
    references = Column(Text, nullable=True)
    resend_email_id = Column(String, nullable=True, index=True)
    rfc_message_id = Column(String, nullable=True)
    status = Column(String(32), nullable=False, index=True)
    createdAt = Column(DateTime(timezone=True), nullable=False, index=True)
    updatedAt = Column(DateTime(timezone=True), nullable=False)
    failure_category = Column(String(64), nullable=True)
    correlation_id = Column(String(64), nullable=False)


class ResendWebhookEvent(Base):
    __tablename__ = "resend_webhook_events"

    event_id = Column(String, primary_key=True)
    event_type = Column(String, nullable=False)
    receivedAt = Column(DateTime(timezone=True), nullable=False)
