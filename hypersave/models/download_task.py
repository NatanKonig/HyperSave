from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from pyrogram import Client
from pyrogram.types import Message


@dataclass
class DownloadTask:
    """Represents a download task"""

    # Task identification
    task_id: str
    user_id: str

    # Telegram info
    user_client: Client
    chat_id: Any  # Can be int or str
    message_id: int

    # Messages for updates
    original_message: Message
    status_message: Message
    bot: Client

    # Progress tracking
    start_time: Optional[float]
    progress: int
    total_size: int

    # Status
    is_completed: bool

    # Result path
    output_path: Optional[Path]

    # Thread/topic id for forum topics (if applicable)
    message_thread_id: Optional[int] = None

    # Media group info
    is_media_group: bool = False
    media_group_id: Optional[str] = None

    # Lista para armazenar legendas de cada item em um grupo de mídia
    media_captions: List[str] = None
