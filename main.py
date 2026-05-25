import asyncio
import logging
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram import Dispatcher
from handler import message_handler
from handler import inline_handler
from config.config import bot
from config.dbConfig import SessionLocal
from config.dbConfig import Base, engine
from data.dbInit import ensure_user_token_columns
from data.model.user import User
from controller.authController import handle_request
from controller.customerSearchHandler import handle_customer_search
from controller.tmaController import register_tma_routes
from services.sessionService import refresh_sessions_loop

from aiohttp import web

dp = Dispatcher()


app = web.Application()
app.router.add_post('/api/v1/auth', handle_request)
app.router.add_get('/api/v1/customer-users/search', handle_customer_search)
register_tma_routes(app)

logging.basicConfig(level=logging.INFO)

async def start_flask():   
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("Web server started at http://localhost:8080")
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()

async def start_bot():
    print("Bot is starting...")
    dp.include_router(message_handler.router)  
    dp.include_router(inline_handler.router)
    await dp.start_polling(bot)

async def main():
    Base.metadata.create_all(bind=engine)
    ensure_user_token_columns()
    await asyncio.gather(start_flask(), start_bot(), refresh_sessions_loop())

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except TelegramUnauthorizedError:
        logging.exception("Telegram bot authorization failed. Check BOT_TOKEN.")
    except KeyboardInterrupt:
        print('Exit')
