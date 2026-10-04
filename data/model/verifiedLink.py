from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, String

from config.dbConfig import Base
from data.model.worldKycAccount import WorldKycAccount  # noqa: F401 - registers FK table metadata


class VerifiedLink(Base):
    __tablename__ = "verified_links"
    __table_args__ = (
        Index("ix_verified_links_mailbox_alias_user_id", "mailboxAlias", "userId"),
    )

    reference = Column(String, primary_key=True, index=True)
    # Kept during the cutover for delivery/audit compatibility. Ownership is userId.
    telegramId = Column(BigInteger, ForeignKey("users.telegramId"), nullable=True, index=True)
    userId = Column(
        String,
        ForeignKey("world_kyc_accounts.userId"),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=True)
    status = Column(String, nullable=True)
    mailboxAlias = Column(String(64), nullable=True, index=True)
    updatedAt = Column(DateTime(timezone=True), nullable=False, index=True)
