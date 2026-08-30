from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String

from config.dbConfig import Base
from data.model.worldKycAccount import WorldKycAccount  # noqa: F401 - registers FK table metadata


class VerifiedLink(Base):
    __tablename__ = "verified_links"

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
    updatedAt = Column(DateTime(timezone=True), nullable=False, index=True)
