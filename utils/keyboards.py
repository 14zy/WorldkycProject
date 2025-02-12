from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

web = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Website", web_app=WebAppInfo(url="https://tonstealthid.com/"))]
])
