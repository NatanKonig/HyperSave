import asyncio
import os
from collections import defaultdict
from time import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from pathlib import Path

from pyrogram import Client, enums
from pyrogram.errors import PeerIdInvalid, RPCError
from pyrogram.types import InputMediaPhoto, InputMediaVideo, Message

from hypersave.settings import Settings
from hypersave.utils.create_thumb import get_video_info, move_metadata_to_start, get_video_thumbnail, process_video_thumb


class UserClient(Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id = None
        self.last_used = 0

    async def start(self):
        await super().start()
        self.user_id = (await self.get_me()).id
        self.last_used = time()
        return self


class DownloadManager:
    def __init__(self, max_concurrent_downloads: int = 5):
        self.settings = Settings()
        self.MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB limit

        self.download_queue = asyncio.PriorityQueue()
        self.download_semaphore = asyncio.Semaphore(max_concurrent_downloads)

        self.user_clients: Dict[str, UserClient] = {}

        self.processor_task = asyncio.create_task(self.process_download_queue())

        self.running = True

    async def get_user_client(self, user_id: str, session_string: str) -> UserClient:
        if user_id in self.user_clients and self.user_clients[user_id].is_connected:
            client = self.user_clients[user_id]
            client.last_used = time()
            return client

        # Create new client if needed
        client = UserClient(
            name=f"user_{user_id}",
            session_string=session_string,
            api_id=self.settings.api_id,
            api_hash=self.settings.api_hash,
            device_model="HyperSave Bot",
            max_concurrent_transmissions=5,
            workdir="./sessions/",
        )

        try:
            await client.start()
            self.user_clients[user_id] = client
            return client
        except Exception as e:
            print(f"Error creating user client for {user_id}: {e}")
            raise

    async def enqueue_download(
        self,
        user_id: str,
        session_string: str,
        download_function: Callable,
        download_args: Dict[str, Any],
        priority: int = 10,
        callback: Optional[Callable] = None,
    ) -> asyncio.Future:
        """
        Add a download task to the queue

        Args:
            user_id: User identifier
            session_string: User's session string
            download_function: Function to execute for download
            download_args: Arguments for the download function
            priority: Priority level (lower = higher priority)
            callback: Optional callback function to execute after download

        Returns:
            Future representing the download task
        """
        # Create a future to track the download result
        future = asyncio.get_event_loop().create_future()

        # Create the download task
        download_task = {
            "user_id": user_id,
            "session_string": session_string,
            "function": download_function,
            "args": download_args,
            "future": future,
            "callback": callback,
        }

        # Add to queue with priority
        await self.download_queue.put((priority, download_task))

        return future

    async def process_download_queue(self):
        """Background task that processes the download queue"""
        while self.running:
            try:
                # Get next download task
                _, task = await self.download_queue.get()

                # Process with semaphore to limit concurrent downloads
                asyncio.create_task(self.execute_download_task(task))

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in download queue processor: {e}")

    async def execute_download_task(self, task):
        """Execute a single download task with concurrency control"""
        async with self.download_semaphore:
            user_id = task["user_id"]
            session_string = task["session_string"]
            download_function = task["function"]
            download_args = task["args"]
            future = task["future"]
            callback = task["callback"]

            try:
                # Get the user client
                user_client = await self.get_user_client(user_id, session_string)

                # Execute the download function
                result = await download_function(user_client, **download_args)

                # Set result and call callback if provided
                future.set_result(result)
                if callback:
                    await callback(result)

            except Exception as e:
                print(f"Download task failed: {e}")
                future.set_exception(e)
            finally:
                # Mark task as done
                self.download_queue.task_done()

    def parse_chat_id_and_message_id(self, url: str) -> Tuple[str, int]:
        """Parse Telegram URL to extract chat ID and message ID"""
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.strip("/").split("/")

        if len(path_parts) >= 3 and path_parts[0] == "c":
            # Private channel format: t.me/c/1234567890/123
            chat_id = int("-100" + path_parts[1])
            message_id = int(path_parts[2])
            return chat_id, message_id
        elif len(path_parts) >= 2:
            # Public channel format: t.me/channel_name/123
            chat_id = path_parts[0]
            message_id = int(path_parts[1])
            return chat_id, message_id
        else:
            raise ValueError("Invalid Telegram URL format")

    async def file_size_check(self, file_size: int, message: Message) -> bool:
        """Check if file size is within limits"""
        if file_size > self.MAX_FILE_SIZE:
            size_gb = self.MAX_FILE_SIZE / (1024 * 1024 * 1024)
            await message.reply(
                f"O arquivo excede {size_gb:.2f}GB do limite e não pode ser baixado."
            )
            return False
        return True

    async def download_media_from_url(
        self,
        user_id: str,
        session_string: str,
        url: str,
        message: Message,
        bot: Client,
        priority: int = 10,
    ) -> asyncio.Future:
        """
        Download media from a Telegram URL

        Args:
            user_id: User identifier
            session_string: User's session string
            url: Telegram message URL
            message: Original user message for updates
            bot: Bot client for sending responses
            priority: Priority level (lower = higher priority)

        Returns:
            Future representing the download task
        """
        chat_id, message_id = self.parse_chat_id_and_message_id(url)

        # Create download arguments
        download_args = {
            "chat_id": chat_id,
            "message_id": message_id,
            "original_message": message,
            "bot": bot,
        }

        # Enqueue the download
        return await self.enqueue_download(
            user_id,
            session_string,
            self._handle_media_download,
            download_args,
            priority,
        )

    async def _handle_media_download(
        self,
        user_client: UserClient,
        chat_id: Any,
        message_id: int,
        original_message: Message,
        bot: Client,
    ):
        """Internal function to handle the actual media download process"""
        try:
            # Get message from the source
            source_message = await user_client.get_messages(chat_id, message_id)

            # Check if it's a media group
            if source_message.media_group_id:
                return await self._process_media_group(
                    user_client, chat_id, message_id, original_message, bot
                )

            # Process single media
            if source_message.media:
                # Check file size
                file_size = 0
                if source_message.document:
                    file_size = source_message.document.file_size
                elif source_message.video:
                    file_size = source_message.video.file_size
                elif source_message.audio:
                    file_size = source_message.audio.file_size

                if file_size > 0 and not await self.file_size_check(
                    file_size, original_message
                ):
                    return None

                # Download the media
                progress_message = await original_message.reply("Downloading media...")
                start_time = time()

                # Format caption if any
                caption = await self.get_parsed_msg(
                    source_message.caption or "", source_message.caption_entities
                )

                # Download the file
                media_path = await source_message.download(
                    progress=self._progress_callback,
                    progress_args=(progress_message, start_time),
                )

                media_path = Path(media_path)


                # Send downloaded media back to user
                await self._send_media(
                    bot,
                    original_message,
                    media_path,
                    self._get_media_type(source_message),
                    caption,
                    progress_message,
                )

                # Clean up
                if os.path.exists(media_path):
                    os.remove(media_path)

                await progress_message.delete()
                return media_path

            elif source_message.text:
                # Format and send text message
                parsed_text = await self.get_parsed_msg(
                    source_message.text, source_message.entities
                )
                await original_message.reply(parsed_text)
                return parsed_text

            else:
                await original_message.reply("No media or text found in the message.")
                return None

        except PeerIdInvalid:
            await original_message.reply(
                "The user client is not a member of the source chat."
            )
            return None
        except Exception as e:
            await original_message.reply(f"Failed to download: {str(e)}")
            raise

    async def _process_media_group(
        self,
        user_client: UserClient,
        chat_id: Any,
        message_id: int,
        original_message: Message,
        bot: Client,
    ):
        """Process a media group (multiple photos/videos)"""
        try:
            # Get media group messages
            media_group_messages = await user_client.get_media_group(
                chat_id, message_id
            )
            media_list = []
            downloaded_paths = []

            progress_message = await original_message.reply(
                "Downloading media group..."
            )

            # Process each media in group
            for msg in media_group_messages:
                if msg.photo:
                    media_path = await msg.download()
                    downloaded_paths.append(media_path)
                    caption = await self.get_parsed_msg(
                        msg.caption or "", msg.caption_entities
                    )
                    media_list.append(
                        InputMediaPhoto(media=media_path, caption=caption)
                    )

                elif msg.video:
                    media_path = await msg.download()
                    media_path = Path(media_path)
                    await move_metadata_to_start(media_path)
                    thumb_path = media_path.with_suffix(".jpg")
                    await get_video_thumbnail(media_path, thumb_path)
                    duration, width, height = await get_video_info(media_path)
                    downloaded_paths.append(media_path)
                    caption = await self.get_parsed_msg(
                        msg.caption or "", msg.caption_entities
                    )
                    media_list.append(
                        InputMediaVideo(media=media_path, caption=caption, thumb=thumb_path, duration=duration, width=width, height=height)
                    )

            # Send media group
            if media_list:
                await bot.send_media_group(
                    chat_id=original_message.chat.id, media=media_list
                )

            # Clean up downloaded files
            for path in downloaded_paths:
                if os.path.exists(path):
                    os.remove(path)

            await progress_message.delete()
            return downloaded_paths

        except Exception as e:
            await original_message.reply(f"Error processing media group: {str(e)}")
            raise

    def _get_media_type(self, message: Message) -> str:
        """Determine the media type of a message"""
        if message.photo:
            return "photo"
        elif message.video:
            return "video"
        elif message.audio:
            return "audio"
        elif message.document:
            return "document"
        else:
            return "unknown"

    async def _send_media(
        self,
        bot: Client,
        original_message: Message,
        media_path: Path,
        media_type: str,
        caption: str,
        progress_message: Message,
    ):
        """Send downloaded media back to user"""
        chat_id = original_message.chat.id

        if media_type == "photo":
            await bot.send_photo(chat_id, media_path, caption=caption)
        elif media_type == "video":
            await move_metadata_to_start(media_path)
            duration, width, height = await get_video_info(media_path)
            thumb_path = media_path.with_suffix(".jpg")
            await get_video_thumbnail(media_path, thumb_path)
            if duration <= 180:
                await bot.send_video(
                    chat_id,
                    media_path,
                    caption=caption,
                    duration=duration,
                    width=width,
                    height=height,
                )
            else:
                thumb_path_full = media_path.with_suffix(".thumb.jpg")
                await process_video_thumb(media_path, thumb_path_full)
                media_group = [
                    InputMediaVideo(
                        media=str(media_path),
                        caption=caption,
                        duration=duration,
                        width=width,
                        height=height,
                        thumb=str(thumb_path),
                    ),
                    InputMediaPhoto(media=str(thumb_path_full)),
                ]
                await bot.send_media_group(chat_id, media_group)
        elif media_type == "audio":
            await bot.send_audio(chat_id, media_path, caption=caption)
        elif media_type == "document":
            await bot.send_document(chat_id, media_path, caption=caption)
        else:
            await bot.send_document(chat_id, media_path, caption=caption)

    async def _progress_callback(self, current, total, progress_message, start_time):
        """Callback for download progress updates"""
        if total == 0:
            return

        percentage = current * 100 / total
        speed = current / (time() - start_time)

        # Calculate estimated time of arrival (ETA)
        if speed > 0:
            eta = (total - current) / speed
            eta_str = self._format_time(eta)
        else:
            eta_str = "∞"

        # Format speed
        if speed < 1024:
            speed_str = f"{speed:.2f} B/s"
        elif speed < 1024 * 1024:
            speed_str = f"{speed/1024:.2f} KB/s"
        else:
            speed_str = f"{speed/(1024*1024):.2f} MB/s"

        # Update progress message periodically to avoid flood
        if current % (total // 10) == 0 or current == total:
            try:
                await progress_message.edit_text(
                    f"📥 Downloading: {percentage:.1f}%\n"
                    f"🚀 Speed: {speed_str}\n"
                    f"⏱️ ETA: {eta_str}"
                )
            except:
                pass

    def _format_time(self, seconds: float) -> str:
        """Format seconds into readable time string"""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds//60:.0f}m {seconds%60:.0f}s"
        else:
            return f"{seconds//3600:.0f}h {(seconds%3600)//60:.0f}m"

    async def get_parsed_msg(self, message_text: str, entities: List = None) -> str:
        if not message_text or not entities:
            return message_text

        priority = {
            enums.MessageEntityType.BOLD: 1,
            enums.MessageEntityType.ITALIC: 2,
            enums.MessageEntityType.UNDERLINE: 3,
            enums.MessageEntityType.STRIKETHROUGH: 4,
            enums.MessageEntityType.SPOILER: 5,
            enums.MessageEntityType.CODE: 6,
            enums.MessageEntityType.PRE: 7,
            enums.MessageEntityType.TEXT_LINK: 8,
            enums.MessageEntityType.HASHTAG: 9,
        }
        default_priority = 100

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
            entities.sort(
                key=lambda x: priority.get(x.type, default_priority), reverse=True
            )
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

    async def close(self):
        """Close all user sessions and stop the manager"""
        self.running = False
        if self.processor_task:
            self.processor_task.cancel()

        # Close all user clients
        for user_id, client in self.user_clients.items():
            if client.is_connected:
                await client.stop()
