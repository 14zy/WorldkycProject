from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint

from config.dbConfig import Base


class VMailMessage(Base):
    __tablename__ = "vmail_messages"
    __table_args__ = (
        UniqueConstraint("mailbox", "imap_uid", "recipient_alias", name="uq_vmail_messages_mailbox_uid_alias"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    mailbox = Column(String, nullable=False)
    imap_uid = Column(String, nullable=False)
    message_id = Column(String, nullable=True, index=True)
    recipient_alias = Column(String, nullable=False, index=True)
    telegramId = Column(BigInteger, nullable=True, index=True)
    userId = Column(String, nullable=True, index=True)
    from_header = Column(String, nullable=False)
    reply_to = Column(String, nullable=True)
    subject = Column(String, nullable=False)
    snippet = Column(String, nullable=False)
    body_text = Column(Text, nullable=False)
    sender_trust = Column(String, nullable=False, default="anonymous")
    notary_status = Column(String, nullable=True)
    identity_status = Column(String, nullable=True)
    governance_status = Column(String, nullable=True)
    delivery_status = Column(String, nullable=False, index=True)
    receivedAt = Column(DateTime(timezone=True), nullable=True, index=True)
    processedAt = Column(DateTime(timezone=True), nullable=False, index=True)
    is_read = Column(Boolean, nullable=False, default=False)
    error = Column(String, nullable=True)
