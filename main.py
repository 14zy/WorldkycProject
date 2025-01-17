import asyncio
import logging
from aiogram import Dispatcher
from handler import message_handler
from handler import inline_handler
from config.config import bot
from config.dbConfig import SessionLocal
from config.dbConfig import Base, engine
from data.model.user import User
from controller.authController import app
from aiohttp import web

dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

async def start_flask():   
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("Web server started at http://localhost:8080")

async def start_bot():
    print("Bot is starting...")
    dp.include_router(message_handler.router)  
    dp.include_router(inline_handler.router)
    await dp.start_polling(bot)

async def main():
    Base.metadata.create_all(bind=engine)
    await asyncio.gather(start_flask(), start_bot())

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Exit')
