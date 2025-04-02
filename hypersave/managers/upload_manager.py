import asyncio
import os
from pathlib import Path
from time import time
from typing import Dict, List, Optional

from pyrogram import Client
from pyrogram.errors import RPCError
from pyrogram.types import InputMediaPhoto, InputMediaVideo, Message

from hypersave.logger import logger
from hypersave.models.upload_task import UploadTask
from hypersave.settings import Settings
from hypersave.utils.media_processor import (
    get_video_info,
    get_video_thumbnail,
    move_metadata_to_start,
    process_video_thumb,
)


class UploadManager:
    def __init__(self, max_concurrent_uploads: int = 3):
        self.upload_queue = asyncio.Queue()
        self.upload_semaphore = asyncio.Semaphore(max_concurrent_uploads)

        # Track active and completed uploads
        self.active_uploads: Dict[str, UploadTask] = {}
        self.completed_uploads: List[str] = []

        # Processor task
        self.processor_task = None
        self.running = False

        self.settings = Settings()

    def start(self):
        """Start the upload manager processing loop"""
        if not self.running:
            self.running = True
            self.processor_task = asyncio.create_task(self.process_upload_queue())

    async def stop(self):
        """Stop the upload manager"""
        self.running = False
        if self.processor_task:
            self.processor_task.cancel()
            try:
                await self.processor_task
            except asyncio.CancelledError:
                pass

    async def enqueue_upload(
        self,
        bot: Client,
        user_id: str,
        file_path: Path,
        source_message: Message,
        original_message: Message,
        status_message: Message,
    ) -> str:
        """
        Add a upload task to the queue

        Args:
            bot: Bot client
            user_id: User identifier
            file_path: Path to the file to upload
            source_message: Original source message
            original_message: User's message that triggered the download
            status_message: Message for status updates

        Returns:
            task_id: Unique identifier for this upload task
        """
        # Create a unique task ID
        task_id = f"upload_{user_id}_{int(time())}_{file_path.name}"

        # Get caption from source message if available
        caption = source_message.caption or ""

        # Verify the file exists
        if not os.path.exists(file_path):
            await status_message.edit_text(f"❌ File not found: {file_path}")
            return task_id

        # Create upload task
        task = UploadTask(
            task_id=task_id,
            user_id=user_id,
            bot=bot,
            file_path=file_path,
            original_message=original_message,
            status_message=status_message,
            source_message=source_message,
            caption=caption,
            start_time=None,  # Will be set when upload starts
            progress=0,
            total_size=os.path.getsize(file_path) if os.path.exists(file_path) else 0,
            is_completed=False,
            is_media_group=False,
            media_group_id=None,
            media_group_files=[],
        )

        # Put task in queue
        await self.upload_queue.put(task)

        # Update status message if provided
        if status_message:
            # Store last message text to avoid duplicate updates
            task.last_progress_text = (
                f"⏳ Upload queued. Position: {self.upload_queue.qsize()}"
            )
            try:
                await status_message.edit_text(task.last_progress_text)
            except Exception as e:
                if "MESSAGE_NOT_MODIFIED" not in str(e):
                    logger.error(f"Error updating upload queue status: {e}")

        return task_id

    async def enqueue_media_group(
        self,
        bot: Client,
        user_id: str,
        file_paths: List[Path],
        media_group_id: str,
        original_message: Message,
        status_message: Message,
        media_captions: List[str] = None,  # Nova lista para legendas
    ) -> str:
        """
        Add a media group upload task to the queue

        Args:
            bot: Bot client
            user_id: User identifier
            file_paths: List of paths to the files to upload
            media_group_id: Media group identifier
            original_message: User's message that triggered the download
            status_message: Message for status updates
            media_captions: List of captions for each media item

        Returns:
            task_id: Unique identifier for this upload task
        """
        # Create a unique task ID
        task_id = f"upload_group_{user_id}_{int(time())}_{media_group_id}"

        # Filter out files that don't exist
        valid_files = []
        valid_captions = []
        for i, path in enumerate(file_paths):
            if os.path.exists(path):
                valid_files.append(path)
                # Adicionar a legenda correspondente se disponível
                if media_captions and i < len(media_captions):
                    valid_captions.append(media_captions[i])
                else:
                    valid_captions.append("")
            else:
                logger.warning(f"File not found in media group: {path}")

        if not valid_files:
            await status_message.edit_text("❌ No valid files found in media group")
            return task_id

        # Create upload task for the group
        task = UploadTask(
            task_id=task_id,
            user_id=user_id,
            bot=bot,
            file_path=(
                valid_files[0] if valid_files else None
            ),  # Primary file just for reference
            original_message=original_message,
            status_message=status_message,
            source_message=None,  # No single source message for groups
            caption="",  # Will be set per media item
            start_time=None,  # Will be set when upload starts
            progress=0,
            total_size=sum(os.path.getsize(f) for f in valid_files),
            is_completed=False,
            is_media_group=True,
            media_group_id=media_group_id,
            media_group_files=valid_files,
            media_captions=valid_captions,  # Armazenar as legendas
        )

        # Put task in queue
        await self.upload_queue.put(task)

        # Update status message
        if status_message:
            # Store last message text to avoid duplicate updates
            task.last_progress_text = f"⏳ Media group upload queued ({len(valid_files)} items). Position: {self.upload_queue.qsize()}"
            try:
                await status_message.edit_text(task.last_progress_text)
            except Exception as e:
                if "MESSAGE_NOT_MODIFIED" not in str(e):
                    logger.error(f"Error updating upload queue status: {e}")

        return task_id

    async def process_upload_queue(self):
        """Process the upload queue in the background"""
        while self.running:
            try:
                # Get next task
                task = await self.upload_queue.get()

                # Process with semaphore to limit concurrent uploads
                asyncio.create_task(self.process_upload_task(task))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in upload queue processor: {e}")

    async def process_upload_task(self, task: UploadTask):
        """Process a single upload task"""
        async with self.upload_semaphore:
            try:
                # Update task as active
                self.active_uploads[task.task_id] = task

                # Update status message
                try:
                    await task.status_message.edit_text("📤 Upload started...")
                    task.last_progress_text = "📤 Upload started..."
                except Exception as e:
                    if "MESSAGE_NOT_MODIFIED" not in str(e):
                        logger.error(f"Error updating upload start status: {e}")

                # Mark upload start time
                task.start_time = time()

                # Process based on whether it's a media group or single file
                if task.is_media_group:
                    await self._upload_media_group(task)
                else:
                    # Check if file exists
                    if not os.path.exists(task.file_path):
                        await task.status_message.edit_text(
                            f"❌ File not found for upload: {task.file_path}"
                        )
                        return

                    # Determine media type and upload accordingly
                    await self._upload_media(task)

                # Mark as completed
                task.is_completed = True
                self.completed_uploads.append(task.task_id)

                # Update status
                try:
                    await task.status_message.edit_text("✅ Upload completed!")
                    task.last_progress_text = "✅ Upload completed!"
                except Exception as e:
                    if "MESSAGE_NOT_MODIFIED" not in str(e):
                        logger.error(f"Error updating upload completion status: {e}")

                # Clean up files
                await self._cleanup_files(task)

            except Exception as e:
                # Update status with error
                error_msg = f"❌ Upload failed: {str(e)}"
                logger.error(f"Error processing upload task: {e}")
                try:
                    await task.status_message.edit_text(error_msg)
                except Exception as msg_err:
                    logger.error(f"Failed to send error message: {msg_err}")
            finally:
                # Remove from active uploads
                if task.task_id in self.active_uploads:
                    del self.active_uploads[task.task_id]

                # Mark queue task as done
                self.upload_queue.task_done()

    async def _upload_media_group(self, task: UploadTask):
        """Process and upload a media group"""
        try:
            # Prepare media list for the group
            media_list = []
            chat_id = task.original_message.chat.id
            sent_message_ids = (
                []
            )  # Lista para armazenar todos os IDs de mensagens enviadas

            # Update status
            status_text = (
                f"📤 Processing media group ({len(task.media_group_files)} items)..."
            )
            try:
                await task.status_message.edit_text(status_text)
                task.last_progress_text = status_text
            except Exception as e:
                if "MESSAGE_NOT_MODIFIED" not in str(e):
                    logger.error(f"Error updating media group process status: {e}")

            # Process each file in the group
            for i, file_path in enumerate(task.media_group_files):
                if not os.path.exists(file_path):
                    logger.warning(f"File not found in media group: {file_path}")
                    continue

                file_ext = file_path.suffix.lower()

                # Pegar a legenda específica para este item
                caption = (
                    task.media_captions[i]
                    if task.media_captions and i < len(task.media_captions)
                    else ""
                )

                # Process based on file type
                if file_ext in [".jpg", ".jpeg", ".png"]:
                    # Add as photo - ensure correct dimensions
                    thumb_info = f"Processing photo {i+1}/{len(task.media_group_files)}"
                    logger.info(thumb_info)

                    # Add with caption
                    media_list.append(
                        InputMediaPhoto(media=str(file_path), caption=caption)
                    )

                elif file_ext in [".mp4", ".avi", ".mov", ".mkv"]:
                    try:
                        # Process video
                        await move_metadata_to_start(file_path)
                        duration, width, height = await get_video_info(file_path)

                        # Log video info
                        video_info = f"Video {i+1}/{len(task.media_group_files)}: duration={duration}s, dimensions={width}x{height}"
                        logger.info(video_info)

                        # Generate thumbnail with proper aspect ratio
                        thumb_path = file_path.with_suffix(".jpg")
                        thumb_result = await get_video_thumbnail(file_path, thumb_path)

                        # Add to media group, only include thumbnail if successfully created
                        if thumb_result and os.path.exists(thumb_result):
                            logger.info(f"Adding video with thumbnail: {thumb_result}")
                            media_list.append(
                                InputMediaVideo(
                                    media=str(file_path),
                                    thumb=str(thumb_result),
                                    duration=duration,
                                    width=width,
                                    height=height,
                                    caption=caption,  # Incluir a legenda
                                )
                            )
                        else:
                            logger.info("Adding video without thumbnail")
                            media_list.append(
                                InputMediaVideo(
                                    media=str(file_path),
                                    duration=duration,
                                    width=width,
                                    height=height,
                                    caption=caption,  # Incluir a legenda
                                )
                            )
                    except Exception as e:
                        logger.error(f"Error processing video in media group: {e}")
                        # Try adding without processing
                        media_list.append(
                            InputMediaVideo(media=str(file_path), caption=caption)
                        )

            # Send in batches (maximum of 10 per group - Telegram limit)
            all_sent_messages = []  # Lista para armazenar todas as mensagens enviadas
            first_message_id = None  # Primeiro ID de mensagem para encaminhamento

            if media_list:
                total_batches = (len(media_list) + 9) // 10  # Ceiling division

                for i in range(0, len(media_list), 10):
                    batch = media_list[i : i + 10]
                    batch_num = i // 10 + 1

                    # Update status
                    status_text = (
                        f"📤 Sending media group... (Batch {batch_num}/{total_batches})"
                    )
                    try:
                        await task.status_message.edit_text(status_text)
                        task.last_progress_text = status_text
                    except Exception as e:
                        if "MESSAGE_NOT_MODIFIED" not in str(e):
                            logger.error(
                                f"Error updating media group upload status: {e}"
                            )

                    try:
                        # Send the group
                        sent_messages = await task.bot.send_media_group(
                            chat_id=chat_id, media=batch
                        )

                        # Armazenar todas as mensagens enviadas
                        all_sent_messages.extend(sent_messages)

                        # Armazenar o primeiro ID de mensagem se ainda não tiver sido definido
                        if sent_messages and not first_message_id:
                            first_message_id = sent_messages[0].id
                            first_message = sent_messages[0]

                        # Armazenar IDs para possível uso posterior
                        for msg in sent_messages:
                            sent_message_ids.append(msg.id)

                    except Exception as e:
                        error_msg = (
                            f"Error sending batch {batch_num}/{total_batches}: {str(e)}"
                        )
                        logger.error(error_msg)
                        await task.original_message.reply(error_msg)

                # Encaminhar para o grupo privado se configurado
                if (
                    all_sent_messages
                    and hasattr(self.settings, "private_group_id")
                    and self.settings.private_group_id
                ):
                    try:
                        # Verificar se temos um media_group_id
                        if first_message and first_message.media_group_id:
                            logger.info(
                                f"Encaminhando grupo de mídia para o grupo privado usando forward_media_group"
                            )
                            # Usar forward_media_group para encaminhar o grupo completo
                            await task.bot.forward_media_group(
                                chat_id=self.settings.private_group_id,
                                from_chat_id=chat_id,
                                message_id=first_message_id,
                            )
                        else:
                            # Fallback: encaminhar cada mensagem individualmente
                            logger.info(
                                f"Encaminhando mensagens individualmente para o grupo privado"
                            )
                            for message_id in sent_message_ids:
                                await task.bot.forward_messages(
                                    chat_id=self.settings.private_group_id,
                                    from_chat_id=chat_id,
                                    message_ids=message_id,
                                )
                    except Exception as e:
                        logger.error(f"Erro ao encaminhar para o grupo privado: {e}")
                        # Tentar método alternativo
                        try:
                            logger.info(
                                "Tentando método alternativo de encaminhamento usando forward_messages"
                            )
                            await task.bot.forward_messages(
                                chat_id=self.settings.private_group_id,
                                from_chat_id=chat_id,
                                message_ids=sent_message_ids,
                            )
                        except Exception as e2:
                            logger.error(f"Também falhou com método alternativo: {e2}")

                # Update final status
                final_status = (
                    f"✅ Media group sent successfully! ({len(media_list)} items)"
                )
                try:
                    await task.status_message.edit_text(final_status)
                    task.last_progress_text = final_status
                except Exception as e:
                    if "MESSAGE_NOT_MODIFIED" not in str(e):
                        logger.error(f"Error updating media group final status: {e}")
            else:
                await task.status_message.edit_text(
                    "❌ No valid media files found in the group"
                )

        except Exception as e:
            logger.error(f"Error in _upload_media_group: {e}")
            await task.status_message.edit_text(
                f"❌ Error processing media group: {str(e)}"
            )
            raise

    async def _upload_media(self, task: UploadTask):
        """Upload media based on file type"""
        file_path = task.file_path
        file_ext = file_path.suffix.lower()
        chat_id = task.original_message.chat.id
        sent_message = None

        try:
            # Process media based on file type
            if file_ext in [".jpg", ".jpeg", ".png"]:
                # Upload as photo
                try:
                    sent_message = await task.bot.send_photo(
                        chat_id=chat_id,
                        photo=str(file_path),
                        caption=task.caption,
                        progress=self._progress_callback,
                        progress_args=(task,),
                    )
                except RPCError as e:
                    if "PHOTO_INVALID_DIMENSIONS" in str(e):
                        logger.error(f"Invalid photo dimensions: {e}")
                        # Try to send as document instead
                        sent_message = await task.bot.send_document(
                            chat_id=chat_id,
                            document=str(file_path),
                            caption=task.caption,
                            progress=self._progress_callback,
                            progress_args=(task,),
                        )

            elif file_ext in [".mp4", ".avi", ".mov", ".mkv"]:
                # Process video before upload
                await move_metadata_to_start(file_path)
                duration, width, height = await get_video_info(file_path)

                # Log video information
                video_info = (
                    f"Video info: duration={duration}s, dimensions={width}x{height}"
                )
                logger.info(video_info)

                # Create thumbnail using the same aspect ratio as the video
                thumb_path = file_path.with_suffix(".jpg")
                thumb_result = await get_video_thumbnail(file_path, thumb_path)

                # Upload video
                if duration <= 180:  # Short video
                    # Upload with thumbnail if available
                    if thumb_result and os.path.exists(thumb_result):
                        logger.info(
                            f"Sending short video with thumbnail: {thumb_result}"
                        )
                        sent_message = await task.bot.send_video(
                            chat_id=chat_id,
                            video=str(file_path),
                            caption=task.caption,
                            duration=duration,
                            width=width,
                            height=height,
                            thumb=str(thumb_result),
                            progress=self._progress_callback,
                            progress_args=(task,),
                        )
                    else:
                        logger.info("Sending short video without thumbnail")
                        sent_message = await task.bot.send_video(
                            chat_id=chat_id,
                            video=str(file_path),
                            caption=task.caption,
                            duration=duration,
                            width=width,
                            height=height,
                            progress=self._progress_callback,
                            progress_args=(task,),
                        )
                else:  # Longer video, create timeline preview
                    # Timeline preview should be created with proper aspect ratio
                    thumb_preview_path = file_path.with_suffix(".thumb.jpg")

                    # Create timeline preview with our updated function
                    preview_result = await process_video_thumb(
                        file_path, thumb_preview_path, duration
                    )

                    if preview_result and os.path.exists(preview_result):
                        logger.info(f"Preview thumbnail created: {preview_result}")

                        # Verify if thumbnail exists
                        if not thumb_result or not os.path.exists(thumb_result):
                            # If main thumbnail failed, try to create it again
                            thumb_result = await get_video_thumbnail(
                                file_path, thumb_path
                            )
                            logger.info(f"Recreated main thumbnail: {thumb_result}")

                        # If both thumbnails exist, send as media group
                        if thumb_result and os.path.exists(thumb_result):
                            logger.info(
                                f"Sending video with timeline preview as media group"
                            )

                            try:
                                # Create media group
                                media_group = [
                                    InputMediaVideo(
                                        media=str(file_path),
                                        caption=task.caption,
                                        thumb=str(thumb_result),
                                        duration=duration,
                                        width=width,
                                        height=height,
                                    ),
                                    InputMediaPhoto(media=str(preview_result)),
                                ]

                                # Send media group
                                sent_messages = await task.bot.send_media_group(
                                    chat_id=chat_id, media=media_group
                                )

                                if sent_messages:
                                    sent_message = sent_messages[
                                        0
                                    ]  # Use first message as reference
                                    logger.info(
                                        f"Successfully sent video with timeline preview"
                                    )
                                else:
                                    logger.warning(
                                        "No messages returned from send_media_group"
                                    )
                            except Exception as e:
                                logger.error(f"Error sending media group: {e}")
                                # Fallback to sending just the video
                                logger.info(
                                    "Falling back to sending video without preview"
                                )
                                sent_message = await task.bot.send_video(
                                    chat_id=chat_id,
                                    video=str(file_path),
                                    caption=task.caption,
                                    duration=duration,
                                    width=width,
                                    height=height,
                                    thumb=(
                                        str(thumb_result)
                                        if thumb_result and os.path.exists(thumb_result)
                                        else None
                                    ),
                                    progress=self._progress_callback,
                                    progress_args=(task,),
                                )
                        else:
                            # If only the preview exists but no thumbnail
                            logger.info(f"Sending video with only timeline preview")
                            try:
                                media_group = [
                                    InputMediaVideo(
                                        media=str(file_path),
                                        caption=task.caption,
                                        duration=duration,
                                        width=width,
                                        height=height,
                                    ),
                                    InputMediaPhoto(media=str(preview_result)),
                                ]

                                sent_messages = await task.bot.send_media_group(
                                    chat_id=chat_id, media=media_group
                                )

                                if sent_messages:
                                    sent_message = sent_messages[0]
                                    logger.info(
                                        f"Successfully sent video with timeline preview (no thumbnail)"
                                    )
                            except Exception as e:
                                logger.error(
                                    f"Error sending media group with only preview: {e}"
                                )
                                # Fallback to sending just the video
                                sent_message = await task.bot.send_video(
                                    chat_id=chat_id,
                                    video=str(file_path),
                                    caption=task.caption,
                                    duration=duration,
                                    width=width,
                                    height=height,
                                    progress=self._progress_callback,
                                    progress_args=(task,),
                                )
                    else:
                        # If timeline preview creation failed
                        logger.warning(
                            "Failed to create timeline preview, sending video only"
                        )
                        sent_message = await task.bot.send_video(
                            chat_id=chat_id,
                            video=str(file_path),
                            caption=task.caption,
                            duration=duration,
                            width=width,
                            height=height,
                            thumb=(
                                str(thumb_result)
                                if thumb_result and os.path.exists(thumb_result)
                                else None
                            ),
                            progress=self._progress_callback,
                            progress_args=(task,),
                        )

                # Clean up thumbnail and preview files - moved to _cleanup_files

            elif file_ext in [".mp3", ".m4a", ".ogg", ".flac"]:
                # Upload as audio
                sent_message = await task.bot.send_audio(
                    chat_id=chat_id,
                    audio=str(file_path),
                    caption=task.caption,
                    progress=self._progress_callback,
                    progress_args=(task,),
                )

            else:
                # Upload as document for other types
                sent_message = await task.bot.send_document(
                    chat_id=chat_id,
                    document=str(file_path),
                    caption=task.caption,
                    progress=self._progress_callback,
                    progress_args=(task,),
                )

            # Forward to private group if configured and message was sent successfully
            if sent_message:
                # Encaminhar para o grupo privado, se configurado
                if (
                    hasattr(self.settings, "private_group_id")
                    and self.settings.private_group_id
                ):
                    try:
                        # Verificar se esta é uma mensagem de grupo de mídia
                        if (
                            hasattr(sent_message, "media_group_id")
                            and sent_message.media_group_id
                        ):
                            logger.info(
                                f"Enviando mensagem de grupo de mídia para o grupo privado usando forward_media_group"
                            )
                            # Usar forward_media_group para encaminhar o grupo completo
                            await task.bot.forward_media_group(
                                chat_id=self.settings.private_group_id,
                                from_chat_id=chat_id,
                                message_id=sent_message.id,
                            )
                        else:
                            # Para mensagens individuais
                            logger.info(
                                f"Encaminhando mensagem individual para o grupo privado"
                            )
                            await sent_message.forward(
                                chat_id=self.settings.private_group_id
                            )
                    except Exception as e:
                        logger.error(f"Erro ao encaminhar para o grupo privado: {e}")
                        # Método alternativo
                        try:
                            await task.bot.forward_messages(
                                chat_id=self.settings.private_group_id,
                                from_chat_id=chat_id,
                                message_ids=sent_message.id,
                            )
                        except Exception as e2:
                            logger.error(f"Método alternativo também falhou: {e2}")

        except RPCError as e:
            logger.error(f"Telegram API error: {str(e)}")
            await task.status_message.edit_text(f"❌ Telegram API error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Upload error: {str(e)}")
            await task.status_message.edit_text(f"❌ Upload error: {str(e)}")
            raise

    async def _cleanup_files(self, task: UploadTask):
        """Clean up files after upload"""
        try:
            if task.is_media_group:
                # Clean up all files in the group
                for file_path in task.media_group_files:
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except Exception as e:
                            logger.warning(f"Error removing media group file: {e}")

                    # Also remove thumbnails if they exist
                    thumb_path = file_path.with_suffix(".jpg")
                    if os.path.exists(thumb_path):
                        try:
                            os.remove(thumb_path)
                        except Exception as e:
                            logger.warning(f"Error removing thumbnail: {e}")

                    # Remove timeline preview if it exists
                    thumb_preview = file_path.with_suffix(".thumb.jpg")
                    if os.path.exists(thumb_preview):
                        try:
                            os.remove(thumb_preview)
                        except Exception as e:
                            logger.warning(f"Error removing preview thumbnail: {e}")
            else:
                # Clean up the single file
                if os.path.exists(task.file_path):
                    try:
                        os.remove(task.file_path)
                    except Exception as e:
                        logger.warning(f"Error removing file: {e}")

                # Clean up thumbnails
                thumb_path = task.file_path.with_suffix(".jpg")
                if os.path.exists(thumb_path):
                    try:
                        os.remove(thumb_path)
                    except Exception as e:
                        logger.warning(f"Error removing thumbnail: {e}")

                # Clean up timeline preview
                thumb_preview = task.file_path.with_suffix(".thumb.jpg")
                if os.path.exists(thumb_preview):
                    try:
                        os.remove(thumb_preview)
                    except Exception as e:
                        logger.warning(f"Error removing preview thumbnail: {e}")
        except Exception as e:
            logger.error(f"Error cleaning up files: {e}")

    async def _progress_callback(self, current: int, total: int, task: UploadTask):
        """Callback for upload progress updates"""
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
            f"📤 Uploading: {percentage:.1f}%\n"
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
                        logger.error(f"Error updating progress: {e}")

    def _format_time(self, seconds: float) -> str:
        """Format seconds into readable time string"""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds//60:.0f}m {seconds%60:.0f}s"
        else:
            return f"{seconds//3600:.0f}h {(seconds%3600)//60:.0f}m"

    def get_queue_status(self) -> Dict:
        """Get current status of upload queue"""
        return {
            "queue_size": self.upload_queue.qsize(),
            "active_uploads": len(self.active_uploads),
            "active_tasks": [
                {
                    "task_id": task_id,
                    "user_id": task.user_id,
                    "file": task.file_path.name if task.file_path else "Media Group",
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
                for task_id, task in self.active_uploads.items()
            ],
            "completed_tasks": len(self.completed_uploads),
        }

    def _calculate_speed(self, task: UploadTask) -> str:
        """Calculate current upload speed for a task"""
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

    def _calculate_eta(self, task: UploadTask) -> str:
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
