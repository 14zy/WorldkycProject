from config.dbConfig import SessionLocal
from data.model.user import User

db = SessionLocal()

def findUserByTelegramId(telegramId):
    user = db.query(User).filter(User.telegramId == telegramId).first()
    return user

def saveUser(telegramId: int, user_id: str, accessToken: str, refreshToken: str):
    user = findUserByTelegramId(telegramId)
    if not user:
        user = User(telegramId = telegramId, userId = user_id, accessToken = accessToken, refreshToken = refreshToken)
        db.add(user)
    else:
        user.telegramId = telegramId
        user.accessToken = accessToken
        user.refreshToken = refreshToken
    db.commit()