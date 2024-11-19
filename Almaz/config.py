import os
from dotenv import load_dotenv
from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher

# Загрузка переменных окружения из файла .env
load_dotenv()

TOKEN_BOT = os.getenv("TOKEN_BOT")
API_URL = os.getenv("API_URL")
TOKEN_AUTHENTICATION = os.getenv("TOKEN_AUTHENTICATION")
CHAT_ID = ''

# Объект бота
bot = Bot(TOKEN_BOT);
# Диспетчер
dp = Dispatcher(bot)