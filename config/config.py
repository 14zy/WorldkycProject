from aiogram import Bot
import os
from dotenv import load_dotenv


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
AUTHORIZED_TOKEN = os.getenv("AUTHORIZED_TOKEN")

url_webapp = "https://t.me/worldkycbot"
bot = Bot(token=BOT_TOKEN)
