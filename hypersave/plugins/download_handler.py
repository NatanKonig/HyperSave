from hypersave.bot import ClientBot
from hypersave.managers.download_manager import DownloadManager


from pyrogram import Client
from pyrogram import filters
from pyrogram.types import Message
from pyrogram.errors import PeerIdInvalid

dw_manager = DownloadManager()

@ClientBot.on_message(filters.regex(r"https://t\.me/.+/.+/.+") & filters.private)
async def download_media(bot: Client, message: Message):

    post_url = message.text.strip()

    await bot.send_reaction(message.chat.id, message_id=message.id, emoji="⚡")

    try:
        chat_id, message_id = dw_manager.parse_chat_id_and_message_id(post_url)
        chat_message = await user.get_messages(chat_id, message_id)
        if chat_message.document or chat_message.video or chat_message.audio:
            file_size = chat_message.document.file_size if chat_message.document else \
                        chat_message.video.file_size if chat_message.video else \
                        chat_message.audio.file_size

            if not await dw_manager.fileSizeLimit(file_size, message, "download"):
                return

        parsed_caption = await dw_manager.get_parsed_msg(chat_message.caption or "", chat_message.caption_entities)
        parsed_text = await dw_manager.get_parsed_msg(chat_message.text or "", chat_message.entities)

        if chat_message.media_group_id:
            if not await dw_manager.processMediaGroup(user, chat_id, message_id, bot, message):
                await message.reply("Could not extract any valid media from the media group.")
            return

        elif chat_message.media:
            start_time = time()
            progress_message = await message.reply("Starting...")

            # Proceed with downloading the file
            media_path = await chat_message.download(progress=Leaves.progress_for_pyrogram, progress_args=progressArgs(
                "📥 Downloading Progress", progress_message, start_time
            ))

            media_type = "photo" if chat_message.photo else "video" if chat_message.video else "audio" if chat_message.audio else "document"
            await send_media(bot, message, media_path, media_type, parsed_caption, progress_message, start_time)

            os.remove(media_path)
            await progress_message.delete()

        elif chat_message.text or chat_message.caption:
            await message.reply(parsed_text or parsed_caption)
        else:
            await message.reply("No media or text found in the post URL.")

    except PeerIdInvalid:
        await message.reply("Make sure the user client is part of the chat.")
    except Exception as e:
        error_message = f"Failed to download the media: {str(e)}"
        await message.reply(error_message)