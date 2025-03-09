import asyncio
import os
from asyncio.subprocess import PIPE
from pathlib import Path
from shutil import rmtree

import cv2
from PIL import Image, ImageDraw, ImageFont

from hypersave.settings import Settings

settings = Settings()


async def get_video_info(video_path: Path) -> tuple:
    """
    Get video information (duration, width, height)

    Args:
        video_path: Path to the video file

    Returns:
        tuple: (duration, width, height)
    """
    try:
        video = cv2.VideoCapture(str(video_path))
        if not video.isOpened():
            raise RuntimeError(f"Failed to open video {video_path}")

        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = int(frame_count / fps) if fps > 0 else 0
        width = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))

        video.release()

        return duration, width, height
    except Exception as e:
        print(f"Error getting video info: {e}")
        return 0, 0, 0


async def get_video_thumbnail(video_path: Path, output_path: Path) -> Path:
    """
    Extract thumbnail from a video

    Args:
        video_path: Path to video file
        output_path: Path to save thumbnail

    Returns:
        Path to the thumbnail
    """
    if not video_path.exists():
        print(f"Arquivo de vídeo não encontrado para thumbnail: {video_path}")
        return output_path

    try:
        # Garantir que o diretório de saída existe
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]

        process = await asyncio.create_subprocess_exec(*cmd, stderr=PIPE, stdout=PIPE)
        await process.communicate()

        if process.returncode != 0:
            print(f"Failed to extract thumbnail from {video_path}")

        # Retorna o caminho mesmo se falhar (o upload vai funcionar sem thumbnail)
        return output_path
    except Exception as e:
        print(f"Error getting video thumbnail: {e}")
        return output_path


async def move_metadata_to_start(video_path: Path):
    """
    Move metadata to start of video file for faster streaming

    Args:
        video_path: Path to the video file
    """
    if not video_path.exists():
        print(f"Arquivo de vídeo não encontrado: {video_path}")
        return

    try:
        tmp_video_path = video_path.with_suffix(".tmp.mp4")

        cmd = [
            "ffmpeg",
            "-i",
            str(video_path),
            "-c",
            "copy",
            "-movflags",
            "faststart",
            "-y",
            str(tmp_video_path),
        ]

        process = await asyncio.create_subprocess_exec(*cmd, stderr=PIPE, stdout=PIPE)
        await process.communicate()

        if process.returncode == 0 and tmp_video_path.exists():
            # Replace original with optimized version
            tmp_video_path.replace(video_path)
        else:
            print(f"Warning: Failed to optimize video {video_path}")
    except FileNotFoundError as e:
        print(f"Error optimizing video: {e}")
    except Exception as e:
        print(f"Error optimizing video: {e}")


async def extract_frames(video_path: Path, frames: int) -> Path:
    """
    Extract frames from a video

    Args:
        video_path: Path to the video file
        frames: Number of frames to extract

    Returns:
        Path to the folder containing extracted frames
    """
    try:
        # Create folder for frames
        folder = settings.THUMBS_DIR / video_path.stem
        folder.mkdir(parents=True, exist_ok=True)

        # Get video duration
        duration, _, _ = await get_video_info(video_path)
        interval = duration / frames if duration > 0 and frames > 0 else 1

        # Extract frames at regular intervals
        for i in range(frames):
            time_position = i * interval
            out_path = folder / f"thumb{i+1:03d}.jpg"

            cmd = [
                "ffmpeg",
                "-ss",
                str(time_position),
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(out_path),
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd, stderr=PIPE, stdout=PIPE
            )
            await process.communicate()

            # Add timestamp to the frame
            if os.path.exists(out_path):
                await draw_time_on_image(out_path, time_position)

        return folder
    except Exception as e:
        print(f"Error extracting frames: {e}")
        raise


async def draw_time_on_image(image_path: Path, time_seconds: float):
    """
    Add timestamp to an image

    Args:
        image_path: Path to the image
        time_seconds: Timestamp in seconds
    """
    try:
        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)

        # Format time string
        hours, remainder = divmod(int(time_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            time_str = f"{hours:02}:{minutes:02}:{seconds:02}"
        else:
            time_str = f"{minutes:02}:{seconds:02}"

        # Get font
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 60)
        except IOError:
            font = ImageFont.load_default()

        # Calculate text size
        text_bbox = draw.textbbox((0, 0), time_str, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        # Position text at bottom left
        text_position = (10, img.height - text_height - 10)

        # Draw background
        background_position = [
            text_position[0] - 5,
            text_position[1] - 5,
            text_position[0] + text_width + 10,
            text_position[1] + text_height + 10,
        ]
        draw.rectangle(background_position, fill=(0, 0, 0))

        # Draw text with shadow
        shadow_offset = (2, 2)
        shadow_color = (0, 0, 0)
        text_color = (255, 255, 255)

        draw.text(
            (text_position[0] + shadow_offset[0], text_position[1] + shadow_offset[1]),
            time_str,
            font=font,
            fill=shadow_color,
        )
        draw.text(text_position, time_str, font=font, fill=text_color)

        # Save image
        img = img.convert("RGB")
        img.save(image_path)
    except Exception as e:
        print(f"Error drawing time on image: {e}")


async def create_thumb_grid(
    frames_folder: Path, output_path: Path, grid_size: tuple = (4, 4)
) -> Path:
    """
    Create a grid of thumbnails

    Args:
        frames_folder: Folder containing frame images
        output_path: Path to save the grid image
        grid_size: Grid dimensions (width, height)

    Returns:
        Path to the grid image
    """
    try:
        # Get frame files
        frame_files = sorted(frames_folder.glob("*.jpg"))

        if len(frame_files) < grid_size[0] * grid_size[1]:
            print(
                f"Warning: Not enough frames for grid. Found {len(frame_files)}, need {grid_size[0] * grid_size[1]}"
            )

        # Select frames to use
        selected_frames = frame_files[: grid_size[0] * grid_size[1]]

        if not selected_frames:
            raise ValueError("No frames found to create grid")

        # Open images
        images = [Image.open(frame) for frame in selected_frames]

        # Get image dimensions
        width, height = images[0].size

        # Create new image for grid
        grid_img = Image.new("RGB", (grid_size[0] * width, grid_size[1] * height))

        # Paste images into grid
        for index, img in enumerate(images):
            x = (index % grid_size[0]) * width
            y = (index // grid_size[0]) * height
            grid_img.paste(img, (x, y))

        # Save grid image
        grid_img.save(output_path)

        # Clean up frames folder
        rmtree(frames_folder)

        return output_path
    except Exception as e:
        print(f"Error creating thumbnail grid: {e}")
        raise


async def process_video_thumb(
    video_path: Path, thumb_path: Path, frames: int = 16, grid: tuple = (4, 4)
) -> Path:
    """
    Process video to create a thumbnail grid

    Args:
        video_path: Path to the video file
        thumb_path: Path to save the thumbnail grid
        frames: Number of frames to extract
        grid: Grid dimensions (width, height)

    Returns:
        Path to the thumbnail grid
    """
    try:
        # Make sure parent directories exist
        thumb_path.parent.mkdir(parents=True, exist_ok=True)

        # For very large videos, reduce the number of frames to avoid timeout
        file_size = video_path.stat().st_size
        if file_size > 100 * 1024 * 1024:  # 100 MB
            frames = min(frames, 9)  # Use 3x3 grid for large videos
            grid = (3, 3)
        elif file_size > 50 * 1024 * 1024:  # 50 MB
            frames = min(frames, 12)  # Use 4x3 grid for medium videos
            grid = (4, 3)

        # Extract frames
        frames_folder = await extract_frames(video_path, frames)

        # Create thumbnail grid
        await create_thumb_grid(frames_folder, thumb_path, grid)

        return thumb_path
    except Exception as e:
        print(f"Error processing video thumbnail: {e}")
        # Return a default thumbnail if we failed to create one
        try:
            # Try to at least get a single frame
            await get_video_thumbnail(video_path, thumb_path)
            return thumb_path
        except:
            # If all else fails, just return the path (will be missing but upload will still work)
            return thumb_path
