from sqlalchemy import Column, Integer, String
from config.dbConfig import Base

class User(Base):
    __tablename__ = "users"

    telegramId = Column(Integer, primary_key=True, index=True)
    userId = Column(String, index=True)
    accessToken = Column(String, index=True)
    refreshToken = Column(String, index=True)
    