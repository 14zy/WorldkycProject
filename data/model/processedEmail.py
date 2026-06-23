from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from config.dbConfig import Base


class ProcessedEmail(Base):
    __tablename__ = "processed_emails"
    __table_args__ = (
        UniqueConstraint("mailbox", "imap_uid", name="uq_processed_emails_mailbox_uid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    mailbox = Column(String, nullable=False, index=True)
    imap_uid = Column(String, nullable=False)
    message_id = Column(String, nullable=True, index=True)
    recipient_alias = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, index=True)
    processedAt = Column(DateTime(timezone=True), nullable=False, index=True)
    error = Column(String, nullable=True)
