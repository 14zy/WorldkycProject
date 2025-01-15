from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

web = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Login", web_app=WebAppInfo(url="https://t.me/worldkycbot/app"))]
])
