from pyrogram import Client, filters
from pyrogram.types import Message

from hypersave.bot import ClientBot
from hypersave.utils.message_utils import save_message_info
from hypersave.plugins.custom_filters import CustomFilters


custom_filters = CustomFilters()


@ClientBot.on_message(filters.command("start") & filters.private)
async def start_command(client: ClientBot, message: Message):
    await save_message_info(message)
    await message.reply(
        "Olá! Eu sou um bot de salvamento de mídias privadas do Telegram!\n\nPara saber mais /help"
    )


@ClientBot.on_message(filters.command("help") & filters.private)
async def handle_help_command(bot: Client, message: Message):
    help_text = (
        "🤖 **Comandos Disponíveis**\n\n"
        "- Envie um link do Telegram (https://t.me/...) para baixar mídia\n"
        "- /login - Fazer login com sua conta do Telegram\n"
        "- /help - Exibir esta mensagem de ajuda\n\n"
        "📱 **Como usar:**\n"
        "1. Cole links de mídia do Telegram para baixar\n"
        "⚠️ Somente baixe conteúdo relevante, não baixe porcaria!!"
    )

    await message.reply(help_text)


@ClientBot.on_message(filters.command("id") & custom_filters.is_admin)
async def handle_peer_command(client: ClientBot, message: Message):
    await message.reply(f"Peer ID: {message.chat.id}")