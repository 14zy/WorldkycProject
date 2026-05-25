from datetime import datetime

from config.dbConfig import SessionLocal
from data.model.user import User


def findUserByTelegramId(telegramId):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegramId == telegramId).first()
        return user
    finally:
        db.close()


def findLinkedUsers():
    db = SessionLocal()
    try:
        return (
            db.query(User)
            .filter(User.accessToken.isnot(None), User.refreshToken.isnot(None))
            .all()
        )
    finally:
        db.close()


def saveUser(
    telegramId: int,
    user_id: str,
    accessToken: str,
    refreshToken: str,
    accessTokenExpiresAt: datetime | None = None,
    refreshTokenExpiresAt: datetime | None = None,
    lastTokenRefreshAt: datetime | None = None,
):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegramId == telegramId).first()
        if not user:
            user = User(
                telegramId=telegramId,
                userId=user_id,
                accessToken=accessToken,
                refreshToken=refreshToken,
                accessTokenExpiresAt=accessTokenExpiresAt,
                refreshTokenExpiresAt=refreshTokenExpiresAt,
                lastTokenRefreshAt=lastTokenRefreshAt,
            )
            db.add(user)
        else:
            user.telegramId = telegramId
            user.userId = user_id
            user.accessToken = accessToken
            user.refreshToken = refreshToken
            user.accessTokenExpiresAt = accessTokenExpiresAt
            user.refreshTokenExpiresAt = refreshTokenExpiresAt
            user.lastTokenRefreshAt = lastTokenRefreshAt
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def updateUserTokens(
    telegramId: int,
    accessToken: str,
    refreshToken: str,
    accessTokenExpiresAt: datetime | None = None,
    refreshTokenExpiresAt: datetime | None = None,
    lastTokenRefreshAt: datetime | None = None,
):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegramId == telegramId).first()
        if not user:
            return None

        user.accessToken = accessToken
        user.refreshToken = refreshToken
        user.accessTokenExpiresAt = accessTokenExpiresAt
        user.refreshTokenExpiresAt = refreshTokenExpiresAt
        user.lastTokenRefreshAt = lastTokenRefreshAt
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def clearUserTokens(telegramId: int):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegramId == telegramId).first()
        if not user:
            return

        user.accessToken = None
        user.refreshToken = None
        user.accessTokenExpiresAt = None
        user.refreshTokenExpiresAt = None
        user.lastTokenRefreshAt = None
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
