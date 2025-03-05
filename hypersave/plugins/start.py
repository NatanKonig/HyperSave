from pyrogram import Client, filters
from pyrogram.types import Message

from hypersave.bot import ClientBot
from hypersave.utils.message_utils import save_message_info


@ClientBot.on_message(filters.command("start") & filters.private)
async def start_command(client: ClientBot, message: Message):
    await save_message_info(message)
    await message.reply(
        "Olá! Eu sou um bot de salvamento de mídias privadas do Telegram!"
    )
