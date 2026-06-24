from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String

from config.dbConfig import Base


class VerifiedLink(Base):
    __tablename__ = "verified_links"

    reference = Column(String, primary_key=True, index=True)
    telegramId = Column(BigInteger, ForeignKey("users.telegramId"), nullable=False, index=True)
    userId = Column(String, nullable=False, index=True)
    name = Column(String, nullable=True)
    status = Column(String, nullable=True)
    updatedAt = Column(DateTime(timezone=True), nullable=False, index=True)
