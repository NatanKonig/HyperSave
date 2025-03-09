from pyrogram import Client, filters
from pyrogram.types import Message

from hypersave.bot import ClientBot
from hypersave.utils.message_utils import save_message_info


@ClientBot.on_message(filters.command("start") & filters.private)
async def start_command(client: ClientBot, message: Message):
    await save_message_info(message)
    await message.reply(
        "Olá! Eu sou um bot de salvamento de mídias privadas do Telegram!\n\nPara saber mais /help"
    )


@ClientBot.on_message(filters.command("help") & filters.private)
async def handle_help_command(bot: Client, message: Message):
    """Handle help command"""
    help_text = (
        "🤖 **Comandos Disponíveis**\n\n"
        "- Envie um link do Telegram (https://t.me/...) para baixar mídia\n"
        "- /login - Fazer login com sua conta do Telegram\n"
        "- /logout - Fazer logout da sua conta\n"
        "- /status - Ver status atual dos downloads e uploads\n"
        "- /clear - Limpar histórico de tarefas concluídas\n"
        "- /help - Exibir esta mensagem de ajuda\n\n"
        "📱 **Como usar:**\n"
        "1. Use /login e forneça sua string de sessão\n"
        "2. Cole links de mídia do Telegram para baixar\n"
        "3. Use /status para verificar o progresso\n\n"
        "⚠️ Somente baixe conteúdo que você tem permissão para acessar!"
    )

    await message.reply(help_text)
