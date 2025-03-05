from pyrogram import Client, filters
from pyrogram.types import Message

from hypersave.bot import ClientBot


@ClientBot.on_message(filters.command("start") & filters.private)
async def start_command(client: ClientBot, message: Message):
    await message.reply(
        "Olá! Eu sou um bot de salvamento de mídias privadas do Telegram!"
    )
