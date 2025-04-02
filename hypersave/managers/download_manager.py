import asyncio
import os
from pathlib import Path
from time import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from pyrogram import Client
from pyrogram.errors import PeerIdInvalid, RPCError
from pyrogram.types import Message

from hypersave.models.download_task import DownloadTask
from hypersave.models.media_info import MediaInfo
from hypersave.settings import Settings


class DownloadManager:
    def __init__(self, max_concurrent_downloads: int = 5):
        self.settings = Settings()
        self.MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB limit

        # Queue for downloads
        self.download_queue = asyncio.Queue()
        self.download_semaphore = asyncio.Semaphore(max_concurrent_downloads)

        # Track active and queued downloads
        self.active_downloads: Dict[str, DownloadTask] = {}  # task_id -> DownloadTask
        self.completed_downloads: List[str] = []  # List of task_ids

        # Processor task
        self.processor_task = None
        self.running = False

        # Upload manager reference (will be set after initialization)
        self.upload_manager = None

    def start(self):
        """Start the download manager processing loop"""
        if not self.running:
            self.running = True
            self.processor_task = asyncio.create_task(self.process_download_queue())

    async def stop(self):
        """Stop the download manager"""
        self.running = False
        if self.processor_task:
            self.processor_task.cancel()
            try:
                await self.processor_task
            except asyncio.CancelledError:
                pass

    def parse_telegram_url(self, url: str) -> Tuple[str, int]:
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

    async def enqueue_download(
        self, user_client: Client, user_id: str, url: str, message: Message, bot: Client
    ) -> str:
        """
        Add a download task to the queue

        Args:
            user_client: User's Pyrogram client
            user_id: User identifier
            url: Telegram message URL
            message: Original message for status updates
            bot: Bot client for sending responses

        Returns:
            task_id: Unique identifier for this download task
        """
        try:
            # Parse chat_id and message_id from URL
            chat_id, message_id = self.parse_telegram_url(url)

            # Create a unique task ID
            task_id = f"{user_id}_{chat_id}_{message_id}_{int(time())}"

            # Create status message
            status_message = await message.reply("⏳ Download added to queue...")

            # Create download task
            task = DownloadTask(
                task_id=task_id,
                user_id=user_id,
                user_client=user_client,
                chat_id=chat_id,
                message_id=message_id,
                original_message=message,
                status_message=status_message,
                bot=bot,
                start_time=None,  # Will be set when download starts
                progress=0,
                total_size=0,
                is_completed=False,
                output_path=None,
            )

            # Store last progress text to avoid duplicate updates
            task.last_progress_text = "⏳ Download added to queue..."

            # Put task in queue
            await self.download_queue.put(task)

            # Update status message
            queue_text = f"🔄 Download queued. Position: {self.download_queue.qsize()}"
            if queue_text != task.last_progress_text:
                await status_message.edit_text(queue_text)
                task.last_progress_text = queue_text

            return task_id

        except Exception as e:
            await message.reply(f"Error queueing download: {str(e)}")
            raise

    async def process_download_queue(self):
        """Process the download queue in the background"""
        while self.running:
            try:
                # Get next task
                task = await self.download_queue.get()

                # Process with semaphore to limit concurrent downloads
                asyncio.create_task(self.process_download_task(task))

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in download queue processor: {e}")

    async def process_download_task(self, task: DownloadTask):
        """Process a single download task"""
        async with self.download_semaphore:
            try:
                # Update task as active
                self.active_downloads[task.task_id] = task

                # Update status message
                await task.status_message.edit_text("📥 Download started...")

                # Mark download start time
                task.start_time = time()

                # Check if message is a media group
                source_message = await task.user_client.get_messages(
                    task.chat_id, task.message_id
                )

                if source_message.media_group_id:
                    # Handle media group - vamos preservar informação de grupo
                    output_files = await self._download_media_group(
                        task, source_message
                    )

                    # Adicionar metadado de grupo na task para o upload_manager saber que é um grupo
                    task.is_media_group = True
                    task.media_group_id = source_message.media_group_id
                else:
                    # Handle single media
                    output_file = await self._download_single_media(
                        task, source_message
                    )
                    output_files = [output_file] if output_file else []
                    task.is_media_group = False
                    task.media_group_id = None

                # Mark download as completed
                task.is_completed = True
                self.completed_downloads.append(task.task_id)

                # Queue for upload if we have files and upload manager is set
                if output_files and self.upload_manager:
                    if task.is_media_group:
                        # Se for um grupo de mídia, envia todos os arquivos juntos para preservar agrupamento
                        valid_files = [
                            path
                            for path in output_files
                            if path and os.path.exists(path)
                        ]
                        if valid_files:
                            await self.upload_manager.enqueue_media_group(
                                task.bot,
                                task.user_id,
                                valid_files,
                                source_message.media_group_id,
                                task.original_message,
                                task.status_message,
                                task.media_captions,  # Passar as legendas capturadas
                            )
                    else:
                        # Uploads individuais para mídias não agrupadas
                        for output_path in output_files:
                            if output_path and os.path.exists(output_path):
                                # Add to upload queue
                                await self.upload_manager.enqueue_upload(
                                    task.bot,
                                    task.user_id,
                                    output_path,
                                    source_message,
                                    task.original_message,
                                    task.status_message,
                                )

            except Exception as e:
                # Update status with error
                await task.status_message.edit_text(f"❌ Download failed: {str(e)}")
                print(f"Error processing download task: {e}")
            finally:
                # Remove from active downloads if still there
                if task.task_id in self.active_downloads:
                    del self.active_downloads[task.task_id]

                # Mark queue task as done
                self.download_queue.task_done()

    async def _download_single_media(
        self, task: DownloadTask, source_message: Message
    ) -> Optional[Path]:
        """Download a single media item"""
        try:
            if not source_message.media:
                if source_message.text:
                    # Just text message, no download needed
                    await task.original_message.reply(source_message.text)
                    await task.status_message.edit_text(
                        "✅ Text message processed (no media)"
                    )
                else:
                    await task.status_message.edit_text(
                        "❌ No media or text found in the message"
                    )
                return None

            # Get file size if available
            file_size = 0
            if hasattr(source_message, "document") and source_message.document:
                file_size = source_message.document.file_size
            elif hasattr(source_message, "video") and source_message.video:
                file_size = source_message.video.file_size
            elif hasattr(source_message, "audio") and source_message.audio:
                file_size = source_message.audio.file_size

            # Set total size in the task
            task.total_size = file_size

            # Check size limit
            if file_size > self.MAX_FILE_SIZE:
                size_gb = self.MAX_FILE_SIZE / (1024 * 1024 * 1024)
                await task.status_message.edit_text(
                    f"❌ File exceeds {size_gb:.2f}GB limit and cannot be downloaded."
                )
                return None

            # Determine file extension based on media type
            file_ext = self._get_file_extension(source_message)

            # Create output path
            output_path = (
                self.settings.DOWNLOADS_DIR
                / f"{task.chat_id}_{task.message_id}{file_ext}"
            )

            # Download media file with progress tracking and melhor tratamento de erros
            try:
                file_path = await source_message.download(
                    file_name=str(output_path),
                    progress=self._progress_callback,
                    progress_args=(task,),
                )

                # Update task with result
                task.output_path = Path(file_path)

                # Update status
                await task.status_message.edit_text(
                    "✅ Download completed. Queued for upload..."
                )

                return Path(file_path)

            except FileNotFoundError as e:
                # Problemas comuns no Docker com arquivos temporários
                error_msg = (
                    f"Erro ao salvar arquivo. Tentando novamente com novo nome: {e}"
                )
                print(error_msg)

                # Tentar com novo nome para evitar conflitos
                new_output_path = output_path.with_name(
                    f"{output_path.stem}_retry{output_path.suffix}"
                )

                try:
                    # Tentar novamente com novo nome
                    file_path = await source_message.download(
                        file_name=str(new_output_path)
                    )

                    task.output_path = Path(file_path)
                    await task.status_message.edit_text(
                        "✅ Download completed após retentativa. Queued for upload..."
                    )

                    return Path(file_path)
                except Exception as retry_error:
                    await task.status_message.edit_text(
                        f"❌ Falha no download após retentativa: {str(retry_error)}"
                    )
                    raise

        except Exception as e:
            error_msg = f"❌ Download failed: {str(e)}"
            print(error_msg)
            try:
                await task.status_message.edit_text(error_msg)
            except Exception as msg_error:
                if "MESSAGE_NOT_MODIFIED" not in str(msg_error):
                    print(f"Erro ao atualizar mensagem de erro: {msg_error}")
            raise

    async def _download_media_group(
        self, task: DownloadTask, source_message: Message
    ) -> List[Path]:
        """Download a media group (multiple photos/videos)"""
        try:
            # Get all messages in the media group
            media_group_messages = await task.user_client.get_media_group(
                task.chat_id, task.message_id
            )

            output_paths = []
            captions = []  # Lista para armazenar legendas

            # Update status message and track last text
            status_text = (
                f"📥 Downloading media group ({len(media_group_messages)} items)..."
            )
            if (
                not hasattr(task, "last_progress_text")
                or task.last_progress_text != status_text
            ):
                await task.status_message.edit_text(status_text)
                task.last_progress_text = status_text

            # Download each media in the group
            for i, msg in enumerate(media_group_messages):
                if not msg.media:
                    continue

                # Armazenar a legenda deste item
                captions.append(msg.caption or "")

                # Update progress with careful tracking of last message
                new_status = (
                    f"📥 Downloading media {i+1}/{len(media_group_messages)}..."
                )
                if task.last_progress_text != new_status:
                    try:
                        await task.status_message.edit_text(new_status)
                        task.last_progress_text = new_status
                    except Exception as e:
                        if "MESSAGE_NOT_MODIFIED" not in str(e):
                            print(f"Error updating status: {e}")

                # Get file extension
                file_ext = self._get_file_extension(msg)

                # Create unique filename
                output_path = (
                    self.settings.DOWNLOADS_DIR / f"{task.chat_id}_{msg.id}{file_ext}"
                )

                # Download the file
                file_path = await msg.download(file_name=str(output_path))

                output_paths.append(Path(file_path))

            # Armazenar legendas na task
            task.media_captions = captions

            # Update status with final message
            final_status = f"✅ Media group download completed ({len(output_paths)}/{len(media_group_messages)} files). Queued for upload..."
            if task.last_progress_text != final_status:
                try:
                    await task.status_message.edit_text(final_status)
                    task.last_progress_text = final_status
                except Exception as e:
                    if "MESSAGE_NOT_MODIFIED" not in str(e):
                        print(f"Error updating final status: {e}")

            return output_paths

        except Exception as e:
            await task.status_message.edit_text(
                f"❌ Media group download failed: {str(e)}"
            )
            raise

    async def _progress_callback(self, current: int, total: int, task: DownloadTask):
        """Callback for download progress updates"""
        if total == 0:
            return

        # Update task progress
        task.progress = current
        task.total_size = total

        # Calculate percentage and speed
        percentage = current * 100 / total
        elapsed_time = time() - task.start_time
        speed = current / elapsed_time if elapsed_time > 0 else 0

        # Calculate ETA
        if speed > 0:
            eta = (total - current) / speed
            eta_str = self._format_time(eta)
        else:
            eta_str = "∞"

        # Format speed string
        if speed < 1024:
            speed_str = f"{speed:.2f} B/s"
        elif speed < 1024 * 1024:
            speed_str = f"{speed/1024:.2f} KB/s"
        else:
            speed_str = f"{speed/(1024*1024):.2f} MB/s"

        # Store previous progress info to avoid duplicate updates
        if not hasattr(task, "last_progress_text"):
            task.last_progress_text = ""

        # Prepare new progress text
        new_progress_text = (
            f"📥 Downloading: {percentage:.1f}%\n"
            f"🚀 Speed: {speed_str}\n"
            f"⏱️ ETA: {eta_str}"
        )

        # Only update if the text actually changed or at 100%
        if new_progress_text != task.last_progress_text or current == total:
            # Update status periodically (not too often to avoid flood)
            if current == total or current % (max(1, total // 10)) == 0:
                try:
                    await task.status_message.edit_text(new_progress_text)
                    task.last_progress_text = new_progress_text
                except Exception as e:
                    # Ignore MESSAGE_NOT_MODIFIED errors
                    if "MESSAGE_NOT_MODIFIED" not in str(e):
                        print(f"Error updating progress: {e}")

    def _format_time(self, seconds: float) -> str:
        """Format seconds into readable time string"""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds//60:.0f}m {seconds%60:.0f}s"
        else:
            return f"{seconds//3600:.0f}h {(seconds%3600)//60:.0f}m"

    def _get_file_extension(self, message: Message) -> str:
        """Determine file extension based on media type"""
        if message.photo:
            return ".jpg"
        elif message.video:
            return ".mp4"
        elif message.audio:
            return ".mp3"
        elif message.voice:
            return ".ogg"
        elif message.document:
            # Try to get original extension if available
            if message.document.file_name:
                return Path(message.document.file_name).suffix

        # Default extension for other types
        return ".file"

    def get_queue_status(self) -> Dict[str, Any]:
        """Get current status of download queue"""
        return {
            "queue_size": self.download_queue.qsize(),
            "active_downloads": len(self.active_downloads),
            "active_tasks": [
                {
                    "task_id": task_id,
                    "user_id": task.user_id,
                    "progress": (
                        f"{(task.progress / task.total_size * 100):.1f}%"
                        if task.total_size
                        else "0%"
                    ),
                    "speed": self._calculate_speed(task) if task.start_time else "N/A",
                    "eta": (
                        self._calculate_eta(task)
                        if task.start_time and task.total_size and task.progress
                        else "N/A"
                    ),
                }
                for task_id, task in self.active_downloads.items()
            ],
            "completed_tasks": len(self.completed_downloads),
        }

    def _calculate_speed(self, task: DownloadTask) -> str:
        """Calculate current download speed for a task"""
        if not task.start_time:
            return "N/A"

        elapsed_time = time() - task.start_time
        if elapsed_time <= 0 or task.progress <= 0:
            return "0 B/s"

        speed = task.progress / elapsed_time

        if speed < 1024:
            return f"{speed:.2f} B/s"
        elif speed < 1024 * 1024:
            return f"{speed/1024:.2f} KB/s"
        else:
            return f"{speed/(1024*1024):.2f} MB/s"

    def _calculate_eta(self, task: DownloadTask) -> str:
        """Calculate ETA for a task"""
        if not task.start_time or task.progress <= 0 or task.total_size <= 0:
            return "N/A"

        elapsed_time = time() - task.start_time
        if elapsed_time <= 0:
            return "N/A"

        speed = task.progress / elapsed_time
        if speed <= 0:
            return "∞"

        remaining_bytes = task.total_size - task.progress
        eta_seconds = remaining_bytes / speed

        return self._format_time(eta_seconds)
