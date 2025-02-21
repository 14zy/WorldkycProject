import logging
from aiogram.types import Message, CallbackQuery
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode
from utils.keyboards import web
from config.config import url_webapp

logging.basicConfig(level=logging.INFO)

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name

    welcome_text = (
f'''Hello, {first_name} 👋
Welcome to TON Stealth ID App! You can verify yourself and friends in your community in just a few minutes.
Click OPEN to start the app or type /help to get support
'''
    )
    if message.chat.type != 'private':
        await message.answer(welcome_text)
    else:
        await message.answer(welcome_text, reply_markup=web)

@router.message(Command('ref_links'))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    ref_link = f"Your referral link: {url_webapp}?startapp={user_id}"
    await message.answer(ref_link, disable_web_page_preview=True)

@router.message(Command('ref_stats'))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    balance = f"Your referral earnings is 0. Please invite more people to start earning."
    await message.answer(balance)

@router.message(Command('upload'))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    balance = f"Upload a document or photo in next message"
    await message.answer(balance)

@router.message(Command('verify'))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    balance = f"Verify a person or a document"
    await message.answer(balance)

@router.message(Command('vlinks'))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    balance = f"You don't have any verification links. Please create one"
    await message.answer(balance)

@router.message(Command('rules'))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    balance = f"Rules of the group or community"
    await message.answer(balance)

@router.message(Command('report'))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    balance = f"Report a message or a person to administrator"
    await message.answer(balance)

@router.message(Command('ban'))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    balance = f"Ban a person"
    await message.answer(balance)

@router.message(Command('balance'))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    balance = f"Your balance: 0"
    await message.answer(balance)

@router.message(Command('score'))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    balance = f"Your current Trust Score is 0, please verify yourself to increase it."
    await message.answer(balance)

@router.message(Command('help'))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    balance = f"Please use system responsibly to verify yourself or your friends with World KYC App and receive rewards. Type / to see the list of commands. More information on our website: https://worldkyc.com"
    await message.answer(balance)

