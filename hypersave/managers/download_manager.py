from urllib.parse import urlparse
from collections import defaultdict
from pyrogram import enums
from pyrogram.types import InputMediaPhoto, InputMediaVideo
import os

from asyncio import Queue


class DownloadManager:
    def __init__(self):
        self.dw_queue: Queue = Queue()
        self.MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024

    async def processMediaGroup(self, user, chat_id, message_id, bot, message):
        media_group_messages = await user.get_media_group(chat_id, message_id)
        media_list = []

        for msg in media_group_messages:
            if msg.photo:
                media_path = await user.download_media(msg.photo.file_id)
                media_list.append(InputMediaPhoto(media=media_path, caption=await self.get_parsed_msg(msg.caption or "", msg.caption_entities)))
            elif msg.video:
                media_path = await user.download_media(msg.video.file_id)
                media_list.append(InputMediaVideo(media=media_path, caption=await self.get_parsed_msg(msg.caption or "", msg.caption_entities)))

        if media_list:
            try:
                await bot.send_media_group(chat_id=message.chat.id, media=media_list)
            except Exception as e:
                await message.reply(f"Error sending media group: {str(e)}")
            finally:
                # Remova os arquivos baixados para economizar espaço
                for media in media_list:
                    if os.path.exists(media.media):
                        os.remove(media.media)
            return True
        return False

    def parse_chat_id_and_message_id(self, url):
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.strip('/').split('/')
        if len(path_parts) == 3 and path_parts[0] == 'c':
            chat_id = int('-100' + path_parts[1])
            message_id = int(path_parts[2])
            return chat_id, message_id
        elif len(path_parts) == 2:
            chat_id = path_parts[0]
            message_id = int(path_parts[1])
            return chat_id, message_id
        else:
            raise ValueError("Invalid URL format")
        
    async def fileSizeLimit(self, file_size, message, action_type="download"):
        if not self.chkFileSize(file_size):
            await message.reply(f"O arquivo excede {self.MAX_FILE_SIZE / (1024 * 1024 * 1024):.2f}GB do limite e não pode ser {action_type}ed.")
            return False
        return True
    
    def chkFileSize(self, file_size):
        return file_size <= self.MAX_FILE_SIZE
    
    async def get_parsed_msg(self, message_text, entities):
        priority = {
            enums.MessageEntityType.BOLD: 1,
            enums.MessageEntityType.ITALIC: 2,
            enums.MessageEntityType.UNDERLINE: 3,
            enums.MessageEntityType.STRIKETHROUGH: 4,
            enums.MessageEntityType.SPOILER: 5,
            enums.MessageEntityType.CODE: 6,
            enums.MessageEntityType.PRE: 7,
            enums.MessageEntityType.TEXT_LINK: 8,
            enums.MessageEntityType.HASHTAG: 9
        }
        default_priority = 100

        if not entities:
            return message_text

        entity_dict = defaultdict(list)
        for entity in entities:
            start = entity.offset
            end = entity.offset + entity.length
            entity_dict[(start, end)].append(entity)

        last_end = 0
        result = []
        for (start, end), entities in sorted(entity_dict.items()):
            if start > last_end:
                result.append(message_text[last_end:start])
            formatted_text = message_text[start:end]
            entities.sort(key=lambda x: priority.get(x.type, default_priority), reverse=True)
            for entity in entities:
                if entity.type == enums.MessageEntityType.BOLD:
                    formatted_text = f"**{formatted_text}**"
                elif entity.type == enums.MessageEntityType.ITALIC:
                    formatted_text = f"__{formatted_text}__"
                elif entity.type == enums.MessageEntityType.UNDERLINE:
                    formatted_text = f"--{formatted_text}--"
                elif entity.type == enums.MessageEntityType.STRIKETHROUGH:
                    formatted_text = f"~~{formatted_text}~~"
                elif entity.type == enums.MessageEntityType.SPOILER:
                    formatted_text = f"||{formatted_text}||"
                elif entity.type == enums.MessageEntityType.CODE:
                    formatted_text = f"`{formatted_text}`"
                elif entity.type == enums.MessageEntityType.PRE:
                    formatted_text = f"```{formatted_text}```"
                elif entity.type == enums.MessageEntityType.TEXT_LINK:
                    formatted_text = f"[{formatted_text}]({entity.url})"
                elif entity.type == enums.MessageEntityType.HASHTAG:
                    formatted_text = f"{formatted_text}"

            result.append(formatted_text)
            last_end = end

        if last_end < len(message_text):
            result.append(message_text[last_end:])

        return "".join(result)