from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, func

from config.dbConfig import Base


class TelegramLink(Base):
    __tablename__ = "telegram_links"

    telegramId = Column(BigInteger, primary_key=True)
    userId = Column(
        String,
        ForeignKey("world_kyc_accounts.userId", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    linkedAt = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revokedAt = Column(DateTime(timezone=True), nullable=True, index=True)
