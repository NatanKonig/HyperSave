from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class MediaInfo:
    """Information about a media file"""

    # File paths
    file_path: Path
    thumbnail_path: Optional[Path] = None

    # Media type
    media_type: str = "unknown"  # photo, video, audio, document

    # File metadata
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[int] = None
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: int = 0

    # Caption
    caption: Optional[str] = None
