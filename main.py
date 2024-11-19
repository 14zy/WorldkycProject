import asyncio
import logging
from aiogram import Dispatcher
from handlers import message_handler
from data.config import bot

dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

async def main():
    dp.include_routers(message_handler.router)
    print("Launched bot")
    await dp.start_polling(bot)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Exit')
