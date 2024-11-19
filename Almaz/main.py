# инициализируем необходимые библиотеки
import json
from aiogram import Dispatcher, types
from aiogram.types import Message
from aiogram.utils import executor
from config import API_URL, TOKEN_AUTHENTICATION, bot, dp
import logging
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

####################################################
#
# Функция для проверки пользователя через API
#
####################################################

async def check_user_request(user_id: int):
    url = f'{API_URL}/users/{user_id}'
    headers = {
        'accept': 'application/json',
        'x-api-key': TOKEN_AUTHENTICATION
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                result = await response.json()
                return result  # Пользователь найден в БД
            elif response.status == 422:
                return None  # Ошибка валидации — нет в БД
            else:
                return None  # Другие статусы

####################################################
#
# Обработчик добавления новых участников в чат
#
####################################################

@dp.message_handler(content_types=types.ContentType.NEW_CHAT_MEMBERS)
async def on_user_join(message: types.Message):
    new_members = message.new_chat_members
    for member in new_members:
        user_id = member.id
        user_data = await check_user_request(user_id)

        if user_data is None:  # Пользователь не найден в БД
            try:
                await bot.kick_chat_member(message.chat.id, user_id)
                await message.reply(
                    f"Пользователь {member.full_name} был заблокирован, так как не найден в базе данных."
                )
            except Exception as e:
                print(f"Ошибка при попытке заблокировать пользователя: {e}")

####################################################
#
# Получение id
#
####################################################

@dp.message_handler(commands=['get_id'])
async def get_id(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    await bot.send_message(chat_id, f"Ваш ID: {user_id}\nChat ID: {chat_id}", parse_mode=types.ParseMode.HTML)

####################################################
#
# запуск бота
#
####################################################

async def on_startup(_):
    print('Бот успешно запустился')

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
