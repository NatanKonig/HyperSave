from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from pyrogram import Client
from pyrogram.types import Message


@dataclass
class UploadTask:
    """Represents an upload task"""

    # Task identification
    task_id: str
    user_id: str

    # Clients
    bot: Client

    # File info
    file_path: Path
    caption: str

    # Messages for updates
    original_message: Message
    status_message: Message
    source_message: Message

    # Progress tracking
    start_time: Optional[float]
    progress: int
    total_size: int

    # Status
    is_completed: bool

    # Media group info
    is_media_group: bool = False
    media_group_id: Optional[str] = None
    media_group_files: List[Path] = None
