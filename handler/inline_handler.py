import logging
from aiogram.types import Message, CallbackQuery
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode
from utils.keyboards import web
from config.config import url_webapp
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
import api.worldKycApi as worldKycApi
import data.repository.userRepository as userRepository

logging.basicConfig(level=logging.INFO)

router = Router()


@router.inline_query()
async def inline(query: InlineQuery):
    user_query = query.query  
    user_id = query.from_user.id
    base_url = 'https://app.worldkyc.com/vl/'

    user = userRepository.findUserByTelegramId(user_id)
    if user:
        links = worldKycApi.getVlink(user.accessToken)
    else:
        links = None

    if(links == None):
        item = InlineQueryResultArticle(
            id="1", 
            title= f"You are not logged in",
            input_message_content=InputTextMessageContent(
                message_text=f"You are not logged in"
            )
        )
        await query.answer([item], cache_time=1)
    else:
        answer_item = []
        for link in links:
            item = InlineQueryResultArticle(
                id=link['verifiedLinkId'], 
                title= f"{link['verifiedLinkReference']}({link['verifiedLinkName']})",
                input_message_content=InputTextMessageContent(
                    message_text=f"{base_url+link['verifiedLinkReference']}"
                )
            )
            answer_item.append(item)
        await query.answer(answer_item, cache_time=1)