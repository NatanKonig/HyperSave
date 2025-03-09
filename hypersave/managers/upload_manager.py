import asyncio
import os
from pathlib import Path
from time import time
from typing import Dict, List, Optional, Tuple

from pyrogram import Client
from pyrogram.errors import RPCError
from pyrogram.types import InputMediaPhoto, InputMediaVideo, Message

from hypersave.models.upload_task import UploadTask
from hypersave.utils.media_processor import (
    get_video_info, 
    get_video_thumbnail, 
    move_metadata_to_start,
    process_video_thumb
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
        status_message: Message
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
            media_group_files=[]
        )
        
        # Put task in queue
        await self.upload_queue.put(task)
        
        # Update status message if provided
        if status_message:
            # Store last message text to avoid duplicate updates
            task.last_progress_text = f"⏳ Upload queued. Position: {self.upload_queue.qsize()}"
            try:
                await status_message.edit_text(task.last_progress_text)
            except Exception as e:
                if "MESSAGE_NOT_MODIFIED" not in str(e):
                    print(f"Error updating upload queue status: {e}")
        
        return task_id
    
    async def enqueue_media_group(
        self,
        bot: Client,
        user_id: str,
        file_paths: List[Path],
        media_group_id: str,
        original_message: Message,
        status_message: Message
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
            
        Returns:
            task_id: Unique identifier for this upload task
        """
        # Create a unique task ID
        task_id = f"upload_group_{user_id}_{int(time())}_{media_group_id}"
        
        # Create upload task for the group
        task = UploadTask(
            task_id=task_id,
            user_id=user_id,
            bot=bot,
            file_path=file_paths[0] if file_paths else None,  # Primary file just for reference
            original_message=original_message,
            status_message=status_message,
            source_message=None,  # No single source message for groups
            caption="",  # Will be set per media item
            start_time=None,  # Will be set when upload starts
            progress=0,
            total_size=sum(os.path.getsize(f) for f in file_paths if os.path.exists(f)),
            is_completed=False,
            is_media_group=True,
            media_group_id=media_group_id,
            media_group_files=file_paths
        )
        
        # Put task in queue
        await self.upload_queue.put(task)
        
        # Update status message
        if status_message:
            # Store last message text to avoid duplicate updates
            task.last_progress_text = f"⏳ Media group upload queued ({len(file_paths)} items). Position: {self.upload_queue.qsize()}"
            try:
                await status_message.edit_text(task.last_progress_text)
            except Exception as e:
                if "MESSAGE_NOT_MODIFIED" not in str(e):
                    print(f"Error updating upload queue status: {e}")
        
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
                print(f"Error in upload queue processor: {e}")
    
    async def process_upload_task(self, task: UploadTask):
        """Process a single upload task"""
        async with self.upload_semaphore:
            try:
                # Update task as active
                self.active_uploads[task.task_id] = task
                
                # Update status message
                if not hasattr(task, 'last_progress_text') or task.last_progress_text != "📤 Upload started...":
                    try:
                        await task.status_message.edit_text("📤 Upload started...")
                        task.last_progress_text = "📤 Upload started..."
                    except Exception as e:
                        if "MESSAGE_NOT_MODIFIED" not in str(e):
                            print(f"Error updating upload start status: {e}")
                
                # Mark upload start time
                task.start_time = time()
                
                # Process based on whether it's a media group or single file
                if task.is_media_group:
                    await self._upload_media_group(task)
                else:
                    # Check if file exists
                    if not os.path.exists(task.file_path):
                        await task.status_message.edit_text(f"❌ File not found for upload: {task.file_path}")
                        return
                    
                    # Determine media type and upload accordingly
                    await self._upload_media(task)
                
                # Mark as completed
                task.is_completed = True
                self.completed_uploads.append(task.task_id)
                
                # Update status
                if not hasattr(task, 'last_progress_text') or task.last_progress_text != "✅ Upload completed!":
                    try:
                        await task.status_message.edit_text("✅ Upload completed!")
                        task.last_progress_text = "✅ Upload completed!"
                    except Exception as e:
                        if "MESSAGE_NOT_MODIFIED" not in str(e):
                            print(f"Error updating upload completion status: {e}")
                
                # Clean up files
                await self._cleanup_files(task)
                
            except Exception as e:
                # Update status with error
                await task.status_message.edit_text(f"❌ Upload failed: {str(e)}")
                print(f"Error processing upload task: {e}")
            finally:
                # Remove from active uploads
                if task.task_id in self.active_uploads:
                    del self.active_uploads[task.task_id]
                
                # Mark queue task as done
                self.upload_queue.task_done()
    
    async def _upload_media_group(self, task: UploadTask):
        """Process and upload a media group"""
        try:
            # Preparar a lista de mídias para o grupo
            media_list = []
            chat_id = task.original_message.chat.id
            
            # Update status
            status_text = f"📤 Processando grupo de mídia ({len(task.media_group_files)} itens)..."
            if not hasattr(task, 'last_progress_text') or task.last_progress_text != status_text:
                try:
                    await task.status_message.edit_text(status_text)
                    task.last_progress_text = status_text
                except Exception as e:
                    if "MESSAGE_NOT_MODIFIED" not in str(e):
                        print(f"Error updating media group process status: {e}")
            
            # Processar cada arquivo no grupo
            for i, file_path in enumerate(task.media_group_files):
                if not os.path.exists(file_path):
                    continue
                
                file_ext = file_path.suffix.lower()
                
                # Preparar de acordo com o tipo de mídia
                if file_ext in ['.jpg', '.jpeg', '.png']:
                    # Adicionar como foto
                    media_list.append(
                        InputMediaPhoto(media=str(file_path))
                    )
                
                elif file_ext in ['.mp4', '.avi', '.mov', '.mkv']:
                    # Processar vídeo
                    await move_metadata_to_start(file_path)
                    duration, width, height = await get_video_info(file_path)
                    
                    # Gerar thumbnail
                    thumb_path = file_path.with_suffix('.jpg')
                    await get_video_thumbnail(file_path, thumb_path)
                    
                    # Adicionar como vídeo
                    media_list.append(
                        InputMediaVideo(
                            media=str(file_path),
                            thumb=str(thumb_path),
                            duration=duration,
                            width=width,
                            height=height
                        )
                    )
            
            # Enviar em lotes (máximo 10 por grupo - limite do Telegram)
            if media_list:
                total_batches = (len(media_list) + 9) // 10  # Teto da divisão
                
                for i in range(0, len(media_list), 10):
                    batch = media_list[i:i+10]
                    batch_num = i // 10 + 1
                    
                    # Atualizar status
                    status_text = f"📤 Enviando grupo de mídia... (Lote {batch_num}/{total_batches})"
                    if not hasattr(task, 'last_progress_text') or task.last_progress_text != status_text:
                        try:
                            await task.status_message.edit_text(status_text)
                            task.last_progress_text = status_text
                        except Exception as e:
                            if "MESSAGE_NOT_MODIFIED" not in str(e):
                                print(f"Error updating media group upload status: {e}")
                    
                    # Enviar o grupo
                    try:
                        await task.bot.send_media_group(
                            chat_id=chat_id,
                            media=batch
                        )
                    except Exception as e:
                        error_msg = f"Erro ao enviar lote {batch_num}/{total_batches}: {str(e)}"
                        await task.original_message.reply(error_msg)
                
                # Atualizar status final
                final_status = f"✅ Grupo de mídia enviado com sucesso! ({len(media_list)} itens)"
                if not hasattr(task, 'last_progress_text') or task.last_progress_text != final_status:
                    try:
                        await task.status_message.edit_text(final_status)
                        task.last_progress_text = final_status
                    except Exception as e:
                        if "MESSAGE_NOT_MODIFIED" not in str(e):
                            print(f"Error updating media group final status: {e}")
            else:
                await task.status_message.edit_text("❌ Nenhum arquivo de mídia válido encontrado no grupo")
        
        except Exception as e:
            await task.status_message.edit_text(f"❌ Erro ao processar grupo de mídia: {str(e)}")
            raise
    
    async def _upload_media(self, task: UploadTask):
        """Upload media based on file type"""
        file_path = task.file_path
        file_ext = file_path.suffix.lower()
        chat_id = task.original_message.chat.id
        
        try:
            # Process media based on file type
            if file_ext in ['.jpg', '.jpeg', '.png']:
                # Upload as photo
                await task.bot.send_photo(
                    chat_id=chat_id,
                    photo=str(file_path),
                    caption=task.caption,
                    progress=self._progress_callback,
                    progress_args=(task,)
                )
            
            elif file_ext in ['.mp4', '.avi', '.mov', '.mkv']:
                # Process video before upload
                await move_metadata_to_start(file_path)
                duration, width, height = await get_video_info(file_path)
                
                # Create thumbnail
                thumb_path = file_path.with_suffix('.jpg')
                await get_video_thumbnail(file_path, thumb_path)
                
                # Upload video
                if duration <= 180:  # Short video
                    await task.bot.send_video(
                        chat_id=chat_id,
                        video=str(file_path),
                        caption=task.caption,
                        duration=duration,
                        width=width,
                        height=height,
                        thumb=str(thumb_path),
                        progress=self._progress_callback,
                        progress_args=(task,)
                    )
                else:  # Longer video, create preview
                    thumb_preview_path = file_path.with_suffix('.thumb.jpg')
                    await process_video_thumb(file_path, thumb_preview_path)
                    
                    media_group = [
                        InputMediaVideo(
                            media=str(file_path),
                            caption=task.caption,
                            thumb=str(thumb_path),
                            duration=duration,
                            width=width,
                            height=height
                        ),
                        InputMediaPhoto(media=str(thumb_preview_path))
                    ]
                    
                    await task.bot.send_media_group(
                        chat_id=chat_id,
                        media=media_group
                    )
                    
                    # Clean up preview thumbnail
                    if os.path.exists(thumb_preview_path):
                        os.remove(thumb_preview_path)
                
                # Clean up thumbnail
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
            
            elif file_ext in ['.mp3', '.m4a', '.ogg', '.flac']:
                # Upload as audio
                await task.bot.send_audio(
                    chat_id=chat_id,
                    audio=str(file_path),
                    caption=task.caption,
                    progress=self._progress_callback,
                    progress_args=(task,)
                )
            
            else:
                # Upload as document for other types
                await task.bot.send_document(
                    chat_id=chat_id,
                    document=str(file_path),
                    caption=task.caption,
                    progress=self._progress_callback,
                    progress_args=(task,)
                )
                
        except RPCError as e:
            await task.status_message.edit_text(f"❌ Telegram API error: {str(e)}")
            raise
        except Exception as e:
            await task.status_message.edit_text(f"❌ Upload error: {str(e)}")
            raise
    
    async def _cleanup_files(self, task: UploadTask):
        """Clean up files after upload"""
        try:
            if task.is_media_group:
                # Limpar todos os arquivos do grupo
                for file_path in task.media_group_files:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    
                    # Também remover thumbnails se existirem
                    thumb_path = file_path.with_suffix('.jpg')
                    if os.path.exists(thumb_path):
                        os.remove(thumb_path)
            else:
                # Clean up the single file
                if os.path.exists(task.file_path):
                    os.remove(task.file_path)
        except Exception as e:
            print(f"Error cleaning up files: {e}")
    
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
        if not hasattr(task, 'last_progress_text'):
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
                        print(f"Error updating progress: {e}")
    
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
                    "progress": f"{(task.progress / task.total_size * 100):.1f}%" if task.total_size else "0%",
                    "speed": self._calculate_speed(task) if task.start_time else "N/A",
                    "eta": self._calculate_eta(task) if task.start_time and task.total_size and task.progress else "N/A"
                }
                for task_id, task in self.active_uploads.items()
            ],
            "completed_tasks": len(self.completed_uploads)
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