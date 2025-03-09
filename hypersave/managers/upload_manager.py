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
            is_completed=False
        )
        
        # Put task in queue
        await self.upload_queue.put(task)
        
        # Update status message if provided
        if status_message:
            await status_message.edit_text(f"⏳ Upload queued. Position: {self.upload_queue.qsize()}")
        
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
                await task.status_message.edit_text("📤 Upload started...")
                
                # Mark upload start time
                task.start_time = time()
                
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
                await task.status_message.edit_text("✅ Upload completed!")
                
                # Clean up the file if it still exists
                if os.path.exists(task.file_path):
                    os.remove(task.file_path)
                
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
        
        # Update status periodically (not too often to avoid flood)
        if current == total or current % (max(1, total // 10)) == 0:
            try:
                await task.status_message.edit_text(
                    f"📤 Uploading: {percentage:.1f}%\n"
                    f"🚀 Speed: {speed_str}\n"
                    f"⏱️ ETA: {eta_str}"
                )
            except Exception:
                pass
    
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
                    "file": task.file_path.name,
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