from aiogram import Bot

import os
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")

url_webapp = "https://t.me/worldkycbot"
# url_webapp = "https://t.me/worldkycbot/app"

bot = Bot(token=API_TOKEN)
