from aiogram import Bot
import os
from dotenv import load_dotenv


load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
AUTHORIZED_TOKEN = os.getenv("AUTHORIZED_TOKEN")

url_webapp = "https://t.me/worldkycbot"
bot = Bot(token=API_TOKEN)
