from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from config.config import TMA_URL

web = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="OPEN", web_app=WebAppInfo(url=TMA_URL))]
])
