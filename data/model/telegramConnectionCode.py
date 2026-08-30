from sqlalchemy import BigInteger, Column, DateTime, String, func

from config.dbConfig import Base


class TelegramConnectionCode(Base):
    __tablename__ = "telegram_connection_codes"

    codeHash = Column(String(64), primary_key=True)
    telegramId = Column(BigInteger, nullable=False, index=True)
    createdAt = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expiresAt = Column(DateTime(timezone=True), nullable=False, index=True)
    usedAt = Column(DateTime(timezone=True), nullable=True, index=True)
