from pyrogram import Client
from pyrogram.types import Message

from hypersave.database.models import User
from hypersave.database.user_repository import UserRepository

user_repository = UserRepository()


async def save_message_info(message: Message):
    if str(message.chat.type) == "ChatType.PRIVATE":
        await process_private_message(message)


async def process_private_message(message):
    user_id = message.from_user.id
    name = f'{message.from_user.first_name} {message.from_user.last_name if message.from_user.last_name else ""}'
    username = message.from_user.username
    user = User(t_id=user_id, t_name=name, t_username=username)
    user_repository.add(user)
