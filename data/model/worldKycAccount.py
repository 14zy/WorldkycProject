from sqlalchemy import Column, DateTime, String, func

from config.dbConfig import Base


class WorldKycAccount(Base):
    __tablename__ = "world_kyc_accounts"

    userId = Column(String, primary_key=True)
    emailAddress = Column(String, nullable=True, index=True)
    createdAt = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updatedAt = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
