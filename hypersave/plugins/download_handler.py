import traceback

from pyrogram import Client, filters
from pyrogram.errors import PeerIdInvalid
from pyrogram.types import Message

from hypersave.bot import ClientBot
from hypersave.database.user_repository import UserRepository
from hypersave.logger import logger
from hypersave.managers.download_manager import DownloadManager

dw_manager = DownloadManager()
user_repository = UserRepository()


@ClientBot.on_message(filters.regex(r"https://t\.me/.+/.+") & filters.private)
async def handle_download_request(bot: Client, message: Message):
    post_url = message.text.strip()
    user_id = str(message.from_user.id)

    try:
        session_string = user_repository.get_string_session(user_id)

        if not session_string:
            await message.reply(
                "Você precisa fazer login primeiro. Use /login para fazer login!."
            )
            return

        await bot.send_reaction(message.chat.id, message_id=message.id, emoji="⚡")

        download_future = await dw_manager.download_media_from_url(
            user_id=user_id,
            session_string=session_string,
            url=post_url,
            message=message,
            bot=bot,
        )

        # You can optionally wait for the result here
        # result = await download_future
        # But it's not needed since the download manager handles feedback

    except ValueError as e:
        await message.reply(f"Formato de URL invalido")
    except Exception as e:
        logger.error(f"Error processing your request: {str(e)}")
        traceback.print_exc()
