import re
import traceback

from pyrogram import Client, filters
from pyrogram.types import Message

from hypersave.bot import ClientBot
from hypersave.logger import logger
from hypersave.managers.download_manager import DownloadManager
from hypersave.managers.upload_manager import UploadManager
from hypersave.managers.user_manager import UserManager
from hypersave.utils.message_utils import save_message_info

# Create manager instances
user_manager = UserManager()
download_manager = DownloadManager()
upload_manager = UploadManager()

# Link download and upload managers
download_manager.upload_manager = upload_manager

# Start managers
user_manager.start()
download_manager.start()
upload_manager.start()


@ClientBot.on_message(filters.regex(r"https://t\.me/.+/.+") & filters.private)
async def handle_download_request(bot: Client, message: Message):
    """Handle messages containing Telegram links for download"""
    try:
        # Save message info for analytics
        await save_message_info(message)

        # Extract URL from message
        post_url = message.text.strip()
        user_id = str(message.from_user.id)

        # Get user client
        user_client = await user_manager.get_user_client(user_id)

        if not user_client:
            await message.reply(
                "Você precisa fazer login primeiro. Use /login para fazer login!"
            )
            return

        # React to show the request is being processed
        await bot.send_reaction(message.chat.id, message_id=message.id, emoji="⚡")

        # Queue the download
        await download_manager.enqueue_download(
            user_client=user_client,
            user_id=user_id,
            url=post_url,
            message=message,
            bot=bot,
        )

    except ValueError as e:
        await message.reply("Formato de URL inválido")
    except Exception as e:
        error_message = f"Erro ao processar sua solicitação: {str(e)}"
        logger.error(error_message)
        traceback.print_exc()
        await message.reply(error_message)
